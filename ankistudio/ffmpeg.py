"""ffmpeg helpers: cut audio clips and grab frames from a video file,
transcode audio between formats — all cached on disk.

Time handling: subtitles store ORIGINAL cue times; the effective time of a
cue = its time shifted by the source's shift config:
    effective(t) = the shift of the LAST segment with `at` <= t
                   (falling back to the global offset), where segments are
                   absolute ("from here on, total shift is X").
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

CACHE_DIR = Path("data/media-cache")
PAD = 0.35          # lead/tail padding around a cue, seconds


def effective_time(t: float, meta: dict) -> float:
    shift = float(meta.get("offset", 0) or 0)
    for seg in sorted(meta.get("segments") or [], key=lambda s: s.get("at", 0)):
        if float(seg.get("at", 0)) <= t:
            shift = float(seg.get("shift", 0) or 0)
    return t + shift


def _cache_path(kind: str, key: tuple, ext: str) -> Path:
    h = hashlib.sha1("|".join(str(x) for x in key).encode()).hexdigest()[:22]
    return CACHE_DIR / f"{kind}-{h}.{ext}"


def _run(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-y", *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cut_audio(video: Path, start: float, end: float, fmt: str = "mp3",
              meta: dict | None = None, key_extra: tuple = ()) -> Path:
    """Cut [start-PAD, end+PAD] (shifted times) as an audio file, cached."""
    meta = meta or {}
    s = max(0.0, effective_time(start, meta) - PAD)
    e = effective_time(end, meta) + PAD
    dur = max(0.3, e - s)
    enc = {"mp3": ["-vn", "-acodec", "libmp3lame", "-q:a", "4"],
           "m4a": ["-vn", "-acodec", "aac", "-b:a", "128k"],
           "wav": ["-vn", "-acodec", "pcm_s16le"],
           "ogg": ["-vn", "-acodec", "libvorbis", "-q:a", "4"]}[fmt]
    out = _cache_path("cut", (str(video), video.stat().st_mtime,
                              round(s, 2), round(dur, 2), fmt, key_extra), fmt)
    if not out.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _run(["-ss", f"{s:.3f}", "-t", f"{dur:.3f}", "-i", str(video), *enc,
              str(out)])
    return out


def grab_frame(video: Path, t: float, meta: dict | None = None,
               width: int = 640) -> Path:
    meta = meta or {}
    s = max(0.0, effective_time(t, meta))
    out = _cache_path("frame", (str(video), video.stat().st_mtime,
                                round(s, 2), width), "jpg")
    if not out.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _run(["-ss", f"{s:.3f}", "-i", str(video), "-frames:v", "1",
              "-vf", f"scale={width}:-2", str(out)])
    return out


def transcode_audio(src: bytes, src_ext: str, fmt: str) -> bytes:
    """Re-encode raw audio bytes to another format (for Save-as)."""
    import tempfile, os
    enc = {"mp3": ["-acodec", "libmp3lame", "-q:a", "4"],
           "m4a": ["-acodec", "aac", "-b:a", "128k"],
           "wav": ["-acodec", "pcm_s16le"],
           "ogg": ["-acodec", "libvorbis", "-q:a", "4"]}[fmt]
    with tempfile.TemporaryDirectory() as td:
        inp = Path(td) / f"in.{src_ext or 'bin'}"
        outp = Path(td) / f"out.{fmt}"
        inp.write_bytes(src)
        _run(["-i", str(inp), *enc, str(outp)])
        return outp.read_bytes()
