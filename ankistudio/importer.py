"""Import an .apkg deck into the sentence store, with deck-agnostic quality
heuristics (ported from the CureDolly cleaner: duplicates, fragments,
karaoke/garble, overlong lines, romaji/English contamination).
"""
from __future__ import annotations

import re
from pathlib import Path

from .apkg import DeckReader
from .store import Store

# field-name candidates in rough order of preference (case-insensitive)
JP_FIELDS = ["jp", "japanese", "sentkanji", "expression", "original",
             "front", "anverso", "sentence", "text", "kanji"]
READ_FIELDS = ["reading", "sentfurigana", "kana", "furigana", "readme"]
TRANS_FIELDS = ["translation", "senteng", "english", "traducción",
                "traduccion", "translationen", "meaning", "reverso", "back"]
AUDIO_FIELDS = ["audio", "sentaudio", "sound", "audio-sentence"]
IMAGE_FIELDS = ["image", "snapshot", "extra", "picture", "img"]
EP_FIELDS = ["id", "number", "source", "episode", "source_id"]


def default_level_order(levels: list[str]) -> list[str]:
    """Order levels easy -> hard. JLPT-style N5..N1 sorts by DESCENDING
    number (N5 easiest); A1..C2 / numeric styles sort ascending. Stray
    non-conforming level strings (import noise) sort last."""
    import re as _re
    uniq = list(dict.fromkeys(levels))
    ns = [l for l in uniq if _re.fullmatch(r"N\d+", l.strip().upper())]
    if ns and len(ns) >= max(1, int(len(uniq) * 0.8)):
        rest = [l for l in uniq if l not in ns]
        return sorted(ns, key=lambda l: -int(l[1:])) + rest
    def sort_key(l):
        m = _re.search(r"\d+", l)
        return (int(m.group()) if m else 999, l)
    return sorted(uniq, key=sort_key)

KANA_KANJI = re.compile(r"[\u3040-\u30ff\u4e00-\u9faf]")
ASCII_WORDS = re.compile(r"[A-Za-z]{4,}")          # 4+ latin letters = suspicious
KARAOKE = re.compile(r"[♪♫agnostics♬]|＃")
INTERJECTIONS = {"うん", "うんん", "ああ", "えっ", "ええ", "おお", "ふーん", "ほう",
                 "へえ", "あー", "えー", "おー", "うー", "ん", "はい", "わあ", "きゃ"}
PUNCT_ONLY = re.compile(r"^[\W\s]+$", re.UNICODE)
SOUND_RE = re.compile(r"\[sound:([^\]]+)\]")
IMG_RE = re.compile(r'<img[^>]+src="([^"]+)"')

MAX_CHARS = 60        # configurable per import; docs legacy was 50 for L4


def pick_field(fields: list[str], candidates: list[str]) -> str | None:
    low = [f.lower() for f in fields]
    for want in candidates:
        for i, f in enumerate(low):
            if f == want:
                return fields[i]
    for want in candidates:
        for i, f in enumerate(low):
            if want in f:
                return fields[i]
    return None


