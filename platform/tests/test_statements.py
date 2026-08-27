"""Offline assertions run against bytes captured live on 2026-08-26.

Real values throughout: real senate.texas.gov press-room and newsroom
listings, the real Lt. Governor newsroom, and the real house.texas.gov
District 87 page — the page the audit uses to demonstrate that a House
district URL silently becomes a different person's content on turnover.
"""

from __future__ import annotations

import pytest

from lobbybook.core.docstore import load_latest, store_document
from lobbybook.core.registry import get
from lobbybook.sources.statements import (
    StatementsConnector,
    house_member_name,
    parse_ltgov_listing,
    parse_senate_listing,
    senate_actor,
    statement_id,
    store_statement,
)


def _st(fixtures, name: str) -> bytes:
    return (fixtures / "statements" / name).read_bytes()


def _pressroom(fixtures):
    return parse_senate_listing(_st(fixtures, "senate_pressroom_d7.html"), district=7)


# ------------------------------------------------- Senate per-senator press room
def test_press_room_parses_the_full_archive_with_dates(fixtures):
    """Bettencourt's District 7 archive runs 2015 -> 2026; the audit's point is
    that the Senate keeps its history where the House does not."""
    items = _pressroom(fixtures)
    assert len(items) == 406
    assert all(s.title for s in items)
    assert sum(1 for s in items if s.published) == len(items)
    assert min(s.published for s in items) == "2015-01-21"
    assert max(s.published for s in items) == "2026-08-19"
    assert senate_actor(_st(fixtures, "senate_pressroom_d7.html")) == "Senator Paul Bettencourt"


def test_press_room_top_item_is_verbatim(fixtures):
    top = _pressroom(fixtures)[0]
    assert top.title == (
        "Harris Co. Commissioners’ Court Considers 2nd Largest Property Tax "
        "Increase in County History!"
    )
    assert top.published == "2026-08-19"
    assert top.native_id == "7-20260819a"
    assert top.url == "https://senate.texas.gov/press.php?id=7-20260819a&ref=1"
    assert top.office == "senate_d7" and top.actor_raw == "Senator Paul Bettencourt"


def test_compound_native_id_is_district_date_and_intraday_letter(fixtures):
    """'7-20250530a' is a real primary key the Senate hands us — district +
    date + intraday sequence. The House publishes nothing equivalent."""
    items = _pressroom(fixtures)
    same_day = [s for s in items if s.published == "2025-04-23"]
    assert len(same_day) > 1
    letters = sorted(s.native_id[-1] for s in same_day if s.native_id)
    assert letters == sorted(set(letters))  # the letter disambiguates, not collides
    assert all(s.native_id.startswith("7-2025") for s in same_day if s.native_id)


def test_pdf_releases_keep_the_same_compound_id(fixtures):
    """Older releases are PDFs with no id parameter, but the path still fully
    determines the compound ID (district + date + intraday letter), so a PDF
    release is keyed the same way an HTML one is."""
    pdfs = [s for s in _pressroom(fixtures) if s.kind == "pdf"]
    assert len(pdfs) > 100
    letter = next(s for s in pdfs if s.url.endswith("p20221221a.pdf"))
    assert letter.native_id == "7-20221221a"
    assert letter.title == "Senator Bettencourt's Letter to the Editor of the Houston Chronicle"
    assert letter.published == "2022-12-21"


def test_same_day_html_and_pdf_releases_do_not_collide(conn, fixtures):
    """A verified source-quality wart: District 7 published both
    press.php?id=7-20220302a (a Senate-floor release) and
    members/d07/press/en/p20220302a.pdf (a letter to the Lt. Governor) on
    2022-03-02. The intraday letter is unique per format, not per day, so the
    PDF namespace is suffixed — otherwise one real statement silently
    overwrites the other."""
    items = _pressroom(fixtures)
    same = [s for s in items if s.native_id == "7-20220302a"]
    assert {s.kind for s in same} == {"html", "pdf"}
    ids = {statement_id(s.office, s.native_id, s.url, s.kind) for s in same}
    assert ids == {"senate_d7:7-20220302a", "senate_d7:7-20220302a.pdf"}
    for s in items:
        store_statement(conn, s, None, captured="2026-08-26T21:00:00Z")
    assert conn.execute("SELECT COUNT(*) c FROM statement").fetchone()["c"] == len(items)


