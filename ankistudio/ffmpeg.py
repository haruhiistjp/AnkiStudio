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


def _pad_value(v) -> float:
    return max(0.0, min(5.0, float(v)))


def cut_audio(path: Path, start: float, end: float, fmt: str = "mp3",
              meta: dict | None = None, key_extra: tuple = (),
              pad_start: float | None = None,
              pad_end: float | None = None) -> Path:
    """Cut [start-lead, end+tail] (shifted times) as an audio file, cached.
    Lead/tail padding come from the explicit arguments or the source meta
    (pad_start/pad_end, falling back to the old single-sided `pad`)."""
    meta = meta or {}
    lead = _pad_value(pad_start if pad_start is not None
                      else meta.get("pad_start", meta.get("pad", PAD)))
    tail = _pad_value(pad_end if pad_end is not None
                      else meta.get("pad_end", meta.get("pad", PAD)))
    s = max(0.0, effective_time(start, meta) - lead)
    e = effective_time(end, meta) + tail
    dur = max(0.3, e - s)
    enc = {"mp3": ["-vn", "-acodec", "libmp3lame", "-q:a", "4"],
           "m4a": ["-vn", "-acodec", "aac", "-b:a", "128k"],
           "wav": ["-vn", "-acodec", "pcm_s16le"],
           "ogg": ["-vn", "-acodec", "libvorbis", "-q:a", "4"]}[fmt]
    out = _cache_path("cut", (str(path), path.stat().st_mtime,
                              round(s, 2), round(dur, 2), fmt, lead, tail,
                              key_extra), fmt)
    if not out.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _run(["-ss", f"{s:.3f}", "-t", f"{dur:.3f}", "-i", str(path), *enc,
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


# ---------- video-import pipeline: keep only audio + frames ----------

def _ffprobe(args: list[str]) -> dict:
    import json
    r = subprocess.run(["ffprobe", "-v", "error", *args, "-of", "json"],
                       check=True, capture_output=True, text=True)
    return json.loads(r.stdout or "{}")


def probe_audio(path: Path) -> dict:
    """Audio streams of a file, with the suggested Japanese default.
    `aindex` is the stream's ordinal among audio streams (what ffmpeg
    `-map 0:a:N` expects), `index` its global stream id."""
    data = _ffprobe(["-select_streams", "a", "-show_entries",
                     "stream=index,codec_name,channels:"
                     "stream_tags=language,title", str(path)])
    streams = []
    for n, s in enumerate(data.get("streams", [])):
        tags = s.get("tags") or {}
        streams.append({"aindex": n, "index": s.get("index", n),
                        "codec": s.get("codec_name", "?"),
                        "channels": s.get("channels", "?"),
                        "lang": (tags.get("language") or "").strip(),
                        "title": (tags.get("title") or "").strip()})
    default = next((s["aindex"] for s in streams
                    if s["lang"].lower() in ("ja", "jp", "jpn")), None)
    if default is None:
        import re as _re
        default = next((s["aindex"] for s in streams
                        if _re.search(r"jap|jpn|日本", s["title"], _re.I)), None)
    return {"streams": streams, "default": default if default is not None else 0}


def stream_label(s: dict) -> str:
    bits = [f"#{s['aindex']}"]
    if s["lang"]:
        bits.append(s["lang"])
    if s["title"]:
        bits.append(s["title"][:24])
    bits.append(f"{s['codec']} {s['channels']}ch")
    return " · ".join(bits)


def extract_audio(video: Path, aindex: int, out_dir: Path, stem: str) -> Path:
    """Copy one audio track out of the video into a small .mka — no
    re-encode, a few % of the video's size. This is the only part of the
    video the project keeps long-term."""
    import re as _re
    import uuid as _uuid
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = _re.sub(r"[^\w.\-]+", "_", stem).strip("._") or "audio"
    out = out_dir / f"{_uuid.uuid4().hex[:8]}-{safe}.mka"
    _run(["-i", str(video), "-map", f"0:a:{aindex}",
          "-c:a", "copy", str(out)])
    return out


def frame_cache_path(source_id: int, ref: str) -> Path:
    """Deterministic per-cue frame location, so frames grabbed at import
    time stay findable after the video file itself is deleted."""
    return CACHE_DIR / f"src{source_id}-{ref}.jpg"


def cached_frame(source_id: int, ref: str) -> Path | None:
    p = frame_cache_path(source_id, str(ref))
    return p if p.exists() else None


def grab_frame_to(video: Path, t: float, out: Path, meta: dict | None = None,
                  width: int = 640) -> Path:
    meta = meta or {}
    s = max(0.0, effective_time(t, meta))
    out.parent.mkdir(parents=True, exist_ok=True)
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
