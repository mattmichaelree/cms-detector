"""Offline tests for the Texas Attorney General connector.

Every assertion below is a real value read out of a fixture captured live from
texasattorneygeneral.gov (and its legacy www2 host) on 2026-08-26: the actual
1939 Gerald Mann ledger row, actual KP- numbers with their publication dates,
an actual pending request with its named requestor, the actual request
cross-reference printed inside an actual opinion PDF, and actual entries from
the overruled/modified/affirmed/withdrawn list.
"""

from __future__ import annotations

import pytest

from lobbybook.sources.ag import (
    AGConnector,
    apply_supersession,
    classify_by_what,
    extract_opinion_pdf,
    extract_statute_cites,
    iso_date,
    normalize_status,
    numbers_below,
    parse_administrations,
    parse_browse_options,
    parse_recent_opinions,
    parse_recent_requests,
    parse_request_page,
    parse_supersession,
    parse_supersession_disclaimer,
    request_url,
    store_opinion,
)


def _fx(fixtures, name: str) -> bytes:
    return (fixtures / "ag" / name).read_bytes()


# ------------------------------------------------------- the numbering ledger


def test_opinion_ledger_reaches_the_1939_o_series(fixtures):
    """The index is a numbering ledger, and its last row is the corpus floor:
    Gerald Mann, 1939-43, O-0001 through O-5740."""
    admins = parse_administrations(_fx(fixtures, "opinions_index.html"), "opinion")
    assert len(admins) == 16
    mann = admins[-1]
    assert mann["ag_name"] == "Gerald Mann"
    assert mann["years_raw"] == "1939 - 1943"
    assert (mann["year_start"], mann["year_end"]) == (1939, 1943)
    assert mann["range_raw"] == "O-0001 - O-5740"
    assert (mann["first_number"], mann["last_number"]) == ("O-0001", "O-5740")
    assert mann["prefix"] == "O"
    assert mann["count_est"] == 5740
    assert mann["url"] == "https://www.texasattorneygeneral.gov/opinions/gerald-mann"
    # The O- series spans two administrations: Sellers picks it up mid-run.
    sellers = admins[-2]
    assert (sellers["ag_name"], sellers["range_raw"]) == ("Grover Sellers", "O-5741 - O-7543")


def test_sitting_ag_leaves_the_range_open_and_provisionals_are_flagged(fixtures):
    admins = parse_administrations(_fx(fixtures, "opinions_index.html"), "opinion")
    by_slug = {a["slug"]: a for a in admins}
    paxton = by_slug["ken-paxton"]
    assert paxton["years_raw"] == "2015 - Present"
    assert paxton["year_end"] is None          # a sitting AG's range still grows
    assert paxton["last_number"] == "KP-0526"
    # Two provisional AGs held the office in 2023 and issued their own series.
    assert by_slug["angela-colmenero"]["provisional"] == 1
    assert by_slug["angela-colmenero"]["range_raw"] == "AC-0001 - AC-0005"
    assert by_slug["john-scott"]["range_raw"] == "JS-0001 - JS-0007"
    assert by_slug["greg-abbott"]["provisional"] == 0


def test_ga_opinion_numbers_are_scoped_to_the_ag_role(fixtures):
    """`GA-0001 - GA-1096` here is Abbott *as AG* (2002-14). The governor
    connector's `GA-##` executive orders are the same man in the other role —
    the ledger's date span is what tells the two apart."""
    admins = parse_administrations(_fx(fixtures, "opinions_index.html"), "opinion")
    abbott = next(a for a in admins if a["slug"] == "greg-abbott")
    assert (abbott["year_start"], abbott["year_end"]) == (2002, 2014)
    assert abbott["prefix"] == "GA" and abbott["count_est"] == 1096