def clean_text(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def classify_quality(text: str, max_chars: int) -> tuple[str, str]:
    """return (drop_code or '', flags) — keep when drop_code is ''."""
    flags = []
    if not text or not KANA_KANJI.search(text):
        return "C01", ""                       # empty / no Japanese script
    if KARAOKE.search(text):
        return "C05", ""                       # karaoke / music symbols
    if ASCII_WORDS.search(text):
        flags.append("F_ROMAJI")               # latin words mixed in
    core = re.sub(r"[\W\s]", "", text, flags=re.UNICODE)
    if len(core) > max_chars:
        return "C04", ""                       # overlong
    bare = text.rstrip("…。！？、,.!? ")
    if bare in INTERJECTIONS or (len(bare) <= 4 and PUNCT_ONLY.match(bare)):
        return "C13", ""                       # interjection / fragment
    return "", ",".join(filter(None, flags))


def import_apkg(store: Store, path: str | Path, max_chars: int = MAX_CHARS,
                name: str | None = None) -> dict:
    """Index every note of a deck as candidate sentences. Returns summary."""
    path = Path(path)
    reader = DeckReader.open(path)
    src_id = store.add_source(
        "apkg", name or path.name.replace(".apkg", ""), str(path),
        {"note_types": [nt.name for nt in reader.note_types.values()]})

    rows, dropped, seen = [], {}, {}
    for note in reader.notes():
        f = note.fields
        jp_f = pick_field(list(f), JP_FIELDS)
        if not jp_f:
            continue
        text = clean_text(f.get(jp_f, ""))
        code, flags = classify_quality(text, max_chars)
        rd_f = pick_field(list(f), READ_FIELDS)
        tr_f = pick_field(list(f), TRANS_FIELDS)
        au_f = pick_field(list(f), AUDIO_FIELDS)
        im_f = pick_field(list(f), IMAGE_FIELDS)
        ep_f = pick_field(list(f), EP_FIELDS)
        audio = SOUND_RE.search(f.get(au_f, "") or "") if au_f else None
        image = IMG_RE.search(f.get(im_f, "") or "") if im_f else None
        key = text
        if not code and key in seen:
            code = "C08"                       # duplicate text in this deck
        seen[key] = True
        rows.append({
            "source_id": src_id, "ref": str(note.note_id),
            "text": text,
            "reading": clean_text(f.get(rd_f, "")) if rd_f else "",
            "translation": clean_text(f.get(tr_f, "")) if tr_f else "",
            "episode": clean_text(f.get(ep_f, ""))[:40] if ep_f else "",
            "start": "", "end": "",
            "media_audio": reader.media_filename(audio.group(1)) if audio else "",
            "media_image": reader.media_filename(image.group(1)) if image else "",
            "char_len": len(re.sub(r"\W", "", text, flags=re.UNICODE)),
            "flags": flags, "keep": 0 if code else 1,
            "drop_code": code or "", "known": "{}",
        })
        dropped[code or "kept"] = dropped.get(code or "kept", 0) + 1

    store.add_sentences(src_id, rows)
    reader.close()
    return {"source_id": src_id, "notes": len(rows),
            "kept": dropped.get("kept", 0), "drops": {k: v for k, v in dropped.items()
                                                      if k != "kept"}}


def import_freq_tsv(store: Store, path: str | Path, name: str | None = None,
                    word_col: int = 0, level_col: int = 1, rank_col: int | None = None,
                    level_order: list[str] | None = None) -> int:
    """Frequency list as TSV/CSV: word<TAB>level<TAB>rank."""
    path = Path(path)
    words, levels = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = [p.strip() for p in re.split(r"\t|,", line)]
        if len(parts) <= word_col or not parts[word_col]:
            continue
        lvl = parts[level_col] if len(parts) > level_col else ""
        rk = int(parts[rank_col]) if rank_col is not None and len(parts) > rank_col \
            and parts[rank_col].isdigit() else None
        if lvl and lvl not in levels:
            levels.append(lvl)
        words.append((parts[word_col], lvl, rk if rk is not None else 0))
    if not level_order:
        level_order = default_level_order(levels)
    return store.add_lexicon(name or path.stem, words, level_order)


def import_freq_apkg(store: Store, path: str | Path, name: str | None = None,
                     word_field: str | None = None, level_field: str | None = None,
                     level_order: list[str] | None = None) -> int:
    """Frequency list straight from an Anki deck (e.g. Kaishi 1.5k):
    guesses word/level fields if not given."""
    path = Path(path)
    reader = DeckReader.open(path)
    words, levels = [], []
    for note in reader.notes():
        f = note.fields
        keys = list(f)
        wf = word_field or pick_field(keys, ["word", "vocab", "expression",
                                             "kanji", "front", "vocab-expression"])
        lf = level_field or pick_field(keys, ["level", "jlpt", "grade", "tag"])
        if not wf:
            continue
        w = clean_text(f.get(wf, ""))
        if not w:
            continue
        lvl = clean_text(f.get(lf, "")) if lf else ""
        if lvl and lvl not in levels:
            levels.append(lvl)
        words.append((w, lvl, len(words) + 1))
    if not level_order:
        level_order = default_level_order(levels)
    lid = store.add_lexicon(name or path.stem, words, level_order)
    reader.close()
    return lid


def import_video(store, video_path: str | Path, subs_path: str | Path,
                 offset: float = 0.0, name: str | None = None) -> dict:
    """Index a video + subtitles pair. Cue times are stored ORIGINAL;
    the global offset and any later shift segments live in sources.meta
    and are applied at media-cut time (no re-import needed)."""
    from . import subs as subs_mod
    video_path, subs_path = Path(video_path), Path(subs_path)
    cues = subs_mod.parse(subs_path)
    if not cues:
        raise ValueError("no cues parsed from the subtitle file")
    src_id = store.add_source(
        "video", name or video_path.stem, str(video_path),
        {"video": str(video_path), "subs": str(subs_path), "subs_name":
         subs_path.name, "offset": offset, "segments": []})
    rows = []
    for i, (start, end, text) in enumerate(cues, 1):
        code, flags = classify_quality(text, MAX_CHARS)
        rows.append({
            "source_id": src_id, "ref": str(i),
            "text": text, "reading": "", "translation": "",
            "episode": "", "start": f"{start:.3f}", "end": f"{end:.3f}",
            "media_audio": "cut", "media_image": "frame",
            "char_len": len(re.sub(r"\W", "", text, flags=re.UNICODE)),
            "flags": flags, "keep": 0 if code else 1,
            "drop_code": code or "", "known": "{}",
        })
    store.add_sentences(src_id, rows)
    return {"source_id": src_id, "cues": len(rows),
            "kept": sum(1 for r in rows if r["keep"])}
