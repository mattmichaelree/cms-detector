"""Name normalization and entity resolution.

The audit named this the central investment: witnesses, donors, clients, rule
commenters and statement authors are all free text with no IDs anywhere. The
rule here is that we never silently merge — every match returns a confidence
and a method, low-confidence matches are recorded rather than applied, and the
resulting edges are 'inferred' by construction.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata

DDL = """
CREATE TABLE IF NOT EXISTS name_resolution (
    raw         TEXT NOT NULL,
    kind        TEXT NOT NULL,
    resolved_id TEXT,
    confidence  REAL NOT NULL,
    method      TEXT NOT NULL,
    PRIMARY KEY (raw, kind)
);
"""

# Confidence at or above which a caller may act on a match automatically.
MATCH_THRESHOLD = 0.90

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_ORG_SUFFIXES = {
    "inc", "llc", "corp", "corporation", "co", "company", "lp", "llp",
    "pllc", "ltd", "pc", "the",
}
_PUNCT = re.compile(r"[^\w\s]")
# Apostrophes are dropped rather than split on, so "Ass'n" -> "assn" and
# "O'Brien" -> "obrien" stay single tokens for overlap scoring.
_APOS = re.compile(r"[\u2019']")
_WS = re.compile(r"\s+")


def _ascii_fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_person(raw: str) -> str:
    """'Bell, C.' -> 'c bell'; 'John Seago Jr.' -> 'john seago'.

    Comma form is treated as 'Last, First' and reordered so both orderings
    converge. Initials are preserved (the journals' own disambiguator).
    """
    s = _APOS.sub("", _ascii_fold(raw or "").strip())
    if "," in s:
        last, _, rest = s.partition(",")
        s = f"{rest.strip()} {last.strip()}"
    s = _PUNCT.sub(" ", s).lower()
    parts = [p for p in _WS.sub(" ", s).split(" ") if p and p not in _SUFFIXES]
    return " ".join(parts)


def normalize_org(raw: str) -> str:
    """'American Pharmacies, Inc.' -> 'american pharmacies'."""
    s = _APOS.sub("", _ascii_fold(raw or "").lower()).replace("&", " and ")
    s = _PUNCT.sub(" ", s)
    parts = [p for p in _WS.sub(" ", s).split(" ") if p]
    while parts and parts[-1] in _ORG_SUFFIXES:
        parts.pop()
    while parts and parts[0] in _ORG_SUFFIXES:
        parts.pop(0)
    return " ".join(parts)


def _token_overlap(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _match(conn, raw, normalize, name_table, name_col, id_col, canon_table, canon_col):
    norm = normalize(raw)
    if not norm:
        return (None, 0.0, "empty")

    best_id, best_conf, method = None, 0.0, "none"
    for table, col, idc in ((name_table, name_col, id_col), (canon_table, canon_col, "id")):
        for row in conn.execute(f"SELECT {idc} AS eid, {col} AS nm FROM {table}"):
            cand = normalize(row["nm"] or "")
            if not cand:
                continue
            if cand == norm:
                return (row["eid"], 1.0, f"exact:{table}")
            score = _token_overlap(norm, cand)
            if score > best_conf:
                best_id, best_conf, method = row["eid"], score, f"tokens:{table}"
    # Token overlap is a candidate signal only — deliberately capped below the
    # action threshold so a partial match never auto-merges two entities.
    return (best_id, min(best_conf, 0.85), method) if best_id else (None, 0.0, "none")


def _record(conn: sqlite3.Connection, raw: str, kind: str, result: tuple) -> tuple:
    conn.execute(
        """INSERT INTO name_resolution (raw, kind, resolved_id, confidence, method)
           VALUES (?,?,?,?,?)
           ON CONFLICT(raw, kind) DO UPDATE SET
             resolved_id=excluded.resolved_id, confidence=excluded.confidence,
             method=excluded.method""",
        (raw, kind, result[0], result[1], result[2]),
    )
    return result


def match_person(conn: sqlite3.Connection, raw: str) -> tuple[str | None, float, str]:
    r = _match(conn, raw, normalize_person,
               "person_name", "name_raw", "person_id", "person", "canonical_name")
    return _record(conn, raw, "person", r)


def match_org(conn: sqlite3.Connection, raw: str) -> tuple[str | None, float, str]:
    r = _match(conn, raw, normalize_org,
               "org_name", "name_raw", "org_id", "organization", "canonical_name")
    return _record(conn, raw, "org", r)
