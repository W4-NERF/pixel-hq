"""Read-only SQLite projections that tolerate missing optional columns."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path


def ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)


def _identifier(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError("invalid SQL identifier")
    return '"' + name + '"'


def columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info({_identifier(table)})")}


def warning(warnings: list[str], source: str, error) -> None:
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