def test_request_ledger_stops_at_1998(fixtures):
    """Opinions reach 1939; requests only reach 1998 — the audit's coverage
    asymmetry, visible in the ledger itself."""
    admins = parse_administrations(_fx(fixtures, "requests_index.html"), "request")
    assert len(admins) == 5
    assert admins[0]["last_number"] == "RQ-0653-KP"
    assert admins[0]["prefix"] == "KP"
    oldest = admins[-1]
    assert oldest["ag_name"] == "John Cornyn"
    assert oldest["year_start"] == 1998
    assert oldest["range_raw"] == "RQ-0001-JC - RQ-0632-JC"
    assert min(a["year_start"] for a in admins) == 1998


# ------------------------------------------------------------- index feeds


def test_recent_opinions_carry_number_date_summary_and_pdf(fixtures):
    ops = parse_recent_opinions(_fx(fixtures, "opinions_index.html"))
    assert [o["number"] for o in ops] == ["KP-0526", "KP-0525", "KP-0524"]
    assert [o["date"] for o in ops] == ["2026-08-26", "2026-08-26", "2026-08-20"]
    assert ops[0]["summary"].startswith(
        "Considering whether a deputy constable assigned as a School Resource Officer")
    assert ops[0]["pdf_url"] == (
        "https://www.texasattorneygeneral.gov/sites/default/files/"
        "opinion-files/opinion/2026/kp-0526.pdf")
    assert ops[2]["url"] == "https://www.texasattorneygeneral.gov/opinions/ken-paxton/kp-0524"


def test_recent_requests_are_dated_from_the_time_element(fixtures):
    rqs = parse_recent_requests(_fx(fixtures, "requests_index.html"))
    assert [r["number"] for r in rqs] == ["RQ-0653-KP", "RQ-0652-KP", "RQ-0651-KP"]
    assert [r["date"] for r in rqs] == ["2026-08-12", "2026-08-11", "2026-08-04"]
    assert rqs[0]["date_raw"] == "2026-08-12T12:00:00Z"
    assert rqs[1]["summary"].startswith("Whether a municipality violates Section 54.202(b)")
    # The index names no requestor — that is one page deeper.
    assert "requestor" not in rqs[0]


def test_iso_date_handles_both_published_date_forms():
    assert iso_date("August 26, 2026") == "2026-08-26"
    assert iso_date("Aug 4, 2026") == "2026-08-04"
    assert iso_date("2026-08-12T12:00:00Z") == "2026-08-12"
    assert iso_date(None) is None and iso_date("no date here") is None


# ------------------------------------------------- pending request detail


def test_pending_request_names_its_requestor_before_any_answer_exists(fixtures):
    """RQ-0651-KP: a Reeves County Auditor purchasing dispute, published with
    the requestor named and no opinion yet — the forward-looking window the
    audit values this feed for."""
    rec = parse_request_page(_fx(fixtures, "request_rq_0651_kp.html"))
    assert rec["number"] == "RQ-0651-KP"
    assert rec["date"] == "2026-08-04"
    assert rec["status"] == "Pending"
    assert rec["requestor"] == "Reeves County Auditor"
    assert rec["requestor_location"] == "Pecos, Texas"
    assert rec["requestor_raw"] == "Reeves County Auditor, Pecos, Texas"
    assert rec["summary"] == (
        "Whether a county may pay an invoice for a purchase made without the "
        "authorization of the county purchasing agent")
    assert rec["pdf_url"].endswith("/request-files/request/2026/RQ0651KP.pdf")
    # The page states the absence explicitly; no answer is asserted.
    assert rec["answered_by"] is None


def test_detail_urls_are_a_pure_function_of_the_number():
    assert request_url("RQ-0650-KP") == (
        "https://www.texasattorneygeneral.gov/requests/ken-paxton/rq-0650-kp")
    assert request_url("RQ-0007-AC", "angela-colmenero").endswith(
        "/requests/angela-colmenero/rq-0007-ac")


def test_poller_walks_below_the_numbers_the_index_already_dated():
    """The index dates its three newest; the detail budget goes to the ones
    below them, which is where new information actually is."""
    seen = {"RQ-0653-KP", "RQ-0652-KP", "RQ-0651-KP"}
    assert numbers_below("RQ-0653-KP", 3, skip=seen) == [
        "RQ-0650-KP", "RQ-0649-KP", "RQ-0648-KP"]
    assert numbers_below("RQ-0653-KP", 2) == ["RQ-0653-KP", "RQ-0652-KP"]
    assert numbers_below("KP-0524", 2) == []      # opinion numbers are not requests


