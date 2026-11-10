"""FastAPI app: JSON API + static UI. Run with `ankistudio serve`."""
from __future__ import annotations

import re
import sqlite3
import subprocess as _sp
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel


def _ensure_readable(p: Path, what: str):
    """exists() alone is not enough on macOS: privacy protection (TCC)
    denies open() for e.g. ~/Downloads or external volumes while stat
    still succeeds. Turn that into a clear message instead of a 500."""
    try:
        with p.open("rb"):
            pass
    except PermissionError:
        raise HTTPException(403, (
            f"macOS privacy protection blocks reading {what}: {p} — "
            "pick the file through the system dialog in the web UI "
            "(the browser uploads it), or grant the app running the server "
            "access in System Settings → Privacy & Security → "
            "Files and Folders / Full Disk Access."))
    except OSError as e:
        raise HTTPException(400, f"cannot read {what} {p}: {e}")


class ImportReq(BaseModel):
    path: str
    max_chars: int = 60


class FreqTsvReq(BaseModel):
    path: str
    word_col: int = 0
    level_col: int = 1


class FreqApkgReq(BaseModel):
    path: str
    word_field: str | None = None
    level_field: str | None = None


class DecideReq(BaseModel):
    ids: list[int]
    decision: str          # approved | discarded | ''


class PointsImportReq(BaseModel):
    yaml_text: str = ""
    path: str = ""


class PoolReq(BaseModel):
    point: str = ""              # target point (label for approvals)
    q: str = ""
    source: int = 0
    level: str = ""
    min_len: int = 0
    max_len: int = 60
    size: int = 40
    per_show: int = 3            # max candidates per source
    balanced: bool = True        # force length spread within each source
    exclude_deck: bool = True    # skip sentences already in the deck
    match_mode: str = "contains" # contains | starts | ends | regex
    exclude: str = ""            # exclude sentences containing this


class DeckAddReq(BaseModel):
    sentence_id: int
    point: str = ""
    note: str = ""


class PointUpdateReq(BaseModel):
    template: str | None = None
    boilerplate: str | None = None
    title: str | None = None
    note_type_id: int | None = None


class NoteTypeReq(BaseModel):
    name: str
    fields: list[str]
    css: str = ""
    front: str = ""
    back: str = ""
    model_id: int | None = None   # auto-assigned if omitted


class TemplateApplyReq(BaseModel):
    point: str


class AIFillReq(BaseModel):
    item_id: int                   # deck item to explain
    instruction: str = ""


class AIBlockReq(BaseModel):
    point: str
    instruction: str = ""
    only_empty: bool = True


class SettingsReq(BaseModel):
    values: dict[str, str] = {}


class DeckUpdateReq(BaseModel):
    position: int | None = None
    note: str | None = None
    point: str | None = None


class ProjectOpenReq(BaseModel):
    path: str


class PoolDecideReq(BaseModel):
    sentence_id: int
    context: str = "global"        # 'global' or 'point:GP-XXX'
    decision: str                   # 'approved' | 'discarded' | ''


class ClassifyReq(BaseModel):
    lexicon_id: int


class VideoReq(BaseModel):
    video: str
    subs: str
    offset: float = 0.0
    pad_start: float = 0.35        # lead padding seconds
    pad_end: float = 0.35          # tail padding seconds
    name: str | None = None
    astream: int | None = None     # audio stream ordinal; None = auto (Japanese)
    sub_lang: str = "auto"         # auto | ja | zh | '' (keep all lines)


class AnalyzeReq(BaseModel):
    path: str


class PreWhisperReq(BaseModel):
    video: str                      # temp upload path
    subs: str                       # stored subs path
    astream: int | None = None      # None = auto (Japanese)
    sub_lang: str = "auto"


class ShiftReq(BaseModel):
    offset: float = 0.0
    segments: list[dict] = []      # [{at: seconds, shift: seconds}] absolute
    pad_start: float | None = None  # lead padding seconds (before the line)
    pad_end: float | None = None    # tail padding seconds (after the line)
    name: str | None = None         # rename the source


class ExportReq(BaseModel):
    name: str = "AnkiStudio export"
    preset: str = "immersion"      # immersion | reading
    status: str = "approved"       # approved | pending | all
    source: int = 0
    level: str = ""
    out_dir: str = "result"
    pad_start: float | None = None  # override lead padding; None = source's own
    pad_end: float | None = None    # override tail padding; None = source's own
    subdecks: bool = True           # Module::GP hierarchy on export

from .importer import import_apkg, import_freq_apkg, import_freq_tsv
from .store import Store

STATIC = Path(__file__).resolve().parent.parent / "static"


