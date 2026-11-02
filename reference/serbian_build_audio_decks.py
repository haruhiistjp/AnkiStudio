#!/usr/bin/env python3
"""Package the Serbian decks with audio, in English and Russian.

The originals are left untouched. Each audio deck is a separate note type and
deck (new IDs, GUIDs derived from the source notes) so importing it never
rewrites the unvoiced decks in the user's collection.

The Russian decks reuse the English decks' audio and Serbian text; only the
English glosses and translations are replaced, from translations/ru/.

    python build_audio_decks.py                 # all four decks
    python build_audio_decks.py --deck freq --lang ru
"""

from __future__ import annotations

import argparse
import json
from functools import lru_cache
from pathlib import Path

import genanki

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "_work_audio"
AUDIO = WORK / "audio"
RU_DIR = ROOT / "translations" / "ru"

POS_RU = {
    "noun": "сущ.", "verb": "гл.", "adverb": "нар.", "adjective": "прил.",
    "pronoun": "мест.", "preposition": "предл.", "numeral": "числ.",
    "conjunction": "союз", "interjection": "межд.", "particle": "част.",
}

AUDIO_CSS = """
.word-audio{margin:0 0 .4em}
.form-audio{margin:.1em 0 .35em}
.replay-button{vertical-align:middle}
"""

# ------------------------------------------------------------------ frequency

FREQ_MODEL_ID = 1700000000021
FREQ_DECK_ID = 1700000000022
FREQ_DECK_NAME = "Serbian::Frequency (Audio)"
FREQ_MODEL_NAME = "Serbian Frequency (word\u2192meaning, audio)"

FREQ_CSS = """.card{font-family:-apple-system,"Segoe UI",Roboto,Arial,sans-serif;font-size:20px;text-align:center;color:#222;background:#fff;line-height:1.4}
.nightMode.card,.night_mode.card{color:#e6e6e6;background:#1e1e1e}
.word{font-size:2.2em;font-weight:500;margin:.6em 0}
.cyr{font-size:.8em;color:#888}
.pos{font-size:.65em;letter-spacing:.08em;text-transform:uppercase;color:#999}
.meaning{font-size:1.15em;margin:.4em 0 1em}
.ex{margin:.5em 0 0}
.en{font-size:.8em;color:#888;margin:0 0 .6em}
hr#answer{border:0;border-top:1px solid #ddd;margin:.8em auto;width:30%}
""" + AUDIO_CSS

FREQ_QFMT = '<div class="word">{{Word}}</div>\n<div class="word-audio">{{Word_Audio}}</div>\n'

FREQ_AFMT = (
    '{{FrontSide}}<hr id=answer>'
    '<div class="cyr">{{Cyrillic}}</div>'
    '<div class="pos">{{POS}}</div>'
    '<div class="meaning">{{Meaning}}</div>'
    "{{#Example1}}<div class=\"ex\">{{Example1}} {{Example1_Audio}}</div>"
    '<div class="en">{{Example1_EN}}</div>{{/Example1}}'
    "{{#Example2}}<div class=\"ex\">{{Example2}} {{Example2_Audio}}</div>"
    '<div class="en">{{Example2_EN}}</div>{{/Example2}}'
)

FREQ_FIELDS = [
    "Rank", "Word", "Cyrillic", "POS", "Meaning",
    "Example1", "Example1_EN", "Example2", "Example2_EN",
    "Word_Audio", "Example1_Audio", "Example2_Audio",
]

FREQ_MODEL_ID_RU = 1700000000041
FREQ_DECK_ID_RU = 1700000000042
FREQ_DECK_NAME_RU = "Serbian-Russian::Frequency (Audio)"
FREQ_MODEL_NAME_RU = "Serbian Frequency (word→meaning, audio, RU)"
FREQ_AFMT_RU = FREQ_AFMT.replace("_EN}}", "_RU}}")
FREQ_FIELDS_RU = [
    "Rank", "Word", "Cyrillic", "POS", "Meaning",
    "Example1", "Example1_RU", "Example2", "Example2_RU",
    "Word_Audio", "Example1_Audio", "Example2_Audio",
]

# ----------------------------------------------------------------------- verbs

VERB_MODEL_ID = 1700000000031
VERB_DECK_ID = 1700000000032
VERB_DECK_NAME = "Serbian::Verbs (Audio)"
VERB_MODEL_NAME = "Serbian Verb Pattern (gap, audio)"

