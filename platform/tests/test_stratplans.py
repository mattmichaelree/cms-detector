"""Agency strategic-plan connector tests.

Offline tests run against a real TEA plan PDF (a page excerpt of the live
2025-2029 file, text layer intact) and TEA's real plan-index page, and assert
*real* values: the actual mission and vision sentences, the actual strategic
priorities, the actual bill numbers and legislature sessions the agency cites.

The load-bearing test is :func:`test_filename_and_cover_vintage_disagree` —
the audit's version trap, proven on the real document rather than described.
Live tests are opt-in (LOBBYBOOK_LIVE=1) and bounded.
"""

from __future__ import annotations

import pytest

from lobbybook.sources import stratplans as sp
from lobbybook.sources.stratplans import SeedPlan, StratPlansConnector

TEA_URL = (
    "https://tea.texas.gov/about-tea/government-relations-and-legal/"
    "government-relations/lbb-strategic-plan-2024-final-2.pdf"
)
TEA_INDEX = "https://tea.texas.gov/about-tea/welcome-and-overview/tea-strategic-plan"
TEA_SEED = SeedPlan(
    agency="Texas Education Agency", agency_code="701", url=TEA_URL, verified="fetched"
)


def _load(fixtures, name: str) -> bytes:
    return (fixtures / "stratplans" / name).read_bytes()


@pytest.fixture()
def tea_pdf(fixtures) -> bytes:
    return _load(fixtures, "tea-strategic-plan-2025-2029-excerpt.pdf")


@pytest.fixture()
def tea_plan(tea_pdf) -> dict:
    return sp.parse_plan(tea_pdf, url=TEA_URL)


class _Resp:
    def __init__(self, content: bytes, status: int = 200, headers: dict | None = None):
        self.content = content
        self.status_code = status
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")


class _FixtureFetcher:
    def __init__(self, fixtures):
        self.dir = fixtures / "stratplans"
        self.requested: list[str] = []

    def head(self, url):
        self.requested.append(f"HEAD {url}")
        size = len((self.dir / "tea-strategic-plan-2025-2029-excerpt.pdf").read_bytes())
        return _Resp(b"", headers={"Content-Length": str(size)})

    def get(self, url, **kwargs):
        self.requested.append(url)
        name = (
            "tea-strategic-plan-2025-2029-excerpt.pdf"
            if url.endswith(".pdf")
            else "tea-strategic-plan-index.html"
        )
        return _Resp((self.dir / name).read_bytes())


@pytest.fixture()
def offline_fetch(monkeypatch, fixtures):
    fake = _FixtureFetcher(fixtures)
    monkeypatch.setattr("lobbybook.sources.stratplans.fetcher", lambda: fake)
    return fake


# ------------------------------------------- THE VERSION TRAP (the point)
def test_filename_and_cover_vintage_disagree(tea_plan):
    """The audit's finding, proven on the real file.

    The URL says ``lbb-strategic-plan-2024-final-2.pdf``. The cover page says
    ``FISCAL YEARS 2025 TO 2029 / Updated March 2025``. Anything that dedups on
    the filename gets the vintage wrong by a year and misses the revision
    entirely.
    """
    assert sp.filename_vintage(TEA_URL)["label"] == "2024"
    assert sp.filename_vintage(TEA_URL)["years"] == [2024]

    assert tea_plan["fy_range"] == "2025-2029"
    assert (tea_plan["fy_start"], tea_plan["fy_end"]) == (2025, 2029)
    assert tea_plan["cover_revision_raw"] == "Updated March 2025"
    assert tea_plan["cover_revision"] == "2025-03"
    # The base issue date is a third, separate number on the same cover.
    assert tea_plan["cover_date"] == "2024-06-01"

    assert tea_plan["filename_disagrees"] is True
    assert tea_plan["filename_vintage"] != tea_plan["fy_range"]


def test_dedup_key_is_the_cover_vintage_not_the_filename(tea_plan):
    key = sp.plan_key("701", "strategic_plan", tea_plan["fy_range"], tea_plan["cover_revision"])
    assert key == "701:strategic_plan:2025-2029:2025-03"
    # A later mid-cycle revision of the same FY range is a DIFFERENT plan...
    assert sp.plan_key("701", "strategic_plan", "2025-2029", "2026-01") != key
    # ...and the filename plays no part in identity at all.
    assert "2024" not in key.split(":")[2]


