"""Export selected sentences as an .apkg deck (genanki), packaging the
sentence's real audio + screenshot from its source deck.

Note types (stored in the note_types table) define the card layout:
fields, CSS, front/back templates. The two built-in types exactly match
the legacy immersion/reading presets. Custom types are built dynamically
from the database — the exporter just fills fields by name.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import genanki

from .apkg import read_media_file
from .media import image_bytes

DECK_ID = 2059400802

# values the exporter knows how to fill, by field name (case-insensitive)
_FIELD_VALUES = {
    "sentence": lambda ctx: ctx["text"],
    "reading": lambda ctx: ctx["reading"],
    "translation": lambda ctx: ctx["translation"],
    "image": lambda ctx: ctx["img_html"],
    "audio": lambda ctx: ctx["audio_html"],
    "source": lambda ctx: ctx["src"],
    "note": lambda ctx: ctx["note"],
    "episode": lambda ctx: ctx.get("episode", ""),
    "level": lambda ctx: ctx.get("level", ""),
    # cloze-friendly aliases
    "text": lambda ctx: ctx["text"],
    "extra": lambda ctx: ctx["translation"],
    "expression": lambda ctx: ctx["text"],
    "meaning": lambda ctx: ctx["translation"],
}


def _build_model(nt) -> genanki.Model:
    """genanki Model from a note_types row."""
    fields = json.loads(nt["fields"])
    return genanki.Model(
        nt["model_id"], nt["name"] or "Custom",
        fields=[{"name": f} for f in fields],
        templates=[{
            "name": "Card 1",
            "qfmt": nt["front"] or "{{Sentence}}",
            "afmt": nt["back"] or '{{FrontSide}}<hr id="answer">{{Reading}}',
        }],
        css=nt["css"] or "")


def _fill_fields(model_fields: list[str], ctx: dict) -> list[str]:
    """Map sentence context → ordered field values by field name."""
    out = []
    for f in model_fields:
        fn = f.lower().strip()
        out.append(_FIELD_VALUES.get(fn, lambda _: "")(ctx))
    return out


def _ext(name: str, default: str) -> str:
    m = re.search(r"\.([A-Za-z0-9]+)$", name or "")
    return m.group(1).lower() if m else default


def build_deck(store, name: str, preset: str = "immersion",
               status: str = "approved", source_id: int = 0,
               level: str = "", out_dir: str | Path = "result",
               pad_start: float | None = None,
               pad_end: float | None = None) -> dict:
    """Export sentences as an .apkg. For status='deck', each block uses its
    own note type; for other statuses, `preset` selects one (by name or id)."""
    # load note types and build genanki models
    nts = {nt["id"]: nt for nt in store.note_types()}
    if not nts:
        return {"error": "no note types defined"}
    models = {tid: _build_model(nt) for tid, nt in nts.items()}

    # resolve the default note type from the preset parameter
    default_tid = 1   # immersion
    if preset:
        for nt in nts.values():
            if nt["name"].lower() == preset.lower():
                default_tid = nt["id"]
                break
        else:
            try:
                default_tid = int(preset)
            except ValueError:
                pass

    where, args = ["n.keep=1"], []
    if status == "deck":
        rows = [dict(r) for r in store.db.execute(
            "select n.*, s.name source_name, s.path source_path,"
            " s.kind source_kind, s.meta source_meta, d.note deck_note,"
            " d.point deck_point, gp.note_type_id note_type_id"
            " from deck_items d"
            " join sentences n on n.id=d.sentence_id"
            " join sources s on s.id=n.source_id"
            " left join grammar_points gp on gp.id=d.point"
            " order by d.point, d.position, d.id")]
        return _package(store, rows, name, out_dir, pad_start, pad_end,
                        nts, models, default_tid)
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
    rows = store.db.execute(
        f"select n.*, s.name source_name, s.path source_path, s.kind source_kind,"
        f" s.meta source_meta, '' deck_note, '' deck_point, {default_tid} note_type_id"
        f" from sentences n"
        f" join sources s on s.id=n.source_id where {' and '.join(where)}"
        f" order by n.id", args).fetchall()
    if not rows:
        return {"error": "no sentences matched the filters"}
    return _package(store, [dict(r) for r in rows], name, out_dir,
                    pad_start, pad_end, nts, models, default_tid)


def _package(store, rows: list[dict], name: str, out_dir,
             pad_start, pad_end, nts, models, default_tid) -> dict:
    deck = genanki.Deck(DECK_ID, name or "AnkiStudio export")
    media: list[str] = []
    n_media = 0
    from . import ffmpeg as _ff

    for r in rows:
        tid = r.get("note_type_id") or default_tid
        nt = nts.get(tid) or nts[default_tid]
        model = models[tid] if tid in models else models[default_tid]
        nt_fields = json.loads(nt["fields"])

        img_html = audio_html = ""
        ctx = {
            "text": r["text"] or "", "reading": r["reading"] or "",
            "translation": r["translation"] or "",
            "note": r.get("deck_note") or "",
            "episode": r.get("episode") or "",
            "level": r.get("level") or "",
            "img_html": "", "audio_html": "",
            "src": f"{r['source_name']}"
                   f"{(' · ep ' + r['episode']) if r['episode'] else ''}",
        }

        if r["source_kind"] == "video":
            meta = json.loads(r["source_meta"] or "{}")
            try:
                start, end = float(r["start"]), float(r["end"])
                lead = pad_start if pad_start is not None \
                    else meta.get("pad_start", meta.get("pad", 0.35))
                tail = pad_end if pad_end is not None \
                    else meta.get("pad_end", meta.get("pad", 0.35))
                media_path = store.resolve_media(
                    meta.get("audio") or r["source_path"])
                fp = _ff.cut_audio(media_path, start, end, "mp3",
                                   meta=meta, pad_start=lead, pad_end=tail)
                media.append(str(fp))
                ctx["audio_html"] = f"[sound:{fp.name}]"
                n_media += 1
                imgp = _ff.cached_frame(r["source_id"], r["ref"],
                                        base=store.path.parent / "media-cache")
                if imgp is None:
                    legacy = store.resolve_media(r["source_path"])
                    if legacy.exists() and legacy.suffix.lower() in (
                            ".mp4", ".mkv", ".m4v", ".avi", ".mov", ".webm", ".ts"):
                        imgp = _ff.grab_frame(legacy,
                                              start + (end - start) * 0.4, meta=meta)
                if imgp is not None:
                    media.append(str(imgp))
                    ctx["img_html"] = f'<img src="{imgp.name}">'
                    n_media += 1
            except Exception:
                pass
        else:
            try:
                if r["media_image"] and r["source_path"]:
                    data, _ = image_bytes(r["source_path"], r["media_image"])
                    p = Path(f"as-{r['id']}.jpg")
                    Path("data/export-tmp").mkdir(exist_ok=True)
                    fp = Path("data/export-tmp") / p
                    fp.write_bytes(data)
                    media.append(str(fp))
                    ctx["img_html"] = f'<img src="{p}">'
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
                        ctx["audio_html"] = f"[sound:{p}]"
                        n_media += 1
            except Exception:
                pass

        values = _fill_fields(nt_fields, ctx)
        deck.add_note(genanki.Note(
            guid=genanki.guid_for("as", r["id"]),
            model=model,
            fields=values))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w\-]+", "_", name or "ankistudio").strip("_") or "ankistudio"
    path = out / f"{slug}.apkg"
    genanki.Package(deck, media_files=media).write_to_file(path)
    return {"path": str(path), "notes": len(rows), "media_files": n_media,
            "note_type": nts[default_tid]["name"]}