def test_items_without_a_native_id_fall_back_to_a_url_hash(fixtures):
    """Press-conference video entries carry no release ID; they still need a
    stable key rather than being dropped."""
    videos = [s for s in _pressroom(fixtures) if "videoplayer.php" in s.url]
    assert videos and all(s.native_id is None for s in videos)
    sid = statement_id(videos[0].office, None, videos[0].url)
    assert sid.startswith("senate_d7:") and len(sid) == len("senate_d7:") + 16
    assert sid == statement_id(videos[0].office, None, videos[0].url)  # deterministic


# ------------------------------------------------------- Senate general newsroom
def test_newsroom_listing_parses_with_bare_native_ids(fixtures):
    items = parse_senate_listing(_st(fixtures, "senate_newsroom.html"))
    assert len(items) == 115
    top = items[0]
    assert top.title == "WEEK IN REVIEW"
    assert top.published == "2025-09-04"
    assert top.native_id == "20250904a"  # no district prefix on chamber-wide items
    assert top.url == "https://senate.texas.gov/news.php?id=20250904a&lang=en"
    assert top.office == "senate" and top.actor_raw == "The Texas Senate"

    redistricting = next(s for s in items if s.native_id == "20250825a")
    assert redistricting.title == "Senate Sends New Congressional Map to Governor"


# ------------------------------------------------------------ Lt. Governor
def test_ltgov_wordpress_permalinks_and_dates(fixtures):
    items = parse_ltgov_listing(_st(fixtures, "ltgov_news.html"))
    assert len(items) == 10
    assert all(s.published and s.title and s.office == "lt_governor" for s in items)
    top = items[0]
    assert top.title == "Lt. Gov. Dan Patrick Releases 7 New 2026 Interim Charges to the Texas Senate"
    assert top.published == "2026-07-27"
    assert top.native_id == "post-8262"
    assert top.url == (
        "https://www.ltgov.texas.gov/2026/07/27/"
        "lt-gov-dan-patrick-releases-7-new-2026-interim-charges-to-the-texas-senate/"
    )
    # Joint statements are a real edge type in this family (co-signature graphs).
    joint = next(s for s in items if "Joint Statement" in s.title)
    assert "Speaker Dustin Burrows" in joint.title


# ---------------------------------------------------------------- storage
def test_statement_rows_carry_published_and_captured(conn, fixtures):
    items = _pressroom(fixtures)[:25]
    for s in items:
        store_statement(conn, s, None, captured="2026-08-26T21:00:00Z")
    rows = conn.execute("SELECT * FROM statement ORDER BY published DESC").fetchall()
    assert len(rows) == 25
    assert rows[0]["id"] == "senate_d7:7-20260819a"
    assert rows[0]["published"] == "2026-08-19"
    assert rows[0]["captured"] == "2026-08-26T21:00:00Z"
    assert rows[0]["actor_raw"] == "Senator Paul Bettencourt"
    # person_id is left for the spine to resolve; never guessed from a title.
    assert all(r["person_id"] is None for r in rows)


def test_recrawl_updates_content_but_never_rewrites_captured(conn, fixtures):
    """captured is a first-seen timestamp. If a re-crawl could move it, the
    turnover evidence this family exists to preserve would be worthless."""
    s = _pressroom(fixtures)[0]
    store_statement(conn, s, None, captured="2026-08-20T00:00:00Z")
    store_statement(conn, s, None, captured="2026-08-26T21:00:00Z")
    rows = conn.execute("SELECT * FROM statement").fetchall()
    assert len(rows) == 1
    assert rows[0]["captured"] == "2026-08-20T00:00:00Z"


# ------------------------------------------ the turnover-archival job (House)
def test_house_member_page_names_its_current_occupant(fixtures):
    """District 87's URL now serves Rep. Caroline Fairly; her predecessor
    Four Price is nowhere on it. Capturing the name is what makes a snapshot
    legible as *whose* page it was."""
    assert house_member_name(_st(fixtures, "house_member_87.html")) == "Fairly, Caroline"