VERB_CSS = """.card{font-family:-apple-system,"Segoe UI",Roboto,Arial,sans-serif;font-size:20px;text-align:center;color:#222;background:#fff;line-height:1.5}
.nightMode.card,.night_mode.card{color:#e6e6e6;background:#1e1e1e}
.prompt{font-size:1.5em;margin:.8em 0 .3em}
.cue{font-size:.75em;color:#888;letter-spacing:.04em}
.sent{font-size:1.3em;margin:.6em 0 .2em}
.en{font-size:.85em;color:#888;margin-bottom:.8em}
.para{font-size:.8em;color:#666;margin:.3em 0}
.small{font-size:.7em;color:#999;margin:.2em 0}
b{color:#2a6fdb}
.nightMode b,.night_mode b{color:#6fa8ff}
hr#answer{border:0;border-top:1px solid #ddd;margin:.8em auto;width:30%}
""" + AUDIO_CSS

VERB_QFMT = (
    '<div class="prompt">{{Prompt}}</div>'
    '<div class="cue">{{Verb}} &middot; {{Person}}</div>'
)

VERB_AFMT = (
    "{{FrontSide}}<hr id=answer>"
    '<div class="form-audio">{{Answer_Audio}}</div>'
    '<div class="sent">{{Sentence}} {{Sentence_Audio}}</div>'
    '<div class="en">{{English}}</div>'
    '<div class="para">{{Paradigm}}</div>'
    '<div class="small">{{Gloss}} &middot; past: {{Past}}</div>'
    "{{#Pair}}<div class=\"small\">pair: {{Pair}}</div>{{/Pair}}"
    "{{#Note}}<div class=\"small\">{{Note}}</div>{{/Note}}"
)

VERB_FIELDS = [
    "Rank", "Verb", "Gloss", "Person", "Prompt", "Answer",
    "Sentence", "English", "Paradigm", "Past", "Pair", "Note",
    "Answer_Audio", "Sentence_Audio",
]

VERB_MODEL_ID_RU = 1700000000051
VERB_DECK_ID_RU = 1700000000052
VERB_DECK_NAME_RU = "Serbian-Russian::Verbs (Audio)"
VERB_MODEL_NAME_RU = "Serbian Verb Pattern (gap, audio, RU)"
VERB_AFMT_RU = (
    VERB_AFMT.replace("{{English}}", "{{Russian}}")
    .replace("past: ", "прош.: ")
    .replace("pair: ", "пара: ")
)
VERB_FIELDS_RU = [
    "Rank", "Verb", "Gloss", "Person", "Prompt", "Answer",
    "Sentence", "Russian", "Paradigm", "Past", "Pair", "Note",
    "Answer_Audio", "Sentence_Audio",
]


@lru_cache(maxsize=None)
def load_ru_freq() -> dict[int, dict]:
    lines = (RU_DIR / "freq.tsv").read_text(encoding="utf-8").splitlines()[1:]
    out = {}
    for line in lines:
        rank, meaning, ex1, ex2 = line.split("\t")
        out[int(rank)] = {"meaning": meaning, "example1_ru": ex1, "example2_ru": ex2}
    return out


@lru_cache(maxsize=None)
def load_ru_verbs() -> dict[str, dict]:
    lines = (RU_DIR / "verbs.tsv").read_text(encoding="utf-8").splitlines()[1:]
    out = {}
    for line in lines:
        guid, gloss, english, note, pair = line.split("\t")
        out[guid] = {"gloss": gloss, "russian": english, "note": note, "pair": pair}
    return out


def localize_freq_ru(note: dict) -> dict:
    ru = dict(load_ru_freq()[note["rank"]])
    if note.get("swapped"):
        ru["example1_ru"], ru["example2_ru"] = ru["example2_ru"], ru["example1_ru"]
    return {"pos": POS_RU[note["pos"]], **ru}


def localize_verb_ru(note: dict) -> dict:
    return load_ru_verbs()[note["guid"]]


