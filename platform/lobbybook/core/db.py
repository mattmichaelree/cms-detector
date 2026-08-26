"""SQLite access layer.

SQLite is the development store; the DDL in schema.sql is written to stay
Postgres-portable so the upgrade path is a connection-string change plus a
driver swap, not a schema rewrite.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from importlib import resources
from pathlib import Path

_DEFAULT_DB = "var/lobbybook.db"


def db_path() -> Path:
    return Path(os.environ.get("LOBBYBOOK_DB", _DEFAULT_DB))


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Apply the canonical schema plus every registered connector's extra DDL."""
    schema = resources.files("lobbybook.core").joinpath("schema.sql").read_text()
    conn.executescript(schema)
    from lobbybook.core.registry import iter_ddl

    for ddl in iter_ddl():
        conn.executescript(ddl)
    conn.commit()


def upsert(
    conn: sqlite3.Connection,
    table: str,
    row: dict,
    conflict_cols: Iterable[str],
    update_cols: Iterable[str] | None = None,
) -> None:
    """INSERT ... ON CONFLICT DO UPDATE for the given natural key."""
    cols = list(row)
    placeholders = ", ".join("?" for _ in cols)
    conflict = ", ".join(conflict_cols)
    updates = list(update_cols) if update_cols is not None else [c for c in cols if c not in conflict_cols]
    if updates:
        set_clause = ", ".join(f"{c}=excluded.{c}" for c in updates)
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) DO UPDATE SET {set_clause}"
        )
    else:
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) DO NOTHING"
        )
    conn.execute(sql, [row[c] for c in cols])


PROVENANCE_CLASSES = ("explicit", "derived", "inferred")

# TLO session codes: '89R' regular, '891'..'894' called sessions.
_SESSION_RE = __import__("re").compile(r"^(\d{2,3})(R|[1-4])$")


def ensure_session(conn: sqlite3.Connection, session_id: str) -> None:
    """Insert a minimal session row (approximate=1) so FK-dependent inserts
    succeed before the spine's authoritative session load runs."""
    m = _SESSION_RE.match(session_id)
    leg = int(m.group(1)) if m else 0
    seq = 0 if (not m or m.group(2) == "R") else int(m.group(2))
    conn.execute(
        """INSERT INTO session (id, legislature, seq, approximate) VALUES (?,?,?,1)
           ON CONFLICT(id) DO NOTHING""",
        (session_id, leg, seq),
    )


def add_edge(
    conn: sqlite3.Connection,
    src_type: str,
    src_id: str,
    predicate: str,
    dst_type: str,
    dst_id: str,
    provenance: str,
    source_doc: str | None = None,
    confidence: float | None = None,
    span: str | None = None,
) -> None:
    # INSERT OR IGNORE would swallow the schema CHECK; enforce here instead.
    if provenance not in PROVENANCE_CLASSES:
        raise ValueError(f"provenance must be one of {PROVENANCE_CLASSES}, got {provenance!r}")
    conn.execute(
        """INSERT OR IGNORE INTO edge
           (src_type, src_id, predicate, dst_type, dst_id, provenance, confidence, source_doc, span)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (src_type, src_id, predicate, dst_type, dst_id, provenance, confidence, source_doc, span),
    )
