# AnkiStudio architecture

A local-first web application for developing Anki decks from existing
decks, video+subtitles, and audio+transcripts. Japanese-first, but the
data model is language-agnostic.

## Stack

- **Backend**: Python 3.12+, FastAPI, SQLite (one db per project)
- **Frontend**: Vanilla JavaScript + CSS in a single `static/index.html`
  (no build step, no framework)
- **CLI**: `ankistudio` command (same pipelines the UI calls)
- **Media**: ffmpeg for cutting/transcoding, Pillow for image re-encoding
- **Japanese NLP**: fugashi + unidic-lite (optional `[jp]` extra) for
  tokenized level classification

## The project model

Everything revolves around the **project** — a single SQLite database
holding all state. The app works on one project at a time; `.aproj`
files are portable snapshots (see [APROJ.md](APROJ.md)).

```
┌─────────────────────────────────────────────────────────────┐
│                         project.db                          │
├──────────┬──────────────────────────────────────────────────┤
│ sources  │ where sentences came from (.apkg, video, text)   │
│ sentences│ every indexed sentence (~220k) — text/media/meta │
│ grammar_ │ the grammar taxonomy (id, title, pattern, level) │
│   points │                                                  │
│ deck_    │ cards in the deck (sentence ↔ point + position) │
│   items  │                                                  │
│ pool_    │ multidimensional decisions per (sentence, ctx)  │
│ decisions│                                                  │
│ lexicons │ frequency lists for level classification         │
│ settings │ project metadata                                 │
└──────────┴──────────────────────────────────────────────────┘
```

## The pipeline

```
import → index → classify → pool → review → deck → export
```

1. **Import** — index sources into the sentence store:
   - `.apkg` Anki decks (all three format generations)
   - Video + subtitles (SRT/VTT/ASS with piecewise shift editor)
   - (planned) audio + transcript alignment

2. **Classify** — compute vocabulary levels per sentence against an
   imported frequency list. Uses fugashi tokenization when available;
   falls back to substring matching.

3. **Pool** — build a diverse candidate pool for a grammar point or
   free-text query. Controls: per-source cap, length-balanced sampling
   (quantile spread), level filter, exclude-deck, context-aware
   rejection filtering.

4. **Review** — keyboard-driven batch review (triangle-style):
   `Space` replay / `A` approve → deck / `X` reject (for this point
   only) / `S` skip. Audio autoplays; progress strip tracks decisions.

5. **Deck** — the deck redactor shows every grammar point as a block
   (filled or empty), with per-show balance chips, card notes,
   reordering, and a "+ Fill from pool" button per block.

6. **Export** — build an `.apkg` for Anki:
   - Presets: immersion (front: image+audio) or reading (front: text)
   - Stable GUIDs (re-import updates, never duplicates)
   - Per-card notes become a "Note" field on the card back
   - Media packaged from source decks or cut from video

## Multidimensional decisions

The core insight: **rejecting a sentence for GP-001 doesn't mean it's
bad for GP-002.** The `pool_decisions` table stores decisions per
(sentence, context):

```sql
pool_decisions(sentence_id, context, decision, decided_at)
-- context = 'global' or 'point:GP-XXX'
```

When building a pool for GP-001, we exclude sentences that are:
- globally discarded (`context='global'`, `decision='discarded'`)
- discarded for this point (`context='point:GP-001'`, `decision='discarded'`)

A sentence discarded only for GP-001 still appears in GP-002's pool.

## Anki deck format handling

The `.apkg` reader handles all three generations:

| Generation | Database | Media map | Notes |
|---|---|---|---|
| Classic | `collection.anki2` (plain SQLite) | JSON `{"0": "file.mp3"}` | |
| Transitional | zstd-compressed `collection.anki2` | JSON or protobuf | WAL header needs reset |
| Modern (2024+) | `collection.anki21b` (zstd SQLite) | protobuf-zstd | Individual media entries also zstd-compressed; note types in separate `notetypes`/`fields` tables |

## Video + subtitles

Subtitle times are stored as **originals**; shifts live in
`sources.meta` and apply at media-cut time (no re-import needed).
Shift segments are absolute: `{at: 0, shift: 5}` means "from cue time 0
onward, the total shift is +5 seconds." The Whisper engine can suggest
a global offset by transcribing a sample of cues.

## Level classification

With the `[jp]` extra (fugashi + unidic-lite):
1. Tokenize each sentence
2. Match tokens by lemma against the frequency list
3. Assign the easiest level where no harder word appears AND the
   unknown-content-word count fits the budget

Without tokenization (fallback): match lexicon words by substring;
a sentence's level = the easiest level ≥ all found word levels.

## AI features (planned)

The provider layer will support:
- **ASR**: local faster-whisper (default) or API fallback
- **TTS**: Gemini batch (proven in the Serbian project) or OpenAI-compatible
- **LLM**: translations, explanations, grammar-point matching

Every feature in the UI is badged 🟢 local / 🔑 needs key.
