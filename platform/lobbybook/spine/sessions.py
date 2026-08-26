"""Session spine: the canonical table of Texas legislative sessions.

Session codes follow TLO's convention ('89R' regular, '891'..'894' called).
Modern entries (71st onward) carry real convene years; the deep historical
series is generated formulaically and flagged approximate=1 so nothing
downstream mistakes a derived year for a verified one. The audit's LRL
session list (1846 -> 2027) is the authority for a later precise refresh.
"""

from __future__ import annotations

import sqlite3

from lobbybook.core import db as dbx
from lobbybook.core.registry import Connector, SmokeResult, register

# Called sessions per legislature, verified in the audit's deep dives
# (88th had four; 89th had two; 87th three; 85th one; 83rd three; 82nd one).
CALLED: dict[int, int] = {71: 6, 72: 4, 79: 3, 82: 1, 83: 3, 85: 1, 87: 3, 88: 4, 89: 2}

FIRST_MODERN = 71          # 71st Legislature convened 1989
FIRST_MODERN_YEAR = 1989
LATEST = 90                # 90th convenes January 2027


def build_sessions() -> list[dict]:
    """Generate the full session series. Regular sessions convene in January
    of odd years; legislature n convenes 1846 + 2*(n-1)."""
    rows: list[dict] = []
    for leg in range(1, LATEST + 1):
        year = FIRST_MODERN_YEAR + 2 * (leg - FIRST_MODERN)
        approximate = 0 if leg >= FIRST_MODERN else 1
        rows.append(
            {
                "id": f"{leg}R",
                "legislature": leg,
                "seq": 0,
                "convened": f"{year}-01-01" if not approximate else None,
                "adjourned": None,
                "label": f"{leg}th Legislature, Regular Session ({year})",
                # 90R has not convened yet; its dates are scheduled, not historical.
                "approximate": 1 if (approximate or leg == LATEST) else 0,
            }
        )
        for n in range(1, CALLED.get(leg, 0) + 1):
            rows.append(
                {
                    "id": f"{leg}{n}",
                    "legislature": leg,
                    "seq": n,
                    "convened": None,
                    "adjourned": None,
                    "label": f"{leg}th Legislature, {n}{_ord(n)} Called Session",
                    "approximate": 1,
                }
            )
    return rows


def _ord(n: int) -> str:
    return {1: "st", 2: "nd", 3: "rd"}.get(n, "th")


def load_sessions(conn: sqlite3.Connection) -> dict:
    rows = build_sessions()
    for row in rows:
        dbx.upsert(conn, "session", row, ["id"])
    conn.commit()
    precise = sum(1 for r in rows if not r["approximate"])
    return {"sessions": len(rows), "precise": precise, "approximate": len(rows) - precise}


@register
class SessionsConnector(Connector):
    name = "spine_sessions"
    tier = 0
    cadence = "static"

    def backfill(self, conn: sqlite3.Connection, **kwargs) -> dict:
        return load_sessions(conn)

    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        return load_sessions(conn)

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        stats = load_sessions(conn)
        row = conn.execute("SELECT * FROM session WHERE id='883'").fetchone()
        ok = bool(row) and row["legislature"] == 88 and row["seq"] == 3 and stats["sessions"] >= 100
        return SmokeResult(ok=ok, detail=f"{stats['sessions']} sessions loaded", stats=stats)
