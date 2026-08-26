"""Offline tests for the Texas Governor connector.

Every assertion below is a real value read out of a fixture captured live from
gov.texas.gov in August 2026 — actual appointee names, actual board names,
actual dated proclamation titles, and the actual text-extraction outcome for
the sampled EO PDF.
"""

from __future__ import annotations

from datetime import date

import pytest

from lobbybook.sources.governor import (
    GANumberCollision,
    GovernorConnector,
    action_id,
    ag_opinion_id,
    classify_action,
    eo_id,
    extract_pdf_text,
    infer_year,
    next_page_url,
    normalize_eo_number,
    parse_appointment_post,
    parse_appointment_title,
    parse_eo_pdf_text,
    parse_listing,
    parse_post,
    split_names,
    store_appointment,
)

# The day the fixtures were captured; listing cards carry no year, so every
# offline parse is pinned to this reference instead of "today".
CAPTURED = date(2026, 8, 26)


def _fx(fixtures, name: str) -> bytes:
    return (fixtures / "governor" / name).read_bytes()


# ------------------------------------------------------------- listing pages


def test_appointment_listing_items_are_dated(fixtures):
    items = parse_listing(_fx(fixtures, "appointment_category.html"), "appointment", CAPTURED)
    assert len(items) == 8
    assert items[0]["title"] == "Governor Abbott Appoints Bodnar To Private Sector Advisory Council"
    assert items[0]["date"] == "2026-08-26"
    assert items[0]["url"] == (
        "https://gov.texas.gov/news/post/"
        "governor-abbott-appoints-bodnar-to-private-sector-advisory-council"
    )
    # Feed cadence: 8 announcements spanning three calendar days.
    assert {i["date"] for i in items} == {"2026-08-26", "2026-08-25", "2026-08-24"}


def test_listing_year_is_inferred_because_cards_print_none(fixtures):
    """Cards render only 'Aug 26'. A card cannot postdate the poll, so a month
    ahead of the reference month belongs to the previous year."""
    assert infer_year("Aug", 26, CAPTURED) == 2026
    assert infer_year("Jun", 16, CAPTURED) == 2026
    assert infer_year("Dec", 31, CAPTURED) == 2025
    assert infer_year("Aug", 27, CAPTURED) == 2025


def test_listing_exposes_offset_pagination(fixtures):
    # The only way deeper than the 8-item first page; RSS is a 10-item window.
    assert next_page_url(_fx(fixtures, "appointment_category.html")) == (
        "https://gov.texas.gov/news/category/appointment/P8"
    )


def test_proclamation_listing_titles_and_dates(fixtures):
    items = parse_listing(_fx(fixtures, "proclamation_category.html"), "proclamation", CAPTURED)
    titled = {i["title"]: i["date"] for i in items}
    assert titled["Governor Abbott Issues Severe Storm Disaster Proclamation In June 2026"] == "2026-06-15"
    assert titled["Governor Abbott Renews Border Security Disaster Proclamation In June 2026"] == "2026-06-16"
    assert titled["Governor Abbott Issues New World Screwworm Disaster Proclamation In June 2026"] == "2026-06-05"
    # The renewal-chain trap: two same-subject screwworm proclamations, May and
    # June, under near-identical titles — chained, never collapsed.
    screwworm = sorted(i["date"] for i in items if "Screwworm" in i["title"])
    assert screwworm == ["2026-05-29", "2026-06-05"]


# ---------------------------------------------------------- title extraction


def test_title_gives_surname_and_board_only(fixtures):
    items = parse_listing(_fx(fixtures, "appointment_category.html"), "appointment", CAPTURED)
    rec = parse_appointment_title(items[2]["title"])
    assert rec["surnames"] == ["Nielsen"]
    assert rec["board"] == "Texas State Board Of Examiners Of Marriage And Family Therapists"
    assert rec["action"] == "appointed"
    assert rec["generic"] is False


