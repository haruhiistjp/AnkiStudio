"""Convert the CureDolly project into an AnkiStudio .aproj file (v2).

Reads (read-only!) from the CureDolly repo:
  - build/index.sqlite       -> ALL kept clips become sentences (the pool)
  - data/inventory/points.yaml -> grammar_points
  - data/examples/level*.yaml  -> approved examples get deck_items + decision
  - data/sources/index.yaml    -> deck filename mapping

v2 imports the FULL sentence pool (~219k kept clips), not just the ~2k
approved examples. Approved examples are marked with decision='approved'
and linked to grammar points via deck_items; everything else stays
decision='' — available as pool candidates.

Writes: <out>.aproj (zip: manifest.json + project.db)
"""
from __future__ import annotations

import glob
import json
import re
import sqlite3
import zipfile
import tempfile
import datetime
from pathlib import Path

import yaml

from .store import Store


def convert_curedolly(cd_home: str | Path, out_path: str | Path,
                      project_name: str = "CureDolly") -> dict:
    cd = Path(cd_home)
    out = Path(out_path)
    if not str(out).endswith(".aproj"):
        out = out / f"{project_name}.aproj"

    cdb = sqlite3.connect(cd / "build" / "index.sqlite")
    cdb.row_factory = sqlite3.Row

    tmp = Path(tempfile.mkdtemp()) / "project.db"
    store = Store(tmp)
    store.set_setting("project_name", project_name)
    store.set_setting("language", "ja")

    # ---- grammar points ---------------------------------------------------
    points = yaml.safe_load(
        (cd / "data" / "inventory" / "points.yaml").read_text(encoding="utf-8"))
    store.add_points([{
        "id": p["id"],
        "title": (p.get("title") or {}).get("en", ""),
        "pattern": p.get("pattern", ""),
        "level": str(p.get("level", "")),
        "module": str(p.get("module", "")),
        "hints": ",".join(p.get("target_hint") or []),
    } for p in points])

    # ---- deck filename map ------------------------------------------------
    idx = yaml.safe_load(
        (cd / "data" / "sources" / "index.yaml").read_text(encoding="utf-8"))
    deck_files = {d["id"]: d["deck"] for d in idx["decks"]}
    pretty = {sid: fn.replace(".apkg", "") for sid, fn in deck_files.items()}

    # ---- pass 1: ALL kept clips -> sentences (the pool) ---------------------
    src_ids: dict[str, int] = {}
    n_sent = 0
    sent_by_clip: dict[int, int] = {}

    for clip in cdb.execute(
            "select id, deck_id, note_id, jp_norm, reading_norm, translation_raw,"
            " audio_file, image_file, episode, start, end from clips"
            " where keep=1 and jp_norm != ''"):
        did = clip["deck_id"]
        if did not in src_ids:
            src_ids[did] = store.add_source(
                "apkg", pretty.get(did, did),
                str(cd / "source" / deck_files.get(did, "")),
                {"deck_id": did, "curedolly": True})
        sid = src_ids[did]
        text = clip["jp_norm"] or ""
        char_len = len(re.sub(r"\W", "", text, flags=re.UNICODE))
        cur = store.db.execute(
            "insert into sentences(source_id,ref,text,reading,translation,"
            "episode,start,end,media_audio,media_image,char_len,flags,keep,"
            "drop_code,decision,decided_at,level,known)"
            " values (?,?,?,?,?,?,?,?,?,?,?,'',1,'','',NULL,'','{}')",
            (sid, str(clip["note_id"]), text,
             clip["reading_norm"] or "",
             clip["translation_raw"] or "",
             clip["episode"] or "",
             str(clip["start"] or ""), str(clip["end"] or ""),
             clip["audio_file"] or "",
             clip["image_file"] or "",
             char_len))
        sent_by_clip[clip["id"]] = cur.lastrowid
        n_sent += 1
        if n_sent % 50000 == 0:
            store.db.commit()
            print(f"  {n_sent} clips imported…")
    store.db.commit()
    print(f"pass 1: {n_sent} sentences from {len(src_ids)} sources")

    # ---- pass 2: approved examples -> mark + deck_items --------------------
    n_item = 0
    for f in sorted(glob.glob(str(cd / "data" / "examples" / "level*.yaml"))):
        for e in yaml.safe_load(open(f, encoding="utf-8")) or []:
            if e.get("status") != "approved":
                continue
            ref = e.get("source_ref", "")
            if not ref.startswith("clip:"):
                continue
            clip_id = int(ref.split(":", 1)[1])
            sentence_id = sent_by_clip.get(clip_id)
            if sentence_id is None:
                continue
            store.db.execute(
                "update sentences set decision='approved', decided_at=?"
                " where id=?",
                (datetime.datetime.now().timestamp(), sentence_id))
            store.deck_add(sentence_id, e.get("point", ""),
                           note=e.get("gloss") or "")
            n_item += 1
    store.db.commit()
    print(f"pass 2: {n_item} approved examples linked to grammar points")

    # ---- Tongari Boushi video sources (from the working project) ----------
    try:
        wdb = sqlite3.connect("data/studio.db")
        wdb.row_factory = sqlite3.Row
        from .importer import import_video
        for r in wdb.execute(
                "select name, path, meta from sources where kind='video'"):
            m = json.loads(r["meta"] or "{}")
            audio = m.get("audio") or r["path"]
            subs_file = m.get("subs")
            if not subs_file or not Path(subs_file).exists():
                continue
            try:
                vr = import_video(store, audio, subs_file,
                                  offset=m.get("offset", 0),
                                  pad_start=m.get("pad_start", m.get("pad", 0.35)),
                                  pad_end=m.get("pad_end", m.get("pad", 0.35)),
                                  name=r["name"][:50])
                print(f"  video: {r['name'][:30]} -> {vr['cues']} cues")
            except Exception as ve:
                print(f"  video {r['name'][:20]}: {ve}")
        wdb.close()
    except Exception as e:
        print(f"  video sources: {e}")

    # ---- package ------------------------------------------------------------
    total = store.db.execute("select count(*) from sentences").fetchone()[0]
    manifest = {
        "format": "ankistudio-project", "version": 2,
        "name": project_name,
        "created": datetime.datetime.now().isoformat(),
        "app": "AnkiStudio",
        "converter": "curedolly-v2",
        "points": len(points),
        "sentences": total,
        "approved": n_item,
        "sources": len(src_ids),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json",
                   json.dumps(manifest, ensure_ascii=False, indent=1))
        z.write(tmp, "project.db")

    store.close()
    cdb.close()
    return {"path": str(out), **manifest}