def test_browse_page_enumerates_the_whole_request_series(fixtures):
    """The audit's 'renders empty without JS' index: the <option> list is
    plain HTML and carries every number in the administration."""
    opts = parse_browse_options(_fx(fixtures, "requests_ken_paxton.html"))
    assert len(opts) == 650
    assert opts[0] == {"number": "RQ-0651-KP", "node": "/node/286941"}
    assert opts[-1]["number"] == "RQ-0001-KP"
    # The browse page lags the index ledger (RQ-0653-KP live), which is why
    # the poller counts down from the ledger instead of reading this page.
    assert "RQ-0653-KP" not in {o["number"] for o in opts}


# ---------------------------------------------------------- the opinion PDF


def test_opinion_pdf_yields_the_explicit_request_cross_reference(fixtures):
    """KP-0524's Re: line ends '(RQ-0518-KP)' — the one printed join between
    the request corpus and the opinion corpus."""
    rec = extract_opinion_pdf(_fx(fixtures, "kp-0524.pdf"))
    assert rec["number"] == "KP-0524"
    assert rec["date"] == "2026-08-20"
    assert rec["request_number"] == "RQ-0518-KP"
    assert rec["pages"] == 8
    assert rec["text_recovered"] is True and rec["error"] is None
    # Question presented = the Re: line with its own number factored out.
    assert rec["question"] == (
        "Authority of a county commissioners court to adopt a policy prohibiting use of "
        "county-owned law enforcement vehicles in the performance of private security "
        "jobs outside the county")
    assert "(RQ-0518-KP)" in rec["re_line"] and "RQ-0518-KP" not in rec["question"]


def test_opinion_pdf_conclusion_comes_from_the_summary_block(fixtures):
    rec = extract_opinion_pdf(_fx(fixtures, "kp-0524.pdf"))
    assert rec["conclusion"].startswith(
        "To satisfy article III, subsection 52(a) of the Texas Constitution")
    assert rec["conclusion"].endswith(
        "questions of fact that cannot be resolved in an Attorney General opinion.")
    # The signature block is not part of the conclusion.
    assert "truly yours" not in rec["conclusion"] and "BRENT WEBSTER" not in rec["conclusion"]


def test_statute_citations_are_mined_from_prose_at_section_level(fixtures):
    rec = extract_opinion_pdf(_fx(fixtures, "kp-0524.pdf"))
    assert "Local Government Code §86.021" in rec["statutes"]   # from "§§ 86.021(d)"
    assert "Local Government Code §85.003" in rec["statutes"]
    assert "Government Code §311.021" in rec["statutes"]
    # Pincites collapse onto their section, so the edge lands on one node.
    assert "Local Government Code §86.021(d)" not in rec["statutes"]


def test_citation_parser_matches_the_platform_canonical_form():
    # Opinions print citations in small caps and wrap them across lines; the
    # output form is the register/courts connectors' node id, so all three
    # feeds land on the same statute.
    text = "vehicles. TEX.\nLOC. GOV’T CODE § 170.001(a). See also Texas Government Code section 552.201(b)."
    assert extract_statute_cites(text) == [
        "Local Government Code §170.001", "Government Code §552.201"]


# ----------------------------------------------------- the supersession list


def test_supersession_list_publishes_its_own_incompleteness(fixtures):
    """The most important sentence on the page: the office says the list "is
    not entirely complete". Everything downstream treats it as a signal."""
    disclaimer = parse_supersession_disclaimer(_fx(fixtures, "opinions_overruled.html"))
    assert "is not entirely complete" in disclaimer
    assert "recently enacted statute" in disclaimer


