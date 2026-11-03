"""Subtitle parsing: SRT, WebVTT and ASS/SSA -> cues with times in seconds.
Styling/HTML tags are stripped. Cues keep their style name and per-segment
text (ASS \\N / multi-line SRT), which powers language analysis: fansub
releases often carry two languages in one file (Japanese + Chinese), either
as two Dialogue lines per cue, two styles, or two segments in one line.
"""
from __future__ import annotations

import re
from pathlib import Path

_TS = r"(\d+):(\d{2}):(\d{2})[.,](\d{1,3})"
TAG_RE = re.compile(r"</?[^>]+>")
ASS_DRAWING = re.compile(r"\{[^}]*\}")
KANA_RE = re.compile(r"[\u3041-\u309f\u30a0-\u30fa\u30fc-\u30ff\u31f0-\u31ff]")
HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _ts(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _clean(text: str) -> str:
    text = ASS_DRAWING.sub("", text)
    text = TAG_RE.sub("", text)
    return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()


def line_lang(text: str) -> str:
    """'ja' when the text contains kana (Chinese subtitles never do),
    'zh' for han-only lines, else 'other'."""
    if KANA_RE.search(text):
        return "ja"
    if HAN_RE.search(text):
        return "zh"
    return "other"


def parse_detail(path: str | Path) -> list[dict]:
    """Cues as dicts: {start, end, text, style, segs} where segs is the
    per-segment text list (one segment for plain single-language cues)."""
    p = Path(path)
    raw = p.read_text(encoding="utf-8", errors="replace")
    if "[Script Info]" in raw or re.search(r"^Dialogue:", raw, re.M):
        return _ass(raw)
    if raw.lstrip().startswith("WEBVTT"):
        return _vtt(raw)
    return _srt(raw)


def parse(path: str | Path) -> list[tuple[float, float, str]]:
    return [(c["start"], c["end"], c["text"]) for c in parse_detail(path)]


def _mk(start: float, end: float, style: str, segs: list[str]) -> dict | None:
    segs = [s for s in segs if s and s != "​"]
    if not segs:
        return None
    return {"start": start, "end": end, "style": style, "segs": segs,
            "text": " ".join(segs)}


def _srt(raw: str) -> list[dict]:
    cues = []
    block_re = re.compile(
        rf"{_TS}\s*-->\s*{_TS}(.*?)(?=\n\s*\n|\Z)", re.S)
    for m in block_re.finditer(raw):
        start = _ts(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _ts(m.group(5), m.group(6), m.group(7), m.group(8))
        # multi-line cue bodies become segments (a bilingual SRT keeps
        # one language per line; a wrapped sentence stays one language)
        segs = [_clean(ln) for ln in m.group(9).splitlines()]
        c = _mk(start, end, "", segs)
        if c:
            cues.append(c)
    return cues


def _vtt(raw: str) -> list[dict]:
    body = re.sub(r"^WEBVTT.*?\n\s*\n", "", raw, count=1, flags=re.S)
    return _srt(body)


def _ass(raw: str) -> list[dict]:
    cues = []
    style_ix = 3                     # default: Layer,Start,End,Style,...
    for line in raw.splitlines():
        if line.startswith("Format:") and "Style" in line:
            cols = [c.strip().lower() for c in line.split(":", 1)[1].split(",")]
            if "style" in cols:
                style_ix = cols.index("style")
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(":", 1)[1].split(",")
        if len(parts) < 10:
            continue

        def t(s: str) -> float:
            s = s.strip()
            h, m, rest = s.split(":")
            sec, cs = rest.split(".", 2)[:2] if "." in rest else (rest, "0")
            return int(h) * 3600 + int(m) * 60 + int(sec) + int(cs) / 100

        start, end = t(parts[1]), t(parts[2])
        style = parts[style_ix].strip() if len(parts) > style_ix else ""
        segs = [_clean(seg) for seg in re.split(r"\\[Nn]", ",".join(parts[9:]))]
        c = _mk(start, end, style, segs)
        if c:
            cues.append(c)
    return cues


# ---------- bilingual-file analysis ----------

def cue_lang(cue: dict) -> str:
    """Language of a cue: 'mix' when its segments disagree (the
    two-languages-in-one-line case), else the common segment language."""
    langs = {line_lang(s) for s in cue["segs"]}
    if "ja" in langs and "zh" in langs:
        return "mix"
    for primary in ("ja", "zh", "other"):
        if primary in langs:
            return primary
    return "other"


def _has_ja(cue: dict) -> bool:
    return any(line_lang(s) == "ja" for s in cue["segs"])


def analyze_cues(cues: list[dict]) -> dict:
    """Decide whether a file is bilingual and by which pattern:
    pairs  — cues sharing exact timings, one Japanese + one Chinese
    styles — per-style language split (e.g. style 'JP' vs 'CN')"""
    n = len(cues)
    if not n:
        return {"total": 0, "kana_lines": 0, "styles": [], "paired_share": 0.0,
                "mode": "", "bilingual": False}
    langs = [cue_lang(c) for c in cues]
    kana_lines = sum(1 for l in langs if l in ("ja", "mix"))

    stylestats: dict[str, dict] = {}
    for c, l in zip(cues, langs):
        s = stylestats.setdefault(c["style"] or "", {"lines": 0, "ja": 0})
        s["lines"] += 1
        if l in ("ja", "mix"):
            s["ja"] += 1

    groups: dict[tuple[float, float], list[int]] = {}
    for i, c in enumerate(cues):
        groups.setdefault((round(c["start"], 2), round(c["end"], 2)), []).append(i)
    paired = 0
    for ix in groups.values():
        ls = [langs[i] for i in ix]
        if len(ix) >= 2 and (("ja" in ls) or ("mix" in ls)) and "zh" in ls:
            paired += len(ix)
    paired_share = paired / n

    mode = ""
    if paired_share >= 0.5:
        mode = "pairs"
    else:
        big = [s for s in stylestats.values() if s["lines"] >= 8]
        ja_styles = [s for s in big if s["ja"] / s["lines"] >= 0.7]
        zh_styles = [s for s in big if s["ja"] / s["lines"] <= 0.2]
        if ja_styles and zh_styles:
            mode = "styles"
        elif sum(1 for l in langs if l == "mix") >= n * 0.3:
            mode = "mixed"            # both languages inside single cues
    return {"total": n, "kana_lines": kana_lines,
            "styles": [{"name": k, "lines": v["lines"], "ja": v["ja"]}
                       for k, v in sorted(stylestats.items())],
            "paired_share": round(paired_share, 3),
            "mode": mode, "bilingual": bool(mode)}


def pick_language(cues: list[dict], keep: str) -> list[dict]:
    """Keep one language of a bilingual file ('ja' or 'zh'); a mixed cue
    (both languages on one line) keeps only its matching segment. Any
    other keep value returns the cues unchanged."""
    if keep not in ("ja", "zh"):
        return cues
    out: list[dict] = []
    for c in cues:
        lang = cue_lang(c)
        if lang == "mix":
            segs = [s for s in c["segs"] if line_lang(s) == keep]
            if segs:
                out.append({**c, "segs": segs, "text": " ".join(segs)})
        elif lang == keep:
            out.append(c)
    return out


# ---------- fixed-subtitle export (timing-only rewrite) ----------

def _ts_ass(s: str) -> float:
    h, m, rest = s.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def _fmt_ass(t: float) -> str:
    t = max(0.0, t)
    hh, mm = int(t // 3600), int(t % 3600 // 60)
    return f"{hh}:{mm:02d}:{t % 60:05.2f}"


_TS_LINE = re.compile(r"(\d+):(\d{2}):(\d{2})([.,])(\d{1,3})\s*-->\s*"
                      r"(\d+):(\d{2}):(\d{2})([.,])(\d{1,3})")


def _fmt_plain(sep: str, pad: int, t: float) -> str:
    """Format shifted seconds with the original timestamp's shape."""
    total_ms = max(0, round(t * 1000))
    hh, rem = divmod(total_ms, 3600_000)
    mm, rem = divmod(rem, 60_000)
    return f"{hh:02d}:{mm:02d}:{rem // 1000:02d}{sep}{rem % 1000:0{pad}d}"


def retime(path: str | Path, shift_fn) -> tuple[str, str]:
    """Rewrite a subtitle file with corrected timings, keeping everything
    else byte-for-byte (styles, both languages, comments). shift_fn(t)
    returns the seconds to add to a cue starting at t. Returns
    (new file text, suggested filename)."""
    p = Path(path)
    raw = p.read_text(encoding="utf-8", errors="replace")
    is_ass = "[Script Info]" in raw or re.search(r"^Dialogue:", raw, re.M)
    if is_ass:
        lines = []
        for line in raw.splitlines():
            if line.startswith(("Dialogue:", "Comment:")):
                head, tail = line.split(":", 1)
                parts = tail.split(",")
                if len(parts) >= 10:
                    try:
                        delta = shift_fn(_ts_ass(parts[1]))
                        parts[1] = _fmt_ass(_ts_ass(parts[1]) + delta)
                        parts[2] = _fmt_ass(_ts_ass(parts[2]) + delta)
                        line = head + ":" + ",".join(parts)
                    except ValueError:
                        pass
            lines.append(line)
        text = "\n".join(lines) + "\n"
    else:
        def sub(m):
            start = _ts(m.group(1), m.group(2), m.group(3), m.group(5))
            delta = shift_fn(start)
            end = _ts(m.group(6), m.group(7), m.group(8), m.group(10)) + delta
            return (f"{_fmt_plain(m.group(4), len(m.group(5)), start + delta)}"
                    f" --> "
                    f"{_fmt_plain(m.group(9), len(m.group(10)), end)}")
        text = _TS_LINE.sub(sub, raw)
    stem = p.stem or "subs"
    return text, f"{stem}.fixed{p.suffix or '.srt'}"