def test_filename_vintage_forms():
    assert sp.filename_vintage("https://x/2023-2027-tea-strategic-plan.pdf")["years"] == [
        2023, 2027,
    ]
    # Two-digit range end, and a plan whose agency label (2017-2021) does not
    # match its own filename either.
    assert sp.filename_vintage("https://x/2016-21-strategic-plan-signed.pdf") == {
        "label": "2016-2021",
        "years": [2016, 2021],
        "basename": "2016-21-strategic-plan-signed.pdf",
    }
    assert sp.filename_vintage("https://x/strategic-plan-final.pdf")["label"] is None


def test_cover_parsing_handles_other_phrasings():
    assert sp.parse_cover("Strategic Plan\nFiscal Years 2027 through 2031\nRevised: June 3, 2026") == {
        "fy_start": 2027,
        "fy_end": 2031,
        "fy_range": "2027-2031",
        "cover_revision": "2026-06-03",
        "cover_revision_raw": "Revised: June 3, 2026",
        "cover_date": None,
    }
    bare = sp.parse_cover("Strategic Plan\nFISCAL YEARS 2019 TO 2023")
    assert bare["fy_range"] == "2019-2023"
    assert bare["cover_revision"] is None


# -------------------------------------------------------- plan structure
def test_mission_and_vision_are_the_real_sentences(tea_plan):
    assert tea_plan["mission"] == (
        "The Texas Education Agency will improve outcomes for all public school students "
        "in the state by providing leadership, guidance, and support to school systems."
    )
    assert tea_plan["vision"] == (
        "Every child, prepared for success in college, a career, or the military."
    )
    # Page furniture must not leak into a field a citation would quote.
    assert "tea.texas.gov" not in tea_plan["vision"]


def test_goals_are_the_real_strategic_priorities(tea_plan):
    assert tea_plan["goals"] == [
        {"ordinal": 1, "title": "Recruit, Support and Retain Teacher and Principals"},
        {"ordinal": 2, "title": "Build a Foundation of Reading and Math"},
    ]


def test_toc_dot_leaders_are_stripped_and_body_headings_win():
    text = (
        "Table of Contents\n"
        "Strategic Priority 1: Recruit, Support, and Retain Teachers ................ 5-7\n"
        "Strategic Priority One: Recruit, Support and Retain Teacher and Principals\n"
        "Specific Action Items to Achieve Strategic Priority One\n"
        "Strategic Priority initiatives.\n"
    )
    goals = sp.parse_goals(text)
    assert goals == [
        {"ordinal": 1, "title": "Recruit, Support and Retain Teacher and Principals"}
    ]


def test_statewide_rubric_blocks_are_counted(tea_plan):
    """Each goal is justified against the five statewide objectives; the block
    heading is the structure marker."""
    assert tea_plan["statewide_objective_blocks"] >= 2
    assert sp.STATEWIDE_OBJECTIVES[0] == "Accountable to tax and fee payers"
    assert len(sp.STATEWIDE_OBJECTIVES) == 5


# -------------------------------------------------------- bill citations
def test_mined_bills_are_the_ones_tea_actually_cites(tea_plan):
    """The audit named HB 3 (86R), HB 1605/1416/1926 and SB 30 (88R). All of
    them, with their sessions, come out of the real text."""
    keys = {c["bill_key"] for c in tea_plan["citations"]}
    assert {"86R-HB3", "88R-HB1605", "88R-HB1416", "88R-HB1926", "88R-SB30"} <= keys
    # Plus the ones the audit did not enumerate.
    assert {"86R-HB3906", "87R-HB1525", "88R-HB3"} <= keys

    by_key = {c["bill_key"]: c for c in tea_plan["citations"]}
    assert by_key["88R-SB30"]["bill_type"] == "SB"
    assert by_key["88R-SB30"]["number"] == 30
    assert by_key["88R-SB30"]["session_id"] == "88R"
    assert by_key["88R-SB30"]["bill_id"] == "88R-SB30"
    assert "1.1 billion" in by_key["88R-SB30"]["context"]


