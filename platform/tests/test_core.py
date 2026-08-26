from __future__ import annotations

import pytest

from lobbybook.core import db as dbx
from lobbybook.core.docstore import load_latest, store_document
from lobbybook.core.fetch import DeniedURL, Fetcher


def test_schema_applies_and_reapplies(conn):
    dbx.init_db(conn)  # idempotent
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for expected in ("document", "bill", "vote_cast", "edge", "rule_action", "witness_slip"):
        assert expected in tables


def test_docstore_versions_and_dedup(conn):
    _, changed = store_document(conn, doc_id="t:1", source_family="test", content=b"alpha")
    assert changed
    _, changed = store_document(conn, doc_id="t:1", source_family="test", content=b"alpha")
    assert not changed
    _, changed = store_document(conn, doc_id="t:1", source_family="test", content=b"beta")
    assert changed
    n = conn.execute("SELECT COUNT(*) AS n FROM document_version WHERE document_id='t:1'").fetchone()["n"]
    assert n == 2
    assert load_latest(conn, "t:1") == b"beta"


def test_upsert_and_edges(conn):
    dbx.upsert(conn, "session", {"id": "89R", "legislature": 89, "seq": 0}, ["id"])
    dbx.upsert(conn, "session", {"id": "89R", "legislature": 89, "seq": 0}, ["id"])
    dbx.add_edge(conn, "bill", "89R-HB1", "referred_to", "committee", "89R-H-C450", "explicit")
    dbx.add_edge(conn, "bill", "89R-HB1", "referred_to", "committee", "89R-H-C450", "explicit")
    assert conn.execute("SELECT COUNT(*) AS n FROM edge").fetchone()["n"] == 1
    with pytest.raises(ValueError):
        dbx.add_edge(conn, "b", "x", "p", "c", "y", "guessed")  # bad provenance class


def test_fetch_denylist_blocks_before_network():
    f = Fetcher()
    for url in (
        "https://lrl.texas.gov/scanned/interim/44/x.pdf",
        "https://search.txcourts.gov/CaseSearch.aspx",
        "https://research.txcourts.gov/anything",
    ):
        with pytest.raises(DeniedURL):
            f.get(url)


def test_tlo_rss_parser_offline():
    from lobbybook.sources.tlo import parse_rss

    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
    <item><title>HB 1500 by Smith - Relating to agencies</title>
    <link>https://capitol.texas.gov/x</link><guid>g1</guid></item>
    <item><title>SB 2 and SJR 1 set for hearing</title><guid>g2</guid></item>
    </channel></rss>"""
    items = parse_rss(feed)
    assert items[0]["bills"] == [("HB", 1500)]
    assert ("SB", 2) in items[1]["bills"] and ("SJR", 1) in items[1]["bills"]


def test_tlo_history_parser_offline():
    from lobbybook.sources.tlo import parse_history

    html = b"""<html><body>
    <span>Caption Text:</span> <span>Relating to the powers of certain districts.</span>
    <table>
    <tr><td>Author:</td><td>Bonnen | Smith</td></tr>
    <tr><td>Subjects:</td><td>State Finances--Appropriations (I0746)</td></tr>
    <tr><td>Companion:</td><td>SB 30</td></tr>
    </table>
    <table>
    <tr><td>H</td><td>Read first time</td><td>03/01/2025</td></tr>
    <tr><td>H</td><td>Referred to Appropriations</td><td>03/01/2025</td></tr>
    </table></body></html>"""
    parsed = parse_history(html, "89R", "HB1")
    assert parsed["caption"].startswith("Relating to")
    assert ("author", "Bonnen") in parsed["authors"]
    assert parsed["subjects"] == [("I0746", "State Finances--Appropriations")]
    assert parsed["companions"] == ["SB30"]
    assert len(parsed["actions"]) == 2


def test_tlo_store_history_roundtrip(conn):
    from lobbybook.sources.tlo import parse_history, store_history

    dbx.upsert(conn, "session", {"id": "89R", "legislature": 89, "seq": 0}, ["id"])
    html = b"<table><tr><td>Author:</td><td>Bonnen</td></tr>" \
           b"<tr><td>H</td><td>Read first time</td><td>03/01/2025</td></tr></table>"
    store_history(conn, "89R", "HB1", parse_history(html, "89R", "HB1"), None)
    row = conn.execute("SELECT * FROM bill WHERE id='89R-HB1'").fetchone()
    assert row["bill_type"] == "HB" and row["number"] == 1
    assert conn.execute("SELECT COUNT(*) n FROM bill_action").fetchone()["n"] == 1


@pytest.mark.live
def test_tlo_live_smoke(conn):
    from lobbybook.core.registry import get

    r = get("tlo").smoke(conn)
    assert r.ok, r.detail