def test_turnover_archival_turns_an_overwrite_into_version_history(conn, fixtures, monkeypatch):
    """The job's whole purpose: when the district URL is reassigned, the
    predecessor's page must survive as version 1 rather than vanish."""
    predecessor = b"<html><head><title>Official Home Page of the Texas House of " \
                  b"Representatives Website for Rep. Price, Four.</title></head><body>x</body></html>"
    successor = _st(fixtures, "house_member_87.html")

    pages = iter([predecessor, successor])

    class _Resp:
        status_code = 200
        headers: dict = {}

        def __init__(self, content):
            self.content = content

    class _Fetcher:
        def get(self, url, **kw):
            assert url == "https://house.texas.gov/members/87"
            return _Resp(next(pages))

    monkeypatch.setattr("lobbybook.sources.statements.fetcher", lambda: _Fetcher())
    c = StatementsConnector()

    before = c.archive_member_pages(conn, [87])
    assert before["snapshots"][0]["member"] == "Price, Four"
    assert before["snapshots"][0]["version_no"] == 1

    after = c.archive_member_pages(conn, [87])
    assert after["snapshots"][0]["member"] == "Fairly, Caroline"
    assert after["snapshots"][0]["version_no"] == 2
    assert after["changed"] == 1

    # Both versions of the same district URL are retrievable, and the latest
    # is the successor's page.
    versions = conn.execute(
        "SELECT version_no, sha256 FROM document_version WHERE document_id=? ORDER BY version_no",
        ("statements:house:district:87",),
    ).fetchall()
    assert [v["version_no"] for v in versions] == [1, 2]
    assert versions[0]["sha256"] != versions[1]["sha256"]
    assert load_latest(conn, "statements:house:district:87") == successor

    # The turnover is queryable: both occupancy edges survive.
    held = {
        r["dst_id"]
        for r in conn.execute(
            "SELECT dst_id FROM edge WHERE src_id='TX-house-87' AND predicate='currently_held_by'"
        )
    }
    assert held == {"Price, Four", "Fairly, Caroline"}
    snaps = conn.execute(
        "SELECT member_raw FROM member_page_snapshot WHERE district='87' ORDER BY captured"
    ).fetchall()
    assert {s["member_raw"] for s in snaps} == {"Price, Four", "Fairly, Caroline"}


def test_unchanged_member_page_is_not_stored_twice(conn, fixtures, monkeypatch):
    page = _st(fixtures, "house_member_87.html")

    class _Resp:
        status_code = 200
        headers: dict = {}
        content = page

    monkeypatch.setattr(
        "lobbybook.sources.statements.fetcher",
        lambda: type("F", (), {"get": lambda self, url, **kw: _Resp()})(),
    )
    c = StatementsConnector()
    c.archive_member_pages(conn, [87])
    second = c.archive_member_pages(conn, [87])
    assert second["changed"] == 0
    assert conn.execute(
        "SELECT COUNT(*) c FROM document_version WHERE document_id=?",
        ("statements:house:district:87",),
    ).fetchone()["c"] == 1


def test_listing_ingest_stores_the_artifact_before_parsing(conn, fixtures, monkeypatch):
    page = _st(fixtures, "senate_pressroom_d7.html")

    class _Resp:
        status_code = 200
        headers: dict = {}
        content = page

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "lobbybook.sources.statements.fetcher",
        lambda: type("F", (), {"get": lambda self, url, **kw: _Resp()})(),
    )
    stats = StatementsConnector().ingest_senate_pressroom(conn, 7)
    assert stats["statements"] == 406 and stats["with_dates"] == 406
    assert stats["actor"] == "Senator Paul Bettencourt"
    doc = conn.execute(
        "SELECT * FROM document WHERE id='statements:senate:pressroom:7'"
    ).fetchone()
    assert doc["authority"] == "C" and doc["doc_type"] == "pressroom_listing"
    assert conn.execute(
        "SELECT COUNT(*) c FROM statement WHERE doc_id=?", (doc["id"],)
    ).fetchone()["c"] == 406


def test_connector_is_registered_at_tier_one_daily():
    c = get("statements")
    assert (c.name, c.tier, c.cadence) == ("statements", 1, "daily")


def test_docstore_roundtrip_of_a_listing(conn, fixtures):
    """Sanity: the artifact we archive is the artifact we can re-parse later —
    the property the whole turnover strategy rests on."""
    raw = _st(fixtures, "ltgov_news.html")
    store_document(conn, doc_id="statements:ltgov:news", source_family="statements",
                   content=raw, url="https://www.ltgov.texas.gov/news/",
                   doc_type="newsroom_listing", authority="C")
    assert parse_ltgov_listing(load_latest(conn, "statements:ltgov:news")) == parse_ltgov_listing(raw)


# ------------------------------------------------------------------- live
@pytest.mark.live
def test_statements_live_smoke(conn):
    r = get("statements").smoke(conn)
    assert r.ok, r.detail
    assert r.stats["statements"] >= 5
    assert r.stats["dated"] >= 5
    assert r.stats["native_ids"] >= 5
