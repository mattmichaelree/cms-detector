"""Sunset connector tests.

Offline tests run against saved fixtures and assert *real* values — the actual
recommendation numbers TDCJ's 2024-25 review produced, their actual outcome
labels ("Adopted as Modified", "Not Adopted"), the actual enacting bill
(SB 2405), the actual document rows on the live agency page, and the actual
2036-37 next-review date. A parser that returns plausible-shaped garbage fails
here. Live tests are opt-in (LOBBYBOOK_LIVE=1) and bounded.
"""

from __future__ import annotations

import pytest

from lobbybook.sources import sunset

EXCERPT = "tdcj-staff-report-with-final-results-excerpt.pdf"
TDCJ = "texas-department-criminal-justice"


def _load(fixtures, name: str) -> bytes:
    return (fixtures / "sunset" / name).read_bytes()


@pytest.fixture(scope="module")
def recs(pytestconfig):
    """The PDF text extraction is the slow part; do it once per session."""
    path = pytestconfig.rootpath / "fixtures" / "sunset" / EXCERPT
    return sunset.parse_recommendations(path.read_bytes())


# ------------------------------------------------------------------ helpers
def test_doc_type_labels():
    assert sunset.doc_type_for("Staff Report with Final Results") == "staff_report_final_results"
    assert sunset.doc_type_for("Staff Report with Commission Decisions") == "staff_report_commission_decisions"
    # 'Staff Report' alone must not win over the longer labels above.
    assert sunset.doc_type_for("Staff Report") == "staff_report"
    assert sunset.doc_type_for("Self-Evaluation Report") == "self_evaluation"
    assert sunset.doc_type_for("Report to the 83rd Legislature Agency Section") == "report_to_legislature"
    assert sunset.doc_type_for("Summary of Results") == "final_results"


def test_cycle_label_and_uninvert():
    assert sunset.cycle_label("2024-2025 Review Cycle, 89th Legislative Session") == "2024-25"
    assert sunset.cycle_label("2028–2029 Review Cycle") == "2028-29"      # en dash
    assert sunset.cycle_label("no cycle here") is None
    assert sunset.uninvert("Criminal Justice, Texas Department of") == "Texas Department of Criminal Justice"
    assert sunset.uninvert("Angelina and Neches River Authority") == "Angelina and Neches River Authority"


# ------------------------------------------------------------- index pages
def test_cycle_index(fixtures):
    cycles = sunset.parse_cycle_index(_load(fixtures, "past-review-cycles.html"))
    # 24 cycles, 1978-81 through 2024-25 — one page row covers two of them.
    assert len(cycles) == 24
    by_cycle = {c["cycle"]: c for c in cycles}
    assert by_cycle["2024-25"]["legislature"] == 89
    assert by_cycle["2024-25"]["url"] == "https://www.sunset.texas.gov/node/204"
    assert by_cycle["2022-23"]["legislature"] == 88
    # The combined row must split into both cycles with the right legislatures.
    assert by_cycle["1978-79"]["legislature"] == 66
    assert by_cycle["1980-81"]["legislature"] == 67
    assert by_cycle["1978-79"]["url"] == by_cycle["1980-81"]["url"]


def test_agency_index(fixtures):
    agencies = sunset.parse_agency_index(_load(fixtures, "agencies-index.html"))
    slugs = {a["slug"] for a in agencies}
    assert len(agencies) > 200          # includes abolished predecessors
    assert TDCJ in slugs
    assert "texas-workforce-commission" in slugs
    assert "texas-employment-commission" in slugs      # abolished predecessor
    first = agencies[0]
    assert first["name_raw"] == "Accountancy, Texas State Board of Public"
    assert first["name"] == "Texas State Board of Public Accountancy"


def test_future_reviews(fixtures):
    rows = sunset.parse_future_reviews(_load(fixtures, "future-reviews-by-year.html"))
    cycles = {r["cycle"] for r in rows}
    # Five future cycles, scheduled out to 2036-37.
    assert cycles == {"2028-29", "2030-31", "2032-33", "2034-35", "2036-37"}
    by_slug = {(r["cycle"], r["slug"]) for r in rows}
    assert ("2028-29", "texas-education-agency") in by_slug
    assert ("2028-29", "public-utility-commission-texas") in by_slug
    assert ("2028-29", "railroad-commission-texas") in by_slug
    assert ("2028-29", "texas-department-transportation") in by_slug