def test_supersession_rows_carry_the_status_and_what_did_it(fixtures):
    rows = parse_supersession(_fx(fixtures, "opinions_overruled.html"))
    assert len(rows) == 422
    by_num = {r["number"]: r for r in rows}

    kp = by_num["KP-0326"]
    assert (kp["year"], kp["status_raw"], kp["status"]) == ("2020", "Overruled by", "overruled")
    assert kp["by_what"] == (
        "HB 1118, 87th Leg., R.S. (2021) (amending Government Code section 2054.5191)")
    assert kp["by_kind"] == "bill"          # the bill, not the section it amended
    assert kp["ag_name"] == "Ken Paxton"

    ga = by_num["GA-0615"]
    assert ga["status"] == "overruled" and ga["by_kind"] == "case"
    assert ga["by_what"].startswith("Van Houten v. City of Fort Worth")
    assert "827 F.3d 530" in ga["by_what"]

    # A statutory supersession, and a withdrawal by a later amended opinion.
    assert by_num["KP-0093"]["by_what"] == "Tex. Gov’t Code § 2261.252(f)"
    assert by_num["KP-0093"]["by_kind"] == "statute"
    assert (by_num["DM-45"]["status"], by_num["DM-45"]["by_what"]) == ("withdrawn", "DM-45A (1991)")


def test_free_text_statuses_normalize_without_losing_the_original():
    assert normalize_status("Overruled to the extent inconsistent with") == "overruled"
    assert normalize_status("Superseded in part by statute") == "superseded"
    assert normalize_status("Withdrawn 1/14/08 Superseded by statute") == "withdrawn"
    assert normalize_status("Affirmed/clarified by") == "affirmed"
    assert normalize_status("Clarified by") == "modified"
    assert normalize_status("Statute on which opinion was based was repealed") == "superseded"
    assert classify_by_what("ORD-624 (1994)") == "opinion"
    assert classify_by_what("Tex. Loc. Gov't Code Ann § 212.004") == "statute"


# ------------------------------------------------------------- ingestion


class _Resp:
    def __init__(self, content, status=200):
        self.content = content
        self.headers = {}
        self.status_code = status

    def raise_for_status(self):
        return None


class _FixtureFetcher:
    def __init__(self, fixtures):
        self.dir = fixtures / "ag"
        self.requested: list[str] = []
        self.missing: set[str] = set()

    def get(self, url, **kwargs):
        self.requested.append(url)
        if url.endswith("/opinions"):
            name = "opinions_index.html"
        elif url.endswith("/requests"):
            name = "requests_index.html"
        elif url.endswith("/requests/ken-paxton"):
            name = "requests_ken_paxton.html"
        elif "/requests/ken-paxton/rq-" in url:
            number = url.rsplit("/", 1)[-1].split("-")[1]
            if number in self.missing:
                return _Resp(b"", 404)
            # Stand-in: every request page shares one shape, so the captured
            # RQ-0651-KP page serves for any number with its number swapped in.
            return _Resp((self.dir / "request_rq_0651_kp.html").read_bytes()
                         .replace(b"0651", number.encode()))
        elif "overruled" in url:
            name = "opinions_overruled.html"
        elif url.endswith(".pdf"):
            name = "kp-0524.pdf"
        else:  # pragma: no cover - a URL the connector should never request
            raise AssertionError(url)
        return _Resp((self.dir / name).read_bytes())


@pytest.fixture()
def offline_fetch(monkeypatch, fixtures):
    fake = _FixtureFetcher(fixtures)
    monkeypatch.setattr("lobbybook.sources.ag.fetcher", lambda: fake)
    return fake


def test_ingest_opinions_stores_the_ledger_and_the_newest_opinions(conn, offline_fetch):
    stats = AGConnector().ingest_opinions(conn)
    assert offline_fetch.requested == ["https://www.texasattorneygeneral.gov/opinions"]
    assert stats["administrations"] == 16 and stats["opinions"] == 3
    assert stats["oldest_series"] == "O-0001"
    # The page itself is a document before anything is parsed out of it.
    doc = conn.execute("SELECT * FROM document WHERE id='ag:index:opinions'").fetchone()
    assert doc["doc_type"] == "ag_opinion_index" and doc["authority"] == "B"
    mann = conn.execute(
        "SELECT * FROM ag_administration WHERE ledger='opinion' AND slug='gerald-mann'"
    ).fetchone()
    assert (mann["year_start"], mann["first_number"], mann["count_est"]) == (1939, "O-0001", 5740)
    op = conn.execute("SELECT * FROM ag_opinion WHERE number='KP-0524'").fetchone()
    assert op["date"] == "2026-08-20" and op["ag_code"] == "KP"
    assert op["status"] == "active"


