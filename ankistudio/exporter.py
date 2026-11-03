"""Export selected sentences as an .apkg deck (genanki), packaging the
sentence's real audio + screenshot from its source deck.

Presets decide what goes on the card:
- immersion: front = screenshot + audio (text-free); back adds sentence,
  reading, translation, source
- reading:   front = sentence; back adds reading, translation, audio, source
"""
from __future__ import annotations

import re
from pathlib import Path

import genanki

from .apkg import read_media_file
from .media import image_bytes

MODEL_ID = 1607391801
DECK_ID = 2059400802

CSS = """.card { font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
  font-size: 22px; text-align: center; color: #213547;
  background-color: #fff; padding: 24px 12px; }
.nightMode .card { color: #e5e7eb; background-color: #1b1b1f; }
.rd { font-size: 16px; color: #6b7280; margin-top: 8px; }
.tr { font-size: 18px; margin-top: 12px; }
.src { font-size: 12px; color: #9ca3af; margin-top: 16px; }
img { max-width: 480px; border-radius: 8px; }
"""

FIELDS = ["Sentence", "Reading", "Translation", "Image", "Audio", "Source", "Note"]

IMMERSION = genanki.Model(
    MODEL_ID, "AnkiStudio Immersion",
    fields=[{"name": f} for f in FIELDS],
    templates=[{
        "name": "Listen",
        "qfmt": "{{Image}}<br>{{Audio}}",
        "afmt": ('{{FrontSide}}<hr id="answer">{{Image}}<br>{{Audio}}'
                 '<div class="jp">{{Sentence}}</div>'
                 '<div class="rd">{{Reading}}</div>'
                 '<div class="tr">{{Translation}}</div>'
                 '{{#Note}}<div class="note" style="font-size:14px;color:#6b7280;'
                 'margin-top:12px">{{Note}}</div>{{/Note}}'
                 '<div class="src">{{Source}}</div>'),
    }],
    css=CSS)

READING = genanki.Model(
    MODEL_ID + 1, "AnkiStudio Reading",
    fields=[{"name": f} for f in FIELDS],
    templates=[{
        "name": "Read",
        "qfmt": '<div class="jp">{{Sentence}}</div>',
        "afmt": ('{{FrontSide}}<hr id="answer">'
                 '<div class="rd">{{Reading}}</div>'
                 '<div class="tr">{{Translation}}</div>'
                 '{{Audio}}'
                 '{{#Note}}<div style="font-size:14px;color:#6b7280;'
                 'margin-top:12px">{{Note}}</div>{{/Note}}'
                 '<div class="src">{{Source}}</div>'),
    }],
    css=CSS)

PRESETS = {"immersion": IMMERSION, "reading": READING}


def _ext(name: str, default: str) -> str:
    m = re.search(r"\.([A-Za-z0-9]+)$", name or "")
    return m.group(1).lower() if m else default


def build_deck(store, name: str, preset: str = "immersion",
               status: str = "approved", source_id: int = 0,
               level: str = "", out_dir: str | Path = "result",
               pad_start: float | None = None,
               pad_end: float | None = None) -> dict:
    where, args = ["n.keep=1"], []
    if status == "deck":
        import json as _json
        rows = [dict(r) for r in store.db.execute(
            "select n.*, s.name source_name, s.path source_path,"
            " s.kind source_kind, s.meta source_meta, d.note deck_note"
            " from deck_items d join sentences n on n.id=d.sentence_id"
            " join sources s on s.id=n.source_id"
            " order by d.point, d.position, d.id")]
        return _package(store, rows, name, preset, out_dir,
                        pad_start, pad_end)
    if status == "approved":
        where.append("n.decision='approved'")
    elif status == "pending":
        where.append("n.decision=''")
    elif status == "all":
        pass
    if source_id:
        where.append("n.source_id=?"); args.append(source_id)
    if level:
        where.append("n.level=?"); args.append(level)
    import json as _json
    rows = store.db.execute(
        f"select n.*, s.name source_name, s.path source_path, s.kind source_kind,"
        f" s.meta source_meta from sentences n"
        f" join sources s on s.id=n.source_id where {' and '.join(where)}"
        f" order by n.id", args).fetchall()
    if not rows:
        return {"error": "no sentences matched the filters"}
    return _package(store, [dict(r) for r in rows], name, preset, out_dir,
                    pad_start, pad_end)


