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

    p_vid = sub.add_parser("import-video", help="index a video + subtitles pair")
    p_vid.add_argument("video")
    p_vid.add_argument("subs")
    p_vid.add_argument("--offset", type=float, default=0.0)
    p_vid.add_argument("--astream", type=int, default=None,
                       help="audio track ordinal (default: auto — Japanese)")
    p_vid.add_argument("--sub-lang", default="auto",
                       choices=["auto", "ja", "zh", "all"],
                       help="bilingual subs: keep one language (default: auto)")

    p_cnv = sub.add_parser("convert-curedolly", help="convert the CureDolly repo into an .aproj")
    p_cnv.add_argument("cd_home")
    p_cnv.add_argument("--out", default="data/projects/CureDolly.aproj")

    p_frq = sub.add_parser("freq", help="import a frequency list (tsv or apkg)")
    p_frq.add_argument("path")
    p_frq.add_argument("--format", choices=["tsv", "apkg"], default=None,
                       help="default: guessed from the extension")

    p_cls = sub.add_parser("classify", help="compute sentence levels from a lexicon")
    p_cls.add_argument("--lexicon", type=int, default=None,
                       help="lexicon id (default: first)")
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

    if args.cmd == "import-video":
        from .importer import import_video
        from .store import Store
        store = Store(db)
        r = import_video(store, args.video, args.subs, offset=args.offset,
                         astream=args.astream,
                         sub_lang="" if args.sub_lang == "all" else args.sub_lang)
        print(f"{args.video}: {r['cues']} cues, {r['kept']} kept")
        store.close()
        return 0

    if args.cmd == "convert-curedolly":
        from .cd_import import convert_curedolly
        r = convert_curedolly(args.cd_home, args.out)
        for k, v in r.items():
            print(f"  {k}: {v}")
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

    if args.cmd == "classify":
        from .classify import classify_store
        from .store import Store
        store = Store(db)
        lex = store.db.execute(
            "select id from lexicons order by id").fetchall()
        if not lex:
            print("no lexicons imported yet (see `ankistudio freq`)"); return 1
        lid = args.lexicon or lex[0]["id"]
        print(classify_store(store, lid))
        store.close()
        return 0

    if args.cmd == "stats":
        from .store import Store
        store = Store(db)
        print(json.dumps(store.stats(), ensure_ascii=False, indent=1))
        store.close()
        return 0

    if args.cmd == "serve":
        import faulthandler
        import signal
        import uvicorn
        from .server import create_app
        # kill -USR1 <pid> dumps all thread stacks to the log — the only
        # sudo-free way to diagnose a wedged server on macOS
        faulthandler.register(signal.SIGUSR1, all_threads=True)
        app = create_app(db)
        print(f"AnkiStudio → http://127.0.0.1:{args.port}  (db: {db})")
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
