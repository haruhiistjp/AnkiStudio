# AnkiStudio

A local-first workbench for building Anki decks from **existing Anki decks**,
**video + subtitles**, and **audio + transcripts**. Japanese-first; the data
model is language-agnostic. Personal, offline use.

## What it does

Pipeline stages (UI buttons and CLI subcommands are the same functions):

    import → index → analyze → select/review → build (.apkg)

- **Deck import & statistics** — import .apkg decks into one sentence store;
  quality heuristics (duplicates, fragments, karaoke/garble, overlong lines);
  dashboards (per-source, lengths, levels); card browser with filters and
  approve/discard review.
- **Lexicons** — import frequency lists (TSV/CSV, or straight from an Anki
  deck like Kaishi 1.5k) and classify sentences by vocabulary level.
- *(later phases)* video+subtitle pipeline with a piecewise subtitle-shift
  editor and ffmpeg clip cutting; local faster-whisper transcription and
  transcript↔audio alignment (reference implementation rescued in
  `reference/kchat/`); vocabulary-deck mining; grammar-deck building;
  AI provider settings (TTS / explanations / ASR).

## Local vs AI — what needs what

| Capability | 🟢 local (no key) | 🔑 needs API key |
|---|---|---|
| Deck import, stats, review, export | ✔ | — |
| Subtitle-based cards + audio cutting (ffmpeg) | ✔ | — |
| Transcription (faster-whisper) | ✔ (slow on CPU, fine for episodes) | optional faster API fallback |
| Transcript↔audio alignment | ✔ | — |
| TTS voicing (AI voice) | — | Gemini / OpenAI-compatible |
| Translations, explanations | — | any LLM |
| Japanese level classification | ✔ more accurate with `fugashi` extra | — |

Nothing phones home; API keys are only used by features you explicitly run.

## Run

    uv venv && uv pip install -e ".[jp]"   # or: pip install -e . (jp extra optional)
    ankistudio import ~/path/to/deck.apkg  # or several; use --db to choose a project file
    ankistudio serve                       # → http://127.0.0.1:8796

## Layout

    ankistudio/          the package (apkg reader, store, importer, server, cli)
    static/              browser UI (vanilla JS, no build step)
    reference/           rescued implementations we port from
      kchat/             K-chat alignment pipeline (whisper + difflib + ffmpeg)
      serbian_*.py       apkg reader, TTS batch, genanki packaging, verifier
      swedish_*.py       corpus sentence mining, QA gate

`reference/` is vendored for study/porting with attribution; the app itself
does not import from it.
