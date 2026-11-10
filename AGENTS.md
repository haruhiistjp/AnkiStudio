# AGENTS.md — AnkiStudio

Local-first workbench for building Anki decks from mined media: .apkg
decks, video+subtitles (audio track extraction, no video kept), grammar
blocks, batch review, a deck redactor with templates/AI, and .apkg export.
FastAPI + SQLite backend (`ankistudio/`), single-page UI
(`static/index.html`, no build step). One user, localhost only.

## Quickstart (run these, in order)

```sh
# 1. uv is the package manager — there is NO pip in the venv
brew install uv ffmpeg          # or your platform's equivalents
uv venv .venv
uv pip install --python .venv/bin/python -e ".[jp]"   # [jp] = fugashi tokenizer

# 2. run from the repo root — data/ dirs are cwd-relative
.venv/bin/ankistudio serve --port 8796
# UI: http://127.0.0.1:8796  (db: data/studio.db, created on first run)
```

Whisper (subtitle-shift detection) auto-installs on first use via
`POST /api/whisper/install` — it builds a dedicated `.venv-whisper`
(Python 3.11 via uv, faster-whisper backend). Requires `uv` + `ffmpeg`.

Server-code changes need a restart; the UI shell is served `no-cache`,
so a browser reload always picks up `static/index.html` changes.
`kill -USR1 <serve pid>` dumps all thread stacks to the log if it hangs.

## Opening a shared project (.aproj / project folder)

- A collaborator's zip containing `project.db` + `uploads/` +
  `media-cache/` goes into `data/projects/<Name>/` — it then appears in
  the app's Projects view; click Open.
- Opening a `.aproj` extracts to `data/projects/<stem>/` and RESUMES the
  working copy if it is newer than the archive (never clobbers).
- The open project is remembered across restarts (`data/current-project`
  pointer) and autosaves ~20s after changes, with hourly history versions
  in `data/projects/<stem>/history/`.
- Source media paths are stored project-relative and resolved by
  `Store.resolve_media()` — absolute path → project-relative →
  `uploads/<basename>`.

## Architecture map

- `server.py` — all HTTP endpoints + project/autosave machinery. Read the
  endpoint list first; it is the API contract for `static/index.html`.
- `store.py` — SQLite schema, migrations, the shared connection. The
  shared connection is NOT thread-safe for concurrent endpoints:
  long-running/streaming endpoints must open `store.ro()` (private
  read-only connection). `snapshot_to()` uses its own connection too.
- `importer.py` / `ffmpeg.py` — video import: temp upload → stream-copy
  ONE audio track to `uploads/*.mka` + grab a frame per kept cue into
  `<project>/media-cache/src<sid>-<ref>.jpg` (parallel) → temp video
  deleted. Cuts happen lazily at preview/export time with the source's
  offset/pads (`ffmpeg.effective_time`).
- `subs.py` — SRT/VTT/ASS parsing, bilingual (ja/zh) detection+filtering,
  timing-only retime for "fixed subtitles" export.
- `whisper.py` — subtitle-shift detector: streams NDJSON progress,
  word-timestamp onsets, estimate = median of the best half of samples
  by match confidence; detects two-shift episodes (`split` → offset +
  segment). Bounded: clip caps, per-run timeouts, ~5 min deadline.
- `ai.py` — dependency-free OpenAI-compatible chat client (deck
  explanations; configured in Settings, works with any provider).

## Rules that keep this app alive

- **Scale**: stores run to 230k+ sentences. Never materialize tables in
  Python — filter/sort/paginate in SQL (see `/api/sentences`,
  `/api/pool`'s window-function sampling).
- **macOS privacy (TCC)**: the server cannot read `~/Downloads` or other
  volumes. Files ALWAYS come in through the browser's system file picker
  → `POST /api/upload`. Never build a custom file-selector UI and never
  read user paths server-side.
- **Filenames with `[brackets]` break `curl -F`** — copy to a safe name
  before uploading from scripts.
- Batch-review decisions are serialized client-side (`RVBUSY` in
  index.html) — do not remove that guard.
- CLI gotcha: `--db` goes BEFORE the subcommand (`ankistudio --db X serve`).
- Test against COPIES of user projects (cp to a scratch dir, run a second
  server on another port with `--db`), never against the live project db.

## Scratch-server pattern for experiments

```sh
mkdir -p /tmp/scratch/data && cd /tmp/scratch
PYTHONPATH=<repo> <repo>/.venv/bin/ankistudio --db data/studio.db serve --port 8797
```
