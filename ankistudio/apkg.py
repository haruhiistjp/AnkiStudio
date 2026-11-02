"""Read .apkg Anki deck packages (collection.anki2 inside a zip).

Handles both classic packages (plain sqlite) and zstd-compressed ones
(Python >= 3.14 has stdlib zstd; older falls back to the `zstandard`
package if installed). Port of the readers proven in the CureDolly and
Serbian projects.
"""
from __future__ import annotations

import json
import sqlite3
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = val = 0
    while True:
        x = buf[i]
        i += 1
        val |= (x & 0x7F) << shift
        if not x & 0x80:
            return val, i
        shift += 7


def _parse_media_protobuf(data: bytes) -> dict[str, str]:
    """Anki's newer media format: ordered records, entry = record index.
    (Ported from the CureDolly cdlib reader.)"""
    mapping: dict[str, str] = {}
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        if tag >> 3 != 1 or tag & 7 != 2:
            raise ValueError(f"unexpected top-level protobuf tag {tag} at {pos}")
        length, pos = _read_varint(data, pos)
        rec = data[pos:pos + length]
        pos += length
        rpos, fname = 0, None
        while rpos < len(rec):
            t, rpos = _read_varint(rec, rpos)
            f, wire = t >> 3, t & 7
            if wire == 2:
                l, rpos = _read_varint(rec, rpos)
                if f == 1:
                    fname = rec[rpos:rpos + l].decode("utf-8", "replace")
                rpos += l
            elif wire == 0:
                _, rpos = _read_varint(rec, rpos)
            else:
                raise ValueError(f"unsupported wire type {wire} in media record")
        if fname is None:
            raise ValueError("media record without filename")
        mapping[str(len(mapping))] = fname
    return mapping


def _zstd_decompress(data: bytes) -> bytes:
    try:
        import compression.zstd as _z   # Python >= 3.14
        return _z.decompress(data)
    except ImportError:
        pass
    try:
        import compression  # Python 3.15 stdlib layout
        return compression.zstd_decompress(data)
    except (ImportError, AttributeError):
        pass
    import zstandard
    return zstandard.ZstdDecompressor().decompress(data)


@dataclass
class NoteType:
    mid: int
    name: str
    fields: list[str]


@dataclass
class Note:
    note_id: int
    note_type: NoteType
    fields: dict[str, str]
    tags: str


ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
SQLITE_MAGIC = b"SQLite format 3\x00"
# newer packages keep a 1-note stub in collection.anki2; prefer 21b/21
_DB_MEMBER_ORDER = ("collection.anki21b", "collection.anki21", "collection.anki2")


def read_media_map(path: str | Path) -> dict[str, str]:
    """Just the media map (entry -> filename) without loading the database —
    for serving single media files on demand."""
    with zipfile.ZipFile(path) as z:
        media_raw = z.read("media")
    if media_raw[:4] == ZSTD_MAGIC:
        return _parse_media_protobuf(_zstd_decompress(media_raw))
    try:
        return json.loads(media_raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _parse_media_protobuf(media_raw)


def read_media_file(path: str | Path, filename: str) -> tuple[bytes, str]:
    """(bytes, zip-entry-name) for a stored media filename, or (b'', entry)."""
    entry = None
    for k, v in read_media_map(path).items():
        if v == filename:
            entry = k
            break
    if entry is None:
        # some formats store entries under their real names directly
        entry = filename
    with zipfile.ZipFile(path) as z:
        try:
            data = z.read(entry)
        except KeyError:
            return b"", entry
    # newer Anki formats zstd-compress individual media entries
    if data[:4] == ZSTD_MAGIC:
        try:
            data = _zstd_decompress(data)
        except Exception:
            pass
    return data, entry


@dataclass
class DeckReader:
    path: Path
    note_types: dict[int, NoteType] = field(default_factory=dict)
    _media: dict[str, str] = field(default_factory=dict)   # entry -> filename

    @classmethod
    def open(cls, path: str | Path) -> "DeckReader":
        self = cls(path=Path(path))
        with zipfile.ZipFile(self.path) as z:
            names = set(z.namelist())
            # pick the best collection member; 21b/21 may be zstd-compressed
            db = None
            for member in _DB_MEMBER_ORDER:
                if member not in names:
                    continue
                raw = z.read(member)
                if raw[:4] == ZSTD_MAGIC:
                    raw = _zstd_decompress(raw)
                if raw[:len(SQLITE_MAGIC)] == SQLITE_MAGIC:
                    db = raw
                    break
            if db is None:
                raise ValueError(f"{path}: no readable collection database")
            media_raw = z.read("media")
        if media_raw[:4] == ZSTD_MAGIC:
            self._media = _parse_media_protobuf(_zstd_decompress(media_raw))
        else:
            try:
                self._media = json.loads(media_raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._media = _parse_media_protobuf(media_raw)

        buf = bytearray(db)
        if buf[18] == 2 or buf[19] == 2:
            # WAL-mode image would look for missing -wal/-shm sidecars;
            # reading doesn't need WAL -> reset to rollback-journal mode
            buf[18] = buf[19] = 1
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.create_collation(
            "unicase", lambda a, b: -1 if a < b else (1 if a > b else 0))
        if hasattr(conn, "deserialize"):
            conn.deserialize(buf)
        else:
            import tempfile, os
            fd, p_tmp = tempfile.mkstemp(suffix=".anki2")
            os.write(fd, db)
            os.close(fd)
            conn.close()
            conn = sqlite3.connect(p_tmp)
            conn.row_factory = sqlite3.Row
        self._load(conn)
        conn.close()
        return self

    def _load(self, conn: sqlite3.Connection) -> None:
        col = None
        try:
            col = conn.execute("select models from col limit 1").fetchone()
        except sqlite3.OperationalError:
            pass
        models = {}
        if col and col["models"]:
            try:
                models = json.loads(col["models"])
            except json.JSONDecodeError:
                models = {}
        if models:
            for mid, m in models.items():
                self.note_types[int(mid)] = NoteType(
                    mid=int(mid), name=m.get("name", "?"),
                    fields=[f["name"] for f in m.get("flds", [])])
        else:
            # newer schema: note types live in their own tables
            for mid, name in conn.execute("select id, name from notetypes"):
                fields = [r[0] for r in conn.execute(
                    "select name from fields where ntid=? order by ord", (mid,))]
                self.note_types[int(mid)] = NoteType(int(mid), name, fields)
        self._rows = conn.execute(
            "select id, mid, flds, tags from notes order by id").fetchall()

    # -- public API -------------------------------------------------------

    def media_filename(self, entry_or_name: str) -> str:
        """media entry number (or already-a-filename) -> stored filename."""
        return self._media.get(entry_or_name, entry_or_name)

    def notes(self):
        for r in self._rows:
            nt = self.note_types.get(r["mid"])
            if nt is None:
                continue
            values = r["flds"].split("\x1f")
            fields = {name: (values[i] if i < len(values) else "")
                      for i, name in enumerate(nt.fields)}
            yield Note(note_id=r["id"], note_type=nt, fields=fields,
                       tags=r["tags"] or "")

    def close(self) -> None:   # compatibility with streaming readers
        pass