def test_ingest_requests_opens_only_the_pages_the_index_does_not_date(conn, offline_fetch):
    stats = AGConnector().ingest_requests(conn, details=3)
    assert offline_fetch.requested == [
        "https://www.texasattorneygeneral.gov/requests",
        "https://www.texasattorneygeneral.gov/requests/ken-paxton/rq-0650-kp",
        "https://www.texasattorneygeneral.gov/requests/ken-paxton/rq-0649-kp",
        "https://www.texasattorneygeneral.gov/requests/ken-paxton/rq-0648-kp",
    ]
    assert stats["high_water"] == "RQ-0653-KP"
    assert stats["index_requests"] == 3 and stats["details_opened"] == 3
    assert stats["dated"] == 6          # three from the index, three from details
    rows = conn.execute(
        "SELECT number, date FROM ag_request WHERE date IS NOT NULL ORDER BY number DESC"
    ).fetchall()
    assert [r["number"] for r in rows][:3] == ["RQ-0653-KP", "RQ-0652-KP", "RQ-0651-KP"]
    detail = conn.execute(
        "SELECT * FROM ag_request_detail WHERE number='RQ-0650-KP'").fetchone()
    assert detail["status"] == "Pending"
    assert detail["requestor_office"] == "Reeves County Auditor"
    # Requestor offices have no stable ID (the audit's entity-resolution gap),
    # so the free-text office is the edge's source node.
    edge = conn.execute(
        "SELECT * FROM edge WHERE predicate='requested' AND dst_id='RQ-0650-KP'").fetchone()
    assert (edge["src_type"], edge["src_id"], edge["provenance"]) == (
        "organization_name", "Reeves County Auditor", "explicit")


def test_a_gap_in_the_numbering_is_recorded_not_retried(conn, offline_fetch):
    offline_fetch.missing = {"0649"}
    stats = AGConnector().ingest_requests(conn, details=3)
    assert (stats["details_opened"], stats["details_missing"]) == (2, 1)
    assert len(offline_fetch.requested) == 4          # the 404 costs one request, once
    assert conn.execute(
        "SELECT COUNT(*) c FROM ag_request WHERE number='RQ-0649-KP'").fetchone()["c"] == 0


def test_opinion_pdf_ingest_stores_bytes_then_writes_the_request_edge(conn, offline_fetch):
    rec = AGConnector().sample_opinion_pdf(
        conn,
        "https://www.texasattorneygeneral.gov/sites/default/files/"
        "opinion-files/opinion/2026/kp-0524.pdf")
    assert rec["number"] == "KP-0524" and rec["request_number"] == "RQ-0518-KP"
    ver = conn.execute(
        "SELECT * FROM document_version WHERE document_id='ag:opinion:KP-0524'").fetchone()
    assert ver["version_no"] == 1
    text = conn.execute("SELECT * FROM ag_opinion_text WHERE number='KP-0524'").fetchone()
    assert text["text_recovered"] == 1 and text["pages"] == 8
    assert text["question"].startswith("Authority of a county commissioners court")
    assert text["conclusion"].startswith("To satisfy article III")
    op = conn.execute("SELECT * FROM ag_opinion WHERE number='KP-0524'").fetchone()
    assert op["request_number"] == "RQ-0518-KP" and op["doc_id"] == "ag:opinion:KP-0524"
    # RQ -> answered_by -> opinion is explicit: the number is printed in the PDF.
    edge = conn.execute("SELECT * FROM edge WHERE predicate='answered_by'").fetchone()
    assert (edge["src_id"], edge["dst_id"], edge["provenance"]) == (
        "RQ-0518-KP", "KP-0524", "explicit")
    assert edge["source_doc"] == "ag:opinion:KP-0524"
    # The answered request becomes a known request even though the request
    # feed only reaches back three items.
    assert conn.execute(
        "SELECT COUNT(*) c FROM ag_request WHERE number='RQ-0518-KP'").fetchone()["c"] == 1
    # Statute citations are mined from prose, so they are derived, not explicit.
    cites = conn.execute(
        "SELECT * FROM edge WHERE predicate='interprets' AND src_id='KP-0524'").fetchall()
    assert {c["provenance"] for c in cites} == {"derived"}
    assert "Local Government Code §86.021" in {c["dst_id"] for c in cites}


