# The .aproj format

An `.aproj` file is a portable **AnkiStudio project** — a self-contained archive of everything needed to develop an Anki deck: sentences, grammar points, lexicons, review decisions, deck composition, and export settings. Think of it as "the .apkg for deck development" rather than for studying.

## Structure

An `.aproj` is a ZIP archive:

```
CureDolly.aproj
├── manifest.json    # project metadata (human-readable JSON)
└── project.db       # SQLite database (the project's entire state)
```

### manifest.json

```json
{
  "format": "ankistudio-project",
  "version": 2,
  "name": "CureDolly",
  "created": "2026-11-03T21:44:00",
  "app": "AnkiStudio",
  "converter": "curedolly-v2",
  "points": 271,
  "sentences": 220089,
  "approved": 2147,
  "sources": 47
}
```

- `format` — always `"ankistudio-project"` (identifies the file type)
- `version` — schema version (currently 2; v1 lacked the full pool)
- `converter` — which tool produced it (e.g. `"curedolly-v2"`, or empty for projects created in-app)

### project.db (SQLite)

The database contains all project state in these tables:

| Table | Purpose |
|---|---|
| `sources` | Where sentences came from (Anki decks, videos, text corpora) |
| `sentences` | Every sentence in the pool (~220k for CureDolly) — text, reading, translation, media references, quality flags, level classification |
| `grammar_points` | The grammar taxonomy (id, title, pattern, level, module, match hints) |
| `deck_items` | Cards placed in the deck (sentence ↔ grammar point link + position + per-card note) |
| `pool_decisions` | **Multidimensional decisions**: approve/reject per (sentence, context) — rejecting for GP-001 ≠ rejecting forever |
| `lexicons` | Frequency lists imported for level classification |
| `lexicon_words` | Individual words in each lexicon |
| `settings` | Project-level key-value settings |

## Key design decisions

### Media stays external

The `.aproj` does **not** embed audio/image files. Sentences reference media by filename, and the source `.apkg`/video path is stored in the `sources` table. This keeps `.aproj` files small (19 MB for 220k sentences vs. many GB with embedded media) and avoids duplicating data.

### Multidimensional decisions

A sentence can be rejected for one grammar point while remaining available for others. The `pool_decisions` table uses `(sentence_id, context)` as its primary key:

- `context = 'global'` — affects the sentence everywhere
- `context = 'point:GP-001'` — only affects pools for GP-001

This mirrors how grammar actually works: a sentence demonstrating both が and を might be perfect for GP-001 but wrong for GP-003.

### The full pool

Unlike a simple "approved examples" export, the `.aproj` contains **every kept sentence** from all sources (~220k). Approved examples are marked with `decision='approved'` and linked to grammar points; everything else is `decision=''` — available as a candidate for any pool. This is what makes the pool builder useful: it can draw from the entire indexed corpus, not just what's already been curated.

## Creating an .aproj

### From the CureDolly project

Download `CureDolly.aproj` from the [releases page](https://github.com/haruhiistjp/AnkiStudio/releases) and place it in `data/projects/`.

Or, if you have the CureDolly source repository locally:

```bash
ankistudio convert-curedolly /path/to/CureDolly
```

### From within AnkiStudio

Use **Save project** in the Export view (writes to `data/projects/`), or **Export project (.aproj)** to pick a destination.

## Opening an .aproj

1. **Projects view** in the AnkiStudio sidebar → click **Open** on any project
2. The server extracts `project.db` to `data/projects/<name>/` and swaps the live store
3. The browser reloads with the new project's data

## Version history

| Version | Change |
|---|---|
| 1 | Approved examples only (~2k sentences) |
| 2 | Full pool (~220k sentences) + Tongari video sources + multidimensional decisions |