def test_title_handles_two_appointees_and_the_as_position_form(fixtures):
    items = parse_listing(_fx(fixtures, "appointment_category_p8.html"), "appointment", CAPTURED)
    by_title = {i["title"]: i for i in items}
    two = parse_appointment_title(
        "Governor Abbott Appoints Hayes, Yelovich To Texas State Board Of Plumbing Examiners"
    )
    assert two["surnames"] == ["Hayes", "Yelovich"]
    assert two["board"] == "Texas State Board Of Plumbing Examiners"

    # "As <office>" is a position, not a board.
    pos = parse_appointment_title(
        "Governor Abbott Appoints Erickson As Director Of Regulatory Compliance Division"
    )
    assert pos["board"] is None
    assert pos["position"] == "Director Of Regulatory Compliance Division"

    # The generic slate title carries no names at all — the body must be read.
    slate = by_title["Governor Abbott Announces Latest Slate Of Appointments"]
    assert parse_appointment_title(slate["title"])["generic"] is True


def test_counted_title_is_generic_not_a_person_named_three():
    rec = parse_appointment_title(
        "Governor Abbott Reappoints Three To Small Business Assistance Advisory Task Force"
    )
    assert rec["generic"] is True
    assert rec["surnames"] == []
    assert rec["board"] == "Small Business Assistance Advisory Task Force"


def test_title_with_two_verbs_and_a_role_word():
    """Real slug observed inside appointment_post_slate.html:
    governor-abbott-names-williams-chair-appoints-lewis-cardenas-to-...."""
    rec = parse_appointment_title(
        "Governor Abbott Names Williams Chair, Appoints Lewis, Cardenas To "
        "Texas State Affordable Housing Corporation Board Of Directors"
    )
    assert rec["surnames"] == ["Williams", "Lewis", "Cardenas"]
    assert rec["board"] == "Texas State Affordable Housing Corporation Board Of Directors"


# -------------------------------------------------------- post-body parsing


def test_single_appointee_post_yields_full_name_and_board(fixtures):
    post = parse_post(_fx(fixtures, "appointment_post_nielsen.html"))
    assert post["date"] == "2026-08-25"
    assert post["categories"] == ["press-release", "appointment"]
    recs = parse_appointment_post(post)
    assert len(recs) == 1
    assert recs[0]["appointee"] == "Misti Nielsen"          # title said only "Nielsen"
    assert recs[0]["board"] == "Texas State Board of Examiners of Marriage and Family Therapists"
    assert recs[0]["action"] == "appointed"
    assert recs[0]["announced"] == "2026-08-25"


def test_slate_post_yields_every_appointee_across_every_board(fixtures):
    """One post, nine boards, twenty people — the reason title-only parsing
    cannot build the roster."""
    post = parse_post(_fx(fixtures, "appointment_post_slate.html"))
    assert post["date"] == "2026-01-09"
    recs = parse_appointment_post(post)
    names = [r["appointee"] for r in recs]
    assert len(recs) == 20
    assert len(set(names)) == 20

    boards = {r["appointee"]: (r["board"] or r["position"]) for r in recs}
    assert boards["Nelda Barrera"] == "Texas Agriculture Finance Authority"
    assert boards["Tommy Henderson"] == "Texas Agriculture Finance Authority"
    assert boards["Kenny Marchant"] == "Texas Department of Housing and Community Affairs"
    assert boards["Jason LaFond"] == "Texas Pharmaceutical Initiative Governing Board"
    # An office, not a board: stored as a position.
    assert boards["Amanda Crawford"] == "Commissioner of Insurance"
    assert next(r for r in recs if r["appointee"] == "Amanda Crawford")["board"] is None

    actions = {r["appointee"]: r["action"] for r in recs}
    assert actions["Eduardo Contreras"] == "reappointed"
    assert actions["Colt McCoy"] == "appointed"
    assert actions["Lemuel Williams, Jr."] == "named"


def test_slate_post_catches_the_second_verb_in_one_sentence(fixtures):
    """'appointed Darryl Heath and Colt McCoy and reappointed Ashlie Thomas' —
    stopping at the first verb silently drops the reappointee."""
    recs = parse_appointment_post(parse_post(_fx(fixtures, "appointment_post_slate.html")))
    thecb = {r["appointee"]: r["action"] for r in recs
             if r["board"] == "Texas Higher Education Coordinating Board"}
    assert thecb == {"Darryl Heath": "appointed", "Colt McCoy": "appointed",
                     "Ashlie Thomas": "reappointed"}


def test_slate_post_keeps_honorifics_out_and_suffixes_in(fixtures):
    recs = parse_appointment_post(parse_post(_fx(fixtures, "appointment_post_slate.html")))
    names = {r["appointee"] for r in recs}
    # Body reads "appointed Col. Omar A. Perea for a term..."
    assert "Omar A. Perea" in names
    # Body reads "named Lemuel Williams, Jr. as chair" — the comma is a suffix,
    # not a second person.
    assert "Lemuel Williams, Jr." in names
    assert "Jr." not in names