# ------------------------------------------------------ the supersession differ


def test_supersession_run_flags_opinions_and_records_its_source(conn, offline_fetch):
    stats = AGConnector().ingest_supersession(conn)
    assert stats["entries"] == 422 and stats["new"] == 422 and stats["gone"] == 0
    assert "is not entirely complete" in stats["disclaimer"]

    op = conn.execute("SELECT * FROM ag_opinion WHERE number='KP-0326'").fetchone()
    assert op["status"] == "overruled"
    assert "Overruled by HB 1118, 87th Leg." in op["status_note"]
    # The note carries where the claim came from and how much it is worth.
    assert "opinions-overruled-modified-affirmed-withdrawn" in op["status_note"]
    assert "incomplete" in op["status_note"]

    row = conn.execute("SELECT * FROM ag_supersession WHERE number='KP-0326'").fetchone()
    assert row["status"] == "overruled" and row["by_kind"] == "bill"
    assert row["source_url"].startswith("https://www2.texasattorneygeneral.gov/")
    assert row["retrieved_at"] and row["doc_id"] == "ag:index:supersession"
    edge = conn.execute(
        "SELECT * FROM edge WHERE predicate='superseded_by' AND src_id='KP-0326'").fetchone()
    assert edge["dst_type"] == "bill" and edge["provenance"] == "explicit"


def test_an_opinion_absent_from_the_list_stays_active_not_verified_good_law(conn, offline_fetch):
    """The office's list is incomplete by its own statement, so absence from it
    proves nothing. KP-0524 (published six days before capture) has no entry:
    it must stay 'active' — meaning "no supersession signal recorded" — and
    must not acquire a status note implying anyone checked."""
    AGConnector().ingest_opinions(conn)
    AGConnector().ingest_supersession(conn)
    assert conn.execute(
        "SELECT COUNT(*) c FROM ag_supersession WHERE number='KP-0524'").fetchone()["c"] == 0
    op = conn.execute("SELECT * FROM ag_opinion WHERE number='KP-0524'").fetchone()
    assert op["status"] == "active"
    assert op["status_note"] is None
    # ...and the flagged neighbours in the same run are unaffected by it.
    assert conn.execute(
        "SELECT status FROM ag_opinion WHERE number='GA-0615'").fetchone()["status"] == "overruled"


def test_rereading_the_index_never_resets_a_recorded_status(conn, offline_fetch):
    """Status is owned by the differ. An index poll re-reads KP-0326's row and
    must not quietly restore an overruled opinion to good law."""
    AGConnector().ingest_supersession(conn)
    store_opinion(conn, {"number": "KP-0326", "date": "2020-06-01", "summary": "re-read"})
    op = conn.execute("SELECT * FROM ag_opinion WHERE number='KP-0326'").fetchone()
    assert op["status"] == "overruled" and op["summary"] == "re-read"


