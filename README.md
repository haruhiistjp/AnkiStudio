# AnkiStudio

A local-first workbench for building Anki decks from existing decks,
video + subtitles, and audio + transcripts. Japanese-first; the data
model is language-agnostic. Personal, offline use.

## What it does

The pipeline: **import → index → classify → pool → review → deck → export**

- **Deck import** — index .apkg decks (all three Anki format generations)
  into one sentence store with quality heuristics and statistics.
- **Video + subtitles** — SRT/VTT/ASS parser, piecewise subtitle-shift
  editor, ffmpeg audio cutting with configurable padding.
- **Grammar points** — import a taxonomy (e.g. CureDolly's 271 points)
  or create your own; every point is a "block" in the deck redactor.
- **Batch review** — keyboard-driven pool review (triangle-style hotkeys,
  audio autoplay, progress strip). Rejections are **multidimensional**:
  discarding for GP-001 doesn't affect GP-002.
- **Deck redactor** — blocks per grammar point showing filled/empty
  status, per-show balance chips, card notes, reordering, and
  "+ Fill from pool" per block.
- **Lexicons** — import frequency lists (TSV/CSV or from an Anki deck)
  and classify sentences by vocabulary level (N5–N1).
- **Projects (.aproj)** — portable project files containing the full
  sentence pool (~220k), grammar points, decisions, and deck composition.
- **Export** — build .apkg decks for Anki with stable GUIDs, media
  packaging, and per-card notes.

## New here?

Read **[QUICKSTART.md](QUICKSTART.md)** — a 5-minute guide for non-technical users.

## Documentation

- [docs/APROJ.md](docs/APROJ.md) — the .aproj project file format
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the app works

## Local vs AI

| Capability | 🟢 local (no key) | 🔑 needs API key |
|---|---|---|
| Deck import, stats, review, export | ✔ | — |
| Video+subs cards, audio cutting (ffmpeg) | ✔ | — |
| Transcription (faster-whisper) | ✔ (slow on CPU) | optional faster API |
| Level classification (fugashi) | ✔ | — |
| TTS voicing (AI voice) | — | Gemini / OpenAI-compatible |
| Translations, explanations | — | any LLM |

Nothing phones home; API keys are only used by features you run.

## Quick start

```bash
cd /Volumes/Ayaneru/AnkiStudio
uv venv && uv pip install -e ".[jp]"

# convert the CureDolly project into an .aproj (~220k sentences)
ankistudio convert-curedolly /Volumes/Ayaneru/AnkiDecks/CureDolly

# start the app
ankistudio serve                    # → http://127.0.0.1:8796
```

Or use individual commands:

```bash
ankistudio import deck.apkg         # index an Anki deck
ankistudio import-video ep.mp4 ep.ja.srt  # video + subtitles
ankistudio freq list.tsv            # frequency list → lexicon
ankistudio classify                 # compute sentence levels
ankistudio stats                    # JSON statistics
```

## Layout

```
ankistudio/          Python package
  apkg.py            .apkg reader (all three format generations)
  store.py           SQLite sentence store (one db per project)
  importer.py        deck/video/text importers + quality rules
  classify.py        vocabulary level classification (fugashi or fallback)
  exporter.py        genanki deck builder (immersion/reading presets)
  cd_import.py       CureDolly → .aproj converter
  ffmpeg.py          audio cutting, frame grabbing, transcoding
  subs.py            SRT/VTT/ASS subtitle parsers
  whisper.py         Whisper-based subtitle shift detection
  server.py          FastAPI endpoints
  cli.py             command-line interface

static/              browser UI (vanilla JS, no build step)
data/projects/       .aproj project files
data/uploads/        uploaded media files
data/media-cache/    transcoded/cut media cache
reference/           rescued implementations (K-chat alignment, Serbian
                     TTS/packaging, Swedish mining) for future porting
```

## The CureDolly project

The converter reads the CureDolly repo (read-only!) and produces a
self-contained .aproj with:
- **271 grammar points** (the full taxonomy from lessons 1–97)
- **220,089 sentences** — every kept clip from all 47 source decks,
  plus two Tongari Boushi video episodes
- **2,147 approved examples** already linked to their grammar points
- **47 sources** (Anki decks + video) with media references

The .aproj is ~19 MB (text only; media stays in the source files).
