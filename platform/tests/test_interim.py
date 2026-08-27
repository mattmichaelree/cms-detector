"""Interim charges / interim reports connector tests.

Offline tests assert *real* values from the real documents: the actual
committee names in Speaker Burrows' March 2026 charge list, the actual text of
specific charges, the actual bill numbers named inside monitoring charges
(HB 43 for Agriculture, SB 1080 + SB 2405 for Corrections), and the actual
shape of the House interim-report archive back to the 76th Legislature. Live
tests are opt-in (LOBBYBOOK_LIVE=1) and bounded.
"""

from __future__ import annotations

import pytest

from lobbybook.core.docstore import store_document
from lobbybook.sources import interim

HOUSE_PDF = "F-Interim-Charges-3.25.pdf"
SENATE_PDF = "2026-Interim-Charges-senate.pdf"


def _load(fixtures, name: str) -> bytes:
    return (fixtures / "interim" / name).read_bytes()


@pytest.fixture(scope="module")
def house(pytestconfig):
    path = pytestconfig.rootpath / "fixtures" / "interim" / HOUSE_PDF
    return interim.parse_house_charges(path.read_bytes())


@pytest.fixture(scope="module")
def senate(pytestconfig):
    path = pytestconfig.rootpath / "fixtures" / "interim" / SENATE_PDF
    return interim.parse_senate_charges(path.read_bytes())


def _by(charges, committee, no):
    return next(c for c in charges if c["committee_raw"] == committee and c["charge_no"] == no)


# ------------------------------------------------------------------ helpers
def test_receiving_leg_is_ordering_plus_one():
    """LRL and the chamber archives index by the legislature that ORDERED the
    study; the 88th's reports serve the 89th session."""
    assert interim.receiving_leg(88) == 89
    assert interim.receiving_leg(89) == 90


def test_bill_refs_every_live_form():
    refs = interim.parse_bill_refs(
        "Monitor rulemaking related to Senate Bill 6, 89th Legislature, including "
        "post-Winter Storm Uri reforms, including Senate Bills 2 and 3, 87th Legislature. "
        "House Bill 149 (89th Legislature), relating to AI. HB 43, relating to the Texas "
        "Agricultural Finance Authority. SB 1080, relating to occupational licenses."
    )
    assert [(r["bill"], r["legislature"]) for r in refs] == [
        ("SB6", 89),
        ("SB2", 87),
        ("SB3", 87),
        ("HB149", 89),
        ("HB43", None),
        ("SB1080", None),
    ]


def test_bill_refs_ignore_bare_legislature_mentions():
    assert interim.parse_bill_refs("enacted by the 89th Legislature to ensure") == []


# ------------------------------------------------------------ House charges
def test_house_committee_coverage(house):
    committees = {c["committee_raw"] for c in house}
    # 25 standing committees, the three new select committees, and seven
    # subcommittees that restart charge numbering inside their parent. The
    # cover block and the bare 'SELECT COMMITTEES' divider are not sections.
    assert len(committees) == 35
    assert "INTERGOVERNMENTAL AFFAIRS: Subcommittee on State-Federal Relations" in committees
    assert "TRANSPORTATION: Subcommittee on Transportation Funding" in committees
    assert "AGRICULTURE AND LIVESTOCK" in committees
    assert "JUDICIARY AND CIVIL JURISPRUDENCE" in committees
    assert "WAYS AND MEANS" in committees
    assert "GOVERNMENTAL OVERSIGHT, SELECT" in committees
    assert "HEALTH CARE AFFORDABILITY, SELECT" in committees
    assert "GENERAL AVIATION, SELECT" in committees
    assert "SELECT COMMITTEES" not in committees
    assert len(house) == 186
    assert all(c["ordering_leg"] == 89 and c["receiving_leg"] == 90 for c in house)
    assert all(c["issuer"] == "speaker" for c in house)


def test_house_charge_text_and_titles(house):
    c = _by(house, "AGRICULTURE AND LIVESTOCK", "2")
    assert c["title"] == "Invasive Species"
    assert c["charge_type"] == "study"
    assert c["text"].startswith(
        "Study the detection and management of invasive species and insects impacting "
        "Texas agriculture, including New World screwworm"
    )
    assert "feral hogs" in c["text"]


