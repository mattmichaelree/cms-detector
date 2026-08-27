"""Cadence-driven orchestration.

The audit's roadmap assigns every source a refresh cadence, and two of them
are urgent for reasons that have nothing to do with convenience: the Texas
Register purges its own archive after about a year, and House member pages are
overwritten when a seat changes hands. A missed window there is unrecoverable,
so cadence is treated as a first-class property of a connector rather than
something a cron file knows about separately.

Runs are recorded so a scheduler can answer "what is overdue" instead of
re-running everything blindly.
"""

from __future__ import annotations

import sqlite3
import time
import traceback
from dataclasses import dataclass

from lobbybook.core import registry

DDL = """
CREATE TABLE IF NOT EXISTS ingest_run (
    id         INTEGER PRIMARY KEY,
    connector  TEXT NOT NULL,
    mode       TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok         INTEGER,
    detail     TEXT,
    error      TEXT
);
CREATE INDEX IF NOT EXISTS idx_run_connector ON ingest_run(connector, started_at);
"""

# Cadence -> how stale a successful run may get before the source is overdue.
# 'session' cadences are deliberately short: during session the record moves daily.
MAX_AGE_SECONDS = {
    "hourly": 3600,
    "hourly_in_session": 3600,
    "daily": 86_400,
    "daily_in_session": 86_400,
    "nightly": 86_400,
    "weekly": 604_800,
    "weekly_friday": 604_800,
    "monthly": 2_592_000,
    "quarterly": 7_776_000,
    "interim_season": 2_592_000,
    "review_cycle": 2_592_000,
    "convention_cycle": 15_552_000,
    "cycle": 15_552_000,
    "biennial": 31_536_000,
    "static": None,          # load once; re-running is harmless but never overdue
}


@dataclass
class RunResult:
    connector: str
    ok: bool
    detail: str
    seconds: float


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.commit()


def last_success(conn: sqlite3.Connection, name: str) -> str | None:
    ensure_tables(conn)
    row = conn.execute(
        "SELECT finished_at FROM ingest_run WHERE connector=? AND ok=1 ORDER BY id DESC LIMIT 1",
        (name,),
    ).fetchone()
    return row["finished_at"] if row else None


def overdue(conn: sqlite3.Connection, name: str) -> bool:
    """True when a connector has never succeeded or its cadence window elapsed."""
    from datetime import UTC, datetime

    ensure_tables(conn)
    connector = registry.get(name)
    window = MAX_AGE_SECONDS.get(connector.cadence, 86_400)
    if window is None:
        return last_success(conn, name) is None
    last = last_success(conn, name)
    if not last:
        return True
    age = (datetime.now(UTC) - datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC))
    return age.total_seconds() > window


def run_one(conn: sqlite3.Connection, name: str, mode: str = "incremental") -> RunResult:
    """Run one connector, recording the attempt either way.

    A failing source must never abort a sweep — a state site being down is a
    normal Tuesday, and the other fifteen connectors still have work to do.
    """
    ensure_tables(conn)
    started = _now()
    cur = conn.execute(
        "INSERT INTO ingest_run (connector, mode, started_at) VALUES (?,?,?)",
        (name, mode, started),
    )
    run_id = cur.lastrowid
    conn.commit()
    t0 = time.monotonic()
    try:
        connector = registry.get(name)
        fn = getattr(connector, mode)
        result = fn(conn)
        detail = str(result)[:500]
        ok, error = True, None
    except NotImplementedError:
        detail, ok, error = f"{name}: {mode} not implemented", True, None
    except Exception as exc:  # noqa: BLE001 - a sweep records failures, never dies on them
        detail, ok = "", None
        error = f"{type(exc).__name__}: {exc}"
        ok = False
        traceback.clear_frames(exc.__traceback__) if exc.__traceback__ else None
    elapsed = time.monotonic() - t0
    conn.execute(
        "UPDATE ingest_run SET finished_at=?, ok=?, detail=?, error=? WHERE id=?",
        (_now(), 1 if ok else 0, detail, error, run_id),
    )
    conn.commit()
    return RunResult(connector=name, ok=bool(ok), detail=detail or (error or ""), seconds=elapsed)


def sweep(
    conn: sqlite3.Connection,
    *,
    cadence: str | None = None,
    tier: int | None = None,
    only_overdue: bool = True,
    mode: str = "incremental",
) -> list[RunResult]:
    """Run every connector matching the filters. Returns one result per attempt."""
    ensure_tables(conn)
    results = []
    for name in registry.names():
        c = registry.get(name)
        if cadence and c.cadence != cadence:
            continue
        if tier is not None and c.tier != tier:
            continue
        if only_overdue and not overdue(conn, name):
            continue
        results.append(run_one(conn, name, mode))
    return results


def status(conn: sqlite3.Connection) -> list[dict]:
    ensure_tables(conn)
    out = []
    for name in registry.names():
        c = registry.get(name)
        out.append(
            {
                "connector": name,
                "tier": c.tier,
                "cadence": c.cadence,
                "last_success": last_success(conn, name),
                "overdue": overdue(conn, name),
            }
        )
    return out
