"""FastAPI app: JSON API + static UI. Run with `ankistudio serve`."""
from __future__ import annotations

import re
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
            lex = store.lexicons()
            if lex:
                wmap = store.lexicon_word_map(lex[0]["id"])
                order = _json.loads(lex[0]["level_order"] or "[]")
                pos = {l: i for i, l in enumerate(order)}
                wanted = pos.get(level, 0)
                hard = [w for w, l in wmap.items()
                        if pos.get(l, 99) > wanted and len(w) >= 2]
                def ok(r):
                    return not any(w in r["text"] for w in hard)
                rows = [r for r in rows if ok(r)]
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

    # ---------- static ui ----------

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app
