"""Subtitle parsing: SRT, WebVTT and ASS/SSA -> cues [(start, end, text)]
with times in seconds. Styling/HTML tags are stripped; multi-line cue text
is joined with a space.
"""
from __future__ import annotations

import re
from pathlib import Path

_TS = r"(\d+):(\d{2}):(\d{2})[.,](\d{1,3})"
TAG_RE = re.compile(r"</?[^>]+>")
ASS_DRAWING = re.compile(r"\{[^}]*\}")


def _ts(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _norm(text: str) -> str:
    text = ASS_DRAWING.sub("", text)
    text = TAG_RE.sub("", text)
    return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()


def parse(path: str | Path) -> list[tuple[float, float, str]]:
    p = Path(path)
    raw = p.read_text(encoding="utf-8", errors="replace")
    if "[Script Info]" in raw or re.search(r"^Dialogue:", raw, re.M):
        return _ass(raw)
    if raw.lstrip().startswith("WEBVTT"):
        return _vtt(raw)
    return _srt(raw)


def _srt(raw: str):
    cues = []
    block_re = re.compile(
        rf"{_TS}\s*-->\s*{_TS}(.*?)(?=\n\s*\n|\Z)", re.S)
    for m in block_re.finditer(raw):
        start = _ts(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _ts(m.group(5), m.group(6), m.group(7), m.group(8))
        text = _norm(m.group(9))
        if text:
            cues.append((start, end, text))
    return cues


def _vtt(raw: str):
    body = re.sub(r"^WEBVTT.*?\n\s*\n", "", raw, count=1, flags=re.S)
    return _srt(body)


def _ass(raw: str):
    cues = []
    for line in raw.splitlines():
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
        text = _norm(",".join(parts[9:]))
        if text and text != "​":
            cues.append((start, end, text))
    return cues
