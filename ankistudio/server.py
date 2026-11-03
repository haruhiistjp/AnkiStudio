"""FastAPI app: JSON API + static UI. Run with `ankistudio serve`."""
from __future__ import annotations

import re
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

from .importer import import_apkg, import_freq_apkg, import_freq_tsv
from .store import Store

STATIC = Path(__file__).resolve().parent.parent / "static"


def create_app(db_path: str | Path) -> FastAPI:
    app = FastAPI(title="AnkiStudio")
    store = Store(db_path)

    # ---------- api ----------

    @app.get("/api/stats")
    def stats():
        return {"stats": store.stats(),
                "sources": [dict(r) for r in store.sources()],
                "lexicons": [dict(r) for r in store.lexicons()]}

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
        """Card browser. Filters + sort + pagination. Level filtering runs in
        Python (lexicon words are checked against sentence text)."""
        import json as _json
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
        rows = [dict(r) for r in store.db.execute(
            f"select n.*, s.name source_name from sentences n"
            f" join sources s on s.id=n.source_id where {' and '.join(where)}",
            args)]
        if req.q and req.match_mode == "regex":
            import re as _re
            try:
                rx = _re.compile(req.q)
            except _re.error:
                raise HTTPException(400, f"bad regex: {req.q}")
            rows = [r for r in rows if rx.search(r["text"] or "")]
        if level:
            # exact: level is precomputed by POST /api/classify
            rows = [r for r in rows if r["level"] == level]
        keyfns = {
            "len": lambda r: (r["char_len"] or 0, r["id"]),
            "len_desc": lambda r: (-(r["char_len"] or 0), r["id"]),
            "source": lambda r: (r["source_id"], r["char_len"] or 0),
            "recent": lambda r: -r["id"],
        }
        rows.sort(key=keyfns.get(sort, keyfns["len"]))
        total = len(rows)
        start = (page - 1) * per
        return {"total": total, "page": page, "per": per,
                "rows": rows[start:start + per]}


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

        r = store.db.execute("select id, kind from sources where id=?",
                             (sid,)).fetchone()
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
                fp = Path(p)
                if fp.resolve().parent == updir and fp.is_file():
                    fp.unlink()
                    removed.append(fp.name)
            except OSError:
                pass
        frames = list((Path("data/media-cache")).glob(f"src{sid}-*.jpg"))
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
            # current sources keep only the extracted audio track; older
            # ones point at a full video file
            media_path = Path(meta["audio"]) if meta.get("audio") else Path(r["path"])
            if not media_path.exists():
                raise HTTPException(410, "source audio file moved or deleted")
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
                p = _ff.cached_frame(r["source_id"], r["ref"])
                if p is None and Path(r["path"]).exists():
                    # legacy source that still has its video file
                    p = _ff.grab_frame(Path(r["path"]),
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
        length spread fight the 'all short copula fragments' monoculture."""
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
        rows = [dict(r) for r in store.db.execute(
            f"select n.*, s.name source_name from sentences n"
            f" join sources s on s.id=n.source_id where {' and '.join(where)}",
            args)]
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
        if req.exclude_deck:
            in_deck = {r["sentence_id"] for r in store.db.execute(
                "select sentence_id from deck_items")}
            rows = [r for r in rows if r["id"] not in in_deck]
        # per-source cap with optional length spread: split each source's
        # candidates into quantiles and take round-robin from them
        by_src: dict[int, list] = {}
        for r in rows:
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
        out = []
        while queues and len(out) < req.size:
            nxt = []
            for q in queues:
                if q and len(out) < req.size:
                    out.append(q.pop(0))
                if q:
                    nxt.append(q)
            queues = nxt
        # shuffle lightly so review isn't length-sorted per show
        import random as _r
        _r.Random(42).shuffle(out)
        if not out and req.exclude_deck and rows:
            # everything is already in the deck — show existing cards for
            # curation instead of returning nothing
            in_deck = {r["sentence_id"] for r in store.db.execute(
                "select sentence_id from deck_items")}
            for src_rows in by_src.values():
                src_rows.sort(key=lambda r: r["char_len"] or 0)
                if req.balanced and len(src_rows) > req.per_show:
                    n = req.per_show
                    picks = [src_rows[int(i * (len(src_rows) - 1) / max(1, n - 1))]
                             for i in range(n)] if n > 1 else src_rows[:1]
                    queues.append(picks)
                else:
                    queues.append(src_rows[:req.per_show])
            # need to rebuild from all rows (not the deck-filtered ones)
            all_rows = [dict(r) for r in store.db.execute(
                f"select n.*, s.name source_name from sentences n"
                f" join sources s on s.id=n.source_id where {' and '.join(where)}",
                args)]
            # apply pool_decisions filter only
            excluded = store.excluded_for(context)
            all_rows = [r for r in all_rows if r["id"] not in excluded]
            by_src2 = {}
            for r in all_rows:
                by_src2.setdefault(r["source_id"], []).append(r)
            queues = []
            for src_rows in by_src2.values():
                src_rows.sort(key=lambda r: r["char_len"] or 0)
                if req.balanced and len(src_rows) > req.per_show:
                    n = req.per_show
                    picks = [src_rows[int(i * (len(src_rows) - 1) / max(1, n - 1))]
                             for i in range(n)] if n > 1 else src_rows[:1]
                    queues.append(picks)
                else:
                    queues.append(src_rows[:req.per_show])
            out = []
            while queues and len(out) < req.size:
                nxt = []
                for q in queues:
                    if q and len(out) < req.size:
                        out.append(q.pop(0))
                    if q:
                        nxt.append(q)
                queues = nxt
            _r.Random(42).shuffle(out)
            return {"pool": out, "total_matching": len(all_rows),
                    "point": req.point, "note": "showing cards already in deck"}
        return {"pool": out, "total_matching": len(rows), "point": req.point}

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

    # ---------- project (.aproj) ----------

    @app.get("/api/project/save")
    def project_save(path: str = "", name: str = "ankistudio"):
        """Snapshot the live store into a portable .aproj (zip: manifest +
        project.db). Media stays in its sources; the file references them."""
        import json as _j
        import zipfile as _z
        import tempfile as _t
        out = Path(path).expanduser() if path else None
        if out and not str(out).endswith(".aproj"):
            out = out / f"{name}.aproj"
        if not out:
            result = Path("result"); result.mkdir(exist_ok=True)
            out = result / f"{name}.aproj"
        out.parent.mkdir(parents=True, exist_ok=True)
        with _t.TemporaryDirectory() as td:
            dbfile = Path(td) / "project.db"
            store.snapshot_to(dbfile)
            manifest = {
                "format": "ankistudio-project", "version": 1,
                "name": name,
                "created": __import__("datetime").datetime.now().isoformat(),
                "app": "AnkiStudio",
                "sources": [dict(r) for r in store.sources()],
            }
            with _z.ZipFile(out, "w", _z.ZIP_DEFLATED) as z:
                z.writestr("manifest.json", _j.dumps(manifest, ensure_ascii=False, indent=1))
                z.write(dbfile, "project.db")
        return {"path": str(out)}

    @app.post("/api/project/open")
    def project_open(req: ProjectOpenReq):
        import zipfile as _z
        import tempfile as _t
        p = Path(req.path).expanduser()
        if not p.exists() or p.suffix != ".aproj":
            raise HTTPException(404, f"not an .aproj file: {p}")
        try:
            with _z.ZipFile(p) as z:
                names = z.namelist()
                if "project.db" not in names or "manifest.json" not in names:
                    raise ValueError("not an AnkiStudio project archive")
                dest_dir = Path("data/projects") / p.stem
                dest_dir.mkdir(parents=True, exist_ok=True)
                z.extract("project.db", dest_dir)
                manifest = __import__("json").loads(z.read("manifest.json"))
        except (_z.BadZipFile, ValueError) as e:
            raise HTTPException(400, f"bad .aproj: {e}")
        store.reopen(dest_dir / "project.db")
        return {"opened": str(p), "name": manifest.get("name"),
                "sources": manifest.get("sources", 0)}

    # ---------- projects ----------

    @app.get("/api/projects")
    def projects_list():
        """All .aproj files in data/projects/ + the live db."""
        import glob as _g
        projs = []
        for f in sorted(Path("data/projects").glob("*.aproj")):
            try:
                import zipfile as _z, json as _j
                with _z.ZipFile(f) as z:
                    m = _j.loads(z.read("manifest.json"))
                projs.append({"file": str(f), "name": m.get("name", f.stem),
                              "points": m.get("points"), "sentences": m.get("sentences"),
                              "converter": m.get("converter", "")})
            except Exception:
                projs.append({"file": str(f), "name": f.stem, "error": True})
        # the live db is also a project (unsaved)
        live_name = store.get_setting("project_name", "working project")
        return {"projects": projs, "current": {
            "name": live_name, "live": True,
            "sources": len(store.sources()),
            "points": len(store.points())}}

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
        if req.preset not in ("immersion", "reading"):
            raise HTTPException(400, "preset must be immersion|reading")

        def pad(v):
            return max(0.0, min(5.0, v)) if v is not None else None
        res = build_deck(store, req.name, req.preset, req.status,
                         req.source, req.level, out_dir=req.out_dir,
                         pad_start=pad(req.pad_start), pad_end=pad(req.pad_end))
        if "error" in res:
            raise HTTPException(400, res["error"])
        return res

    @app.get("/api/export/file")
    def export_file(name: str):
        from fastapi.responses import FileResponse
        p = Path(name)
        if not p.is_absolute():
            p = Path.cwd() / p
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