def build(deck_key: str, *, model_id: int, model_name: str, deck_id: int,
          deck_name: str, fields: list[str], qfmt: str, afmt: str, css: str,
          description: str, guid_prefix: str, audio_fields: list[tuple[str, str]],
          output: Path, localize=None) -> None:
    """audio_fields is a list of (note key holding the mp3, Anki field name)."""
    notes = json.loads((WORK / deck_key / "notes.json").read_text(encoding="utf-8"))["notes"]

    model = genanki.Model(
        model_id,
        model_name,
        fields=[{"name": name} for name in fields],
        templates=[{"name": model_name, "qfmt": qfmt, "afmt": afmt}],
        css=css,
    )
    deck = genanki.Deck(deck_id, deck_name, description=description)

    media: list[str] = []
    for note in notes:
        if localize:
            note = {**note, **localize(note)}
        values = {name: str(note.get(name.lower(), "")) for name in fields}
        for key, field_name in audio_fields:
            filename = note[key]
            values[field_name] = f"[sound:{filename}]"
            media.append(str(AUDIO / filename))
        deck.add_note(
            genanki.Note(
                model=model,
                fields=[values[name] for name in fields],
                tags=note["tags"],
                guid=genanki.guid_for(guid_prefix, note["guid"]),
            )
        )

    missing = [p for p in media if not Path(p).exists()]
    if missing:
        raise SystemExit(f"missing audio ({len(missing)}): {missing[:3]}")

    genanki.Package(deck, media_files=media).write_to_file(str(output))
    size = output.stat().st_size / 1024 / 1024
    print(f"{output.name}: {len(notes)} notes, {len(media)} clips, {size:.1f} MB")


def build_freq(target: Path, lang: str = "en") -> None:
    ru = lang == "ru"
    build(
        "freq",
        model_id=FREQ_MODEL_ID_RU if ru else FREQ_MODEL_ID,
        model_name=FREQ_MODEL_NAME_RU if ru else FREQ_MODEL_NAME,
        deck_id=FREQ_DECK_ID_RU if ru else FREQ_DECK_ID,
        deck_name=FREQ_DECK_NAME_RU if ru else FREQ_DECK_NAME,
        fields=FREQ_FIELDS_RU if ru else FREQ_FIELDS,
        qfmt=FREQ_QFMT,
        afmt=FREQ_AFMT_RU if ru else FREQ_AFMT,
        css=FREQ_CSS,
        description=(
            "Полная частотная колода с сербским аудио на каждой карточке: слово и "
            "оба примера."
            if ru else
            "The complete frequency deck with Serbian audio on every card: the "
            "headword and both example sentences."
        ),
        guid_prefix="sr_freq_audio_ru" if ru else "sr_freq_audio",
        audio_fields=[
            ("word_audio", "Word_Audio"),
            ("example1_audio", "Example1_Audio"),
            ("example2_audio", "Example2_Audio"),
        ],
        output=target,
        localize=localize_freq_ru if ru else None,
    )


def build_verb(target: Path, lang: str = "en") -> None:
    ru = lang == "ru"
    build(
        "verb",
        model_id=VERB_MODEL_ID_RU if ru else VERB_MODEL_ID,
        model_name=VERB_MODEL_NAME_RU if ru else VERB_MODEL_NAME,
        deck_id=VERB_DECK_ID_RU if ru else VERB_DECK_ID,
        deck_name=VERB_DECK_NAME_RU if ru else VERB_DECK_NAME,
        fields=VERB_FIELDS_RU if ru else VERB_FIELDS,
        qfmt=VERB_QFMT,
        afmt=VERB_AFMT_RU if ru else VERB_AFMT,
        css=VERB_CSS,
        description=(
            "Колода глагольных моделей с аудио: недостающая форма, затем полное "
            "предложение."
            if ru else
            "The verb-pattern deck with audio: the missing form, then the full "
            "sentence."
        ),
        guid_prefix="sr_verb_audio_ru" if ru else "sr_verb_audio",
        audio_fields=[
            ("answer_audio", "Answer_Audio"),
            ("sentence_audio", "Sentence_Audio"),
        ],
        output=target,
        localize=localize_verb_ru if ru else None,
    )


def main() -> None:
    global WORK, AUDIO

    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", choices=["freq", "verb", "all"], default="all")
    ap.add_argument("--lang", choices=["en", "ru", "all"], default="all")
    ap.add_argument("--outdir", default=str(ROOT))
    ap.add_argument("--workdir", default=str(WORK))
    args = ap.parse_args()

    WORK = Path(args.workdir)
    AUDIO = WORK / "audio"

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    for lang in (["en", "ru"] if args.lang == "all" else [args.lang]):
        suffix = "_RU" if lang == "ru" else ""
        if args.deck in ("freq", "all"):
            build_freq(outdir / f"Serbian_Frequency{suffix}.apkg", lang)
        if args.deck in ("verb", "all"):
            build_verb(outdir / f"Serbian_Verbs{suffix}.apkg", lang)


if __name__ == "__main__":
    main()