def test_every_standing_committee_charge_one_is_monitoring(house):
    """The audit's observation, checked against the document: charge 1 of every
    standing committee is the monitoring charge. (The three new select
    committees and the subcommittees are the documented exceptions — two of the
    three selects still open with one, General Aviation does not.)"""
    firsts = [
        c for c in house
        if c["charge_no"] == "1"
        and "SELECT" not in c["committee_raw"]
        and "Subcommittee" not in c["committee_raw"]
    ]
    assert len(firsts) == 25
    assert all(c["charge_type"] == "monitoring" for c in firsts)
    assert all(c["title"] == "Monitoring" for c in firsts)


def test_monitoring_charges_name_enacted_bills(house):
    ag = _by(house, "AGRICULTURE AND LIVESTOCK", "1")
    assert [b["bill"] for b in ag["bills"]] == ["HB43"]
    # The legislature is stated once in the charge stem, not per bill.
    assert ag["bills"][0]["legislature"] == 89
    assert ag["bills"][0]["legislature_derived"] is True

    corrections = _by(house, "CORRECTIONS", "1")
    assert [b["bill"] for b in corrections["bills"]] == ["SB1080", "SB2405"]
    assert "revocation of an occupational license" in corrections["text"]

    named = {b["bill"] for c in house for b in c["bills"]}
    assert len(named) >= 70
    assert {"HB14", "HB150", "SB2405"} <= named

    with_bills = [c for c in house if c["charge_type"] == "monitoring" and c["bills"]]
    assert len(with_bills) >= 20


# ----------------------------------------------------------- Senate charges
def test_senate_committee_coverage(senate):
    committees = {c["committee_raw"] for c in senate}
    assert len(committees) == 15
    assert "Business and Commerce Committee" in committees
    assert "Select Committee on Homeland and Border Security" in committees
    assert "Water, Agriculture, and Rural Affairs Committee" in committees
    assert all(c["issuer"] == "lt_governor" for c in senate)
    # The cover page lists every committee; it must not open a section.
    assert not any(c["committee_raw"] == "Dan Patrick" for c in senate)


def test_senate_charges_are_titled_bullets(senate):
    first = _by(senate, "Business and Commerce Committee", "1")
    assert first["title"] == "Assessing the State of the Texas Electric Grid"
    assert first["charge_type"] == "monitoring"
    assert first["text"].startswith("Monitor rulemaking related to Senate Bill 6, 89th Legislature")
    assert [(b["bill"], b["legislature"]) for b in first["bills"]][:1] == [("SB6", 89)]
    # 'Senate Bills 2 and 3, 87th Legislature' expands, and 87 is not read as a bill.
    assert ("SB2", 87) in [(b["bill"], b["legislature"]) for b in first["bills"]]
    assert ("SB87", None) not in [(b["bill"], b["legislature"]) for b in first["bills"]]

    monitoring = next(c for c in senate
                      if c["committee_raw"] == "Business and Commerce Committee"
                      and c["title"] == "Monitoring")
    assert [b["bill"] for b in monitoring["bills"]] == [
        "SB815", "SB1964", "HB14", "HB149", "HB150"
    ]
    assert all(b["legislature"] == 89 for b in monitoring["bills"])


def test_senate_charges_pdf_url(fixtures):
    url = interim.senate_charges_url(_load(fixtures, "ltgov-2026-interim-charges.html"))
    assert url == "https://www.ltgov.texas.gov/wp-content/uploads/2026/03/2026-Interim-Charges.pdf"


# ------------------------------------------------------------ report index
def test_report_index(fixtures):
    rows = interim.parse_report_index(_load(fixtures, "house-interim-reports-index.html"))
    reports = [r for r in rows if r["kind"] == "report"]
    assert len(reports) > 300
    legs = sorted({r["ordering_leg"] for r in reports})
    # Chamber-site archive reaches back to the 76th (1999).
    assert legs[0] == 76
    assert 88 in legs

    crim = next(r for r in reports
                if r["ordering_leg"] == 88 and r["committee_raw"] == "Criminal Jurisprudence")
    assert crim["url"].endswith(
        "88interim/House-Committee-on-Criminal-Jurisprudence-Interim-Report-2024.pdf"
    )
    # The 88th ordered it; the 89th session is the audience.
    assert crim["receiving_leg"] == 89
    assert interim.report_id(crim) == (
        "house:88:House-Committee-on-Criminal-Jurisprudence-Interim-Report-2024"
    )
    # Size suffixes are stripped from the link text.
    assert "[PDF" not in crim["title"]

    # Charge PDFs live in the same listing and are not reports.
    charges = [r for r in rows if r["kind"] == "charges"]
    assert any(r["url"].endswith("F-Interim-Charges-3.25.pdf") for r in charges)

    # A group heading belongs to its own session block only.
    assert all(r["group"] is None for r in reports if r["ordering_leg"] == 76)