def test_split_names_distinguishes_separators_from_suffixes():
    assert split_names("Nelda Barrera, Colby McClendon, and Scott Frazier") == [
        "Nelda Barrera", "Colby McClendon", "Scott Frazier"]
    assert split_names("Kenny Marchant and Ajay Thomas") == ["Kenny Marchant", "Ajay Thomas"]
    assert split_names("Lemuel Williams, Jr.") == ["Lemuel Williams, Jr."]


# ------------------------------------------- executive actions & id scoping


def test_proclamations_classify_and_get_minted_role_scoped_ids(fixtures):
    items = parse_listing(_fx(fixtures, "proclamation_category.html"), "proclamation", CAPTURED)
    acts = [classify_action(i) for i in items]
    assert all(a and a["kind"] == "proclamation" for a in acts)
    # No native identifier exists, so the key is minted from date + slug.
    storm = next(a for a in acts if a["title"].startswith("Governor Abbott Issues Severe Storm"))
    assert action_id("proclamation", "abbott", storm) == (
        "PROC:abbott:2026-06-15:"
        "governor-abbott-issues-severe-storm-disaster-proclamation-in-june-2026"
    )
    assert storm["number"] is None


def test_eo_detected_from_an_attached_pdf_even_when_the_title_is_silent():
    """EOs post as ordinary press releases; the only tell can be the upload."""
    item = {"url": "https://gov.texas.gov/news/post/governor-abbott-issues-order",
            "title": "Governor Abbott Takes Action To Secure The Border",
            "date": "2022-07-07", "category": "press-release"}
    assert classify_action(item) is None
    act = classify_action(item, ("https://gov.texas.gov/uploads/files/press/EO-GA-41.pdf",))
    assert act["kind"] == "eo"
    assert act["number"] == "GA-41"
    assert action_id("eo", "abbott", act) == "EO:abbott:GA-41"


def test_special_session_call_is_its_own_kind():
    item = {"url": "https://gov.texas.gov/news/post/x", "date": "2025-07-09",
            "title": "Governor Abbott Issues Proclamation Convening Special Session",
            "category": "press-release"}
    assert classify_action(item)["kind"] == "special_session_call"
    assert action_id("special_session_call", "abbott", classify_action(item)).startswith("SSC:abbott:")


def test_ga_number_collision_guard():
    """GA-#### is an Abbott *AG opinion* (2002-14); GA-## is an Abbott
    *executive order* (2015+). A bare number is ambiguous across the two roles,
    so ids are role-scoped and AG-shaped numbers are refused outright."""
    assert eo_id("abbott", "GA-41") == "EO:abbott:GA-41"
    assert eo_id("abbott", "ga41") == "EO:abbott:GA-41"
    assert eo_id("abbott", 41) == "EO:abbott:GA-41"

    # The AG side of the collision lives in a different namespace entirely.
    assert ag_opinion_id("abbott", "GA-0041") == "AG:abbott:GA-0041"
    assert ag_opinion_id("abbott", "GA-0041") != eo_id("abbott", "GA-41")
    assert not eo_id("abbott", "GA-41").endswith("GA-0041")

    # An AG-opinion number can never be minted as an EO id.
    for ag in ("GA-0041", "GA-0001", "GA-1099", "0041"):
        with pytest.raises(GANumberCollision):
            eo_id("abbott", ag)
    with pytest.raises(GANumberCollision):
        normalize_eo_number("GA-0057")

    # And no id is ever a bare number.
    assert eo_id("abbott", "GA-57") == "EO:abbott:GA-57"
    assert eo_id("abbott", "GA-57") != "GA-57"


# ---------------------------------------------------------- the OCR lottery


def test_sampled_eo_pdf_records_what_extraction_actually_recovered(fixtures):
    """EO-GA-41 (July 7, 2022) is office-scanner output that happens to carry
    an *imperfect* OCR text layer — the audit's finding, asserted as measured
    fact rather than assumed. Sibling EOs of similar vintage carry none, which
    is why the flag exists at all."""
    info = extract_pdf_text(_fx(fixtures, "EO-GA-41.pdf"))
    assert info["error"] is None
    assert info["pages"] == 4
    assert info["text_recovered"] is True
    assert info["chars"] > 5000
    # Imperfect, not born-digital: the scanner's OCR glues words together
    # ("Secretary ofState", "Governor ofthe State ofTexas", "ofSit").
    assert info["ocr_artifacts"] >= 10
    assert "ofState" in info["text"]
    assert "Executive Order No. GA-41" in info["text"]


