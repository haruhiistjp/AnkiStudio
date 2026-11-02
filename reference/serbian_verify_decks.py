#!/usr/bin/env python3
"""Verify a packaged Serbian audio deck end to end.

Checks that every [sound:...] reference resolves to an embedded media file,
that the note type and field list look right, and reports the audio totals.

    python verify_decks.py                      # both new decks
    python verify_decks.py some.apkg
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DEFAULT_DECKS = [
    ROOT / "Serbian_Frequency.apkg",
    ROOT / "Serbian_Verbs.apkg",
    ROOT / "Serbian_Frequency_RU.apkg",
    ROOT / "Serbian_Verbs_RU.apkg",
]

SOUND = re.compile(r"\[sound:([^\]]+)\]")


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def check(deck_path: Path) -> bool:
    print(f"\n=== {deck_path.name}  ({deck_path.stat().st_size / 1e6:.1f} MB)")
    ok = True

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        with zipfile.ZipFile(deck_path) as z:
            z.extract("collection.anki2", tmpdir)
            z.extract("media", tmpdir)
            media = json.loads((tmpdir / "media").read_text())
            for idx, name in media.items():
                with z.open(idx) as src, open(tmpdir / name, "wb") as dst:
                    dst.write(src.read())

        con = sqlite3.connect(tmpdir / "collection.anki2")
        models = json.loads(con.execute("select models from col").fetchone()[0])
        model = list(models.values())[0]
        fields = [f["name"] for f in model["flds"]]
        rows = con.execute("select flds, tags from notes").fetchall()
        cards = con.execute("select count(*) from cards").fetchone()[0]
        con.close()

        print(f"  note type : {model['name']}")
        print(f"  fields    : {len(fields)}  {fields[-3:] if len(fields) > 3 else fields}")
        print(f"  notes     : {len(rows)}   cards: {cards}   media: {len(media)}")

        if len(rows) != cards:
            print("  !! note/card mismatch")
            ok = False

        referenced: Counter[str] = Counter()
        missing: list[str] = []
        for flds, _tags in rows:
            for value in flds.split("\x1f"):
                for name in SOUND.findall(value):
                    referenced[name] += 1
                    if not (tmpdir / name).exists():
                        missing.append(name)

        if missing:
            print(f"  !! {len(missing)} missing media: {missing[:5]}")
            ok = False

        unreferenced = set(media.values()) - set(referenced)
        if unreferenced:
            print(f"  !! {len(unreferenced)} unreferenced media files")
            ok = False

        total = sum(duration(tmpdir / n) for n in media.values())
        print(f"  audio     : {len(media)} files, {total / 60:.1f} min, "
              f"{total / max(1, len(media)):.2f}s avg")

        short = [n for n in media.values() if duration(tmpdir / n) < 0.25]
        if short:
            print(f"  !! {len(short)} clips under 0.25s: {short[:3]}")
            ok = False

    print("  RESULT    :", "ok" if ok else "PROBLEMS FOUND")
    return ok


def main() -> None:
    targets = [Path(a) for a in sys.argv[1:]] or DEFAULT_DECKS
    results = [check(p) for p in targets if p.exists()]
    missing = [p.name for p in targets if not p.exists()]
    if missing:
        print("\nmissing:", ", ".join(missing))
    if not all(results) or missing:
        sys.exit(1)


if __name__ == "__main__":
    main()
