"""LBB connector tests.

Offline tests run against saved fixtures and assert *real* values from the
real documents (89R SB 2's actual dollar figures, actual FY labels, actual
source-agency codes) — a parser that returns plausible-shaped garbage fails
here. Live tests are opt-in (LOBBYBOOK_LIVE=1) and bounded.
"""

from __future__ import annotations

import pytest

from lobbybook.core.docstore import store_document
from lobbybook.sources import lbb


def _load(fixtures, name: str) -> bytes:
    return (fixtures / "lbb" / name).read_bytes()


# ----------------------------------------------------------------- helpers
def test_url_shapes():
    assert lbb.bill_code("SB", 2) == "SB00002"
    assert lbb.bill_code("hb", 796) == "HB00796"
    assert (
        lbb.fiscal_note_url("89R", "SB00002", "I")
        == "https://capitol.texas.gov/tlodocs/89R/fiscalnotes/html/SB00002I.htm"
    )
    assert lbb.fiscal_note_url("89R", "SB00002", "e", fmt="pdf").endswith(
        "/fiscalnotes/pdf/SB00002E.pdf"
    )
    assert lbb.gaa_url(2026, 2027).endswith("General_Appropriations_Act_2026_2027.pdf")


def test_parse_money_signs():
    assert lbb.parse_money("($4,821,000,000)") == -4821000000.0
    assert lbb.parse_money("($1,000,000,000)") == -1000000000.0
    assert lbb.parse_money("$257,546,337") == 257546337.0
    assert lbb.parse_money("$0") == 0.0
    # FTE counts look numeric but are not money and must not become estimates.
    assert lbb.parse_money("42.0") is None
    assert lbb.parse_money("") is None
    assert lbb.parse_money("n/a") is None


# ------------------------------------------------------- the table form
def test_sb2_introduced_table_form(fixtures):
    note = lbb.parse_fiscal_note(_load(fixtures, "SB00002I.htm"))

    assert note["bill"] == "SB2"
    assert note["version_label"] == "As Introduced"
    assert note["date"] == "2025-01-28"
    assert note["caption"] == (
        "Relating to the establishment of an education savings account program."
    )
    assert note["no_significant_impact"] is False
    assert note["two_year_net_impact"] == -1006958766.0

    years = sorted({e["fiscal_year"] for e in note["estimates"]})
    assert years == [2026, 2027, 2028, 2029, 2030]

    cells = {(e["fiscal_year"], e["fund"]): e["amount"] for e in note["estimates"]}
    # 'Probable Net Positive/(Negative) Impact to General Revenue Related Funds'
    assert cells[(2026, "General Revenue Related Funds")] == -6958766.0
    assert cells[(2028, "General Revenue Related Funds")] == -2986809893.0
    assert cells[(2030, "General Revenue Related Funds")] == -3751784702.0
    # 'Probable Savings/(Cost) from' columns carry the fund's numeric code.
    assert cells[(2030, "General Revenue Fund (1)")] == -4557317230.0
    assert cells[(2028, "Foundation School Fund (193)")] == 257546337.0
    assert cells[(2030, "Foundation School Fund (193)")] == 805532528.0
    assert cells[(2026, "Foundation School Fund (193)")] == 0.0
    assert len(note["estimates"]) == 15  # 5 years x (1 GR-related + 2 funds)

    # The FTE column is parsed as a column but never as a dollar estimate.
    funds = {e["fund"] for e in note["estimates"]}
    assert not any("Number of State Employees" in f for f in funds)
    all_columns = [c["fund"] for t in note["tables"] for c in t["columns"]]
    assert "Change in Number of State Employees from FY 2025" in all_columns

    assert dict(note["agencies"]) == {
        "304": "Comptroller of Public Accounts",
        "313": "Department of Information Resources",
        "323": "Teacher Retirement System",
        "405": "Department of Public Safety",
        "701": "Texas Education Agency",
    }
    assert note["lbb_staff"] == ["JMc", "NC", "ASA", "MJe"]