def test_the_same_bill_number_is_two_different_bills(tea_plan):
    """TEA's plan cites HB 3 twice, under two legislatures: 86R's school
    finance act and 88R's school safety act. A session-less 'HB 3' edge would
    be wrong half the time, which is why the key carries the session."""
    by_key = {c["bill_key"]: c for c in tea_plan["citations"]}
    assert "86R-HB3" in by_key and "88R-HB3" in by_key
    assert "Teacher Incentive Allotment" in by_key["86R-HB3"]["context"]
    assert "School Safety" in by_key["88R-HB3"]["context"]


def test_unqualified_citation_stays_unresolved_when_the_plan_is_ambiguous(tea_plan):
    """A bare 'HB3' cannot be resolved here — the document qualifies HB 3 as
    both 86R and 88R — so it is kept as an unresolved citation rather than
    guessed at."""
    by_key = {c["bill_key"]: c for c in tea_plan["citations"]}
    assert "?-HB3" in by_key
    assert by_key["?-HB3"]["session_id"] is None
    assert by_key["?-HB3"]["bill_id"] is None
    assert by_key["?-HB3"]["session_source"] is None


def test_unqualified_citation_folds_in_when_the_document_is_unambiguous(tea_plan):
    """HB 3906 is qualified only as 86R anywhere in the plan, so its one bare
    mention folds into that key and is marked as document-level resolution."""
    by_key = {c["bill_key"]: c for c in tea_plan["citations"]}
    assert "?-HB3906" not in by_key
    assert by_key["86R-HB3906"]["mentions"] == 3
    assert by_key["86R-HB3906"]["session_source"] == "trailing"


def test_session_designator_forms():
    long_form = sp.mine_bill_citations(
        "House Bill 1605 (88th Regular Legislative Session) established a process"
    )
    assert long_form[0]["session_id"] == "88R"
    assert long_form[0]["session_source"] == "trailing"

    short_form = sp.mine_bill_citations("materials in HB 1605 (88-R) and school safety")
    assert short_form[0]["session_id"] == "88R"

    comma_form = sp.mine_bill_citations("The measure follows House Bill 1605, 88-R. Data Source:")
    assert comma_form[0]["session_id"] == "88R"

    called = sp.mine_bill_citations("Senate Bill 1 (88th Second Called Legislative Session)")
    assert called[0]["session_id"] == "882"

    leading = sp.mine_bill_citations(
        "In the 87th legislative session, the legislature allocated $51 million "
        "through House Bill 1525 for intensive educational supports"
    )
    assert leading[0]["session_id"] == "87R"
    assert leading[0]["session_source"] == "leading"

    bare = sp.mine_bill_citations("Investments described in HB3. Later work continues")
    assert bare[0]["session_id"] is None
    assert bare[0]["bill_type"] == "HB" and bare[0]["number"] == 3


def test_statute_citations_are_not_mistaken_for_bills():
    cites = sp.mine_bill_citations(
        "funded by the Legislature (TEC Sec. 29.0881.(a)) for students at risk (TEC §29.081)"
    )
    assert cites == []


# ------------------------------------------------------ index discovery
def test_discover_plan_urls_from_the_real_tea_index(fixtures):
    found = sp.discover_plan_urls(_load(fixtures, "tea-strategic-plan-index.html"), TEA_INDEX)
    urls = [c["url"] for c in found]
    assert TEA_URL in urls
    assert (
        "https://tea.texas.gov/about-tea/welcome-and-overview/2023-2027-tea-strategic-plan.pdf"
        in urls
    )
    assert len(found) == 5  # five retained cycles, 2017-2021 through 2025-2029

    labels = {c["label"] for c in found}
    assert "TEA Strategic Plan 2025-2029" in labels
    # The customer-service report on the same page is not a strategic plan.
    assert not any("customer-service" in u for u in urls)

    # Two of the five files carry a filename that disagrees with their label.
    mismatched = [
        c for c in found
        if c["label_fy_range"] and c["filename_vintage"] != c["label_fy_range"]
    ]
    assert {c["label_fy_range"] for c in mismatched} == {"2025-2029", "2017-2021"}