# ------------------------------------------------------------- agency page
def test_agency_page_documents(fixtures):
    page = sunset.parse_agency_page(_load(fixtures, "tdcj-agency.html"), TDCJ)
    assert page["agency"] == "Texas Department of Criminal Justice"
    assert page["last_review_cycle"] == "2024-25"
    assert page["next_review_cycle"] == "2036-37"
    assert page["comment_index_id"] == "30354"

    docs = {(d["cycle"], d["doc_type"]): d for d in page["documents"]}
    # Current cycle: main column. Prior cycles: sidebar. One parse, both regions.
    current = docs[("2024-25", "staff_report_final_results")]
    assert current["label"] == "Staff Report with Final Results"
    assert current["published"] == "Jul 2025"
    assert current["legislature"] == 89
    assert current["url"].endswith("Staff%20Report%20with%20Final%20Results_7-8-25.pdf")
    assert docs[("2024-25", "self_evaluation")]["published"] == "Sep 2023"
    assert docs[("2012-13", "report_to_legislature")]["label"] == (
        "Report to the 83rd Legislature Agency Section"
    )
    assert docs[("1998-99", "staff_report")]["published"] == "May 1998"
    assert {d["cycle"] for d in page["documents"]} == {"2024-25", "2012-13", "2006-07", "1998-99"}
    # The footer's unrelated "Annual Financial Report" PDF must not be adopted
    # by the last cycle heading.
    assert not any("FY25" in d["url"] for d in page["documents"])


# --------------------------------------------------------- recommendations
def test_final_results_bill_and_issues(recs):
    assert recs["bill"]["bill"] == "SB2405"
    assert recs["bill"]["authors_raw"] == "Parker (Canales)"
    issues = {i["number"]: i["title"] for i in recs["issues"]}
    assert len(issues) == 8
    assert issues[1] == (
        "A Changing Workforce and Inmate Population Make Multiple TDCJ Facilities "
        "Almost Impossible to Adequately Staff."
    )
    assert issues[7] == "The State Has a Continuing Need for the Texas Department of Criminal Justice"


def test_recommendation_outcomes(recs):
    latest = sunset.latest_recommendations(recs["recommendations"])
    assert len(latest) == 55

    assert latest["1.1"]["outcome"] == "adopted_modified"
    assert latest["1.1"]["text"] == (
        "Require TDCJ to create a long-term facilities plan that identifies facility "
        "and capacity needs"
    )
    assert latest["1.2"]["outcome"] == "not_adopted"
    assert latest["1.2"]["text"] == (
        "Require TDCJ to develop a phased plan to close facilities with persistent "
        "staffing challenges"
    )
    assert latest["1.3"]["outcome"] == "adopted"
    assert latest["1.3"]["text"] == (
        "Eliminate the requirement for TDCJ to maintain state jails in nine regions "
        "from statute"
    )
    assert latest["1.4"]["text"] == "Eliminate unit maximum capacities from statute"

    counts: dict[str, int] = {}
    for r in latest.values():
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    assert counts == {"adopted": 45, "adopted_modified": 7, "not_adopted": 3}

    # Issue numbering carries through from the issue heads.
    assert latest["1.1"]["issue_no"] == 1
    assert latest["3.5"]["issue_no"] == 3
    assert latest["8.1"]["issue_no"] == 8


def test_recommendation_stages_are_kept_apart(recs):
    """Staff -> commission -> legislature is the delta the audit cares about;
    the parser must not collapse it. This excerpt carries the Final Results and
    Commission Decisions printings of all 55 recommendations."""
    stages = {r["stage"] for r in recs["recommendations"]}
    assert stages == {"final_results", "commission_decisions"}
    assert len(recs["recommendations"]) == 110
    by_stage = {r["stage"]: r for r in recs["recommendations"] if r["number"] == "1.1"}
    # Same number, same verdict, materially different commission wording.
    assert by_stage["commission_decisions"]["outcome"] == "adopted_modified"
    assert by_stage["final_results"]["outcome"] == "adopted_modified"
    assert len(by_stage["commission_decisions"]["text"]) > len(by_stage["final_results"]["text"])
    assert "merge the planning" in by_stage["commission_decisions"]["text"]