def test_empty_and_unreadable_pdfs_report_false_rather_than_raising():
    assert extract_pdf_text(b"not a pdf at all")["text_recovered"] is False
    assert extract_pdf_text(b"not a pdf at all")["error"] is not None


def test_eo_identity_mined_from_the_ocr_layer(fixtures):
    """Letter date and SOS filing stamp are extracted separately; the audit
    warns they need not agree (they do agree on this sample)."""
    text = extract_pdf_text(_fx(fixtures, "EO-GA-41.pdf"))["text"]
    ident = parse_eo_pdf_text(text)
    assert ident["number"] == "GA-41"
    assert ident["subject"] == "returning illegal immigrants to the border"
    assert ident["letter_date"] == "2022-07-07"
    # The stamp OCRs as "JUL 0 7 2022" beneath a mangled "SECRETPRYOF STATE".
    assert ident["sos_filed"] == "2022-07-07"


def test_eo_identity_ignores_body_prose_dates(fixtures):
    """A naive date scan lands on 'issued a disaster proclamation on May 31
    2021' in the body; the stamp must be anchored to the O'CLOCK line."""
    text = extract_pdf_text(_fx(fixtures, "EO-GA-41.pdf"))["text"]
    assert "May 31 2021" in text
    assert parse_eo_pdf_text(text)["sos_filed"] != "2021-05-31"


def test_no_text_layer_yields_no_guessed_identity():
    assert parse_eo_pdf_text("") == {
        "number": None, "subject": None, "letter_date": None, "sos_filed": None}


# ---------------------------------------------------------------- storage


def test_appointments_and_edges_land_in_the_graph(conn, fixtures):
    from lobbybook.core.docstore import store_document

    raw = _fx(fixtures, "appointment_post_slate.html")
    # Framework contract: the artifact lands in the docstore before parsing, so
    # every edge below can cite a stored document.
    store_document(conn, doc_id="governor:post:slate", source_family="governor",
                   content=raw, url="https://gov.texas.gov/news/post/slate",
                   doc_type="governor_post", authority="E")
    post = parse_post(raw)
    for rec in parse_appointment_post(post):
        store_appointment(conn, rec, "https://gov.texas.gov/news/post/slate", "governor:post:slate")
    conn.commit()

    assert conn.execute("SELECT COUNT(*) c FROM appointment").fetchone()["c"] == 20
    row = conn.execute(
        "SELECT * FROM appointment WHERE appointee_raw='Colt McCoy'"
    ).fetchone()
    assert row["board"] == "Texas Higher Education Coordinating Board"
    assert row["governor"] == "abbott"
    assert row["announced"] == "2026-01-09"

    appointed = conn.execute(
        "SELECT COUNT(*) c FROM edge WHERE src_id='abbott' AND predicate='appointed'"
    ).fetchone()["c"]
    assert appointed == 20
    serves = conn.execute(
        """SELECT dst_id FROM edge WHERE predicate='serves_on' AND src_id='Colt McCoy'"""
    ).fetchone()
    assert serves["dst_id"] == "Texas Higher Education Coordinating Board"
    prov = conn.execute("SELECT DISTINCT provenance FROM edge").fetchall()
    assert [p["provenance"] for p in prov] == ["explicit"]

    # An office-holder appointment keeps the office in `position`; `board` is
    # empty-string-normalised so the (appointee, board, announced) natural key
    # still dedups (NULL would compare distinct and duplicate on every poll).
    crawford = conn.execute(
        "SELECT * FROM appointment WHERE appointee_raw='Amanda Crawford'"
    ).fetchone()
    assert crawford["position"] == "Commissioner of Insurance"
    assert crawford["board"] == ""


def test_reingesting_the_same_post_is_idempotent(conn, fixtures):
    """Including the position-only row, whose NULL board would otherwise
    re-insert on every poll."""
    post = parse_post(_fx(fixtures, "appointment_post_slate.html"))
    for _ in range(2):
        for rec in parse_appointment_post(post):
            store_appointment(conn, rec, "https://gov.texas.gov/news/post/slate", None)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM appointment").fetchone()["c"] == 20


