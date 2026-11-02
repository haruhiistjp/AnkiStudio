# Mine natural example sentences for every Kelly A1-A2 word from the corpus.
#
# Inputs:
#   data/lex/kelly_forms.tsv         word -> inflected forms
#   data/corpus/*_articles.txt       articles ("<<<URL>>>" + text lines)
#   data/cc_filtered.txt             older scrape (one sentence per line)
# Output:
#   data/mined_examples.tsv          Word, POS, CEFR, Sent1, Sent2
#
# Matching notes:
#   - forms map to SETS of kelly words (inflection is ambiguous across
#     lemmas: jag/mig, bra/bäst, den/det); a sentence indexes under every
#     candidate word.
#   - at selection time, sentences containing a form UNIQUE to the target
#     word are preferred, so 'den' examples actually contain 'den'.
#   - the word itself is always one of its own forms (numerals map to SALDO
#     number senses whose forms don't include the word form).

import csv, re, glob, sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent

# license classes: "open" sources may go into a published deck,
# "restricted" are personal-study only (see data/corpus/LICENSES.md)
SOURCE_LICENSE = {
    "suc2": "open",
    "pocketguide": "open",
    "enkelsvenska": "restricted",
    "8sidor": "restricted",
}
MODE = "all"
if "--sources" in sys.argv:
    MODE = sys.argv[sys.argv.index("--sources") + 1]
if MODE not in ("all", "open"):
    sys.exit("usage: mine_corpus.py [--sources open|all]")

# ---------------------------------------------------------------- load forms
form2words = defaultdict(set)          # form(lower) -> {kelly words}
word_forms = {}                        # word -> set of forms
multiword = []
rows = list(csv.DictReader(open(ROOT / "data/lex/kelly_forms.tsv"), delimiter="\t"))
for r in rows:
    word = r["Word"]
    if " " in word:
        multiword.append(word)
        continue
    forms = set()
    for f in r["Forms"].split():
        if re.fullmatch(r"[a-zA-ZÅÄÖåäöéÉèÈüÜ-]+", f):
            forms.add(f.lower())
    forms.add(word.lower())            # word is always its own form
    word_forms[word] = forms
    for f in forms:
        form2words[f].add(word)

unique_forms = {w: {f for f in fs if form2words[f] == {w}} for w, fs in word_forms.items()}
print(f"forms indexed: {len(form2words)}, multiword expressions: {len(multiword)}")

# ---------------------------------------------------------------- load corpus
JUNK_LINE = re.compile(
    r"^(Hoppa till|Publicerad|Uppdaterad|Foto|Bild|Lyssna|Läs (också|mer)|Källa|"
    r"Dela|Följ oss|Prenumerera|Logga in|Sök|Huvudmeny|Till innehållet|Skicka|"
    r"Tipsa oss|©|Alla rättigheter|Kakpolicy|Kontakta|Mer om|Se också|Arkiv)", re.I)

def articles():
    for path in sorted(glob.glob(str(ROOT / "data/corpus/*_articles.txt"))):
        src = Path(path).stem.replace("_articles", "")
        if MODE == "open" and SOURCE_LICENSE.get(src) != "open":
            continue
        buf, url = [], None
        for line in open(path):
            line = line.rstrip("\n")
            if line.startswith("<<<") and line.endswith(">>>"):
                if url and buf:
                    yield buf
                url, buf = line[3:-3], []
            else:
                buf.append(line)
        if url and buf:
            yield buf

def sentences_from(text):
    lines = []
    for ln in text.split("\n"):
        ln = re.sub(r"\s+", " ", ln).strip()
        if not ln:
            continue
        ln = re.sub(r"\s*[–-]\s*8 Sidor\s*$", "", ln)      # title suffix
        if JUNK_LINE.match(ln) or "@" in ln or "http" in ln:
            continue
        lines.append(ln)
    joined = " ".join(lines)
    for s in re.split(r"(?<=[.!?])\s+(?=[A-ZÅÄÖ“»1-9])", joined):
        yield s.strip()