def test_seed_list_is_extensible_and_records_provenance():
    assert sp.SEED_PLANS[0].url == TEA_URL
    assert sp.SEED_PLANS[0].verified == "fetched"
    assert all(s.agency_code == "701" for s in sp.SEED_PLANS)
    assert all(s.doc_type == "strategic_plan" for s in sp.SEED_PLANS)
    assert sp.SEED_INDEXES == [("Texas Education Agency", "701", TEA_INDEX)]


# ------------------------------------------------------------ persistence
def test_ingest_plan_writes_plan_goals_bills_and_edges(conn, tea_pdf):
    stats = StratPlansConnector().ingest_plan(conn, TEA_SEED, content=tea_pdf)
    assert stats["plan_id"] == "701:strategic_plan:2025-2029:2025-03"

    plan = conn.execute("SELECT * FROM strategic_plan WHERE id=?", (stats["plan_id"],)).fetchone()
    assert plan["agency"] == "Texas Education Agency"
    assert (plan["fy_start"], plan["fy_end"]) == (2025, 2029)
    assert plan["cover_revision"] == "2025-03"
    assert plan["filename_vintage"] == "2024"
    assert plan["filename_disagrees"] == 1
    assert plan["vision"].startswith("Every child, prepared for success")
    assert plan["url"] == TEA_URL

    goals = [
        r["title"]
        for r in conn.execute(
            "SELECT title FROM strategic_plan_goal WHERE plan_id=? ORDER BY ordinal",
            (stats["plan_id"],),
        )
    ]
    assert goals == [
        "Recruit, Support and Retain Teacher and Principals",
        "Build a Foundation of Reading and Math",
    ]

    bills = {
        r["bill_key"]: r
        for r in conn.execute(
            "SELECT * FROM strategic_plan_bill WHERE plan_id=?", (stats["plan_id"],)
        )
    }
    assert {"86R-HB3", "88R-HB3", "88R-SB30", "88R-HB1605", "?-HB3"} <= set(bills)
    assert bills["88R-HB1605"]["session_id"] == "88R"
    assert bills["?-HB3"]["session_id"] is None

    # The agency's own citation is an explicit edge when the plan names the session.
    edges = {
        (e["predicate"], e["dst_type"], e["dst_id"], e["provenance"])
        for e in conn.execute("SELECT * FROM edge WHERE src_id=?", (stats["plan_id"],))
    }
    assert ("cites", "bill", "88R-SB30", "explicit") in edges
    assert ("cites", "bill", "88R-HB1605", "explicit") in edges
    # ...and only derived when the session came from a preceding sentence.
    assert ("cites", "bill", "87R-HB1525", "derived") in edges
    # An unresolvable bill number is recorded as such, not faked into a bill id.
    assert ("cites", "bill_number", "HB3", "explicit") in edges

    filed = conn.execute(
        "SELECT * FROM edge WHERE predicate='files' AND src_id='701'"
    ).fetchone()
    assert filed["dst_id"] == stats["plan_id"]
    assert filed["provenance"] == "explicit"


def test_plan_pdf_is_stored_before_it_is_parsed(conn, tea_pdf):
    StratPlansConnector().ingest_plan(conn, TEA_SEED, content=tea_pdf)
    doc = conn.execute(
        "SELECT * FROM document WHERE id LIKE 'stratplans:strategic_plan:701:%'"
    ).fetchone()
    assert doc["url"] == TEA_URL
    assert doc["doc_type"] == "strategic_plan"
    # Agency-authored self-assessment: B, not A.
    assert doc["authority"] == "B"
    assert conn.execute(
        "SELECT COUNT(*) c FROM document_version WHERE document_id=?", (doc["id"],)
    ).fetchone()["c"] == 1


def test_replaced_in_place_file_becomes_a_second_version_not_a_second_plan(conn, tea_pdf):
    """The audit's change-detection rule: the same URL re-served with different
    bytes is a new document *version*; the plan entity is keyed on the cover."""
    connector = StratPlansConnector()
    first = connector.ingest_plan(conn, TEA_SEED, content=tea_pdf)
    assert first["changed"] is True
    again = connector.ingest_plan(conn, TEA_SEED, content=tea_pdf)
    assert again["changed"] is False
    assert again["plan_id"] == first["plan_id"]
    assert conn.execute("SELECT COUNT(*) c FROM strategic_plan").fetchone()["c"] == 1


