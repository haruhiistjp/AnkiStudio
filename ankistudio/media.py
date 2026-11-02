"""Media helpers: browser-safe image serving with a disk cache.

Some deck screenshots (e.g. CMYK JPEGs from hand-made decks) arrive as
bytes browsers refuse to decode. Pillow re-encodes them once; the result
is cached under data/media-cache keyed by source path + mtime.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

from .apkg import read_media_file

CACHE_DIR = Path("data/media-cache")
RAW_SAFE = {".png", ".webp", ".gif", ".avif"}   # pass through untouched


def image_bytes(apkg_path: str | Path, filename: str) -> tuple[bytes, str]:
    """(browser-safe bytes, content-type); raises KeyError if missing."""
    apkg_path = Path(apkg_path)
    ext = Path(filename).suffix.lower()
    data, _ = read_media_file(apkg_path, filename)
    if not data:
        raise KeyError(filename)
    if ext in RAW_SAFE:
        ctype = {"": ""}  # filled below
        ct = {"png": "image/png", "webp": "image/webp",
              "gif": "image/gif", "avif": "image/avif"}[ext.lstrip(".")]
        return data, ct

    mtime = apkg_path.stat().st_mtime
    key = hashlib.sha1(f"{apkg_path}|{mtime}|{filename}".encode()).hexdigest()[:20]
    cache = CACHE_DIR / f"{key}.jpg"
    if cache.exists():
        return cache.read_bytes(), "image/jpeg"

    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(data))
    try:
        ImageOps.exif_transpose(im, in_place=True)
    except Exception:
        pass
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(buf.getvalue())
    return buf.getvalue(), "image/jpeg"