def test_recommendation_types(recs):
    """Type comes from two independent signals: the staff report's
    'Change in Statute' / 'Management Action' headings, and the inline
    '(Management action - nonstatutory)' marker in the results summary."""
    latest = sunset.latest_recommendations(recs["recommendations"])
    assert latest["1.1"]["rec_type"] == "statute"
    assert latest["1.4"]["rec_type"] == "statute"
    assert latest["2.1"]["rec_type"] == "management"
    assert latest["2.2"]["rec_type"] == "management"
    typed = recs["staff_recommendations"]
    assert typed["1.1"]["rec_type"] == "statute"
    assert typed["2.1"]["rec_type"] == "management"
    assert typed["1.1"]["text"].startswith(
        "Require TDCJ to create a long-term facilities and staffing plan"
    )


def test_hyphenated_line_breaks_survive(recs):
    latest = sunset.latest_recommendations(recs["recommendations"])
    # 'paper-\nbased' across a line break is a real hyphen, not a soft one.
    assert "paper-based processes" in latest["3.5"]["text"]


# ------------------------------------------------------------------- store
def test_store_roundtrip(conn, fixtures):
    page = sunset.parse_agency_page(_load(fixtures, "tdcj-agency.html"), TDCJ)
    doc = next(d for d in page["documents"] if d["doc_type"] == "staff_report_final_results"
               and d["cycle"] == "2024-25")
    parsed = sunset.parse_recommendations(_load(fixtures, EXCERPT))
    rid = sunset.store_review(conn, TDCJ, page["agency"], doc["cycle"])
    assert rid == f"{TDCJ}:2024-25"
    n = sunset.store_recommendations(conn, rid, parsed, "sunset:doc:test", doc["legislature"])
    conn.commit()
    assert n == 55

    row = conn.execute(
        "SELECT * FROM sunset_recommendation WHERE review_id=? AND number='1.2'", (rid,)
    ).fetchone()
    assert row["outcome"] == "not_adopted"
    assert row["rec_type"] == "statute"
    assert row["bill_id"] is None            # not adopted -> no enacting bill
    adopted = conn.execute(
        "SELECT bill_id FROM sunset_recommendation WHERE review_id=? AND number='1.3'", (rid,)
    ).fetchone()
    assert adopted["bill_id"] == "SB2405"

    stages = conn.execute(
        "SELECT COUNT(*) c FROM sunset_recommendation_stage WHERE review_id=?", (rid,)
    ).fetchone()["c"]
    assert stages == 110

    # Outcome edges are per recommendation, addressed by the minted key.
    rejected = conn.execute(
        """SELECT dst_id FROM edge WHERE src_type='sunset_recommendation'
             AND src_id=? AND predicate='rejected_by'""", (f"{rid}#1.2",),
    ).fetchone()
    assert rejected["dst_id"] == "89"
    assert conn.execute(
        """SELECT COUNT(*) c FROM edge WHERE src_type='sunset_review'
             AND predicate='produced' AND dst_type='bill'"""
    ).fetchone()["c"] == 1

    # Re-storing identical input is idempotent.
    sunset.store_recommendations(conn, rid, parsed, "sunset:doc:test", doc["legislature"])
    conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM sunset_recommendation").fetchone()["c"] == 55


def test_doc_id_is_stable_across_upload_generations():
    old = "https://www.sunset.texas.gov/public/uploads/files/reports/X%20Staff%20Report.pdf"
    new = "https://www.sunset.texas.gov/public/uploads/2025-07/X.pdf"
    assert sunset.doc_id_for(old) == "sunset:doc:files/reports/X%20Staff%20Report.pdf"
    assert sunset.doc_id_for(new) == "sunset:doc:2025-07/X.pdf"


# -------------------------------------------------------------------- live
@pytest.mark.live
def test_live_smoke(conn):
    result = sunset.SunsetConnector().smoke(conn)
    assert result.ok, result.detail
    assert result.stats["cycles"] >= 24
    assert result.stats["recommendations"] >= 5
    assert result.stats["bill"] == "SB2405"


@pytest.mark.live
def test_live_future_reviews(conn):
    rows = sunset.SunsetConnector().future_reviews(conn)
    assert len(rows) > 50
    assert any(r["cycle"] == "2036-37" for r in rows)