def _package(store, rows, name, preset, out_dir, pad_start, pad_end) -> dict:
    import json as _json
    model = PRESETS[preset]
    deck = genanki.Deck(DECK_ID + (0 if preset == "immersion" else 1),
                        name or "AnkiStudio export")
    media: list[str] = []
    n_media = 0
    from . import ffmpeg as _ff
    for r in rows:
        img_html = audio_html = ""
        if r["source_kind"] == "video":
            meta = _json.loads(r["source_meta"] or "{}")
            try:
                start, end = float(r["start"]), float(r["end"])
                lead = pad_start if pad_start is not None \
                    else meta.get("pad_start", meta.get("pad", 0.35))
                tail = pad_end if pad_end is not None \
                    else meta.get("pad_end", meta.get("pad", 0.35))
                # current sources keep only the extracted audio track;
                # older ones still point at a full video file
                media_path = Path(meta.get("audio") or r["source_path"])
                fp = _ff.cut_audio(media_path, start, end, "mp3",
                                   meta=meta, pad_start=lead, pad_end=tail)
                media.append(str(fp))
                audio_html = f"[sound:{fp.name}]"
                n_media += 1
                imgp = _ff.cached_frame(r["source_id"], r["ref"])
                if imgp is None and Path(r["source_path"]).exists():
                    imgp = _ff.grab_frame(Path(r["source_path"]),
                                          start + (end - start) * 0.4, meta=meta)
                if imgp is not None:
                    media.append(str(imgp))
                    img_html = f'<img src="{imgp.name}">'
                    n_media += 1
            except Exception:
                pass
            src = f"{r['source_name']}{(' · ep ' + r['episode']) if r['episode'] else ''}"
            deck.add_note(genanki.Note(
                guid=genanki.guid_for("as", r["id"]),
                model=model,
                fields=[r["text"] or "", r["reading"] or "", r["translation"] or "",
                        img_html, audio_html, src, r.get("deck_note") or ""]))
            continue
        try:
            if r["media_image"] and r["source_path"]:
                data, _ = image_bytes(r["source_path"], r["media_image"])
                p = Path(f"as-{r['id']}.jpg")
                Path("data/export-tmp").mkdir(exist_ok=True)
                fp = Path("data/export-tmp") / p
                fp.write_bytes(data)
                media.append(str(fp))
                img_html = f'<img src="{p}">'
                n_media += 1
        except Exception:
            pass
        try:
            if r["media_audio"] and r["source_path"]:
                data, _ = read_media_file(r["source_path"], r["media_audio"])
                if data:
                    ext = _ext(r["media_audio"], "mp3")
                    p = Path(f"as-{r['id']}.{ext}")
                    Path("data/export-tmp").mkdir(exist_ok=True)
                    fp = Path("data/export-tmp") / p
                    fp.write_bytes(data)
                    media.append(str(fp))
                    audio_html = f"[sound:{p}]"
                    n_media += 1
        except Exception:
            pass
        src = f"{r['source_name']}{(' · ep ' + r['episode']) if r['episode'] else ''}"
        deck.add_note(genanki.Note(
            guid=genanki.guid_for("as", r["id"]),
            model=model,
            fields=[r["text"] or "", r["reading"] or "", r["translation"] or "",
                    img_html, audio_html, src, r.get("deck_note") or ""]))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w\-]+", "_", name or "ankistudio").strip("_") or "ankistudio"
    path = out / f"{slug}.apkg"
    genanki.Package(deck, media_files=media).write_to_file(path)
    return {"path": str(path), "notes": len(rows), "media_files": n_media,
            "preset": preset}
