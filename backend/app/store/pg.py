"""Postgres behind the same interface as the sqlite3 connection (launch, item 6).

The store's SQL is written for SQLite. When `DATABASE_URL` (or a `--db`) is a
postgres:// URL, `connect` returns a `Connection` that looks like the sqlite3
one the code already uses (`execute` returning a cursor with
`fetchone/fetchall/rowcount/lastrowid`, rows readable by name and position)
and rewrites each statement on the way:

- `?` placeholders become `%s` (and a literal `%` becomes `%%`);
- `INSERT OR IGNORE` becomes `ON CONFLICT DO NOTHING`, `INSERT OR REPLACE`
  an upsert on the table's primary key;
- every table gets a `rowid` column (a sequence, or the AUTOINCREMENT key
  itself), so `ORDER BY rowid`, `last_insert_rowid()` and `cursor.lastrowid`
  mean what they mean on SQLite; rows never show it (alias it to read it);
- `INTEGER` columns are `BIGINT`, `REAL` is `DOUBLE PRECISION`,
  `AUTOINCREMENT` keys are `BIGSERIAL`;
- `PRAGMA table_info(t)` and `sqlite_master` read the information schema;
  any other PRAGMA does nothing; `BEGIN IMMEDIATE` is `BEGIN`.

Every connection sets `app.bypass_rls = on` (see migration 0034).
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from collections.abc import Iterable, Iterator
from decimal import Decimal
from typing import Any

URL_PREFIXES = ("postgres://", "postgresql://")
TEST_URL_ENV = "AVE_TEST_DATABASE_URL"


def is_url(path: Any) -> bool:
    return isinstance(path, str) and path.startswith(URL_PREFIXES)


def is_pg(conn: Any) -> bool:
    """True when `conn` is a Postgres connection from this module."""
    return isinstance(conn, Connection)


def target(path: Any) -> tuple[str, str | None, bool] | None:
    """Where a `Database(path)` lives on Postgres: (url, schema, throwaway), or
    None for SQLite. A postgres:// path is used as is. Under the test switch
    (`AVE_TEST_DATABASE_URL`) every database is a schema there: `:memory:` a
    fresh one dropped when closed, a file path one named after the path, so
    reopening the same file finds the same rows."""
    if is_url(str(path)):
        return str(path), None, False
    test = os.environ.get(TEST_URL_ENV)
    if not test:
        return None
    if str(path) == ":memory:":
        return test, f"t_{uuid.uuid4().hex[:16]}", True
    digest = hashlib.sha1(os.path.abspath(str(path)).encode()).hexdigest()[:16]
    return test, f"f_{digest}", False


def _open(url: str, schema: str | None):
    import psycopg
    raw = psycopg.connect(url, autocommit=True, prepare_threshold=None, connect_timeout=10)
    if schema:
        raw.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        raw.execute(f'SET search_path TO "{schema}"')
    raw.execute("SELECT set_config('app.bypass_rls', 'on', false)")
    return raw


def connect(url: str, schema: str | None = None) -> Connection:
    conn = Connection(_open(url, schema), schema)
    conn.url = url
    return conn


# ---------------------------------------------------------------- rows

class Row(tuple):
    """A result row, like sqlite3.Row: by position, or by name (any case)."""

    def __new__(cls, values: Iterable, index: dict[str, int], keys: list[str]):
        row = super().__new__(cls, values)
        row._index = index
        row._keys = keys
        return row

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._index[key.lower()])
        return tuple.__getitem__(self, key)

    def keys(self) -> list[str]:
        return list(self._keys)


def _value(v: Any) -> Any:
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _param(v: Any) -> Any:
    # SQLite stores a bool as 0/1; the columns are integers here too.
    return int(v) if isinstance(v, bool) else v


class Cursor:
    def __init__(self, rows: list[Row], rowcount: int, lastrowid: int | None) -> None:
        self._rows = rows
        self._at = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self) -> Row | None:
        if self._at >= len(self._rows):
            return None
        self._at += 1
        return self._rows[self._at - 1]

    def fetchall(self) -> list[Row]:
        out = self._rows[self._at:]
        self._at = len(self._rows)
        return out

    def fetchmany(self, size: int = 1) -> list[Row]:
        out = self._rows[self._at:self._at + size]
        self._at += len(out)
        return out

    def __iter__(self) -> Iterator[Row]:
        while (row := self.fetchone()) is not None:
            yield row


# ---------------------------------------------------------------- rewriting

_TOKEN = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/", re.DOTALL)
_MARK = "\x00{}\x00"
_MARKED = re.compile("\x00(\\d+)\x00")

_SQLITE_MASTER = (
    "(SELECT table_name AS name, 'table' AS type, table_name AS tbl_name FROM information_schema.tables "
    "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' "
    "UNION ALL SELECT DISTINCT trigger_name, 'trigger', event_object_table FROM information_schema.triggers "
    "WHERE trigger_schema = current_schema() "
    "UNION ALL SELECT indexname, 'index', tablename FROM pg_indexes WHERE schemaname = current_schema()) AS sqlite_master")
_TABLE_INFO = (
    "SELECT (ordinal_position - 1) AS cid, column_name AS name, data_type AS type, "
    "CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END AS notnull, column_default AS dflt_value, 0 AS pk "
    "FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = '{}' "
    "AND column_name <> 'rowid' ORDER BY ordinal_position")


def _mask(sql: str) -> tuple[str, list[str]]:
    """Comments dropped, string literals and quoted names swapped for markers."""
    kept: list[str] = []

    def swap(m: re.Match) -> str:
        text = m.group(0)
        if text.startswith(("--", "/*")):
            return " "
        kept.append(text)
        return _MARK.format(len(kept) - 1)
    return _TOKEN.sub(swap, sql), kept


def _unmask(sql: str, kept: list[str]) -> str:
    return _MARKED.sub(lambda m: kept[int(m.group(1))], sql)


_AUTOINC = re.compile(r"\b(\w+)\s+INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", re.IGNORECASE)
_CREATE = re.compile(r"^\s*CREATE\s+TABLE\b", re.IGNORECASE)
_ALTER = re.compile(r"^\s*ALTER\s+TABLE\b", re.IGNORECASE)
_INSERT = re.compile(r"^\s*(?:INSERT|REPLACE)\b", re.IGNORECASE)
_OR_WHAT = re.compile(r"^\s*INSERT\s+OR\s+(IGNORE|REPLACE)\s+INTO\b", re.IGNORECASE)
_INTO = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)\s*\(([^)]*)\)", re.IGNORECASE)
_RETURNING = re.compile(r"\bRETURNING\b", re.IGNORECASE)
_PRAGMA = re.compile(r"^\s*PRAGMA\b", re.IGNORECASE)
_TABLE_INFO_RE = re.compile(r"^\s*PRAGMA\s+table_info\s*\(\s*(\w+)\s*\)\s*$", re.IGNORECASE)
_BEGIN = re.compile(r"^\s*BEGIN\s+(?:IMMEDIATE|EXCLUSIVE|DEFERRED)\b", re.IGNORECASE)
_LAST_ID = re.compile(r"\blast_insert_rowid\s*\(\s*\)", re.IGNORECASE)


class Rewritten:
    """One statement in Postgres form, and what the cursor must do with it."""
    __slots__ = ("returning_rowid", "skip", "sql")

    def __init__(self, sql: str, skip: bool = False, returning_rowid: bool = False) -> None:
        self.sql = sql
        self.skip = skip
        self.returning_rowid = returning_rowid


def rewrite(sql: str, *, has_params: bool, last_rowid: int | None = None,
            conflict_keys=None) -> Rewritten:
    """The Postgres form of one SQLite statement. `conflict_keys(table)` gives
    (primary key columns, rowid is a plain sequence) for INSERT OR REPLACE."""
    text, kept = _mask(sql.strip().rstrip(";"))
    info = _TABLE_INFO_RE.match(text)
    if info:
        return Rewritten(_TABLE_INFO.format(info.group(1)))
    if _PRAGMA.match(text):
        return Rewritten("", skip=True)
    text = _BEGIN.sub("BEGIN", text)
    text = re.sub(r"\bsqlite_master\b", _SQLITE_MASTER, text)
    text = re.sub(r"\bREAL\b", "DOUBLE PRECISION", text, flags=re.IGNORECASE)
    if _LAST_ID.search(text):
        text = _LAST_ID.sub(str(last_rowid) if last_rowid is not None else "NULL", text)
    if _CREATE.match(text):
        text = _create_table(text)
    elif _ALTER.match(text):
        text = re.sub(r"\bINTEGER\b", "BIGINT", text, flags=re.IGNORECASE)
    returning = False
    if _INSERT.match(text):
        text, returning = _insert(text, conflict_keys)
    if has_params:
        text = text.replace("%", "%%").replace("?", "%s")
        kept = [k.replace("%", "%%") for k in kept]
    return Rewritten(_unmask(text, kept), returning_rowid=returning)


def _create_table(text: str) -> str:
    keyed = _AUTOINC.search(text)
    text = _AUTOINC.sub(lambda m: f"{m.group(1)} BIGSERIAL PRIMARY KEY", text)
    text = re.sub(r"\bINTEGER\b", "BIGINT", text, flags=re.IGNORECASE)
    end = text.rfind(")")
    if end < 0 or re.search(r"\browid\b", text, re.IGNORECASE):
        return text
    rowid = (f"rowid BIGINT GENERATED ALWAYS AS ({keyed.group(1)}) STORED" if keyed
             else "rowid BIGSERIAL")
    return f"{text[:end].rstrip()},\n    {rowid}\n{text[end:]}"


def _insert(text: str, conflict_keys) -> tuple[str, bool]:
    what = _OR_WHAT.match(text)
    suffix = ""
    if what:
        text = _OR_WHAT.sub("INSERT INTO", text, count=1)
        if what.group(1).upper() == "IGNORE":
            suffix = " ON CONFLICT DO NOTHING"
        else:
            into = _INTO.match(text)
            if not into or conflict_keys is None:
                raise ValueError(f"INSERT OR REPLACE needs a column list on Postgres: {text[:80]}")
            table = into.group(1)
            cols = [c.strip().strip('"') for c in into.group(2).split(",")]
            keys, plain_rowid = conflict_keys(table)
            sets = [f"{c} = EXCLUDED.{c}" for c in cols if c not in keys]
            if plain_rowid:
                # SQLite's REPLACE deletes and inserts: the row moves to the end.
                sets.append("rowid = DEFAULT")
            suffix = (f" ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {', '.join(sets)}" if sets
                      else " ON CONFLICT DO NOTHING")
    elif re.match(r"^\s*REPLACE\s+INTO\b", text, re.IGNORECASE):
        raise ValueError("REPLACE INTO is not supported on Postgres; use INSERT OR REPLACE")
    if _RETURNING.search(text):
        return text + suffix, False
    return text + suffix + " RETURNING rowid", True


# ---------------------------------------------------------------- connection

class Connection:
    """A psycopg connection that answers like a sqlite3 one (autocommit,
    explicit BEGIN/COMMIT as `isolation_level=None` does)."""

    def __init__(self, raw, schema: str | None = None) -> None:
        self.raw = raw
        self.schema = schema
        self.url: str | None = None
        self._last_rowid: int | None = None
        self._keys: dict[str, tuple[list[str], bool]] = {}

    def _conflict_keys(self, table: str) -> tuple[list[str], bool]:
        if table not in self._keys:
            rows = self.raw.execute(
                "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid "
                "AND a.attnum = ANY(i.indkey) WHERE i.indrelid = to_regclass(%s) AND i.indisprimary "
                "ORDER BY array_position(i.indkey, a.attnum)", (table,)).fetchall()
            generated = self.raw.execute(
                "SELECT attgenerated FROM pg_attribute WHERE attrelid = to_regclass(%s) AND attname = 'rowid'",
                (table,)).fetchone()
            self._keys[table] = ([r[0] for r in rows], bool(generated) and not generated[0])
        return self._keys[table]

    def execute(self, sql: str, params: Iterable | dict | None = None) -> Cursor:
        if isinstance(params, dict):
            raise TypeError("named parameters are not supported on Postgres")
        has_params = params is not None and len(params := tuple(_param(p) for p in params)) > 0
        r = rewrite(sql, has_params=has_params, last_rowid=self._last_rowid,
                    conflict_keys=self._conflict_keys)
        if r.skip:
            return Cursor([], -1, None)
        if re.match(r"^\s*(CREATE|ALTER|DROP)\s+TABLE\b", r.sql, re.IGNORECASE):
            self._keys.clear()
        cur = self.raw.execute(r.sql, params if has_params else None)
        rows: list[Row] = []
        if cur.description is not None:
            names = [d.name for d in cur.description]
            raw_rows = cur.fetchall()
            if r.returning_rowid:
                if raw_rows:
                    self._last_rowid = raw_rows[-1][0]
                return Cursor([], cur.rowcount, self._last_rowid)
            # The added rowid column stays hidden (`SELECT rowid AS rid` still reads it).
            drop = {i for i, n in enumerate(names) if n == "rowid"}
            keys = [n for i, n in enumerate(names) if i not in drop]
            index: dict[str, int] = {}
            for i, n in enumerate(keys):
                index.setdefault(n.lower(), i)
            rows = [Row([_value(v) for i, v in enumerate(row) if i not in drop], index, keys) for row in raw_rows]
        return Cursor(rows, cur.rowcount, None)

    def executemany(self, sql: str, seq: Iterable[Iterable]) -> Cursor:
        total = 0
        for params in seq:
            total += max(self.execute(sql, params).rowcount, 0)
        return Cursor([], total, None)

    def ensure(self) -> bool:
        """Rehearsal item 4 (Postgres restarted under a running app): a closed or
        broken connection is opened again before the next transaction. True when
        it had to reconnect. Without a url (tests that wrap a raw connection) it
        does nothing."""
        if self.url is None or not (self.raw.closed or getattr(self.raw, "broken", False)):
            return False
        try:
            self.raw.close()
        except Exception:  # noqa: BLE001 - already gone
            pass
        self.raw = _open(self.url, self.schema)
        self._keys.clear()
        return True

    def alive(self) -> bool:
        """Ask the server; a dead socket shows up here rather than mid-transaction."""
        try:
            self.raw.execute("SELECT 1")
            return True
        except Exception:  # noqa: BLE001 - psycopg.OperationalError and friends
            return False

    def close(self, drop_schema: bool = False) -> None:
        if self.raw.closed:
            return
        try:
            if drop_schema and self.schema:
                self.raw.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
        finally:
            self.raw.close()
