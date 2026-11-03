"""Sentence store: one SQLite file per project holding every indexed
sentence from every source (decks now; video/audio/text later), plus
lexicons, review decisions, and derived stats helpers.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import threading
from pathlib import Path

SCHEMA = """
create table if not exists sources(
  id integer primary key,
  kind text not null,             -- apkg | video | audio | text
  name text not null,
  path text,
  meta text,                      -- json
  imported_at real
);
create table if not exists sentences(
  id integer primary key,
  source_id integer not null references sources(id),
  ref text,                       -- note id / subtitle index / line no
  text text,
  reading text,
  translation text,
  episode text,
  start text,
  end text,
  media_audio text,               -- filename inside the source package
  media_image text,
  char_len integer,
  flags text,                     -- F_* / D_* quality markers, csv
  keep integer,                   -- 1 unless dropped by heuristics
  drop_code text,
  decision text default '',       -- '' | approved | discarded
  decided_at real,
  known text                      -- json {lexicon_id: unknown_count}
);
create index if not exists sent_src on sentences(source_id);
create index if not exists sent_keep on sentences(keep);
create index if not exists sent_dec on sentences(decision);
create table if not exists lexicons(
  id integer primary key,
  name text not null,
  kind text default 'freq',
  level_order text,               -- json list, easy -> hard
  imported_at real
);
create table if not exists lexicon_words(
  lexicon_id integer references lexicons(id),
  word text,
  level text,
  rank integer
);
create index if not exists lw_word on lexicon_words(word);
create table if not exists settings(
  key text primary key, value text
);
create table if not exists grammar_points(
  id text primary key,           -- GP-001 or any slug
  title text,
  pattern text,
  level text,
  module text,                   -- lesson/topic grouping
  hints text                     -- csv of match hints (optional)
);
create table if not exists deck_items(
  id integer primary key,
  sentence_id integer not null references sentences(id),
  point text,                    -- grammar point id (or free label)
  position integer,
  note text                      -- per-card explanation shown on export
);
create index if not exists deck_point on deck_items(point, position);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # single-user local app: FastAPI serves sync endpoints from a
        # threadpool, so the connection must be usable across threads
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.Lock()
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self):
        self.db.close()

    def reopen(self, path: str | Path):
        """Switch this Store to another database file (.aproj open)."""
        self.db.close()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def snapshot_to(self, dest: str | Path):
        """Consistent copy of the live database (.aproj save)."""
        self.db.execute("vacuum into ?", (str(dest),))

    # -- grammar points ----------------------------------------------------

    def add_points(self, rows: list[dict]) -> int:
        """insert-or-replace grammar points; returns count"""
        self.db.executemany(
            "insert or replace into grammar_points(id,title,pattern,level,module,hints)"
            " values (:id,:title,:pattern,:level,:module,:hints)", rows)
        self.db.commit()
        return len(rows)

    def points(self) -> list:
        return self.db.execute(
            "select * from grammar_points order by id").fetchall()

    def delete_point(self, pid: str):
        self.db.execute("delete from grammar_points where id=?", (pid,))
        self.db.commit()

    # -- deck --------------------------------------------------------------

    def deck_items(self) -> list:
        return self.db.execute(
            "select d.id, d.point, d.position, d.note, n.text, n.translation,"
            " n.reading, n.source_id, s.name source_name, n.episode, n.level,"
            " n.media_audio, n.media_image, n.char_len"
            " from deck_items d join sentences n on n.id=d.sentence_id"
            " join sources s on s.id=n.source_id"
            " order by d.point, d.position, d.id").fetchall()

    def deck_add(self, sentence_id: int, point: str, note: str = "",
                 position: int | None = None) -> int:
        if position is None:
            r = self.db.execute(
                "select coalesce(max(position), -1) + 1 p from deck_items"
                " where point = ? or ? = ''", (point, point)).fetchone()
            position = r["p"]
        cur = self.db.execute(
            "insert into deck_items(sentence_id, point, position, note)"
            " values (?,?,?,?)", (sentence_id, point, position, note))
        self.db.commit()
        return cur.lastrowid

    def deck_update(self, item_id: int, position: int | None = None,
                    note: str | None = None, point: str | None = None):
        sets, args = [], []
        if position is not None:
            sets.append("position=?"); args.append(position)
        if note is not None:
            sets.append("note=?"); args.append(note)
        if point is not None:
            sets.append("point=?"); args.append(point)
        if not sets:
            return
        args.append(item_id)
        self.db.execute(f"update deck_items set {', '.join(sets)} where id=?",
                        args)
        self.db.commit()

    def deck_remove(self, item_id: int):
        self.db.execute("delete from deck_items where id=?", (item_id,))
        self.db.commit()

    # -- settings ---------------------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        r = self.db.execute("select value from settings where key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_setting(self, key: str, value: str):
        with self._lock:
            self.db.execute("insert or replace into settings values (?,?)", (key, value))
            self.db.commit()

    # -- sources & sentences ----------------------------------------------

    def add_source(self, kind: str, name: str, path: str = "", meta: dict | None = None) -> int:
        cur = self.db.execute(
            "insert into sources(kind,name,path,meta,imported_at) values (?,?,?,?,?)",
            (kind, name, path, json.dumps(meta or {}), time.time()))
        self.db.commit()
        return cur.lastrowid

    def add_sentences(self, source_id: int, rows: list[dict]):
        with self._lock:
          self.db.executemany(
            "insert into sentences(source_id,ref,text,reading,translation,episode,"
            "start,end,media_audio,media_image,char_len,flags,keep,drop_code,known)"
            " values (:source_id,:ref,:text,:reading,:translation,:episode,"
            ":start,:end,:media_audio,:media_image,:char_len,:flags,:keep,:drop_code,:known)",
            rows)
          self.db.commit()

    def sources(self):
        return self.db.execute(
            "select s.*, (select count(*) from sentences n where n.source_id=s.id) sentences,"
            "(select count(*) from sentences n where n.source_id=s.id and n.keep=1) kept "
            "from sources s order by s.id").fetchall()

    def decide(self, sentence_ids: list[int], decision: str):
        with self._lock:
            self.db.executemany(
                "update sentences set decision=?, decided_at=? where id=?",
                [(decision, time.time(), i) for i in sentence_ids])
            self.db.commit()

    # -- lexicons -----------------------------------------------------------

    def add_lexicon(self, name: str, words: list[tuple[str, str, int]],
                    level_order: list[str]) -> int:
        cur = self.db.execute(
            "insert into lexicons(name,kind,level_order,imported_at) values (?,?,?,?)",
            (name, "freq", json.dumps(level_order), time.time()))
        lid = cur.lastrowid
        self.db.executemany(
            "insert into lexicon_words(lexicon_id,word,level,rank) values (?,?,?,?)",
            [(lid, w, lvl, rk) for w, lvl, rk in words])
        self.db.commit()
        return lid

    def lexicons(self):
        return self.db.execute(
            "select l.*, (select count(*) from lexicon_words w where w.lexicon_id=l.id) words"
            " from lexicons l order by l.id").fetchall()

    def lexicon_word_map(self, lexicon_id: int) -> dict[str, str]:
        """word -> easiest level it appears in (for known-word checks)."""
        order = json.loads(self.db.execute(
            "select level_order from lexicons where id=?", (lexicon_id,)
        ).fetchone()["level_order"] or '[]')
        pos = {lvl: i for i, lvl in enumerate(order)}
        out: dict[str, str] = {}
        for r in self.db.execute(
                "select word, level from lexicon_words where lexicon_id=?", (lexicon_id,)):
            w = r["word"]
            if w and (w not in out or pos.get(r["level"], 99) < pos.get(out[w], 99)):
                out[w] = r["level"]
        return out

    # -- stats ---------------------------------------------------------------

    def stats(self) -> dict:
        total = self.db.execute("select count(*) c from sentences").fetchone()["c"]
        kept = self.db.execute("select count(*) c from sentences where keep=1").fetchone()["c"]
        dec = {r["decision"]: r["c"] for r in self.db.execute(
            "select decision, count(*) c from sentences group by decision")}
        length_hist = [dict(r) for r in self.db.execute(
            "select (char_len/10)*10 bucket, count(*) c from sentences"
            " where keep=1 and char_len is not null group by bucket order by bucket")]
        per_source = [dict(r) for r in self.db.execute(
            "select s.name, s.kind, count(n.id) sentences, sum(n.keep) kept,"
            " sum(case when n.decision='approved' then 1 else 0 end) approved"
            " from sources s left join sentences n on n.source_id=s.id"
            " group by s.id order by sentences desc")]
        top_dups = [dict(r) for r in self.db.execute(
            "select text, count(*) c from sentences where keep=1"
            " group by text having c > 1 order by c desc limit 10")]
        return {"total": total, "kept": kept,
                "approved": dec.get("approved", 0), "discarded": dec.get("discarded", 0),
                "pending": kept - dec.get("approved", 0) - dec.get("discarded", 0),
                "length_hist": length_hist, "per_source": per_source,
                "top_dups": top_dups,
                "sources": len(per_source)}
