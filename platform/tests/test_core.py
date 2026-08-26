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


def test_cloudflare_challenge_is_not_retried(monkeypatch):
    """A challenge 403 is a verdict on our TLS fingerprint, not a transient
    error. Retrying quadrupled our request count against a host that was always
    going to refuse (observed live on texasgop.org)."""
    import httpx

    from lobbybook.core.fetch import Fetcher

    calls = {"n": 0}

    def fake_get(self, url, headers=None):
        calls["n"] += 1
        return httpx.Response(
            403,
            headers={"cf-mitigated": "challenge", "server": "cloudflare"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    f = Fetcher(max_retries=3)
    f._last_hit["example.org"] = -1e6  # skip the throttle sleep
    resp = f.get("https://example.org/walled")
    assert resp.status_code == 403
    assert calls["n"] == 1, "a challenge must not be retried"


def test_ordinary_403_still_retries(monkeypatch):
    """Plain 403s (e.g. intermittent Akamai on sos.state.tx.us) stay retryable —
    the audit saw those clear on a later attempt."""
    import httpx

    from lobbybook.core.fetch import Fetcher

    calls = {"n": 0}

    def fake_get(self, url, headers=None):
        calls["n"] += 1
        return httpx.Response(403, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setattr("lobbybook.core.fetch.time.sleep", lambda _s: None)
    f = Fetcher(max_retries=2)
    f._last_hit["example.org"] = -1e6
    resp = f.get("https://example.org/flaky")
    assert resp.status_code == 403
    assert calls["n"] == 3, "an ordinary 403 should exhaust its retries"


def test_denylist_covers_txcourts_subdomains():
    """CourtListener's pre-2015 Texas backfill serves every download_url from
    ``www.search.txcourts.gov``; a bare ``search.txcourts.gov`` anchor let all
    20/20 of them through, so a naive full-text fetcher would have walked into
    TAMES unblocked. The legitimate opinion-PDF host must stay reachable."""
    from lobbybook.core.fetch import DeniedURL, Fetcher

    f = Fetcher()
    for url in (
        "http://www.search.txcourts.gov/RetrieveDocument.aspx?DocId=14428&Index=x",
        "https://search.txcourts.gov/Case.aspx?cn=23-0679",
        "https://www.research.txcourts.gov/anything",
        "https://research.txcourts.gov/anything",
    ):
        with pytest.raises(DeniedURL):
            f.get(url)
    f._check_denylist("https://www.txcourts.gov/media/1461283/230679c.pdf")