# ------------------------------------------------------------------- store
def test_store_charges_and_edges(conn, fixtures):
    charges = interim.parse_house_charges(_load(fixtures, HOUSE_PDF))
    store_document(conn, doc_id="interim:charges:house:89", source_family="interim",
                   content=b"%PDF-fixture", url=interim.HOUSE_CHARGES_89,
                   doc_type="interim_charges")
    stats = interim.store_charges(conn, charges, "interim:charges:house:89")
    conn.commit()
    assert stats["charges"] == 186
    assert stats["committees"] == 35

    row = conn.execute(
        """SELECT * FROM interim_charge
            WHERE ordering_leg=89 AND committee_raw='CORRECTIONS' AND charge_no='1'"""
    ).fetchone()
    assert row["charge_type"] == "monitoring"
    assert row["issuer"] == "speaker"
    assert row["text"].startswith("Monitoring: Monitor the implementation")

    key = "89:house:corrections:1"
    bills = [r["bill"] for r in conn.execute(
        "SELECT bill FROM interim_charge_bill WHERE charge_key=? ORDER BY bill", (key,))]
    assert bills == ["SB1080", "SB2405"]

    monitors = conn.execute(
        """SELECT dst_id, span, provenance FROM edge
            WHERE src_type='interim_charge' AND src_id=? AND predicate='monitors'
            ORDER BY dst_id""", (key,)).fetchall()
    assert [(m["dst_id"], m["span"], m["provenance"]) for m in monitors] == [
        ("SB1080", "89R", "explicit"),
        ("SB2405", "89R", "explicit"),
    ]
    assert conn.execute(
        """SELECT COUNT(*) c FROM edge WHERE src_type='interim_charge'
            AND predicate='assigned_to' AND dst_id='CORRECTIONS'"""
    ).fetchone()["c"] == 4

    # Idempotent: a re-run of the same charge list must not duplicate rows.
    interim.store_charges(conn, charges, "interim:charges:house:89")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM interim_charge").fetchone()["c"] == 186


def test_store_reports_records_receiving_legislature(conn, fixtures):
    rows = interim.parse_report_index(_load(fixtures, "house-interim-reports-index.html"))
    store_document(conn, doc_id="interim:reports:house:index", source_family="interim",
                   content=b"<html/>", url=interim.HOUSE_REPORT_INDEX, doc_type="report_index")
    stored = interim.store_reports(conn, rows, "interim:reports:house:index")
    conn.commit()
    assert stored > 300

    rid = "house:88:House-Committee-on-Criminal-Jurisprudence-Interim-Report-2024"
    row = conn.execute("SELECT * FROM interim_report WHERE id=?", (rid,)).fetchone()
    assert row["ordering_leg"] == 88
    assert row["committee_raw"] == "Criminal Jurisprudence"
    meta = conn.execute("SELECT * FROM interim_report_meta WHERE report_id=?", (rid,)).fetchone()
    assert meta["receiving_leg"] == 89
    serves = conn.execute(
        """SELECT dst_id, provenance, span FROM edge
            WHERE src_type='interim_report' AND src_id=? AND predicate='serves'""", (rid,)
    ).fetchone()
    assert (serves["dst_id"], serves["provenance"], serves["span"]) == (
        "89", "derived", "ordering_leg + 1"
    )


# -------------------------------------------------------------------- live
@pytest.mark.live
def test_live_smoke(conn):
    result = interim.InterimConnector().smoke(conn)
    assert result.ok, result.detail
    assert result.stats["charges"] >= 20
    assert result.stats["committees"] >= 10
    assert result.stats["monitoring_charges_naming_bills"] >= 1


@pytest.mark.live
def test_live_senate_charges(conn):
    stats = interim.InterimConnector().ingest_senate_charges(conn)
    assert stats["committees"] >= 10
    assert stats["bill_refs"] >= 10


@pytest.mark.live
def test_live_report_index(conn):
    stats = interim.InterimConnector().ingest_report_index(conn)
    assert stats["reports"] > 300
    assert stats["oldest_leg"] == 76
