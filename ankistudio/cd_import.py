"""Convert the CureDolly project into an AnkiStudio .aproj file.

Reads (read-only!) from the CureDolly repo:
  - data/inventory/points.yaml          -> grammar_points
  - data/examples/level{1..4}.yaml       -> sentences + deck_items (approved only)
  - data/sources/index.yaml             -> source deck file mapping
  - build/index.sqlite                  -> clip text/media lookup

Writes: <out>.aproj (zip: manifest.json + project.db)
"""
from __future__ import annotations

import json
import sqlite3
import zipfile
import tempfile
import datetime
from pathlib import Path

import yaml

from .store import Store, SCHEMA


def convert_curedolly(cd_home: str | Path, out_path: str | Path,
                      project_name: str = "CureDolly") -> dict:
    cd = Path(cd_home)
    out = Path(out_path)
    if not out.suffix == ".aproj":
        out = out / f"{project_name}.aproj"

    # -- connect to the CD index for clip lookups ------------------------
    cdb = sqlite3.connect(cd / "build" / "index.sqlite")
    cdb.row_factory = sqlite3.Row

    # -- create the project database in memory ---------------------------
    tmp = Path(tempfile.mkdtemp()) / "project.db"
    store = Store(tmp)
    store.set_setting("project_name", project_name)
    store.set_setting("language", "ja")

    # -- grammar points ---------------------------------------------------
    points = yaml.safe_load(
        (cd / "data" / "inventory" / "points.yaml").read_text(encoding="utf-8"))
    pt_rows = []
    for p in points:
        pt_rows.append({
            "id": p["id"],
            "title": (p.get("title") or {}).get("en", ""),
            "pattern": p.get("pattern", ""),
            "level": str(p.get("level", "")),
            "module": str(p.get("module", "")),
            "hints": ",".join(p.get("target_hint") or []),
        })
    store.add_points(pt_rows)

    # -- deck filename map ------------------------------------------------
    idx = yaml.safe_load(
        (cd / "data" / "sources" / "index.yaml").read_text(encoding="utf-8"))
    deck_files = {d["id"]: d["deck"] for d in idx["decks"]}

    # -- approved examples -> sentences + deck_items -----------------------
    src_ids: dict[str, int] = {}       # deck short_id -> AnkiStudio source_id
    n_sent = n_item = n_skip = 0
    seen_clip: set[int] = set()         # one sentence per clip

    import glob
    for f in sorted(glob.glob(str(cd / "data" / "examples" / "level*.yaml"))):
        for e in yaml.safe_load(open(f, encoding="utf-8")) or []:
            if e.get("status") != "approved":
                continue
            # resolve the clip
            ref = e.get("source_ref", "")
            if not ref.startswith("clip:"):
                n_skip += 1
                continue
            clip_id = int(ref.split(":", 1)[1])
            if clip_id in seen_clip:
                # same clip approved for multiple points: keep the sentence,
                # add a deck_item under the other point
                pass
            clip = cdb.execute(
                "select * from clips where id=?", (clip_id,)).fetchone()
            if clip is None or not clip["keep"]:
                n_skip += 1
                continue

            deck_sid = e.get("deck", "")
            if deck_sid not in deck_files:
                n_skip += 1
                continue
            if deck_sid not in src_ids:
                apkg_name = deck_files[deck_sid]
                src_ids[deck_sid] = store.add_source(
                    "apkg", apkg_name.replace(".apkg", ""),
                    str(cd / "source" / apkg_name),
                    {"deck_id": deck_sid, "curedolly": True})
            sid = src_ids[deck_sid]

            if clip_id not in seen_clip:
                import re as _re
                text = clip["jp_norm"] or ""
                char_len = len(_re.sub(r"\W", "", text, flags=_re.UNICODE))
                store.db.execute(
                    "insert into sentences(source_id,ref,text,reading,translation,"
                    "episode,start,end,media_audio,media_image,char_len,flags,keep,"
                    "drop_code,decision,decided_at,level,known)"
                    " values (?,?,?,?,?,?,?,?,?,?,?,'',1,'','approved',?,?,'{}')",
                    (sid, str(clip["note_id"]), text,
                     clip["reading_norm"] or "",
                     clip["translation_raw"] or "",
                     clip["episode"] or "",
                     clip["start"] or "", clip["end"] or "",
                     clip["audio_file"] or "",
                     clip["image_file"] or "",
                     char_len, None,
                     f"L{e.get('level', '')}"))
                seen_clip.add(clip_id)
                n_sent += 1
                sentence_id = store.db.execute(
                    "select last_insert_rowid()").fetchone()[0]
            else:
                sentence_id = store.db.execute(
                    "select id from sentences where source_id=? and ref=?",
                    (sid, str(clip["note_id"]))).fetchone()
                if sentence_id:
                    sentence_id = sentence_id[0]
                else:
                    n_skip += 1
                    continue

            store.deck_add(sentence_id, e.get("point", ""),
                           note=e.get("gloss") or "")
            n_item += 1
    store.db.commit()

    # -- package ------------------------------------------------------------
    manifest = {
        "format": "ankistudio-project", "version": 1,
        "name": project_name,
        "created": datetime.datetime.now().isoformat(),
        "app": "AnkiStudio",
        "converter": "curedolly",
        "points": len(pt_rows),
        "sentences": n_sent,
        "deck_items": n_item,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json",
                   json.dumps(manifest, ensure_ascii=False, indent=1))
        z.write(tmp, "project.db")

    store.close()
    cdb.close()
    return {"path": str(out), **manifest}
