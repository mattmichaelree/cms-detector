"""People spine: OpenStates person records as the canonical identity layer.

OpenStates' people repo is CC0 and its ids are designed to be stable across
sessions and redistricting (audit: third-party ecosystem deep dive), so it is
the canonical key; LRL memberIDs and TEC filer IDs attach as crosswalk rows.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register
from lobbybook.spine.resolve import DDL as RESOLVE_DDL

# OpenStates' sanctioned bulk endpoint (linked from open.pluralpolicy.com/data/).
# github.com itself is blocked by this environment's proxy, and scraping its
# HTML listing would be the wrong channel anyway.
CURRENT_CSV = "https://data.openstates.org/people/current/tx.csv"
RAW_BASE = "https://raw.githubusercontent.com/openstates/people/main/data/tx/legislature"


def parse_person_yaml(content: bytes) -> dict:
    """OpenStates person YAML -> {id, name, variants[], roles[], xrefs[]}."""
    data = yaml.safe_load(content) or {}
    pid = str(data.get("id") or "").strip()
    name = (data.get("name") or "").strip()
    variants = []
    for other in data.get("other_names") or []:
        n = (other or {}).get("name") if isinstance(other, dict) else other
        if n:
            variants.append(str(n))
    given, family = data.get("given_name"), data.get("family_name")
    if given and family:
        variants.append(f"{family}, {given}")
    roles = []
    for role in data.get("roles") or []:
        roles.append(
            {
                "role": (role.get("type") or "").lower() or "member",
                "body": role.get("jurisdiction") or "tx",
                "district": str(role.get("district")) if role.get("district") is not None else None,
                "party": None,
                "valid_from": str(role.get("start_date")) if role.get("start_date") else None,
                "valid_to": str(role.get("end_date")) if role.get("end_date") else None,
            }
        )
    parties = data.get("party") or []
    party_name = None
    if parties:
        p0 = parties[0]
        party_name = (p0.get("name") if isinstance(p0, dict) else p0) or None
    for r in roles:
        r["party"] = party_name
    xrefs = []
    for ident in data.get("other_identifiers") or []:
        if isinstance(ident, dict) and ident.get("scheme") and ident.get("identifier"):
            xrefs.append((str(ident["scheme"]), str(ident["identifier"])))
    return {"id": pid, "name": name, "variants": variants, "roles": roles, "xrefs": xrefs}


def store_person(conn: sqlite3.Connection, rec: dict) -> None:
    if not rec["id"] or not rec["name"]:
        return
    dbx.upsert(conn, "person", {"id": rec["id"], "canonical_name": rec["name"],
                                "sort_name": rec["name"]}, ["id"])
    dbx.upsert(conn, "person_xref",
               {"system": "openstates", "external_id": rec["id"], "person_id": rec["id"]},
               ["system", "external_id"])
    for variant in {rec["name"], *rec["variants"]}:
        dbx.upsert(conn, "person_name",
                   {"person_id": rec["id"], "name_raw": variant, "source": "openstates"},
                   ["person_id", "name_raw"], update_cols=[])
    for system, ext in rec["xrefs"]:
        dbx.upsert(conn, "person_xref",
                   {"system": system, "external_id": ext, "person_id": rec["id"]},
                   ["system", "external_id"])
    for role in rec["roles"]:
        exists = conn.execute(
            """SELECT id FROM role_tenure WHERE person_id=? AND role=? AND
               COALESCE(district,'')=? AND COALESCE(valid_from,'')=?""",
            (rec["id"], role["role"], role["district"] or "", role["valid_from"] or ""),
        ).fetchone()
        if not exists:
            conn.execute(
                """INSERT INTO role_tenure (person_id, role, body, district, party,
                                            valid_from, valid_to)
                   VALUES (?,?,?,?,?,?,?)""",
                (rec["id"], role["role"], role["body"], role["district"], role["party"],
                 role["valid_from"], role["valid_to"]),
            )


def load_people_dir(conn: sqlite3.Connection, path: str | Path) -> dict:
    """Load every *.yml under a local clone of openstates/people/data/tx."""
    n = 0
    for f in sorted(Path(path).glob("**/*.yml")):
        store_person(conn, parse_person_yaml(f.read_bytes()))
        n += 1
    conn.commit()
    return {"files": n, "persons": conn.execute("SELECT COUNT(*) c FROM person").fetchone()["c"]}


def parse_people_csv(content: bytes) -> list[dict]:
    """OpenStates current-legislators CSV -> person records.

    Also mines the `links` column for house.texas.gov/members/<id> and
    senate.texas.gov district URLs, which give a free crosswalk to the
    chambers' own member ids.
    """
    import csv
    import io
    import re

    out: list[dict] = []
    reader = csv.DictReader(io.StringIO(content.decode("utf-8", errors="replace")))
    for row in reader:
        pid = (row.get("id") or "").strip()
        name = (row.get("name") or "").strip()
        if not pid or not name:
            continue
        variants = []
        given, family = row.get("given_name"), row.get("family_name")
        if given and family:
            variants += [f"{family}, {given}", f"{given} {family}"]
        if family:
            variants.append(family)

        xrefs = []
        links = row.get("links") or ""
        m = re.search(r"house\.texas\.gov/members/(\d+)", links)
        if m:
            xrefs.append(("tx_house_member", m.group(1)))
        w = (row.get("wikidata") or "").strip()
        if w:
            xrefs.append(("wikidata", w))

        chamber = (row.get("current_chamber") or "").strip()
        district = (row.get("current_district") or "").strip() or None
        roles = []
        if chamber:
            roles.append(
                {
                    "role": chamber,             # 'lower' | 'upper', as OpenStates types them
                    "body": "tx",
                    "district": district,
                    "party": (row.get("current_party") or "").strip() or None,
                    "valid_from": None,          # current-roster export carries no start date
                    "valid_to": None,
                }
            )
        out.append({"id": pid, "name": name, "variants": variants,
                    "roles": roles, "xrefs": xrefs})
    return out


def load_current_roster(conn: sqlite3.Connection) -> dict:
    """Fetch and load the current Texas legislator roster."""
    resp = fetcher().get(CURRENT_CSV)
    resp.raise_for_status()
    store_document(
        conn,
        doc_id="openstates:people:tx:current",
        source_family="openstates",
        content=resp.content,
        url=CURRENT_CSV,
        doc_type="people_csv",
        authority="B",
    )
    records = parse_people_csv(resp.content)
    for rec in records:
        store_person(conn, rec)
    conn.commit()
    return {
        "records": len(records),
        "persons": conn.execute("SELECT COUNT(*) c FROM person").fetchone()["c"],
        "tenures": conn.execute("SELECT COUNT(*) c FROM role_tenure").fetchone()["c"],
    }


@register
class PeopleConnector(Connector):
    name = "spine_people"
    tier = 0
    cadence = "monthly"
    DDL = RESOLVE_DDL

    def backfill(self, conn: sqlite3.Connection, **kwargs) -> dict:
        # A local clone of openstates/people gives full service history; the
        # published CSV gives only the current roster.
        if kwargs.get("path"):
            return load_people_dir(conn, kwargs["path"])
        return load_current_roster(conn)

    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        return load_current_roster(conn)

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        stats = load_current_roster(conn)
        ok = stats["persons"] >= 150 and stats["tenures"] >= 150
        return SmokeResult(ok=ok,
                           detail=f"{stats['persons']} persons, {stats['tenures']} tenures",
                           stats=stats)
