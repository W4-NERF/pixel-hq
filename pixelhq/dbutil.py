"""Read-only SQLite projections that tolerate missing optional columns."""
from __future__ import annotations

import contextlib
import contextvars
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

_CREATE_NOTHING: contextvars.ContextVar[dict | None] = contextvars.ContextVar("pixelhq_create_nothing", default=None)
WAL_WITHOUT_SHM = "write-ahead log without its -shm file was not read; data may be older"
HEADER_UNREADABLE = "header unreadable; the database was not read"
_HEADER_BYTES = 100  # the SQLite file header; byte 18 holds the file format version (1 rollback journal, 2 WAL)


class HeaderUnreadable(sqlite3.DatabaseError):
    """The exporter could not read the database header: the database is skipped (R5-D10)."""


@contextlib.contextmanager
def create_nothing() -> Iterator[dict[Path, str]]:
    """Inside this block ``ro`` never creates a file next to a database (round 5, R5-D10).

    A plain ``mode=ro`` open of a WAL-mode database creates the ``-wal``/``-shm`` side files when they are missing.
    The exporter runs in this block because it promises to create no files; the collector's own reads are unchanged.
    The block yields a dict that collects, per resolved database path, why a database was read with less than all its
    data (:data:`WAL_WITHOUT_SHM`) or not at all (:data:`HEADER_UNREADABLE`), so the exporter can name the profile or
    board in its warning.
    """
    findings: dict[Path, str] = {}
    token = _CREATE_NOTHING.set(findings)
    try:
        yield findings
    finally:
        _CREATE_NOTHING.reset(token)


def _journal_version(path: Path) -> int:
    """Byte 18 of the database header (1 rollback journal, 2 WAL), read without SQLite; ``-1`` when unreadable."""
    try:
        with path.open("rb") as handle:
            header = handle.read(_HEADER_BYTES)
    except FileNotFoundError:
        return 1  # SQLite reports the missing file itself
    except OSError:
        return -1
    return header[18] if len(header) == _HEADER_BYTES else -1


def _exporter_query(resolved: Path, findings: dict[Path, str]) -> str:
    """The URI query of an exporter open: a rollback journal reads with shared locks, a WAL only with its -shm file."""
    version = _journal_version(resolved)
    if version < 0:
        findings[resolved] = HEADER_UNREADABLE
        raise HeaderUnreadable(HEADER_UNREADABLE)
    if version != 2:
        return "?mode=ro"
    wal, shm = (Path(f"{resolved}{suffix}").exists() for suffix in ("-wal", "-shm"))
    if wal and shm:
        return "?mode=ro"
    if wal:
        findings[resolved] = WAL_WITHOUT_SHM
    return "?mode=ro&immutable=1"


def ro(path: Path) -> sqlite3.Connection:
    resolved = Path(path).resolve()
    findings = _CREATE_NOTHING.get()
    query = "?mode=ro" if findings is None else _exporter_query(resolved, findings)
    return sqlite3.connect(resolved.as_uri() + query, uri=True, timeout=2)


def _identifier(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError("invalid SQL identifier")
    return '"' + name + '"'


def columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info({_identifier(table)})")}


def warning(warnings: list[str], source: str, error) -> None:
    if str(error) == HEADER_UNREADABLE:
        return  # the exporter reports it once, with the profile or board name (R5-D10)
    text = f"{source}: {' '.join(str(error).split())}"[:120]
    if text not in warnings:
        warnings.append(text)


def rows(con: sqlite3.Connection, table: str, wanted_cols, where: str = "", params=(), *,
         warnings: list[str], source: str) -> list:
    """Skip only the failing table/query, recording a bounded source diagnostic."""
    try:
        return select(con, table, wanted_cols, where, params).fetchall()
    except sqlite3.Error as exc:
        warning(warnings, f"{source}/{table}", exc)
        return []


def select(con: sqlite3.Connection, table: str, wanted_cols, where: str = "", params=()) -> sqlite3.Cursor:
    """Filter/order the projected columns, so missing names also work in WHERE clauses.

    Identifiers and clauses are developer-owned; untrusted values belong in params.
    A missing table raises sqlite3.OperationalError for the source reader to report.
    """
    available = columns(con, table)
    if not available:
        raise sqlite3.OperationalError(f"no such table: {table}")
    projection = ", ".join(_identifier(col) if col in available else f"NULL AS {_identifier(col)}"
                           for col in wanted_cols)
    suffix = " WHERE " + where if where else ""
    return con.execute(f"SELECT * FROM (SELECT {projection} FROM {_identifier(table)}){suffix}", params)