# --------------------------------------------------- the narrative form
def test_hb796_no_significant_implication_form(fixtures):
    note = lbb.parse_fiscal_note(_load(fixtures, "HB00796I.htm"))

    assert note["bill"] == "HB796"
    assert note["version_label"] == "As Introduced"
    assert note["date"] == "2025-03-25"
    assert note["caption"] == "Relating to the Texas Sovereignty Act."
    assert note["no_significant_impact"] is True
    assert note["summary"] == "No significant fiscal implication to the State is anticipated."
    assert note["tables"] == []
    assert note["estimates"] == []
    assert note["two_year_net_impact"] is None
    assert [c for c, _ in note["agencies"]] == ["300", "302", "307"]


# ------------------------------------------------------- the version trap
def test_version_trap_introduced_vs_engrossed(fixtures):
    intro = lbb.parse_fiscal_note(_load(fixtures, "SB00002I.htm"))
    engr = lbb.parse_fiscal_note(_load(fixtures, "SB00002E.htm"))

    assert engr["version_label"] == "As Engrossed"
    assert engr["date"] == "2025-04-02"

    # Same bill, same biennium, different numbers — citing "the SB 2 fiscal
    # note" without a version code misstates every one of these.
    assert intro["two_year_net_impact"] == -1006958766.0
    assert engr["two_year_net_impact"] == -1008850431.0

    i = {(e["fiscal_year"], e["fund"]): e["amount"] for e in intro["estimates"]}
    e = {(e["fiscal_year"], e["fund"]): e["amount"] for e in engr["estimates"]}
    assert i[(2026, "General Revenue Related Funds")] == -6958766.0
    assert e[(2026, "General Revenue Related Funds")] == -8850431.0
    assert i[(2030, "General Revenue Fund (1)")] == -4557317230.0
    assert e[(2030, "General Revenue Fund (1)")] == -4412464002.0

    shared = set(i) & set(e)
    differing = {k for k in shared if i[k] != e[k]}
    assert len(differing) >= 6
    # The FY2027 $1.0B appropriation cap is the one figure that did not move.
    assert i[(2027, "General Revenue Fund (1)")] == e[(2027, "General Revenue Fund (1)")]


# ------------------------------------------------------------ persistence
def _store(conn, fixtures, name, session, code, version):
    content = _load(fixtures, name)
    doc_id = f"lbb:fiscalnote:{session}:{code}{version}"
    store_document(
        conn,
        doc_id=doc_id,
        source_family="lbb",
        content=content,
        url=lbb.fiscal_note_url(session, code, version),
        doc_type="fiscal_note",
        session_id=session,
        authority="A",
    )
    parsed = lbb.parse_fiscal_note(content)
    stats = lbb.LBBConnector().store_fiscal_note(conn, session, code, version, parsed, doc_id)
    conn.commit()
    return stats


def test_store_fiscal_note_rows_and_edges(conn, fixtures):
    stats = _store(conn, fixtures, "SB00002I.htm", "89R", "SB00002", "I")
    assert stats["bill_id"] == "89R-SB2"
    assert stats["fiscal_years"] == [2026, 2027, 2028, 2029, 2030]

    note = conn.execute("SELECT * FROM fiscal_note WHERE bill_id='89R-SB2'").fetchone()
    assert note["version_code"] == "I"
    assert note["date"] == "2025-01-28"
    assert "negative impact of ($1,006,958,766)" in note["summary"]

    row = conn.execute(
        "SELECT amount FROM fiscal_estimate WHERE fiscal_note_id=? AND fiscal_year=2030 "
        "AND fund='General Revenue Fund (1)'",
        (note["id"],),
    ).fetchone()
    assert row["amount"] == -4557317230.0
    assert conn.execute(
        "SELECT COUNT(*) c FROM fiscal_estimate WHERE fiscal_note_id=?", (note["id"],)
    ).fetchone()["c"] == 15

    bill = conn.execute("SELECT * FROM bill WHERE id='89R-SB2'").fetchone()
    assert bill["bill_type"] == "SB" and bill["number"] == 2
    assert "education savings account" in bill["caption"]
    stage = conn.execute("SELECT * FROM bill_version WHERE bill_id='89R-SB2'").fetchone()
    assert (stage["stage_code"], stage["stage_name"]) == ("I", "Introduced")

    cited = {
        r["dst_id"]
        for r in conn.execute(
            "SELECT dst_id FROM edge WHERE predicate='cites' AND dst_type='agency_code'"
        )
    }
    assert {"304", "701"} <= cited
    assert conn.execute(
        "SELECT COUNT(*) c FROM edge WHERE predicate='estimates_impact_to'"
    ).fetchone()["c"] == 3

    # Re-storing the same note is idempotent.
    _store(conn, fixtures, "SB00002I.htm", "89R", "SB00002", "I")
    assert conn.execute("SELECT COUNT(*) c FROM fiscal_note").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM fiscal_estimate").fetchone()["c"] == 15


