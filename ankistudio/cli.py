"""CLI: the same pipelines the UI calls.

    ankistudio import  deck.apkg [more.apkg ...] [--db PATH] [--max-chars N]
    ankistudio freq   list.tsv | deck.apkg [--tsv | --apkg] [--db PATH]
    ankistudio stats  [--db PATH]
    ankistudio serve  [--db PATH] [--port 8796]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(prog="ankistudio")
    ap.add_argument("--db", default="data/studio.db", help="project database path")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_imp = sub.add_parser("import", help="index .apkg decks into the store")
    p_imp.add_argument("paths", nargs="+")
    p_imp.add_argument("--max-chars", type=int, default=60)

    p_frq = sub.add_parser("freq", help="import a frequency list (tsv or apkg)")
    p_frq.add_argument("path")
    p_frq.add_argument("--format", choices=["tsv", "apkg"], default=None,
                       help="default: guessed from the extension")

    sub.add_parser("stats", help="print store statistics as JSON")
    p_srv = sub.add_parser("serve", help="run the local web app")
    p_srv.add_argument("--port", type=int, default=8796)

    args = ap.parse_args()
    db = Path(args.db)
    if db.parent != Path(""):
        db.parent.mkdir(parents=True, exist_ok=True)

    if args.cmd == "import":
        from .importer import import_apkg
        from .store import Store
        store = Store(db)
        for p in args.paths:
            summary = import_apkg(store, p, max_chars=args.max_chars)
            print(f"{p}: {summary['notes']} notes, {summary['kept']} kept, "
                  f"drops={summary['drops']}")
        store.close()
        return 0

    if args.cmd == "freq":
        from .importer import import_freq_apkg, import_freq_tsv
        from .store import Store
        store = Store(db)
        fmt = args.format or ("apkg" if args.path.endswith(".apkg") else "tsv")
        lid = (import_freq_apkg(store, args.path) if fmt == "apkg"
               else import_freq_tsv(store, args.path))
        n = store.db.execute(
            "select count(*) c from lexicon_words where lexicon_id=?",
            (lid,)).fetchone()["c"]
        print(f"lexicon #{lid}: {n} words")
        store.close()
        return 0

    if args.cmd == "stats":
        from .store import Store
        store = Store(db)
        print(json.dumps(store.stats(), ensure_ascii=False, indent=1))
        store.close()
        return 0

    if args.cmd == "serve":
        import uvicorn
        from .server import create_app
        app = create_app(db)
        print(f"AnkiStudio → http://127.0.0.1:{args.port}  (db: {db})")
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
