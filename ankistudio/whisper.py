"""Estimate a subtitle/audio global shift with Whisper.

Algorithm: pick a handful of well-spread cues, cut a window around each
at ORIGINAL cue times, transcribe with the local whisper CLI, and match
the transcription against the cue text. The matched utterance's first
word timestamp minus the cue's position inside the window is that cue's
drift estimate; the median across cues is the suggested global offset.

Matching must survive real fansub conditions: subtitles written in kanji
while whisper transcribes kana readings, utterances split across two
whisper segments, and noisy windows. So both sides are normalized
(katakana -> hiragana, punctuation dropped), scored with a character
bigram Dice coefficient, and candidates include adjacent segment pairs.
If too few cues match, a second pass runs on FRESH cues with a wider
window — whisper transcribes much better with surrounding context.

Timing model reminder: nothing here touches cut clips. Cuts (and the
whisper windows) are made on demand from the source's full-length audio
track using the ORIGINAL cue times, so detection works identically
before and after import regardless of any offsets set on the source.
"""
from __future__ import annotations

import json
import re
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path

MARGIN = 6.0          # pass 1: seconds of audio around each sampled cue
MARGIN2 = 14.0        # pass 2: wider — more context, whisper does better
CLIP_MAX = 16.0       # pass 1: hard cap on clip length (cue + margins)
CLIP_MAX2 = 26.0      # pass 2 cap
MAX_SHIFT = 12.0      # plausible drift (TV-sub vs web-video can exceed 5s);
                      # pass-1 windows physically cap this near ±7 anyway
MAX_SAMPLES = 6
PASS2_SAMPLES = 3     # fresh cues for the second (slower) pass
RUN_TIMEOUT = (100, 150)   # per whisper invocation, seconds, by pass
DEADLINE = 280.0      # whole analysis, seconds — never run unbounded
MATCH_MIN = 0.2       # Dice coefficient below this = not the same utterance
CONSISTENCY = 0.75    # median absolute deviation above this = inconsistent

_K2H = {chr(k): chr(k - 0x60) for k in range(0x30A1, 0x30F7)}


def _norm_text(s: str) -> str:
    s = (s or "").translate(_K2H)
    return re.sub(r"[^\u3040-\u30ff\u4e00-\u9fffa-z]", "", s.lower())


