"""FastAPI app: JSON API + static UI. Run with `ankistudio serve`."""
from __future__ import annotations

import re
import subprocess as _sp
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel


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


class ClassifyReq(BaseModel):
    lexicon_id: int


class VideoReq(BaseModel):
    video: str
    subs: str
    offset: float = 0.0
    name: str | None = None


class ShiftReq(BaseModel):
    offset: float = 0.0
    segments: list[dict] = []      # [{at: seconds, shift: seconds}] absolute


class ExportReq(BaseModel):
    name: str = "AnkiStudio export"
    preset: str = "immersion"      # immersion | reading
    status: str = "approved"       # approved | pending | all
    source: int = 0
    level: str = ""

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
        return import_apkg(store, p, max_chars=req.max_chars)

    @app.post("/api/import/freq-tsv")
    def freq_tsv(req: FreqTsvReq):
        p = Path(req.path).expanduser()
        if not p.exists():
            raise HTTPException(404, f"no such file: {p}")
        lid = import_freq_tsv(store, p, word_col=req.word_col,
                              level_col=req.level_col)
        return {"lexicon_id": lid}

    @app.post("/api/import/freq-apkg")
    def freq_apkg(req: FreqApkgReq):
        p = Path(req.path).expanduser()
        if not p.exists():
            raise HTTPException(404, f"no such file: {p}")
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
        try:
            return _iv(store, v, b, offset=req.offset, name=req.name)
        except ValueError as e:
            raise HTTPException(400, str(e))

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
        r = store.db.execute("select meta from sources where id=?", (sid,)).fetchone()
        if not r:
            raise HTTPException(404, "no such source")
        meta = _j.loads(r["meta"] or "{}")
        meta["offset"] = req.offset
        meta["segments"] = sorted(req.segments, key=lambda g: g.get("at", 0))
        store.db.execute("update sources set meta=? where id=?",
                         (_j.dumps(meta), sid))
        store.db.commit()
        return meta

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
            video = Path(r["path"])
            if not video.exists():
                raise HTTPException(410, "video moved or deleted")
            try:
                start, end = float(r["start"]), float(r["end"])
            except (TypeError, ValueError):
                raise HTTPException(404, "cue has no timing")
            try:
                if kind == "audio":
                    ext = fmt if fmt in ("mp3", "m4a", "wav", "ogg") else "mp3"
                    p = _ff.cut_audio(video, start, end, ext, meta=meta)
                    return FileResponse(p, filename=f"as-{sid}.{ext}",
                                        headers={"Cache-Control": "private, max-age=3600"})
                p = _ff.grab_frame(video, start + (end - start) * 0.4, meta=meta)
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
        res = build_deck(store, req.name, req.preset, req.status,
                         req.source, req.level)
        if "error" in res:
            raise HTTPException(400, res["error"])
        return res

    @app.get("/api/export/file")
    def export_file(name: str):
        from fastapi.responses import FileResponse
        p = Path(name)
        if not p.is_absolute():
            p = Path.cwd() / p
        if not p.exists() or p.parent.name not in ("result",):
            raise HTTPException(404, "no such export")
        return FileResponse(p, filename=p.name)

    # ---------- static ui ----------

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app
