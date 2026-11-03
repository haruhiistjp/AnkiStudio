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

**Never used a terminal before?** Read **[QUICKSTART.md](QUICKSTART.md)** first — it walks you through every step.

```bash
# 1. Download the app
git clone https://github.com/haruhiistjp/AnkiStudio.git
cd AnkiStudio

# 2. Install (one-time, ~1 minute)
uv venv && uv pip install -e ".[jp]"

# 3. Start the app
ankistudio serve                    # → http://127.0.0.1:8796
```

Then open **http://127.0.0.1:8796** in your browser.

**To open an existing project** (like `CureDolly.aproj` from the [releases page](https://github.com/haruhiistjp/AnkiStudio/releases)):
1. Download the `.aproj` file
2. Put it in the `data/projects/` folder inside the AnkiStudio directory
3. Click **Projects** → **Open** in the app

**To create your own project from scratch:**
1. Click **Sources** → import an Anki deck (`.apkg`) or a video with subtitles
2. Click **Lexicons** → import a frequency list for vocabulary levels
3. Click **Grammar points** → import or create your grammar taxonomy
4. Click **Batch review** → pick a point, build a pool, review with keyboard
5. Click **Export** → build an `.apkg` for Anki

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

A ready-made Japanese grammar project is available as a [release download](https://github.com/haruhiistjp/AnkiStudio/releases). It contains:
- **271 grammar points** (lessons 1–97, beginner to advanced)
- **220,089 sentences** from 47 anime shows + 2 video episodes
- **2,147 pre-approved examples** already placed in the deck
- ~19 MB (text only; audio requires the source Anki decks on your machine)

If you have the [CureDolly source repository](https://github.com/haruhiistjp/CureDolly) locally, you can also regenerate the project file yourself:
```bash
ankistudio convert-curedolly /path/to/CureDolly
```
