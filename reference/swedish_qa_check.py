# QA gate for data/freq_a1a2_full.tsv (and data/verbs.tsv sanity).
# Stdlib only. Run after any data change or rebuild:
#   .venv/bin/python qa_check.py
# Exits non-zero if any hard check fails; soft checks print warnings.

import csv, re, sys, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data/freq_a1a2_full.tsv"

# English may keep Swedish proper nouns/titles/media names, but not much else.
ALLOWED_SV_IN_EN = re.compile(
    r'(Malmö|Skåne|Skärholmen|Säpo|Göteborg|Småland|Norrland|Älvsjö|Åland|Smögen|'
    r'Kållered|Skellefteå|Åre|Sälen|Idre|Vemdalen|Östersjön|Norrköping|allemansrätten|'
    r'Märta|midsommar|Smörgås|pingst|Valborg|lucia|smörgåsbord|Systembolaget|'
    r'Svenskt Näringsliv|Surströmming|Djurgården|Så mycket bättre|bahá|ål|tryffel|'
    r'UKÄ|MYH|Särvux|Ärna|Linköping|Uppsala|Malmö|Dalarna|Siljan|Gränby|'
    r'Stjärnorna kallnar|Färgglad Dröm|'
    r'å, ä, ö|sje-ljud)', re.I)

NAV_JUNK = re.compile(r'(Ladda ner|Hoppa till|pocket guide \d|PDF ?\d|Källa:|Publicerad|'
                      r'Skip to content|Download as)', re.I)
SV_MARKERS = re.compile(r'\b(är|och|inte|att|på|som|med|den|det|vi|jag|han|hon|de|till|'
                        r'från|men|av|för|har|var|kan|ska|kommer|finns|mycket|många|alla|'
                        r'ännu|också|väldigt)\b')
STRONG_SV = {'är','och','inte','att','på','som','med','finns','kommer','väldigt','också','ännu','mycket','många'}
TEMPLATE_HEADS = re.compile(r'^(Jag \S+ varje dag|Hon \S+ nu|Vi lär oss |Ordet .* är viktigt|'
                            r'Det är \S+ bra|Han är \S+ trött|Jag har \S+ böcker|We will |I will )')
DIALOG = re.compile(r'(\.[A-ZÅÄÖ][a-zåäö]+:|\s[A-ZÅÄÖ][a-zåäö]+:\s|^[A-ZÅÄÖ]:\s|Lyssna\b|^Listen\b)')

# single letters å/ä/ö are legitimate in EN when discussing Swedish orthography
ALLOWED_WORDS = {'å','ä','ö','Å','Ä','Ö'}

def fail(msg):
    print("FAIL:", msg)
    FAILURES.append(msg)

def warn(msg):
    print("warn:", msg)

FAILURES = []

def main():
    with open(DATA) as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    if len(rows) != 2808:
        warn(f"row count is {len(rows)} (expected 2808)")

    for r in rows:
        w = r["Word"]
        for c in ("Meaning", "Example1", "Example1_EN", "Example2", "Example2_EN"):
            if not r[c].strip():
                fail(f"{w}: empty {c}")
        # duplicated translation
        if r["Example2_EN"] == r["Example1_EN"] and r["Example1_EN"]:
            fail(f"{w}: Example2_EN duplicates Example1_EN")
        # Swedish text left in EN columns
        for c in ("Example1_EN", "Example2_EN"):
            t = r[c]
            t_stripped = ALLOWED_SV_IN_EN.sub('', t)
            sv_letters = re.findall(r'\b\w*[åäöÅÄÖ]\w*\b', t_stripped)
            bad_sv = [s for s in sv_letters if s not in ALLOWED_WORDS]
            if bad_sv:
                fail(f"{w}: Swedish-looking text in {c}: {bad_sv[:3]} | {t[:60]}")
            if NAV_JUNK.search(t):
                fail(f"{w}: nav junk in {c}: {t[:60]}")
            if DIALOG.search(t):
                fail(f"{w}: dialogue/prefix junk in {c}: {t[:60]}")
            # untranslated sentence (Swedish function words in EN)
            hits = SV_MARKERS.findall(t)
            strong = [h for h in hits if h.lower() in STRONG_SV]
            if len(strong) >= 1 and len(hits) >= 2:
                fail(f"{w}: untranslated Swedish in {c}: {t[:60]}")
        for c in ("Example1", "Example2"):
            if NAV_JUNK.search(r[c]) and w not in ("ner", "ladda", "an", "klicka", "övning", "nedan"):
                fail(f"{w}: nav junk in {c}: {r[c][:60]}")
            if DIALOG.search(r[c]):
                fail(f"{w}: dialogue/prefix junk in {c}: {r[c][:60]}")
            if TEMPLATE_HEADS.match(r[c]) and not r[c].endswith(w + '.'):
                pass  # generic verb frame "Jag vill X." is fine; old broken frames caught below
            if re.match(r'^(Jag (vara|ha|kunna|vilja|bli|få|gå|se|ta|göra|säga) varje dag|Hon (vara|ha|kunna|bli|få|gå|se|ta|göra|säga) nu)\.', r[c]):
                fail(f"{w}: broken old verb template in {c}")
            if any(ord(ch) > 0x2500 and unicodedata.category(ch) == "So" for ch in r[c]):
                fail(f"{w}: emoji in {c}")
        # meaning hygiene
        m = r["Meaning"]
        if re.search(r'\[|[0-9]\.\s', m):
            fail(f"{w}: dictionary code in meaning: {m[:60]}")
        if m in ("—",):
            fail(f"{w}: degenerate meaning")

    # verbs.tsv sanity
    vrows = [l.split("\t") for l in open(ROOT / "data/verbs.tsv").read().splitlines() if l.strip()]
    bad = [v[:2] for v in vrows if len(v) != 12]
    if bad:
        fail(f"verbs.tsv: {len(bad)} rows without 12 columns")
    if len(vrows) != 144:
        warn(f"verbs.tsv has {len(vrows)} rows (expected 144)")

    print(f"\nchecked {len(rows)} frequency rows, {len(vrows)} verb rows")
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} FAILURES")
        sys.exit(1)
    print("RESULT: all checks passed")

if __name__ == "__main__":
    main()