def test_both_versions_persist_side_by_side(conn, fixtures):
    a = _store(conn, fixtures, "SB00002I.htm", "89R", "SB00002", "I")
    b = _store(conn, fixtures, "SB00002E.htm", "89R", "SB00002", "E")
    assert a["note_id"] != b["note_id"]
    assert conn.execute("SELECT COUNT(*) c FROM fiscal_note").fetchone()["c"] == 2

    pair = conn.execute(
        """SELECT n.version_code, e.amount FROM fiscal_note n
           JOIN fiscal_estimate e ON e.fiscal_note_id = n.id
           WHERE n.bill_id='89R-SB2' AND e.fiscal_year=2026
             AND e.fund='General Revenue Related Funds'
           ORDER BY n.version_code"""
    ).fetchall()
    assert [(r["version_code"], r["amount"]) for r in pair] == [
        ("E", -8850431.0),
        ("I", -6958766.0),
    ]


def test_narrative_note_persists_with_zero_estimates(conn, fixtures):
    stats = _store(conn, fixtures, "HB00796I.htm", "89R", "HB00796", "I")
    assert stats["no_significant_impact"] is True
    assert stats["estimates"] == 0
    note = conn.execute("SELECT * FROM fiscal_note WHERE bill_id='89R-HB796'").fetchone()
    assert note["summary"].startswith("No significant fiscal implication")
    assert conn.execute(
        "SELECT COUNT(*) c FROM fiscal_estimate WHERE fiscal_note_id=?", (note["id"],)
    ).fetchone()["c"] == 0


# ---------------------------------------------------------------- riders
def test_parse_riders_article09_packet(fixtures):
    riders = lbb.parse_riders(_load(fixtures, "Article09_Rider.pdf"))

    # The 87th's Article IX conference docket carries 15 numbered sections.
    assert len(riders) >= 15
    numbers = [r["section_no"] for r in riders]
    assert len(numbers) == len(set(numbers))  # two-column doubling is merged away
    assert numbers[0] == "3.04" and numbers[-1] == "17.22"

    by_no = {r["section_no"]: r for r in riders}
    assert by_no["6.08"]["title"] == "Benefits Paid Proportional by Method of Finance"
    assert "Method of Finance" in by_no["6.08"]["text"]
    assert by_no["3.04"]["title"] == "Scheduled Exempt Positions"
    assert by_no["7.13"]["title"] == "Reports for Reducing Expenditures"
    assert by_no["10.04"]["title"] == (
        "Statewide Behavioral Health Strategic Plan and Coordinated Expenditures"
    )
    assert all(len(r["text"]) > 100 for r in riders[:5])