def test_connector_registers_with_its_ddl(conn):
    c = GovernorConnector()
    assert (c.name, c.tier, c.cadence) == ("governor", 1, "daily")
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'governor%'")}
    assert tables == {"governor_news_item", "governor_pdf_text"}


def test_pdf_text_row_records_the_lottery_outcome(conn, fixtures):
    from lobbybook.core.docstore import store_document
    from lobbybook.sources.governor import record_pdf_text

    content = _fx(fixtures, "EO-GA-41.pdf")
    url = "https://gov.texas.gov/uploads/files/press/EO-GA-41.pdf"
    store_document(conn, doc_id="governor:pdf:EO-GA-41.pdf", source_family="governor",
                   content=content, url=url, doc_type="governor_pdf", authority="B")
    record_pdf_text(conn, "governor:pdf:EO-GA-41.pdf", url, content)
    conn.commit()
    row = conn.execute("SELECT * FROM governor_pdf_text").fetchone()
    assert row["text_recovered"] == 1
    assert row["pages"] == 4
    assert row["ocr_artifacts"] >= 10
    assert row["error"] is None


def test_action_rows_carry_role_scoped_ids_and_provenance(conn, fixtures):
    from lobbybook.core.docstore import store_document
    from lobbybook.sources.governor import store_action

    raw = _fx(fixtures, "proclamation_category.html")
    store_document(conn, doc_id="governor:listing:proclamation", source_family="governor",
                   content=raw, url="https://gov.texas.gov/news/category/proclamation",
                   doc_type="governor_listing_proclamation", authority="E")
    items = parse_listing(raw, "proclamation", CAPTURED)
    ids = [store_action(conn, classify_action(i), "governor:listing:proclamation") for i in items]
    conn.commit()
    assert len(set(ids)) == 8
    assert all(i.startswith("PROC:abbott:") for i in ids)
    kinds = {r["kind"] for r in conn.execute("SELECT DISTINCT kind FROM executive_action")}
    assert kinds == {"proclamation"}
    edge = conn.execute(
        "SELECT * FROM edge WHERE predicate='issued' AND dst_type='executive_action' LIMIT 1"
    ).fetchone()
    assert edge["src_id"] == "abbott" and edge["provenance"] == "explicit"


def test_press_release_listing_carries_no_eo_in_the_sampled_window(fixtures):
    """Honest negative: across the 8 most recent press releases (Aug 25-26,
    2026) not one is an executive order. EO cadence is far below daily, which
    is exactly why a 10-item RSS window cannot be the discovery path."""
    items = parse_listing(_fx(fixtures, "press_release_category.html"), "press-release", CAPTURED)
    assert len(items) == 8
    assert [classify_action(i) for i in items] == [None] * 8


# ------------------------------------------------- end-to-end (fixture-backed)


class _FixtureFetcher:
    """Serves the captured fixtures in place of the network so the full
    ingest path — store, parse, upsert, edge — runs offline."""

    def __init__(self, fixtures):
        self.dir = fixtures / "governor"
        self.requested: list[str] = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        if url.endswith("/news/category/appointment"):
            name = "appointment_category.html"
        elif url.endswith("/news/category/proclamation"):
            name = "proclamation_category.html"
        elif url.endswith("/news/category/press-release"):
            name = "press_release_category.html"
        elif url.endswith("slate-of-appointments"):
            name = "appointment_post_slate.html"
        elif "/news/post/governor-abbott-appoints-" in url:
            # Stand-in: every single-appointee post shares this shape, so the
            # captured Nielsen post serves for any of them.
            name = "appointment_post_nielsen.html"
        elif url.endswith(".pdf"):
            name = "EO-GA-41.pdf"
        else:
            name = "proclamation_post_severe_storm.html"
        return _Resp((self.dir / name).read_bytes())


class _Resp:
    def __init__(self, content):
        self.content = content
        self.headers = {}
        self.status_code = 200

    def raise_for_status(self):
        return None


@pytest.fixture()
def offline_fetch(monkeypatch, fixtures):
    fake = _FixtureFetcher(fixtures)
    monkeypatch.setattr("lobbybook.sources.governor.fetcher", lambda: fake)
    return fake


