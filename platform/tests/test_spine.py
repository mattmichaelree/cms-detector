from __future__ import annotations

import pytest

from lobbybook.spine.people import parse_people_csv, parse_person_yaml, store_person
from lobbybook.spine.resolve import (
    MATCH_THRESHOLD,
    match_org,
    match_person,
    normalize_org,
    normalize_person,
)
from lobbybook.spine.sessions import build_sessions, load_sessions


def test_sessions_cover_history_and_called_sessions(conn):
    stats = load_sessions(conn)
    assert stats["sessions"] >= 100
    # TLO called-session codes are opaque: '883' is the 88th's 3rd called session,
    # never arithmetic on the number (audit temporal trap #4).
    row = conn.execute("SELECT * FROM session WHERE id='883'").fetchone()
    assert row["legislature"] == 88 and row["seq"] == 3
    ids = {r["id"] for r in conn.execute("SELECT id FROM session WHERE legislature=88")}
    assert ids == {"88R", "881", "882", "883", "884"}


def test_modern_sessions_precise_historical_flagged_approximate(conn):
    load_sessions(conn)
    r89 = conn.execute("SELECT * FROM session WHERE id='89R'").fetchone()
    assert r89["convened"].startswith("2025") and r89["approximate"] == 0
    r10 = conn.execute("SELECT * FROM session WHERE id='10R'").fetchone()
    assert r10["approximate"] == 1, "pre-modern years are derived, must be flagged"
    r90 = conn.execute("SELECT * FROM session WHERE id='90R'").fetchone()
    assert r90["approximate"] == 1, "90R has not convened yet"


def test_session_ids_unique():
    rows = build_sessions()
    assert len({r["id"] for r in rows}) == len(rows)


def test_org_normalization_collapses_the_audits_observed_variant():
    # Verified live in the audit: these two strings appear on adjacent TEC rows
    # for the same employer with no linking id anywhere.
    assert normalize_org("American Pharmacies, Inc.") == normalize_org("American Pharmacies")
    assert normalize_org("Texas Ass'n of Business & Commerce") == "texas assn of business and commerce"


def test_person_normalization_handles_journal_forms():
    assert normalize_person("Bell, C.") == "c bell"
    assert normalize_person("John Seago Jr.") == "john seago"
    assert normalize_person("Muñoz Jr., Sergio") == normalize_person("Sergio Munoz")


def test_resolver_never_silently_merges_distinct_orgs(conn):
    conn.execute("INSERT INTO organization (id, canonical_name, org_type) VALUES (?,?,?)",
                 ("org:trtl", "Texas Right to Life", "nonprofit"))
    # Same-side, similarly named, but genuinely different organizations — both
    # appear in one witness list in the audit's verified sample.
    oid, conf, method = match_org(conn, "Texans for Life")
    assert conf < MATCH_THRESHOLD, f"would have wrongly merged via {method}"
    oid, conf, _ = match_org(conn, "Texas Right to Life, Inc.")
    assert oid == "org:trtl" and conf == 1.0


def test_resolution_attempts_are_recorded(conn):
    conn.execute("INSERT INTO person (id, canonical_name) VALUES ('p1','Chris Bell')")
    conn.execute("INSERT INTO person_name (person_id, name_raw, source) VALUES ('p1','Bell, C.','test')")
    pid, conf, _ = match_person(conn, "Bell, C.")
    assert pid == "p1" and conf == 1.0
    row = conn.execute("SELECT * FROM name_resolution WHERE raw='Bell, C.'").fetchone()
    assert row["resolved_id"] == "p1" and row["confidence"] == 1.0


def test_openstates_person_yaml_parsed_and_stored(conn):
    y = b"""
id: ocd-person/00000000-1111-2222-3333-444444444444
name: Jane Q. Legislator
given_name: Jane
family_name: Legislator
party:
  - name: Republican
roles:
  - type: lower
    district: 87
    jurisdiction: ocd-jurisdiction/country:us/state:tx/government
    start_date: '2023-01-10'
other_names:
  - name: Jane Legislator
other_identifiers:
  - scheme: legiscan
    identifier: '23184'
"""
    rec = parse_person_yaml(y)
    assert rec["name"] == "Jane Q. Legislator"
    assert rec["roles"][0]["district"] == "87" and rec["roles"][0]["party"] == "Republican"
    store_person(conn, rec)
    assert conn.execute("SELECT COUNT(*) c FROM person").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM role_tenure").fetchone()["c"] == 1
    # Crosswalk: the OpenStates id is canonical, LegiScan attaches as an xref.
    xr = conn.execute("SELECT person_id FROM person_xref WHERE system='legiscan'").fetchone()
    assert xr["person_id"] == rec["id"]
    # Storing twice must not duplicate tenures.
    store_person(conn, rec)
    assert conn.execute("SELECT COUNT(*) c FROM role_tenure").fetchone()["c"] == 1


def test_openstates_roster_csv_parsed(conn):
    csv = (
        b"id,name,current_party,current_district,current_chamber,given_name,family_name,"
        b"gender,email,biography,birth_date,death_date,image,links,sources,capitol_address,"
        b"capitol_voice,capitol_fax,district_address,district_voice,district_fax,twitter,"
        b"youtube,instagram,facebook,wikidata\n"
        b"ocd-person/dd3e49ca-2b2b-4a83-ae63-0ade6ccef73f,A.J. Louderback,Republican,30,lower,"
        b"A.J.,Louderback,Male,aj.louderback@house.texas.gov,,,,img.jpg,"
        b"https://ajlouderback.com/;https://house.texas.gov/members/4620,src,,,,,,,,,,,Q123\n"
    )
    recs = parse_people_csv(csv)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["name"] == "A.J. Louderback"
    assert rec["roles"][0]["district"] == "30" and rec["roles"][0]["party"] == "Republican"
    # The links column yields a free crosswalk to the House's own member id.
    assert ("tx_house_member", "4620") in rec["xrefs"]
    store_person(conn, rec)
    xr = conn.execute("SELECT person_id FROM person_xref WHERE system='tx_house_member'").fetchone()
    assert xr["person_id"] == rec["id"]
    # 'Louderback, A.J.' (journal form) must resolve to this person.
    pid, conf, _ = match_person(conn, "Louderback, A.J.")
    assert pid == rec["id"] and conf == 1.0


@pytest.mark.live
def test_spine_live_smoke(conn):
    from lobbybook.core.registry import get

    assert get("spine_sessions").smoke(conn).ok
    r = get("spine_people").smoke(conn)
    assert r.ok, r.detail