def test_ingest_riders_from_bytes(conn, fixtures):
    content = _load(fixtures, "Article09_Rider.pdf")
    stats = lbb.LBBConnector().ingest_riders(
        conn,
        url=f"{lbb.LBB}/Documents/Appropriations_Bills/87/Initial_Dockets/Article09_Rider.pdf",
        biennium="2022-23",
        article="IX",
        content=content,
    )
    assert stats["riders"] >= 15
    rows = conn.execute("SELECT * FROM gaa_rider ORDER BY id").fetchall()
    assert len(rows) == stats["riders"]
    assert {r["biennium"] for r in rows} == {"2022-23"}
    six = conn.execute("SELECT * FROM gaa_rider WHERE section_no='6.08'").fetchone()
    assert six["title"] == "Benefits Paid Proportional by Method of Finance"
    assert six["doc_id"] == "lbb:riders:2022-23:IX"
    assert conn.execute(
        "SELECT COUNT(*) c FROM document WHERE id='lbb:riders:2022-23:IX'"
    ).fetchone()["c"] == 1


# ------------------------------------------------------------------- CRE
def test_parse_cre_index(fixtures):
    entries = lbb.parse_cre_index(_load(fixtures, "cre_index.html"))
    bienniums = sorted({e["biennium"] for e in entries if e["biennium"]})
    assert "2026-27" in bienniums and "2006-07" in bienniums
    assert len(bienniums) >= 11

    revisions = {e["id"]: e["revision"] for e in entries if e["revision"]}
    assert revisions["cre:2022-23:July 2022"] == "July 2022"
    assert set(revisions) == {
        "cre:2018-19:July 2018",
        "cre:2020-21:July 2020",
        "cre:2022-23:July 2022",
    }

    by_kind = {e["kind"]: e for e in entries if e["biennium"] == "2026-27"}
    assert by_kind["cre_pdf"]["url"].endswith("/2026-27/docs/cre2026-27.pdf")
    assert by_kind["cre_xlsx"]["url"].endswith("/2026-27/docs/cre-2026-27-data.xlsx")
    assert all(e["url"].startswith("https://") for e in entries)


# ------------------------------------------------------------ live tests
@pytest.mark.live
def test_live_smoke(conn):
    """2 live requests: 89R SB2 Introduced + Engrossed."""
    result = lbb.LBBConnector().smoke(conn)
    assert result.ok, result.detail
    assert result.stats["versions"] == ["E", "I"]
    assert len(result.stats["fiscal_years"]["I"]) >= 3
    assert result.stats["differing_cells"] > 0
    assert (
        result.stats["two_year_net_impact"]["I"] != result.stats["two_year_net_impact"]["E"]
    )


@pytest.mark.live
def test_live_version_sweep(conn):
    """5 live requests: I,H,S,E,F for 89R SB 2. 404s are expected."""
    result = lbb.LBBConnector().ingest_bill_fiscal_notes(conn, "89R", "SB", 2)
    assert result["bill"] == "89R-SB2"
    assert "I" in result["versions"] and "E" in result["versions"]
    assert len(result["versions"]) + len(result["missing"]) == 5
    stored = conn.execute(
        "SELECT version_code FROM fiscal_note WHERE bill_id='89R-SB2' ORDER BY version_code"
    ).fetchall()
    assert [r["version_code"] for r in stored] == result["versions"]


@pytest.mark.live
def test_live_cre(conn):
    """3 live requests: index + HEAD of the current PDF and XLSX."""
    result = lbb.LBBConnector().ingest_cre(conn)
    assert "2026-27" in result["bienniums"]
    assert len(result["revisions"]) >= 3
    assert result["probes"]["cre_pdf"]["status"] == 200
    rows = conn.execute("SELECT COUNT(*) c FROM revenue_estimate").fetchone()["c"]
    assert rows == result["entries"]


@pytest.mark.live
def test_live_gaa_is_probed_not_downloaded(conn):
    """2 live HEADs: the GAA is over the cap, the rider docket is not."""
    c = lbb.LBBConnector()
    gaa = c.probe(lbb.gaa_url(2026, 2027))
    assert gaa["status"] == 200
    assert gaa["size"] > 10 * 1024 * 1024
    assert gaa["too_large"] is True

    rider = c.probe(
        f"{lbb.LBB}/Documents/Appropriations_Bills/87/Initial_Dockets/Article09_Rider.pdf"
    )
    assert rider["status"] == 200
    assert rider["too_large"] is False