def _bigrams(s: str) -> set[str]:
    s = _norm_text(s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _dice(a: str, b: str) -> float:
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    return 2 * len(A & B) / (len(A) + len(B))


def _pick_model() -> str:
    cache = Path.home() / ".cache" / "whisper"
    for m in ("small", "base"):
        if (cache / f"{m}.pt").exists():
            return m
    return "small"


def _pick(cues: list[dict], already: set = set()) -> list[dict]:
    """Evenly spread sample, skipping cues measured in an earlier pass."""
    pool = [c for c in cues if c["ref"] not in already]
    if not pool:
        return []
    step = max(1, len(pool) // MAX_SAMPLES)
    return pool[step // 2::step][:MAX_SAMPLES]


def _onset(seg: dict) -> float | None:
    words = seg.get("words") or []
    if words:
        return float(words[0]["start"])
    return None


def _window(start: float, end: float, margin: float,
            clip_max: float) -> tuple[float, float]:
    """[start-margin, end+margin] with the total length capped — long
    windows are what makes whisper crawl on difficult audio."""
    if (end - start) + 2 * margin > clip_max:
        margin = max(1.5, (clip_max - (end - start)) / 2)
    s = max(0.0, start - margin)
    return s, min(end + margin, s + clip_max)


def _measure_clip(media: Path, astream: int | None, cue: dict, margin: float,
                  clip_max: float, run_timeout: int, wbin: str, model: str,
                  td: Path, seq: int) -> dict:
    """Transcribe one window and match it to the cue. Returns a sample
    dict: {ref, text, offset|None, match, heard}."""
    start, end = float(cue["start"]), float(cue["end"])
    s, e = _window(start, end, margin, clip_max)
    wav = td / f"p{seq}.wav"
    try:
        from . import ffmpeg as ff
        args = ["-ss", f"{s:.3f}", "-t", f"{e - s:.3f}", "-i", str(media)]
        if astream is not None:
            args += ["-map", f"0:a:{astream}"]
        args += ["-ar", "16000", "-ac", "1", str(wav)]
        ff._run(args)
        subprocess.run(
            [wbin, str(wav), "--model", model, "--language", "ja",
             "--output_format", "json", "--output_dir", str(td),
             "--word_timestamps", "True", "--verbose", "False",
             "--temperature", "0", "--beam_size", "1"],
            check=True, capture_output=True, timeout=run_timeout)
        segs = json.loads((td / f"{wav.stem}.json").read_text())["segments"]
    except Exception:
        return {"ref": cue["ref"], "text": cue["text"][:30],
                "offset": None, "match": 0.0, "heard": ""}

    # candidates: each segment, plus adjacent pairs (whisper splits
    # utterances mid-sentence); onset = first word of the first segment
    cands = []
    for i, g in enumerate(segs):
        text, on = g.get("text", ""), _onset(g)
        cands.append((text, on, text))
        if i + 1 < len(segs):
            g2 = segs[i + 1]
            joined = text + g2.get("text", "")
            cands.append((joined, on, text))
    best_text, best_heard, best_on, best_score = "", "", None, 0.0
    for text, on, heard in cands:
        sc = _dice(text, cue["text"])
        if sc > best_score:
            best_text, best_heard, best_on, best_score = text, heard, on, sc
    if best_score < MATCH_MIN:
        return {"ref": cue["ref"], "text": cue["text"][:30],
                "offset": None, "match": round(best_score, 2),
                "heard": best_heard[:24]}
    onset = best_on if best_on is not None else float(segs[0]["start"])
    off = onset - (start - s)
    ok = abs(off) <= MAX_SHIFT
    return {"ref": cue["ref"], "text": cue["text"][:30],
            "offset": round(off, 2) if ok else None,
            "match": round(best_score, 2), "heard": best_heard[:24]}


def prepare(media: Path, cues: list[dict], astream: int | None,
            project_root: Path) -> dict:
    """Validate and collect everything run_measure needs. Raises
    ValueError (user-facing) BEFORE any streaming starts."""
    if len(cues) < 2:
        raise ValueError("too few usable cues to measure a shift")
    wbin = _whisper_bin(project_root)
    if not wbin:
        raise ValueError("whisper is not installed — use the Install Whisper "
                         "button (or: pip install -U openai-whisper)")
    return {"media": str(media), "cues": cues, "astream": astream,
            "wbin": wbin, "model": _pick_model()}


def _summarize(samples: list[dict], model: str) -> dict:
    good = [s for s in samples if s["offset"] is not None]
    offsets = [float(s["offset"]) for s in good]
    median = round(statistics.median(offsets), 2) if len(offsets) >= 2 else None
    consistent = False
    if median is not None:
        mad = statistics.median(abs(o - median) for o in offsets)
        consistent = mad <= CONSISTENCY

    # Two-shift detection: when the episode's drift CHANGES partway
    # (different release timings spliced, broadcast cuts), a single
    # global offset cannot fit and `consistent` comes out false. Look
    # for a time-ordered split into two coherent clusters and report it
    # as offset + segment so Apply can configure both.
    split = None
    timed = sorted((s for s in good if s.get("at") is not None),
                   key=lambda s: s["at"])
    if len(timed) >= 4:
        best = None
        for k in range(2, len(timed) - 1):
            left = [s["offset"] for s in timed[:k]]
            right = [s["offset"] for s in timed[k:]]
            m1, m2 = statistics.median(left), statistics.median(right)
            if abs(m1 - m2) < 0.75:
                continue        # not a real shift change
            mad1 = statistics.median(abs(o - m1) for o in left)
            mad2 = statistics.median(abs(o - m2) for o in right)
            if mad1 > 0.5 or mad2 > 0.5:
                continue        # clusters themselves are smeared — not a clean split
            cost = mad1 + mad2
            if best is None or cost < best[0]:
                best = (cost, m1, m2, timed[k]["at"])
        if best:
            _, m1, m2, at = best
            split = {"at": round(float(at), 1), "shift": round(m2, 2),
                     "before": round(m1, 2)}

    return {"samples": samples, "matched": len(offsets),
            "total": len(samples), "median": median,
            "consistent": consistent, "split": split, "model": model}


def run_measure(prep: dict):
    """Generator: yields {"sample": {...}, "done": n} per measured cue and
    one final {"result": {...}}. Bounded: clip-length caps, per-run
    timeouts and a global deadline keep the worst case ~5 minutes."""
    import time as _t
    t0 = _t.time()
    samples: list[dict] = []
    try:
        with tempfile.TemporaryDirectory(prefix="as-whisper-") as td:
            td = Path(td)
            seq = 0
            for margin, clip_max, run_to, maxn in (
                    (MARGIN, CLIP_MAX, RUN_TIMEOUT[0], MAX_SAMPLES),
                    (MARGIN2, CLIP_MAX2, RUN_TIMEOUT[1], PASS2_SAMPLES)):
                picked = _pick(prep["cues"],
                               {s["ref"] for s in samples})[:maxn]
                blind_streak = 0        # text matches but speech not in window
                for cue in picked:
                    if _t.time() - t0 > DEADLINE:
                        break
                    seq += 1
                    smp = _measure_clip(Path(prep["media"]), prep["astream"],
                                        cue, margin, clip_max, run_to,
                                        prep["wbin"], prep["model"], td, seq)
                    smp["window"] = f"±{margin:.0f}s"
                    smp["at"] = round(float(cue["start"]), 1)
                    samples.append(smp)
                    yield {"sample": smp, "done": len(samples)}
                    blind_streak = (blind_streak + 1
                                    if smp["offset"] is None and smp["match"] >= 0.4
                                    else 0)
                    if blind_streak >= 3 and margin < MARGIN2:
                        break            # drift exceeds this window — go wide
                if len([s for s in samples if s["offset"] is not None]) >= 2:
                    break
                if _t.time() - t0 > DEADLINE:
                    break
        yield {"result": _summarize(samples, prep["model"])}
    except Exception as e:                     # streaming has begun; report inline
        yield {"error": f"{type(e).__name__}: {e}"}


# ---------- whisper binary management ----------

def _whisper_bin(project_root: Path | None = None) -> str | None:
    """Whisper executable: on PATH, or previously auto-installed into the
    project's dedicated whisper venv (.venv-whisper)."""
    b = shutil.which("whisper")
    if b:
        return b
    if project_root is not None:
        local = project_root / ".venv-whisper" / "bin" / "whisper"
        if local.exists():
            return str(local)
    return None


def ensure_installed(project_root: Path) -> dict:
    """Make a whisper CLI available, auto-installing it when missing.

    openai-whisper is pinned to older Pythons, so it gets its own venv
    (.venv-whisper, CPython 3.11) managed by uv, which also downloads the
    interpreter when necessary. First install downloads a few hundred MB
    (Python + torch + whisper); models are cached separately in
    ~/.cache/whisper on first use."""
    root = Path(project_root)
    existing = _whisper_bin(root)
    if existing:
        return {"bin": existing, "already": True}
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("whisper not found and uv is not installed — "
                         "get uv from https://docs.astral.sh/uv/, or install "
                         "whisper manually: pip install -U openai-whisper")
    vdir = root / ".venv-whisper"
    py = vdir / "bin" / "python"

    def run(args, timeout):
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)

    if not py.exists():
        r = run([uv, "venv", "--python", "3.11", str(vdir)], 600)
        if r.returncode != 0:
            raise ValueError(f"creating the whisper venv failed: "
                             f"{(r.stderr or r.stdout)[-400:]}")
    r = run([uv, "pip", "install", "--python", str(py),
             "openai-whisper"], 1800)
    if r.returncode != 0:
        raise ValueError(f"installing openai-whisper failed: "
                         f"{(r.stderr or r.stdout)[-400:]}")
    b = _whisper_bin(root)
    if not b:
        raise ValueError("installation finished but no whisper executable "
                         "was found — run it once manually to check")
    return {"bin": b, "already": False}


# ---------- entry points ----------

def _usable(rows) -> list[dict]:
    return [{"ref": r["ref"], "start": r["start"], "end": r["end"],
             "text": r["text"]}
            for r in rows if 8 <= (r["char_len"] or 0) <= 60]


def analyze_shift(store, sid: int) -> dict:
    """Prepare post-import detection against a source's stored audio.
    Feed the result to run_measure()."""
    import json as _j
    src = store.db.execute("select * from sources where id=?", (sid,)).fetchone()
    if not src or src["kind"] != "video":
        raise ValueError("no such video source")
    meta = _j.loads(src["meta"] or "{}")
    audio = store.resolve_media(meta.get("audio") or src["path"] or "")
    if not str(audio) or not audio.exists():
        raise ValueError("source audio file is missing")
    rows = store.db.execute(
        "select ref, start, end, text, char_len from sentences"
        " where source_id=? and keep=1 and start!='' order by start",
        (sid,)).fetchall()
    return prepare(audio, _usable(rows), None, store.path.parent.parent)


def analyze_pre(video: str | Path, subs: str | Path, astream: int | None,
                sub_lang: str = "auto", project_root: Path | None = None) -> dict:
    """Prepare PRE-import detection on the temp video (which audio track
    to use is `astream`; None = auto/Japanese). The measured value belongs
    in the import form's offset field, so the frame images grabbed at
    import land on the right scenes. Feed the result to run_measure()."""
    import re as _re
    from . import ffmpeg as ff
    from . import subs as subs_mod
    video, subs = Path(video), Path(subs)
    cues = subs_mod.parse_detail(subs)
    info = subs_mod.analyze_cues(cues)
    lang = ""
    if sub_lang in ("ja", "zh"):
        lang = sub_lang
    elif sub_lang == "auto" and info["bilingual"]:
        lang = "ja"
    if lang:
        cues = subs_mod.pick_language(cues, lang)
    usable = []
    for i, c in enumerate(cues, 1):
        text = c["text"]
        n = len(_re.sub(r"\W", "", text, flags=_re.UNICODE))
        if 8 <= n <= 60:
            usable.append({"ref": str(i), "start": c["start"],
                           "end": c["end"], "text": text})
    if astream is None:
        astream = ff.probe_audio(video)["default"]
    return prepare(video, usable, astream, project_root)