def test_the_differ_reports_both_directions_of_change(conn, offline_fetch, fixtures):
    from lobbybook.sources.ag import SUPERSESSION_URL

    AGConnector().ingest_supersession(conn)
    again = AGConnector().ingest_supersession(conn)
    assert (again["new"], again["gone"]) == (0, 0)
    assert conn.execute("SELECT COUNT(*) c FROM ag_supersession").fetchone()["c"] == 422

    # An entry vanishing is as newsworthy as one appearing: the office has
    # withdrawn a status claim LobbyBook would otherwise keep repeating. The
    # row is reported, never deleted — the last state it was seen in stays.
    rows = parse_supersession(_fx(fixtures, "opinions_overruled.html"))
    shrunk = [r for r in rows if r["number"] != "KP-0326"]
    diff = apply_supersession(conn, shrunk, SUPERSESSION_URL)
    assert diff["new"] == 0 and diff["gone"] == 1
    assert diff["gone_keys"] == ["KP-0326 Overruled by"]
    assert conn.execute(
        "SELECT COUNT(*) c FROM ag_supersession WHERE number='KP-0326'").fetchone()["c"] == 1

    # ...and a genuinely new entry is counted as new against what was stored.
    fresh = dict(rows[0], number="KP-0999", status_raw="Overruled by",
                 by_what="SB 1, 90th Leg., R.S. (2027)", by_kind="bill", status="overruled")
    diff2 = apply_supersession(conn, [*shrunk, fresh], SUPERSESSION_URL)
    # The withdrawn entry keeps being reported missing until the office puts
    # it back — a one-shot notice would let a stale claim go unnoticed.
    assert diff2["new"] == 1 and diff2["gone_keys"] == ["KP-0326 Overruled by"]
    assert conn.execute(
        "SELECT status FROM ag_opinion WHERE number='KP-0999'").fetchone()["status"] == "overruled"


def test_severity_wins_over_arrival_order(conn):
    """One opinion can carry several entries; a later 'Affirmed by' row must
    not downgrade a recorded overruling."""
    rows = [
        {"number": "H-0090", "year": "1975", "status_raw": "Overruled by",
         "status": "overruled", "by_what": "ORD-344 (1982)", "by_kind": "opinion",
         "ag_name": "John Hill"},
        {"number": "H-0090", "year": "1975", "status_raw": "Affirmed by",
         "status": "affirmed", "by_what": "JM-0100 (1983)", "by_kind": "opinion",
         "ag_name": "John Hill"},
    ]
    apply_supersession(conn, rows, "https://example.invalid/list")
    op = conn.execute("SELECT * FROM ag_opinion WHERE number='H-0090'").fetchone()
    assert op["status"] == "overruled"
    assert conn.execute(
        "SELECT COUNT(*) c FROM ag_supersession WHERE number='H-0090'").fetchone()["c"] == 2


def test_incremental_is_one_bounded_daily_pass(conn, offline_fetch):
    """The scheduler's entry point: both indexes, the newest opinion PDF, N
    request details, and the supersession diff — a request count knowable
    before the run starts."""
    stats = AGConnector().incremental(conn, details=2, pdfs=1)
    assert len(offline_fetch.requested) == 6      # 1 + 1 + (1 + 2) + 1
    assert stats["opinions"]["administrations"] == 16
    assert stats["requests"]["details_opened"] == 2
    assert stats["supersession"]["entries"] == 422
    assert stats["pdfs_parsed"] == ["KP-0524"]
    # The queue is keyed on the URL fetched, so the PDF is not pulled twice.
    assert conn.execute(
        "SELECT COUNT(*) c FROM document WHERE doc_type='ag_opinion_pdf'").fetchone()["c"] == 1


# ------------------------------------------------------------------- live


@pytest.mark.live
def test_smoke_live(conn):
    result = AGConnector().smoke(conn)
    assert result.ok, result.detail
    assert result.stats["administrations"] >= 10
    assert result.stats["oldest_series"].startswith("O-")
    assert result.stats["requests_dated"] >= 5
    mann = conn.execute(
        "SELECT * FROM ag_administration WHERE ledger='opinion' AND year_start=1939"
    ).fetchone()
    assert mann["ag_name"] == "Gerald Mann" and mann["prefix"] == "O"
    dated = conn.execute(
        "SELECT number, date FROM ag_request WHERE date IS NOT NULL").fetchall()
    assert all(r["date"].startswith("20") for r in dated)
    print(result.detail)