WORDTOK = re.compile(r"[a-zA-ZÅÄÖåäöéèü-]+")
def ok_sentence(s):
    if not (25 <= len(s) <= 170):
        return False
    words = WORDTOK.findall(s)
    if not (5 <= len(words) <= 22):
        return False
    if sum(c.isdigit() for c in s) > 4:
        return False
    if s.count('"') % 2 or s.count("«") or s.count("»"):
        return False
    letters = sum(c.isalpha() for c in s)
    if letters / max(len(s), 1) < 0.72:
        return False
    if not s[0].isupper() and s[0] not in "ÅÄÖ":
        return False
    return True

MW_RE = [re.compile(r"(?<![a-zA-Zåäö])" + re.escape(mw.lower()) + r"(?![a-zA-Zåäö])") for mw in multiword]

def hits_of(s, low_toks):
    hits = set()
    for t in low_toks:
        hits |= form2words.get(t, set())
    slow = s.lower()
    for mw, rx in zip(multiword, MW_RE):
        if rx.search(slow):
            hits.add(mw)
    return hits

# ---------------------------------------------------------------- index
by_word = defaultdict(list)   # kelly word -> [(penalty, score, sentence)]
seen_sent = set()
n_sent = 0
for buf in articles():
    for s in sentences_from("\n".join(buf)):
        if not ok_sentence(s):
            continue
        key = s.lower()
        if key in seen_sent:
            continue
        seen_sent.add(key)
        toks = WORDTOK.findall(s)
        low = [t.lower() for t in toks]
        hits = hits_of(s, low)
        if not hits:
            continue
        caps = sum(1 for i, t in enumerate(toks) if i > 0 and t[:1].isupper())
        score = len(toks) + 2 * min(caps, 4)
        n_sent += 1
        for w in hits:
            if len(by_word[w]) < 2000:
                by_word[w].append((score, s))

# old CC pool as fallback only in "all" mode (mixed licenses)
if MODE == "all":
    for s in open(ROOT / "data/cc_filtered.txt"):
        s = s.strip()
        if ok_sentence(s) and s.lower() not in seen_sent:
            toks = [t.lower() for t in WORDTOK.findall(s)]
            hits = hits_of(s, toks)
            for w in hits:
                by_word[w].append((60 + len(toks), s))

print(f"indexed sentences: {n_sent}")

# ---------------------------------------------------------------- select
# Tier 0: sentence contains the literal Kelly word (case-insensitive,
# word-boundary). Tier 1: only an inflected form. SALDO pronoun/determiner
# paradigms overlap heavily (jag..1 includes mig/min), so literal presence is
# the only reliable signal for those words.
LIT_RE = {}
def literal_rx(word):
    if word not in LIT_RE:
        LIT_RE[word] = re.compile(
            r"(?<![a-zA-Zåäö])" + re.escape(word.lower()) + r"(?![a-zA-Zåäö])", re.I)
    return LIT_RE[word]

out = []
for r in rows:
    word = r["Word"]
    cands = by_word.get(word, [])
    rx = literal_rx(word)
    scored = []
    for score, s in cands:
        scored.append((0 if rx.search(s) else 1, score, s))
    scored.sort(key=lambda t: (t[0], t[1]))
    chosen = []
    for pen, score, s in scored:
        if s in chosen:
            continue
        chosen.append(s)
        if len(chosen) == 2:
            break
    out.append((word, r["POS"], r["CEFR"], chosen[0] if chosen else "",
                chosen[1] if len(chosen) > 1 else ""))

OUTFILE = ROOT / ("data/mined_examples_open.tsv" if MODE == "open" else "data/mined_examples.tsv")
with open(OUTFILE, "w") as f:
    f.write("Word\tPOS\tCEFR\tSent1\tSent2\n")
    for r in out:
        f.write("\t".join(r) + "\n")

have1 = sum(1 for r in out if r[3])
have2 = sum(1 for r in out if r[4])
lit1 = sum(1 for r in out if r[3] and literal_rx(r[0]).search(r[3]))
print(f"[{MODE}] coverage: >=1 sentence: {have1}/{len(out)} ({100*have1/len(out):.0f}%), "
      f">=2: {have2}/{len(out)} ({100*have2/len(out):.0f}%)")
print(f"[{MODE}] sent1 contains the literal word: {lit1}/{have1}")
print("wrote", OUTFILE)