def test_ingest_appointments_listing_only(conn, offline_fetch):
    """No post fetches: one listing GET, surname-level rows for all 8 items."""
    stats = GovernorConnector().ingest_appointments(
        conn, details=0, open_generic=False, ref=CAPTURED)
    assert offline_fetch.requested == ["https://gov.texas.gov/news/category/appointment"]
    assert stats == {"items": 8, "titles_parsed": 8, "posts_opened": 0, "appointments": 8}
    names = {r["appointee_raw"] for r in conn.execute("SELECT appointee_raw FROM appointment")}
    assert "Nielsen" in names and "Bramow" in names
    # The listing page itself is stored as a document, before any parsing.
    doc = conn.execute(
        "SELECT * FROM document WHERE id='governor:listing:appointment'").fetchone()
    assert doc["url"] == "https://gov.texas.gov/news/category/appointment"
    assert doc["doc_type"] == "governor_listing_appointment"
    assert conn.execute(
        "SELECT COUNT(*) c FROM governor_news_item").fetchone()["c"] == 8


def test_ingest_appointments_opens_one_post_for_full_names(conn, offline_fetch):
    stats = GovernorConnector().ingest_appointments(
        conn, details=1, open_generic=False, max_posts=3, ref=CAPTURED)
    assert stats["posts_opened"] == 1
    assert len(offline_fetch.requested) == 2
    # The opened post upgrades a listing surname to the real full name.
    names = {r["appointee_raw"] for r in conn.execute("SELECT appointee_raw FROM appointment")}
    assert "Misti Nielsen" in names
    assert sum(1 for n in names if " " in n) == 1
    # ...and the seven unopened items stay at surname level.
    assert "Bramow" in names


def test_max_posts_caps_the_live_request_count(conn, offline_fetch):
    GovernorConnector().ingest_appointments(
        conn, details=99, open_generic=True, max_posts=2, ref=CAPTURED)
    assert len(offline_fetch.requested) == 3   # 1 listing + 2 posts, never more


def test_ingest_actions_records_the_proclamation_feed(conn, offline_fetch):
    counts = GovernorConnector().ingest_actions(
        conn, categories=("proclamation",), ref=CAPTURED)
    assert counts == {"proclamation": 8}
    ids = [r["id"] for r in conn.execute("SELECT id FROM executive_action ORDER BY id")]
    assert all(i.startswith("PROC:abbott:") for i in ids)


def test_sample_pdf_stores_bytes_then_measures_extraction(conn, offline_fetch):
    info = GovernorConnector().sample_pdf(
        conn, "https://gov.texas.gov/uploads/files/press/EO-GA-41.pdf")
    assert info["text_recovered"] is True
    assert info["identity"]["number"] == "GA-41"
    assert info["action_id"] == "EO:abbott:GA-41"
    # Bytes are in the docstore, and the EO row cites that document.
    ver = conn.execute(
        "SELECT * FROM document_version WHERE document_id='governor:pdf:EO-GA-41.pdf'"
    ).fetchone()
    assert ver["version_no"] == 1
    act = conn.execute(
        "SELECT * FROM executive_action WHERE id='EO:abbott:GA-41'").fetchone()
    assert act["kind"] == "eo"
    assert act["number"] == "GA-41"
    assert act["date"] == "2022-07-07"
    assert act["doc_id"] == "governor:pdf:EO-GA-41.pdf"
    assert act["title"] == "returning illegal immigrants to the border"
    # governor -> issued -> EO, explicit, citing the signed PDF.
    edge = conn.execute(
        "SELECT * FROM edge WHERE dst_id='EO:abbott:GA-41'").fetchone()
    assert (edge["src_id"], edge["predicate"], edge["provenance"]) == (
        "abbott", "issued", "explicit")
    assert edge["source_doc"] == "governor:pdf:EO-GA-41.pdf"


# ------------------------------------------------------------------- live


@pytest.mark.live
def test_smoke_live(conn):
    result = GovernorConnector().smoke(conn)
    assert result.ok, result.detail
    assert result.stats["titles_parsed"] >= 5
    assert result.stats["appointments_total"] >= 5
    rows = conn.execute(
        "SELECT appointee_raw, board, position FROM appointment"
    ).fetchall()
    assert all(r["appointee_raw"] for r in rows)
    assert sum(1 for r in rows if r["board"] or r["position"]) >= 5
    print(result.detail)
