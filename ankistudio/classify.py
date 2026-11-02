"""Per-sentence vocabulary-level classification against a lexicon.

With fugashi+unidic available (the [jp] extra) sentences are tokenized and
matched by lemma; otherwise a naive surface-substring fallback is used.
A sentence's level = the easiest lexicon level L such that no lexicon word
harder than L occurs in it AND (tokenized mode only) the count of unknown
content words is within the budget for L. No fit -> level '' (beyond).
"""
from __future__ import annotations

import json
import time

from .store import Store

try:
    from fugashi import Tagger
    _tagger = Tagger()
    CONTENT_POS_SKIP = ("助詞", "助動詞", "記号", "接頭辞", "接尾辞", " filler ")
except Exception:                       # pragma: no cover - jp extra absent
    _tagger = None


def _tokens(text: str) -> list[tuple[str, str, str]]:
    """(surface, lemma, pos) content-ish tokens; empty list in fallback."""
    if _tagger is None:
        return []
    out = []
    for w in _tagger(text):
        pos1 = (w.feature.pos1 or "") if hasattr(w.feature, "pos1") else ""
        if any(skip in pos1 for skip in ("助詞", "助動", "記号")):
            continue
        lemma = w.feature.lemma if hasattr(w.feature, "lemma") else None
        out.append((w.surface, lemma or w.surface, pos1))
    return out


def sentence_level(text: str, word_level: dict[str, int], n_levels: int,
                   budget_base: int = 1) -> int | None:
    """easiest fitting level index, or None if beyond the lexicon."""
    toks = _tokens(text)
    if toks:
        hardest = -1
        unknown = 0
        for surface, lemma, _pos in toks:
            lvl = word_level.get(lemma, word_level.get(surface))
            if lvl is not None:
                hardest = max(hardest, lvl)
            else:
                unknown += 1
        for i in range(n_levels):
            if hardest <= i and unknown <= budget_base + i:
                return i
        return None
    # naive fallback: hardest lexicon word present by substring; unknowns
    # are unknowable without a tokenizer, so only word levels gate the fit
    hardest = -1
    for w, lvl in word_level.items():
        if len(w) >= 2 and w in text:
            hardest = max(hardest, lvl)
    for i in range(n_levels):
        if hardest <= i:
            return i
    return None


def classify_store(store: Store, lexicon_id: int) -> dict:
    """Recompute sentences.level for every kept sentence."""
    store.db.execute(
        "alter table sentences add column level text default ''") \
        if "level" not in {r[1] for r in store.db.execute("pragma table_info(sentences)")} \
        else None
    lex = store.db.execute("select * from lexicons where id=?",
                           (lexicon_id,)).fetchone()
    if not lex:
        raise KeyError(f"no lexicon {lexicon_id}")
    order = json.loads(lex["level_order"] or "[]")
    word_level = {w: order.index(l) for w, l in store.lexicon_word_map(lexicon_id).items()
                  if l in order}
    counts: dict[str, int] = {}
    t0 = time.time()
    rows = store.db.execute(
        "select id, text from sentences where keep=1 and text != ''").fetchall()
    updates = []
    for r in rows:
        idx = sentence_level(r["text"], word_level, len(order))
        lvl = order[idx] if idx is not None else ""
        counts[lvl] = counts.get(lvl, 0) + 1
        updates.append((lvl, r["id"]))
    store.db.executemany("update sentences set level=? where id=?", updates)
    store.db.commit()
    mode = "tokenized (fugashi)" if _tagger else "naive substring (no tokenizer)"
    return {"mode": mode, "classified": len(rows), "by_level": counts,
            "seconds": round(time.time() - t0, 1)}