def test_failed_fetch_is_recorded_as_coverage_not_dropped(conn, monkeypatch):
    """The audit hit HTTP 402 on a posted LAR and 404 on a guessed URL. Those
    are facts about the source, so they are stored."""

    class _Stub:
        def head(self, url):
            return _Resp(b"", status=402, headers={})

    monkeypatch.setattr("lobbybook.sources.stratplans.fetcher", lambda: _Stub())
    seed = SeedPlan(agency="Office of the Attorney General", agency_code="302",
                    url="https://example.texas.gov/lar.pdf", doc_type="lar")
    out = StratPlansConnector().ingest_plan(conn, seed)
    assert out["skipped"] == "HEAD 402"
    row = conn.execute(
        "SELECT * FROM strategic_plan_seed WHERE url=?", (seed.url,)
    ).fetchone()
    assert row["status"] == 402
    assert row["plan_id"] is None
    assert row["agency_code"] == "302"


def test_oversized_plan_is_refused_before_download(conn, monkeypatch):
    class _Stub:
        def head(self, url):
            return _Resp(b"", headers={"Content-Length": str(sp.MAX_DOWNLOAD + 1)})

        def get(self, url, **kwargs):
            raise AssertionError("must not download past the cap")

    monkeypatch.setattr("lobbybook.sources.stratplans.fetcher", lambda: _Stub())
    out = StratPlansConnector().ingest_plan(conn, TEA_SEED)
    assert out["skipped"] == "too_large"


def test_discover_records_new_seeds(conn, offline_fetch):
    stats = StratPlansConnector().discover(conn, *sp.SEED_INDEXES[0])
    assert len(stats["found"]) == 5
    assert stats["new"] == []  # all five are already curated seeds
    rows = conn.execute(
        "SELECT COUNT(*) c FROM strategic_plan_seed WHERE note='discovered'"
    ).fetchone()
    assert rows["c"] == 5
    doc = conn.execute("SELECT * FROM document WHERE id='stratplans:index:701'").fetchone()
    assert doc["doc_type"] == "strategic_plan_index"


def test_offline_smoke_path(conn, offline_fetch):
    result = StratPlansConnector().smoke(conn)
    assert result.ok, result.detail
    assert result.stats["fy_range"] == "2025-2029"
    assert result.stats["filename_vintage"] == "2024"
    assert "88R-SB30" in result.stats["qualified"]
    assert len(offline_fetch.requested) == 3


def test_connector_registration():
    from lobbybook.core import registry

    assert "stratplans" in registry.names()
    connector = registry.get("stratplans")
    assert (connector.tier, connector.cadence) == (2, "biennial")


# ------------------------------------------------------------ live tests
# Live budget for this file: 3 requests, all inside smoke().
@pytest.mark.live
def test_live_smoke(conn):
    """3 live requests: TEA's index page, a HEAD, and the 5.8MB plan itself.

    Everything the offline tests assert against the page excerpt is re-asserted
    here against the whole 171-page live document, so a fixture that drifts out
    of date is caught rather than quietly believed.
    """
    result = StratPlansConnector().smoke(conn)
    assert result.ok, result.detail
    assert result.stats["plan_id"] == "701:strategic_plan:2025-2029:2025-03"
    assert result.stats["fy_range"] == "2025-2029"
    assert result.stats["cover_revision"] == "2025-03"
    assert result.stats["filename_vintage"] == "2024"
    assert {"86R-HB3", "88R-HB1605", "88R-SB30"} <= set(result.stats["qualified"])
    # The full plan carries four strategic priorities; the excerpt has two.
    assert result.stats["goals"] >= 4
    # TEA really does publish a crawlable plan index (the LBB portal does not).
    assert any(u.endswith("lbb-strategic-plan-2024-final-2.pdf") for u in result.stats["index_urls"])

    plan = conn.execute(
        "SELECT * FROM strategic_plan WHERE id=?", (result.stats["plan_id"],)
    ).fetchone()
    assert plan["pages"] > 100
    assert plan["filename_disagrees"] == 1
    assert plan["mission"].startswith("The Texas Education Agency will improve outcomes")