def create_app(db_path: str | Path) -> FastAPI:
    # the data dir (and the project pointer inside it) stay fixed even
    # after the store is switched to a project db
    default_db = Path(db_path).resolve()
    data_dir = default_db.parent
    pointer = data_dir / "current-project"
    startup_db = default_db
    if pointer.exists():
        try:
            p = Path(pointer.read_text(encoding="utf-8").strip())
            if p.suffix == ".db" and p.exists():
                startup_db = p              # resume the last open project
        except OSError:
            pass
    app = FastAPI(title="AnkiStudio")
    store = Store(startup_db)

    def _adopt_project_media():
        """On project open/resume, make the project folder self-contained:
        (1) missing absolute audio paths rebind to the same release in the
        project's uploads (uuid prefixes differ between uploads); (2)
        paths under the project dir are stored relative so the .aproj is
        portable; (3) frame images for this project's sources are copied
        from the app-wide cache into the project's own media-cache."""
        import json as _j
        import shutil as _sh
        if store.path.parent == data_dir:
            return                      # default working project
        base = store.path.parent
        changed = False
        for r in store.db.execute(
                "select id, path, meta from sources where kind='video'"):
            meta = _j.loads(r["meta"] or "{}")
            audio = meta.get("audio") or r["path"] or ""
            p = Path(audio)
            if audio and not p.exists():
                stem = p.name.split("-", 1)[-1]
                cands = [f for f in (base / "uploads").glob("*.mka")
                         if f.name.split("-", 1)[-1] == stem]
                if not cands:
                    cands = [f for f in (base / "uploads").glob("*.mka")
                             if f.name.split("-", 1)[-1][:16] == stem[:16]]
                if len(cands) == 1:
                    p = cands[0]
            try:
                rel = p.resolve().relative_to(base.resolve())
                p = Path(rel)
            except (ValueError, OSError):
                pass
            ref = str(p)
            if ref != (meta.get("audio") or "") or ref != (r["path"] or ""):
                meta["audio"] = ref
                store.db.execute(
                    "update sources set path=?, meta=? where id=?",
                    (ref, _j.dumps(meta), r["id"]))
                changed = True
        if changed:
            store.db.commit()
        src_ids = [x["id"] for x in store.db.execute("select id from sources")]
        dst = base / "media-cache"
        main = data_dir / "media-cache"
        moved = 0
        if main.is_dir() and dst.resolve() != main.resolve():
            for sid in src_ids:
                for f in main.glob(f"src{sid}-*.jpg"):
                    d = dst / f.name
                    if not d.exists():
                        dst.mkdir(parents=True, exist_ok=True)
                        try:
                            _sh.copy2(f, d)
                            moved += 1
                        except OSError:
                            pass
        return moved

    def _reopen(path: Path):
        store.reopen(path)
        pointer.write_text(str(path), encoding="utf-8")
        _adopt_project_media()
        bust_stats()

    if startup_db != default_db:
        _adopt_project_media()      # resumed project: rebind + localize

    def _write_aproj(out: Path, name: str):
        """Snapshot the live store into a portable .aproj at `out`."""
        import json as _j
        import zipfile as _z
        import tempfile as _t
        out.parent.mkdir(parents=True, exist_ok=True)
        with _t.TemporaryDirectory(dir=str(out.parent)) as td:
            dbfile = Path(td) / "project.db"
            store.snapshot_to(dbfile)
            manifest = {
                "format": "ankistudio-project", "version": 1,
                "name": name,
                "created": __import__("datetime").datetime.now().isoformat(),
                "app": "AnkiStudio",
                "sources": [dict(r) for r in store.sources()],
                "sentences": store.db.execute(
                    "select count(*) c from sentences").fetchone()["c"],
                "points": len(store.points()),
            }
            tmp = out.with_suffix(out.suffix + ".partial")
            with _z.ZipFile(tmp, "w", _z.ZIP_DEFLATED) as z:
                z.writestr("manifest.json",
                           _j.dumps(manifest, ensure_ascii=False, indent=1))
                z.write(dbfile, "project.db")
            tmp.replace(out)

    def _archive_db_mtime(aproj: Path) -> float:
        """Timestamp of the db inside the archive — decides whether the
        working copy is newer (must never be clobbered by an old snapshot)."""
        import zipfile as _z
        import calendar as _calendar
        try:
            with _z.ZipFile(aproj) as z:
                # date_time is a (y, m, d, h, min, s) tuple
                return _calendar.timegm(z.getinfo("project.db").date_time)
        except Exception:
            return 0.0

    def _open_aproj(aproj: Path) -> dict:
        import zipfile as _z
        import json as _j
        if not aproj.exists() or aproj.suffix != ".aproj":
            raise HTTPException(404, f"not an .aproj file: {aproj}")
        try:
            with _z.ZipFile(aproj) as z:
                names = z.namelist()
                if "project.db" not in names or "manifest.json" not in names:
                    raise ValueError("not an AnkiStudio project archive")
                manifest = _j.loads(z.read("manifest.json"))
        except (_z.BadZipFile, ValueError) as e:
            raise HTTPException(400, f"bad .aproj: {e}")
        dest_dir = data_dir / "projects" / aproj.stem
        dest_dir.mkdir(parents=True, exist_ok=True)
        wdb = dest_dir / "project.db"
        resumed = False
        if wdb.exists() and wdb.stat().st_mtime >= _archive_db_mtime(aproj):
            # the working copy has newer work than the snapshot — resume it
            resumed = True
        else:
            import zipfile as _zz
            with _zz.ZipFile(aproj) as z:
                z.extract("project.db", dest_dir)
        _reopen(wdb)
        return {"opened": str(aproj), "resumed": resumed,
                "name": manifest.get("name") or aproj.stem,
                "sources": manifest.get("sources", 0)}

    # /api/stats backs every view; on 200k+ sentences its aggregate queries
    # take real time, so short-lived caching keeps navigation snappy
    stats_cache: dict = {"at": 0.0, "v": None}

    def bust_stats():
        stats_cache["v"] = None

    # ---------- api ----------

    @app.get("/api/stats")
    def stats():
        import time as _t
        if stats_cache["v"] is None or _t.time() - stats_cache["at"] > 2.0:
            stats_cache["v"] = {
                "stats": store.stats(),
                "sources": [dict(r) for r in store.sources()],
                "lexicons": [dict(r) for r in store.lexicons()],
            }
            stats_cache["at"] = _t.time()
        return stats_cache["v"]

    @app.post("/api/import/apkg")
    def import_deck(req: ImportReq):
        p = Path(req.path).expanduser()
        if not p.exists():
            raise HTTPException(404, f"no such file: {p}")
        _ensure_readable(p, "deck file")
        return import_apkg(store, p, max_chars=req.max_chars)

    @app.post("/api/import/freq-tsv")
    def freq_tsv(req: FreqTsvReq):
        p = Path(req.path).expanduser()
        if not p.exists():
            raise HTTPException(404, f"no such file: {p}")
        _ensure_readable(p, "frequency list")
        lid = import_freq_tsv(store, p, word_col=req.word_col,
                              level_col=req.level_col)
        return {"lexicon_id": lid}

    @app.post("/api/import/freq-apkg")
    def freq_apkg(req: FreqApkgReq):
        p = Path(req.path).expanduser()
        if not p.exists():
            raise HTTPException(404, f"no such file: {p}")
        _ensure_readable(p, "frequency deck")
        lid = import_freq_apkg(store, p, word_field=req.word_field,
                               level_field=req.level_field)
        return {"lexicon_id": lid}

    @app.post("/api/decide")
    def decide(req: DecideReq):
        if req.decision not in ("approved", "discarded", ""):
            raise HTTPException(400, "decision must be approved|discarded|''")
        store.decide(req.ids, req.decision)
        return {"updated": len(req.ids)}

    @app.get("/api/sentences")
    def sentences(q: str = "", source: int = 0, level: str = "",
                  status: str = "", sort: str = "len", page: int = 1,
                  per: int = 50):
        """Card browser. Filtering, sorting, level selection and pagination
        all run in SQL — the store can hold 200k+ sentences and must never
        be materialized in Python."""
        where, args = ["1=1"], []
        if source:
            where.append("n.source_id=?"); args.append(source)
        if q:
            where.append("(n.text like ? or n.translation like ?)")
            args += [f"%{q}%", f"%{q}%"]
        if status == "approved":
            where.append("n.decision='approved'")
        elif status == "discarded":
            where.append("n.decision='discarded'")
        elif status == "pending":
            where.append("n.decision='' and n.keep=1")
        if level:
            where.append("n.level=?"); args.append(level)
        order = {
            "len": "(n.char_len is null), n.char_len, n.id",
            "len_desc": "(n.char_len is null), n.char_len desc, n.id desc",
            "source": "n.source_id, (n.char_len is null), n.char_len, n.id",
            "recent": "n.id desc",
        }.get(sort, "(n.char_len is null), n.char_len, n.id")
        w = " and ".join(where)
        total = store.db.execute(
            f"select count(*) c from sentences n where {w}",
            args).fetchone()["c"]
        page, per = max(1, page), max(1, min(200, per))
        rows = [dict(r) for r in store.db.execute(
            f"select n.*, s.name source_name from sentences n"
            f" join sources s on s.id=n.source_id where {w}"
            f" order by {order} limit ? offset ?",
            args + [per, (page - 1) * per])]
        return {"total": total, "page": page, "per": per, "rows": rows}


    @app.post("/api/import/video")
    def import_video_ep(req: VideoReq):
        from .importer import import_video as _iv
        v, b = Path(req.video).expanduser(), Path(req.subs).expanduser()
        if not v.exists():
            raise HTTPException(404, f"no video: {v}")
        if not b.exists():
            raise HTTPException(404, f"no subtitles: {b}")
        _ensure_readable(v, "video file")
        _ensure_readable(b, "subtitle file")
        if req.sub_lang not in ("auto", "ja", "zh", ""):
            raise HTTPException(400, "sub_lang must be auto|ja|zh|''")
        try:
            return _iv(store, v, b, offset=req.offset, name=req.name,
                       pad_start=req.pad_start, pad_end=req.pad_end,
                       astream=req.astream, sub_lang=req.sub_lang)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except _sp.CalledProcessError:
            raise HTTPException(400, "ffmpeg failed on this file "
                                     "(is ffmpeg installed and the file valid?)")

    @app.post("/api/analyze-subs")
    def analyze_subs(req: AnalyzeReq):
        """Language stats for an uploaded subtitle file, so the UI can
        offer to keep just one language of a bilingual track."""
        from . import subs as _subs
        p = Path(req.path).expanduser()
        if not p.exists():
            raise HTTPException(404, f"no such file: {p}")
        _ensure_readable(p, "subtitle file")
        try:
            cues = _subs.parse_detail(p)
        except Exception as e:
            raise HTTPException(400, f"cannot parse subtitles: {e}")
        return _subs.analyze_cues(cues)

    @app.post("/api/probe-video")
    def probe_video(req: AnalyzeReq):
        """Audio stream list for an uploaded (temp) video, with the
        suggested Japanese default for the import dialog."""
        from . import ffmpeg as _ff
        p = Path(req.path).expanduser()
        if not p.exists():
            raise HTTPException(404, f"no such file: {p}")
        _ensure_readable(p, "video file")
        try:
            return _ff.probe_audio(p)
        except (_sp.CalledProcessError, FileNotFoundError):
            raise HTTPException(400, "ffprobe failed — is ffmpeg installed?")

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...), temp: bool = False):
        """Store a file picked with the system dialog and return its path.
        The browser reads the file after the user consents in the native
        open panel, so the server never has to touch macOS-protected
        locations (~/Downloads, external volumes).

        temp=1 parks a big video under data/tmp — the import extracts its
        audio track and frame images and deletes it, so the gigabytes never
        become permanent. Regular files (subtitles, decks) land in
        data/uploads; re-uploads of an identical file (same stored name
        and size) reuse the existing copy instead of re-saving it."""
        import uuid as _uuid
        updir = store.path.parent / ("tmp" if temp else "uploads")
        updir.mkdir(parents=True, exist_ok=True)
        orig = file.filename or "upload"
        safe = re.sub(r"[^\w.\-]+", "_", orig).strip("._") or "upload"
        size = file.size                    # from Content-Length
        if size is not None and not temp:
            for cand in updir.glob(f"*-{safe}"):
                try:
                    if cand.is_file() and cand.stat().st_size == size:
                        while await file.read(1 << 20):
                            pass            # drain the request body
                        return {"path": str(cand.resolve()), "name": orig,
                                "size": size, "reused": True}
                except OSError:
                    continue
        dest = updir / f"{_uuid.uuid4().hex[:8]}-{safe}"
        with dest.open("wb") as out:
            while chunk := await file.read(1 << 20):
                out.write(chunk)
        if not dest.stat().st_size:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "empty upload")
        return {"path": str(dest.resolve()), "name": orig,
                "size": dest.stat().st_size, "reused": False}

    @app.get("/api/video/{sid}")
    def video_meta(sid: int):
        r = store.db.execute("select meta from sources where id=?", (sid,)).fetchone()
        if not r:
            raise HTTPException(404, "no such source")
        import json as _j
        return _j.loads(r["meta"] or "{}")

    @app.post("/api/video/{sid}/shift")
    def video_shift(sid: int, req: ShiftReq):
        import json as _j
        r = store.db.execute("select * from sources where id=?", (sid,)).fetchone()
        if not r:
            raise HTTPException(404, "no such source")
        meta = _j.loads(r["meta"] or "{}")
        meta["offset"] = req.offset
        meta["segments"] = sorted(req.segments, key=lambda g: g.get("at", 0))
        meta.pop("pad", None)          # legacy single-sided value
        if req.pad_start is not None:
            meta["pad_start"] = max(0.0, min(5.0, req.pad_start))
        if req.pad_end is not None:
            meta["pad_end"] = max(0.0, min(5.0, req.pad_end))
        store.db.execute("update sources set meta=? where id=?",
                         (_j.dumps(meta), sid))
        name = r["name"]
        if req.name is not None and req.name.strip():
            name = req.name.strip()[:120]
            store.db.execute("update sources set name=? where id=?",
                             (name, sid))
        store.db.commit()
        return {"name": name, **meta}

    @app.post("/api/video/{sid}/whisper")
    def video_whisper(sid: int):
        """Measure the global subtitle shift with Whisper. Streams one
        JSON line per measured cue (live progress), then a final line
        with the median. Read-only — the UI applies the suggested offset
        only on user confirmation."""
        from fastapi.responses import StreamingResponse
        from . import whisper as _wh

        def ndjson(gen):
            import json as _json
            for ev in gen:
                yield _json.dumps(ev, ensure_ascii=False) + "\n"

        # private read-only connection: the shared store connection is
        # not safe for concurrent request threads (InterfaceError races)
        ro = store.ro()
        try:
            r = ro.execute("select id, kind from sources where id=?",
                           (sid,)).fetchone()
        finally:
            ro.close()
        if not r:
            raise HTTPException(404, "no such source")
        try:
            prep = _wh.analyze_shift(store, sid)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return StreamingResponse(ndjson(_wh.run_measure(prep)),
                                 media_type="application/x-ndjson")

    @app.post("/api/whisper/pre")
    def whisper_pre(req: PreWhisperReq):
        """Measure the global shift BEFORE import, on the temp video and
        the stored subtitles — so the offset lands in the import form and
        the frame images grabbed at import are timed correctly. Streams
        progress lines like /api/video/{sid}/whisper."""
        from fastapi.responses import StreamingResponse
        from . import whisper as _wh

        def ndjson(gen):
            import json as _json
            for ev in gen:
                yield _json.dumps(ev, ensure_ascii=False) + "\n"

        v, b = Path(req.video).expanduser(), Path(req.subs).expanduser()
        if not v.exists():
            raise HTTPException(404, f"no video: {v}")
        if not b.exists():
            raise HTTPException(404, f"no subtitles: {b}")
        _ensure_readable(v, "video file")
        _ensure_readable(b, "subtitle file")
        if req.sub_lang not in ("auto", "ja", "zh", ""):
            raise HTTPException(400, "sub_lang must be auto|ja|zh|''")
        try:
            prep = _wh.analyze_pre(v, b, req.astream, req.sub_lang,
                                   store.path.parent.parent)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return StreamingResponse(ndjson(_wh.run_measure(prep)),
                                 media_type="application/x-ndjson")

    @app.post("/api/whisper/install")
    def whisper_install():
        """Auto-install whisper into a dedicated project venv (.venv-whisper,
        CPython 3.11 via uv) when no system whisper is on PATH. Slow the
        first time — downloads Python + torch + whisper."""
        from . import whisper as _wh
        try:
            return _wh.ensure_installed(store.path.parent.parent)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/video/{sid}/subs")
    def video_subs(sid: int):
        """The source's original subtitle file with corrected timings —
        the source's offset and shift segments applied, everything else
        (styles, languages, layout) untouched. Served as a download."""
        import json as _j
        from urllib.parse import quote as _quote
        from fastapi.responses import Response
        from . import subs as _subs
        from . import ffmpeg as _ff
        r = store.db.execute("select * from sources where id=?",
                             (sid,)).fetchone()
        if not r:
            raise HTTPException(404, "no such source")
        meta = _j.loads(r["meta"] or "{}")
        subs_path = Path(meta.get("subs") or "")
        if not subs_path or not subs_path.exists():
            raise HTTPException(404, "original subtitle file not stored "
                                     "for this source")
        _ensure_readable(subs_path, "subtitle file")
        text, _ = _subs.retime(
            subs_path, lambda t: _ff.effective_time(t, meta) - t)
        safe = re.sub(r"[^\w.\-]+", "_", r["name"] or "subs").strip("._") or "subs"
        fname = f"{safe}.fixed{subs_path.suffix or '.srt'}"
        return Response(content=text, media_type="text/plain; charset=utf-8",
                        headers={"Content-Disposition":
                                 f"attachment; filename*=UTF-8''{_quote(fname)}"})

    @app.delete("/api/source/{sid}")
    def delete_source(sid: int):
        """Drop a source with its sentences; media files it owned under
        data/uploads (extracted audio, uploaded decks) are removed too,
        unless another source still references them."""
        import json as _j
        r = store.db.execute("select * from sources where id=?", (sid,)).fetchone()
        if not r:
            raise HTTPException(404, "no such source")
        store.db.execute("delete from sentences where source_id=?", (sid,))
        store.db.execute("delete from sources where id=?", (sid,))
        store.db.commit()
        meta = _j.loads(r["meta"] or "{}")
        owned = {r["path"] or "", meta.get("audio") or ""}
        others = store.db.execute(
            "select path, meta from sources where id<>?", (sid,)).fetchall()
        for o in others:
            owned -= {o["path"] or ""}
            try:
                owned -= {_j.loads(o["meta"] or "{}").get("audio") or ""}
            except ValueError:
                pass
        updir = (store.path.parent / "uploads").resolve()
        removed = []
        for p in list(owned):
            if not p:
                continue
            try:
                fp = store.resolve_media(p)
                if fp.resolve().parent == updir and fp.is_file():
                    fp.unlink()
                    removed.append(fp.name)
            except OSError:
                pass
        frames = []
        for fdir in (store.path.parent / "media-cache", data_dir / "media-cache"):
            frames += list(fdir.glob(f"src{sid}-*.jpg"))
        for fp in frames:
            try: fp.unlink()
            except OSError: pass
        return {"deleted": sid, "sentences_source": r["kind"],
                "files_removed": removed, "frames_removed": len(frames)}

    @app.get("/api/media/{sid}/{kind}")
    def media(sid: int, kind: str, fmt: str = ""):
        """Serve a sentence's audio/image from its source .apkg — or, for
        video sources, cut it on the fly with ffmpeg. ?fmt= transcodes
        audio (mp3|m4a|wav|ogg) for Save-as."""
        import zipfile as _zip
        from fastapi.responses import Response
        from .apkg import read_media_file
        if kind not in ("audio", "image"):
            raise HTTPException(400, "kind must be audio|image")
        r = store.db.execute(
            "select n.*, s.path, s.kind, s.meta from sentences n"
            " join sources s on s.id=n.source_id where n.id=?", (sid,)).fetchone()
        if not r or not r["path"]:
            raise HTTPException(404, "no source file")
        if r["kind"] == "video":
            import json as _j
            from . import ffmpeg as _ff
            meta = _j.loads(r["meta"] or "{}")
            # audio lives in the project (relative path); legacy sources
            # kept a full video file — resolve both ways
            media_path = store.resolve_media(meta.get("audio") or r["path"])
            if not media_path.exists():
                raise HTTPException(410, "source audio file moved or deleted")
            frame_base = store.path.parent / "media-cache"
            try:
                start, end = float(r["start"]), float(r["end"])
            except (TypeError, ValueError):
                raise HTTPException(404, "cue has no timing")
            try:
                if kind == "audio":
                    ext = fmt if fmt in ("mp3", "m4a", "wav", "ogg") else "mp3"
                    p = _ff.cut_audio(media_path, start, end, ext, meta=meta)
                    return FileResponse(p, filename=f"as-{sid}.{ext}",
                                        headers={"Cache-Control": "private, max-age=3600"})
                p = _ff.cached_frame(r["source_id"], r["ref"], base=frame_base)
                if p is None:
                    legacy = store.resolve_media(r["path"])
                    if legacy.exists() and legacy.suffix.lower() in (
                            ".mp4", ".mkv", ".m4v", ".avi", ".mov", ".webm", ".ts"):
                        # legacy source that still has its video file
                        p = _ff.grab_frame(legacy,
                                           start + (end - start) * 0.4, meta=meta)
                if p is None:
                    raise HTTPException(404, "no frame for this cue "
                                             "(video files are deleted after import)")
                return FileResponse(p, media_type="image/jpeg",
                                    headers={"Cache-Control": "private, max-age=3600"})
            except _sp.CalledProcessError:
                raise HTTPException(500, "ffmpeg failed")
        fname = r["media_audio"] if kind == "audio" else r["media_image"]
        if not fname:
            raise HTTPException(404, f"no {kind} on this sentence")
        if kind == "audio" and fmt in ("mp3", "m4a", "wav", "ogg"):
            from .ffmpeg import transcode_audio
            raw, _ = read_media_file(r["path"], fname)
            src_ext = (fname.rsplit(".", 1)[-1] or "").lower()
            try:
                data = transcode_audio(raw, src_ext, fmt) if src_ext != fmt else raw
            except Exception:
                raise HTTPException(500, "ffmpeg transcode failed")
            ct = {"mp3": "audio/mpeg", "m4a": "audio/mp4",
                  "wav": "audio/wav", "ogg": "audio/ogg"}[fmt]
            return Response(content=data, media_type=ct,
                            headers={"Content-Disposition":
                                     f'attachment; filename="as-{sid}.{fmt}"'})
        try:
            if kind == "image":
                from .media import image_bytes
                data, ctype = image_bytes(r["path"], fname)
            else:
                data, _ = read_media_file(r["path"], fname)
                ext = (fname.rsplit(".", 1)[-1] or "").lower()
                ctype = {"mp3": "audio/mpeg", "m4a": "audio/mp4",
                         "aac": "audio/aac", "ogg": "audio/ogg",
                         "wav": "audio/wav", "webm": "audio/webm"}.get(ext, "application/octet-stream")
        except KeyError:
            raise HTTPException(404, "media missing in package")
        except (OSError, _zip.BadZipFile):
            raise HTTPException(410, "source file moved or unreadable")
        if not data:
            raise HTTPException(404, "media missing in package")
        return Response(content=data, media_type=ctype,
                        headers={"Cache-Control": "private, max-age=3600"})

    # ---------- deck development: points / pool / deck ----------

    @app.get("/api/points")
    def points_list():
        return {"points": [dict(r) for r in store.points()]}

    @app.post("/api/points/import")
    def points_import(req: PointsImportReq):
        import yaml as _y
        text = req.yaml_text
        if not text and req.path:
            _ensure_readable(Path(req.path).expanduser(), "points file")
            text = Path(req.path).expanduser().read_text(encoding="utf-8")
        if not text:
            raise HTTPException(400, "no yaml provided")
        try:
            data = _y.safe_load(text)
        except Exception as e:
            raise HTTPException(400, f"yaml parse error: {e}")
        rows = []
        for pt in data or []:
            pid = pt.get("id")
            if not pid:
                continue
            rows.append({
                "id": str(pid),
                "title": (pt.get("title") or {}).get("en") or pt.get("title") or "",
                "pattern": pt.get("pattern") or "",
                "level": str(pt.get("level") or ""),
                "module": str(pt.get("module") or ""),
                "hints": ",".join(pt.get("target_hint") or [])})
        if not rows:
            raise HTTPException(400, "no points with ids found")
        return {"imported": store.add_points(rows)}

    @app.delete("/api/points/{pid}")
    def points_delete(pid: str):
        store.delete_point(pid)
        return {"deleted": pid}

    @app.post("/api/pool")
    def pool(req: PoolReq):
        """Diverse candidate pool for one point/query: per-source caps and
        length spread fight the 'all short copula fragments' monoculture.
        Candidates are SAMPLED per source with bounded SQL (never a
        full-table load) — stores run to 200k+ sentences."""
        POOL_SAMPLE = 200          # per source; plenty for the diversity pass
        where = ["n.keep=1", "n.decision != 'discarded'"]
        args: list = []
        if req.source:
            where.append("n.source_id=?"); args.append(req.source)
        if req.level:
            where.append("n.level=?"); args.append(req.level)
        if req.q:
            if req.match_mode == "starts":
                where.append("n.text like ?"); args.append(f"{req.q}%")
            elif req.match_mode == "ends":
                where.append("n.text like ?"); args.append(f"%{req.q}")
            elif req.match_mode != "regex":
                where.append("n.text like ?"); args.append(f"%{req.q}%")
        if req.exclude:
            where.append("n.text not like ?"); args.append(f"%{req.exclude}%")
        where.append("n.char_len between ? and ?")
        args += [req.min_len, req.max_len]
        w = " and ".join(where)
        total_matching = store.db.execute(
            f"select count(*) c from sentences n where {w}",
            args).fetchone()["c"]
        # single-pass per-source sample: window row_number over the
        # (source_id, id) index order — no per-source queries, no full
        # materialization of a 200k-row table
        rows = []
        for r in store.db.execute(
                f"select * from (select n.*, s.name source_name,"
                f" row_number() over (partition by n.source_id order by n.id) __rn"
                f" from sentences n join sources s on s.id=n.source_id"
                f" where {w}) where __rn <= ? order by id",
                args + [POOL_SAMPLE]):
            d = dict(r)
            d.pop("__rn", None)
            rows.append(d)
        if req.q and req.match_mode == "regex":
            import re as _re
            try:
                rx = _re.compile(req.q)
            except _re.error:
                raise HTTPException(400, f"bad regex: {req.q}")
            rows = [r for r in rows if rx.search(r["text"] or "")]
        context = f"point:{req.point}" if req.point else "global"
        excluded = store.excluded_for(context)
        rows = [r for r in rows if r["id"] not in excluded]

        def pick_queues(cands: list[dict]) -> list[list[dict]]:
            by_src: dict[int, list] = {}
            for r in cands:
                by_src.setdefault(r["source_id"], []).append(r)
            queues = []
            for src_rows in by_src.values():
                src_rows.sort(key=lambda r: r["char_len"] or 0)
                if req.balanced and len(src_rows) > req.per_show:
                    n = req.per_show
                    picks = [src_rows[int(i * (len(src_rows) - 1) / max(1, n - 1))]
                             for i in range(n)] if n > 1 else src_rows[:1]
                    queues.append(picks)
                else:
                    queues.append(src_rows[:req.per_show])
            return queues

        def drain(queues: list[list[dict]]) -> list[dict]:
            out = []
            while queues and len(out) < req.size:
                nxt = []
                for q in queues:
                    if q and len(out) < req.size:
                        out.append(q.pop(0))
                    if q:
                        nxt.append(q)
                queues = nxt
            return out

        import random as _r
        cands = rows
        if req.exclude_deck:
            in_deck = {r["sentence_id"] for r in store.db.execute(
                "select sentence_id from deck_items")}
            fresh = [r for r in rows if r["id"] not in in_deck]
            if fresh or not rows:
                cands = fresh
        out = drain(pick_queues(cands))
        if len(out) < req.size:
            # per-show caps exist for diversity, not starvation: when few
            # sources match, top the pool up with the best remaining
            # candidates instead of returning a near-empty pool
            chosen = {r["id"] for r in out}
            rest = sorted((r for r in cands if r["id"] not in chosen),
                          key=lambda r: r["char_len"] or 0)
            out.extend(rest[:req.size - len(out)])
        _r.Random(42).shuffle(out)
        if not out and rows:
            # everything sampled is already in the deck — show those cards
            # for curation instead of returning nothing
            return {"pool": rows[:req.size], "total_matching": total_matching,
                    "point": req.point, "note": "showing cards already in deck"}
        return {"pool": out, "total_matching": total_matching, "point": req.point}

    @app.get("/api/deck")
    def deck_list():
        return {"items": [dict(r) for r in store.deck_items()],
                "points": [dict(r) for r in store.points()]}

    @app.post("/api/deck/add")
    def deck_add(req: DeckAddReq):
        return {"item_id": store.deck_add(req.sentence_id, req.point, req.note)}

    @app.post("/api/deck/{item_id}")
    def deck_update(item_id: int, req: DeckUpdateReq):
        store.deck_update(item_id, req.position, req.note, req.point)
        return {"updated": item_id}

    @app.delete("/api/deck/{item_id}")
    def deck_remove(item_id: int):
        store.deck_remove(item_id)
        return {"removed": item_id}

    # ---------- deck redactor: templates + AI explanations ----------

    @app.get("/api/settings")
    def settings_get():
        from .ai import DEFAULTS
        vals = {k: store.get_setting(k, "") for k in DEFAULTS}
        vals.update({k: store.get_setting(k, "") for k in (
            "export_out_dir", "pad_start", "pad_end")})
        vals["project_name"] = store.get_setting("project_name", "")
        return {"values": vals, "defaults": DEFAULTS,
                "ai_configured": bool(vals["ai_base"] and vals["ai_model"])}

    @app.post("/api/settings")
    def settings_set(req: SettingsReq):
        from .ai import DEFAULTS
        allowed = set(DEFAULTS) | {
            "export_out_dir", "pad_start", "pad_end", "project_name"}
        for k, v in req.values.items():
            if k in allowed:
                store.set_setting(k, str(v)[:4000])
        return {"ok": True}

    @app.post("/api/ai/test")
    def ai_test():
        from .ai import chat
        try:
            out = chat(store, [{"role": "user",
                                "content": "Reply with exactly: ok"}],
                       max_tokens=5)
            return {"ok": True, "reply": out[:80]}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/point/{pid}")
    def point_update(pid: str, req: PointUpdateReq):
        r = store.db.execute("select id from grammar_points where id=?",
                             (pid,)).fetchone()
        if not r:
            raise HTTPException(404, "no such point")
        for col in ("template", "boilerplate", "title"):
            val = getattr(req, col)
            if val is not None:
                store.db.execute(
                    f"update grammar_points set {col}=? where id=?", (val, pid))
        if req.note_type_id is not None:
            nt = store.note_type(req.note_type_id)
            if not nt:
                raise HTTPException(404, f"no such note type: {req.note_type_id}")
            store.db.execute(
                "update grammar_points set note_type_id=? where id=?",
                (req.note_type_id, pid))
        store.db.commit()
        return {"ok": True}

    # ---------- note types ----------

    @app.get("/api/note-types")
    def note_types_list():
        import json as _j
        return {"types": [{**dict(r), "fields": _j.loads(r["fields"])}
                          for r in store.note_types()]}

    @app.post("/api/note-types")
    def note_type_create(req: NoteTypeReq):
        import random as _r
        model_id = req.model_id or _r.randint(1600000000, 1699999999)
        tid = store.add_note_type(req.name, model_id, req.fields,
                                  req.css, req.front, req.back)
        return {"id": tid, "model_id": model_id}

    @app.post("/api/note-types/{tid}")
    def note_type_update(tid: int, req: NoteTypeReq):
        nt = store.note_type(tid)
        if not nt:
            raise HTTPException(404, "no such note type")
        kwargs = {}
        if req.name and req.name != nt["name"]:
            if nt["builtin"]:
                raise HTTPException(400, "cannot rename a built-in note type")
            kwargs["name"] = req.name
        for k in ("css", "front", "back"):
            v = getattr(req, k)
            if v is not None:
                kwargs[k] = v
        if req.fields:
            kwargs["fields"] = req.fields
        if kwargs:
            store.update_note_type(tid, **kwargs)
        return {"ok": True}

    @app.delete("/api/note-types/{tid}")
    def note_type_delete(tid: int):
        if not store.delete_note_type(tid):
            raise HTTPException(400, "cannot delete a built-in note type,"
                                     " or it does not exist")
        return {"deleted": tid}

    @app.post("/api/boilerplate-apply")
    def boilerplate_apply(req: TemplateApplyReq):
        """Prepend the point's boilerplate to every card of the block that
        doesn't already have it (idempotent — re-applying changes nothing).
        Per-card notes survive below the boilerplate."""
        r = store.db.execute(
            "select boilerplate from grammar_points where id=?",
            (req.point,)).fetchone()
        bp = (r["boilerplate"] or "").strip() if r else ""
        if not r or not bp:
            raise HTTPException(400, "this point has no boilerplate yet")
        items = store.db.execute(
            "select d.id, d.note from deck_items d"
            " join sentences n on n.id=d.sentence_id"
            " where d.point=? order by d.position, d.id",
            (req.point,)).fetchall()
        updated = 0
        for it in items:
            note = (it["note"] or "").strip()
            if bp in note:
                continue
            new_note = bp + ("\n\n" + note if note else "")
            store.deck_update(it["id"], note=new_note)
            updated += 1
        return {"updated": updated, "total": len(items)}

    @app.post("/api/template-apply")
    def deck_template_apply(req: TemplateApplyReq):
        """Fill every EMPTY note of a point's cards from the point's
        template. Placeholders: {sentence} {reading} {translation} {title}
        {pattern} {level} {source} {episode}."""
        r = store.db.execute(
            "select id, title, pattern, level, template from grammar_points"
            " where id=?", (req.point,)).fetchone()
        if not r or not (r["template"] or "").strip():
            raise HTTPException(400, "this point has no template yet")
        items = store.db.execute(
            "select d.id, d.note, n.text, n.reading, n.translation,"
            " n.episode, s.name source_name from deck_items d"
            " join sentences n on n.id=d.sentence_id"
            " join sources s on s.id=n.source_id"
            " where d.point=? order by d.position, d.id",
            (req.point,)).fetchall()
        filled = 0
        for it in items:
            if (it["note"] or "").strip():
                continue
            note = r["template"].format(
                sentence=it["text"] or "", reading=it["reading"] or "",
                translation=it["translation"] or "", title=r["title"] or "",
                pattern=r["pattern"] or "", level=r["level"] or "",
                source=it["source_name"] or "", episode=it["episode"] or "")
            store.deck_update(it["id"], note=note)
            filled += 1
        return {"filled": filled, "total": len(items)}

    @app.post("/api/ai/fill")
    def ai_fill(req: AIFillReq):
        """Explain one deck card through the configured AI API."""
        from .ai import chat, DEFAULTS
        it = store.db.execute(
            "select d.id, d.note, d.point, n.text, n.reading, n.translation,"
            " s.name source_name from deck_items d"
            " join sentences n on n.id=d.sentence_id"
            " join sources s on s.id=n.source_id where d.id=?",
            (req.item_id,)).fetchone()
        if not it:
            raise HTTPException(404, "no such deck item")
        pt = store.db.execute(
            "select id, title, pattern, level, template from grammar_points"
            " where id=?", (it["point"] or "",)).fetchone()
        ctx = (f"Grammar point: {pt['id']} — {pt['title'] or ''}"
               f" (pattern: {pt['pattern'] or '—'})\n"
               if pt else "Grammar point: (none)\n") + \
            f"Sentence: {it['text']}\n" + \
            (f"Reading: {it['reading']}\n" if it["reading"] else "") + \
            (f"Translation: {it['translation']}\n" if it["translation"] else "")
        user = ctx + (f"\nInstruction: {req.instruction}"
                      if req.instruction else "")
        try:
            text = chat(store, [
                {"role": "system",
                 "content": store.get_setting("ai_prompt_card",
                                              DEFAULTS["ai_prompt_card"])},
                {"role": "user", "content": user}])
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"note": text}

    @app.post("/api/ai/fill-block")
    def ai_fill_block(req: AIBlockReq):
        """Explain a whole block (grammar point) in ONE API call — the
        model returns a JSON array keyed by card number, same order."""
        from .ai import chat, extract_json_array, DEFAULTS
        ptsql = "select id, title, pattern from grammar_points where id=?"
        pt = store.db.execute(ptsql, (req.point,)).fetchone()
        items = store.db.execute(
            "select d.id, d.note, n.text from deck_items d"
            " join sentences n on n.id=d.sentence_id"
            " where d.point=? order by d.position, d.id",
            (req.point,)).fetchall()
        if req.only_empty:
            items = [i for i in items if not (i["note"] or "").strip()]
        if not items:
            return {"updated": 0, "message": "no cards without notes"}
        listing = "\n".join(f"{n}. {i['text']}"
                            for n, i in enumerate(items, 1))
        header = (f"Grammar point: {pt['id']} — {pt['title'] or ''}"
                  f" (pattern: {pt['pattern'] or '—'})\n" if pt else "")
        user = header + "Sentences:\n" + listing + \
            (f"\n\nInstruction: {req.instruction}" if req.instruction else "")
        try:
            reply = chat(store, [
                {"role": "system",
                 "content": store.get_setting("ai_prompt_block",
                                              DEFAULTS["ai_prompt_block"])},
                {"role": "user", "content": user}], max_tokens=200 * len(items))
            parsed = extract_json_array(reply)
        except ValueError as e:
            raise HTTPException(400, str(e))
        updated = 0
        for obj in parsed:
            try:
                n = int(obj.get("n", 0))
                note = str(obj.get("note", "")).strip()
                if 1 <= n <= len(items) and note:
                    store.deck_update(items[n - 1]["id"], note=note)
                    updated += 1
            except (TypeError, ValueError):
                continue
        return {"updated": updated, "cards": len(items)}

    # ---------- project (.aproj) ----------

    @app.post("/api/project/open")
    def project_open(req: ProjectOpenReq):
        """Open an .aproj from anywhere on disk. If its extracted working
        copy in data/projects/ holds NEWER work, the working copy is
        resumed instead of being clobbered by the older snapshot."""
        return _open_aproj(Path(req.path).expanduser())

    @app.post("/api/project/open-db")
    def project_open_db(req: ProjectOpenReq):
        """Switch straight to a project's working db (from /api/projects)."""
        import zipfile as _z
        p = Path(req.path).expanduser().resolve()
        projects_root = (data_dir / "projects").resolve()
        # layout is data/projects/<stem>/project.db — the file's
        # GRANDparent is the projects root
        if p.parent.parent != projects_root or p.name != "project.db" \
                or not p.exists():
            raise HTTPException(404, "no such working project")
        _reopen(p)
        return {"opened": str(p), "resumed": True,
                "name": store.get_setting("project_name", p.parent.name)}

    @app.post("/api/project/merge-deck")
    def project_merge_deck(req: ProjectOpenReq):
        """Merge a collaborator's deck edits (notes, templates, boilerplate,
        pool decisions) into the CURRENT project. Safe to run while
        harvesting: it only updates existing rows and upserts decisions —
        rows that exist only on one side (their new cards, your new
        harvest) are left alone. Accepts an .aproj or a working db path."""
        import json as _j
        import zipfile as _z
        import tempfile as _t
        import sqlite3 as _sq
        p = Path(req.path).expanduser()
        if not p.exists():
            raise HTTPException(404, f"no such file: {p}")
        if p.suffix == ".aproj":
            try:
                with _z.ZipFile(p) as z, _t.TemporaryDirectory() as td:
                    z.extract("project.db", td)
                    theirs = _sq.connect(f"file:{Path(td) / 'project.db'}?mode=ro", uri=True)
            except (_z.BadZipFile, KeyError):
                raise HTTPException(400, "not an AnkiStudio .aproj")
        else:
            theirs = _sq.connect(f"file:{p}?mode=ro", uri=True)
        theirs.row_factory = _sq.Row
        # sanity: same project lineage?
        try:
            sig = theirs.execute("select count(*) c from grammar_points").fetchone()["c"]
        except _sq.OperationalError:
            raise HTTPException(400, "not a project database")
        stats = {}
        with store._lock:
            # deck note/point updates by id (ids are stable in a fork)
            rows = [dict(r) for r in theirs.execute(
                "select id, note, point, position from deck_items")]
            upd = 0
            for r in rows:
                cur = store.db.execute(
                    "select note, point, position from deck_items where id=?",
                    (r["id"],)).fetchone()
                if cur and (r["note"] or "") != (cur["note"] or ""):
                    store.db.execute(
                        "update deck_items set note=? where id=?", (r["note"], r["id"]))
                    upd += 1
            stats["notes_updated"] = upd
            # grammar point templates / boilerplate / titles
            upd = 0
            for r in theirs.execute(
                    "select id, title, template, boilerplate from grammar_points"):
                cur = store.db.execute(
                    "select title, template, boilerplate from grammar_points where id=?",
                    (r["id"],)).fetchone()
                if not cur:
                    continue
                t = r["template"] if (r["template"] or "") != "" else cur["template"]
                b = r["boilerplate"] if (r["boilerplate"] or "") != "" else cur["boilerplate"]
                ti = r["title"] if (r["title"] or "") != "" else cur["title"]
                if (t, b, ti) != (cur["template"], cur["boilerplate"], cur["title"]):
                    store.db.execute(
                        "update grammar_points set title=?, template=?, boilerplate=?"
                        " where id=?", (ti, t, b, r["id"]))
                    upd += 1
            stats["points_updated"] = upd
            # their pool decisions (their rejections are valuable curation)
            upd = 0
            for r in theirs.execute(
                    "select sentence_id, context, decision from pool_decisions"):
                cur = store.db.execute(
                    "select decision from pool_decisions where sentence_id=?"
                    " and context=?", (r["sentence_id"], r["context"])).fetchone()
                if cur is None:
                    store.db.execute(
                        "insert into pool_decisions values (?,?,?,?)",
                        (r["sentence_id"], r["context"], r["decision"], 0))
                    upd += 1
            stats["decisions_imported"] = upd
            store.db.commit()
        theirs.close()
        return stats

    @app.post("/api/project/close")
    def project_close():
        """Back to the default working project (data/studio.db)."""
        _reopen(default_db)
        pointer.unlink(missing_ok=True)
        return {"closed": True, "db": str(default_db)}

    @app.get("/api/project/media-check")
    def project_media_check():
        """Is the current project's media intact? Per source: audio track
        present, frame images present vs expected. The .aproj snapshot
        carries the DATABASE — audio and frames live in the project
        folder beside it, which is exactly what this verifies."""
        import json as _j
        out = []
        audio_bytes = 0
        frame_base = store.path.parent / "media-cache"
        for r in store.db.execute(
                "select id, name, kind, path, meta from sources order by id"):
            row = {"id": r["id"], "name": r["name"], "kind": r["kind"]}
            if r["kind"] == "video":
                meta = _j.loads(r["meta"] or "{}")
                audio = store.resolve_media(meta.get("audio") or r["path"])
                row["audio_ok"] = audio.is_file()
                if row["audio_ok"]:
                    audio_bytes += audio.stat().st_size
                row["frames_expected"] = store.db.execute(
                    "select count(*) c from sentences where source_id=?"
                    " and keep=1 and media_image='frame'", (r["id"],)
                ).fetchone()[0]
                row["frames_have"] = len(list(
                    frame_base.glob(f"src{r['id']}-*.jpg")))
            out.append(row)
        return {"sources": out,
                "audio_missing": sum(1 for s in out
                                     if s.get("audio_ok") is False),
                "audio_total_mb": round(audio_bytes / 1e6, 1),
                "frames_total": sum(s.get("frames_have", 0) for s in out),
                "frames_expected": sum(s.get("frames_expected", 0) for s in out)}

    @app.get("/api/project/save")
    def project_save(path: str = "", name: str = ""):
        """Save the project. Without a path, saves in-place to the
        project's own .aproj (same as autosave). With a path, saves there."""
        name = name or store.get_setting("project_name",
                                         store.path.parent.name
                                         if store.path.parent.parent == data_dir / "projects"
                                         else "ankistudio")
        if path:
            out = Path(path).expanduser()
            if not str(out).endswith(".aproj"):
                out = out / f"{name}.aproj"
        else:
            # in-place: overwrite the project's own .aproj
            out = data_dir / "projects" / f"{name}.aproj"
        out.parent.mkdir(parents=True, exist_ok=True)
        _write_aproj(out, name)
        return {"path": str(out)}

    @app.post("/api/project/save-as")
    def project_save_as(name: str = ""):
        """Build the .aproj server-side and return a download URL — the
        browser's save dialog puts it anywhere the user wants."""
        import uuid as _uuid
        name = name or store.get_setting("project_name",
                                         store.path.parent.name
                                         if store.path.parent != data_dir
                                         else "ankistudio")
        out = data_dir / "tmp"
        out.mkdir(parents=True, exist_ok=True)
        f = out / f"{_uuid.uuid4().hex[:8]}-{name}.aproj"
        _write_aproj(f, name)
        return {"path": str(f), "name": name}

    @app.get("/api/projects")
    def projects_list():
        """Everything openable: working copies under data/projects/ (live
        state, mtimes tell which is freshest), their .aproj snapshots, and
        the default working project."""
        import json as _j
        import zipfile as _z
        from datetime import datetime as _dt
        projs_dir = data_dir / "projects"
        entries = []
        cur_path = store.path.resolve()
        if projs_dir.is_dir():
            for d in sorted(projs_dir.iterdir()):
                wdb = d / "project.db"
                if not wdb.exists():
                    continue
                meta = {"name": d.name, "kind": "working",
                        "db": str(wdb), "mtime": wdb.stat().st_mtime,
                        "current": wdb.resolve() == cur_path}
                try:
                    ro = sqlite3.connect(f"file:{wdb}?mode=ro", uri=True)
                    meta["sentences"] = ro.execute(
                        "select count(*) c from sentences").fetchone()[0]
                    meta["deck"] = ro.execute(
                        "select count(*) c from deck_items").fetchone()[0]
                    meta["points"] = ro.execute(
                        "select count(*) c from grammar_points").fetchone()[0]
                    ro.close()
                except Exception:
                    pass
                hist_dir = d / "history"
                if hist_dir.is_dir():
                    meta["history"] = len(list(hist_dir.glob("*.aproj")))
                entries.append(meta)
        for f in sorted(projs_dir.glob("*.aproj")) if projs_dir.is_dir() else []:
            try:
                with _z.ZipFile(f) as z:
                    m = _j.loads(z.read("manifest.json"))
                entries.append({"name": f.stem, "kind": "archive",
                                "file": str(f), "mtime": f.stat().st_mtime,
                                "manifest_name": m.get("name", f.stem),
                                "sentences": m.get("sentences"),
                                "points": m.get("points")})
            except Exception:
                entries.append({"name": f.stem, "kind": "archive",
                                "file": str(f), "mtime": f.stat().st_mtime,
                                "error": True})
        entries.sort(key=lambda e: e["mtime"], reverse=True)
        return {"projects": entries, "current": {
            "db": str(store.path), "name": store.get_setting(
                "project_name", store.path.parent.name
                if store.path.parent != data_dir else "working project"),
            "is_default": store.path.resolve() == default_db.resolve(),
            "live": True,
            "sources": len(store.sources()),
            "points": len(store.points())}}

    # autosave: while a project db is open, keep its .aproj snapshot in
    # data/projects/ fresh (~20s after changes) so a crash or a stray
    # reopen can never lose more than seconds of review work. Once an
    # hour (when work happened) the previous snapshot is moved into the
    # project's history/ folder first — manual saves and old states stay
    # recoverable instead of being overwritten forever.
    import threading
    import time as _time

    def _rotate_history(fresh: Path, keep: int = 24):
        """Move the current snapshot into history/<timestamp>.aproj and
        prune to the newest `keep` versions."""
        hist = fresh.parent / fresh.stem / "history"
        hist.mkdir(parents=True, exist_ok=True)
        stamp = _time.strftime("%Y%m%d-%H%M%S")
        fresh.replace(hist / f"{stamp}{fresh.suffix}")
        versions = sorted(hist.glob(f"*{fresh.suffix}"))
        for old in versions[:-keep]:
            try:
                old.unlink()
            except OSError:
                pass

    def _autosave_loop():
        import sys
        import traceback
        last_changes = None
        last_rotation = 0.0
        while True:
            _time.sleep(20)
            try:
                # layout: data/projects/<stem>/project.db — compare the
                # grandparent, not the direct parent
                if store.path.parent.parent == data_dir / "projects":
                    ch = store.db.total_changes
                    fresh = data_dir / "projects" / f"{store.path.parent.name}.aproj"
                    if ch != last_changes:
                        last_changes = ch
                        if fresh.exists() and _time.time() - last_rotation >= 3600:
                            _rotate_history(fresh)
                            last_rotation = _time.time()
                        _write_aproj(fresh, store.path.parent.name)
            except Exception:
                # never kill the loop — but leave a trace in the server log
                traceback.print_exc(file=sys.stderr)

    threading.Thread(target=_autosave_loop, daemon=True).start()

    @app.post("/api/pool-decide")
    def pool_decide(req: PoolDecideReq):
        if req.decision not in ("approved", "discarded", ""):
            raise HTTPException(400, "decision must be approved|discarded|''")
        store.pool_decide(req.sentence_id, req.context, req.decision)
        return {"ok": True}

    @app.post("/api/classify")
    def classify(req: ClassifyReq):
        from .classify import classify_store
        try:
            return classify_store(store, req.lexicon_id)
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/export")
    def export(req: ExportReq):
        from .exporter import build_deck
        def pad(v):
            return max(0.0, min(5.0, v)) if v is not None else None
        res = build_deck(store, req.name, req.preset, req.status,
                         req.source, req.level, out_dir=req.out_dir,
                         pad_start=pad(req.pad_start), pad_end=pad(req.pad_end),
                         subdecks=req.subdecks)
        if "error" in res:
            raise HTTPException(400, res["error"])
        return res

    @app.get("/api/export/file")
    def export_file(name: str):
        from fastapi.responses import FileResponse
        p = Path(name)
        if not p.is_absolute():
            p = Path.cwd() / p
        # only hand out files the app itself produces, under the project
        # dir or the temp dirs — never an arbitrary path on disk
        import tempfile as _tempfile
        bases = [Path.cwd(), Path("/tmp"), Path(_tempfile.gettempdir())]
        allowed = False
        for base in bases:
            try:
                p.resolve().relative_to(base.resolve())
                allowed = True
                break
            except ValueError:
                continue
        if not allowed:
            raise HTTPException(403, "refusing to serve files outside the "
                                     "project and temp directories")
        if not p.exists():
            raise HTTPException(404, "no such export")
        return FileResponse(p, filename=p.name)

    # ---------- static ui ----------

    @app.get("/")
    def index():
        # no-cache: the UI shell must always revalidate so app updates
        # appear on a normal reload instead of a hard one
        return FileResponse(STATIC / "index.html",
                            headers={"Cache-Control": "no-cache"})

    return app
