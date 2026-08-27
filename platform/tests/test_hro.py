"""HRO / SRC connector tests.

Every offline assertion is pinned to a real value read out of a committed
fixture PDF (88R HB 16, 88R HB 900, 74R HB 1 State Finance Report, and the
enrolled SRC analysis of 88R SB 1577) — no synthetic text.
"""

from __future__ import annotations

import pytest

from lobbybook.core.docstore import store_document
from lobbybook.sources import hro

# --------------------------------------------------------------- fixtures

@pytest.fixture()
def hb16(fixtures) -> bytes:
    return (fixtures / "hro" / "ba88r" / "hb0016.pdf").read_bytes()


@pytest.fixture()
def hb900(fixtures) -> bytes:
    return (fixtures / "hro" / "ba88r" / "hb0900.pdf").read_bytes()


@pytest.fixture()
def hb1_1995(fixtures) -> bytes:
    return (fixtures / "hro" / "ba74r" / "hb0001.pdf").read_bytes()


@pytest.fixture()
def src_sb1577(fixtures) -> bytes:
    return (fixtures / "hro" / "src" / "SB01577F.pdf").read_bytes()


def _sections(parsed) -> dict:
    return {s["section_type"]: s for s in parsed["sections"]}


# ------------------------------------------------------------------- URLs

def test_analysis_url_zero_pads_and_lowercases():
    assert hro.analysis_url("88R", "HB16") == "https://hro.house.texas.gov/pdf/ba88r/hb0016.pdf"
    assert hro.analysis_url("88R", "HB 16", "PDF") == (
        "https://hro.house.texas.gov/pdf/ba88r/hb0016.PDF"
    )
    assert hro.analysis_url("74R", "HB1") == "https://hro.house.texas.gov/pdf/ba74r/hb0001.pdf"
    assert hro.analysis_url("891", "SB2") == "https://hro.house.texas.gov/pdf/ba891/sb0002.pdf"


def test_src_url():
    assert hro.src_url("88R", "SB01577", "F") == (
        "https://capitol.texas.gov/tlodocs/88R/analysis/pdf/SB01577F.pdf"
    )


def test_bill_id():
    assert hro.bill_id("88R", "HB 16") == "88R-HB16"


# ------------------------------------------------------------ header/sections

def test_header_hb16(hb16):
    head = hro.parse_analysis(hb16)["header"]
    assert head["analysis_date"] == "4/19/2023"
    assert head["bill_label"] == "HB 16"
    assert head["author_raw"] == "Moody et al."
    assert head["substitute_of"] == "CSHB 16"
    assert head["substitute_author_raw"] == "A. Johnson"


def test_subject_and_committee_hb16(hb16):
    parsed = hro.parse_analysis(hb16)
    assert hro.section_text(parsed, "subject") == (
        "Amending juvenile court processes and planning for services for juveniles"
    )
    assert parsed["committee_raw"] == "Youth Health & Safety, Select"
    assert parsed["committee_disposition"] == "committee substitute recommended"


def test_stance_sections_hb16(hb16):
    """The headline training labels: real, non-empty, correctly stance-split."""
    secs = _sections(hro.parse_analysis(hb16))

    supporters = secs["supporters_say"]
    assert supporters["label_raw"] == "SUPPORTERS SAY:"
    # verbatim from the fixture, and proof the wrapped 'SUPPORTERS / SAY:'
    # label did not eat the first two lines of body text
    assert supporters["text"].startswith(
        "CSHB 16 would enhance the juvenile court system’s ability to divert"
    )
    assert "youth away from confinement in TJJD facilities" in supporters["text"]
    assert "By increasing collaboration between TJJD and DFPS" in supporters["text"]
    assert len(supporters["text"]) > 2000

    # HRO prints CRITICS SAY: where no organized opposition registered; it is
    # the same against-stance block, so it normalizes to opponents_say and the
    # printed label survives in label_raw.
    opponents = secs["opponents_say"]
    assert opponents["label_raw"] == "CRITICS SAY:"
    assert opponents["text"].startswith("CSHB 16 would not go far enough to transform")
    assert "closure of the five remaining TJJD facilities" in opponents["text"]

    other = secs["other_opponents_say"]
    assert other["label_raw"] == "OTHER CRITICS SAY:"
    assert other["text"].startswith(
        "While the juvenile justice system should focus on keeping youth close to"
    )

    assert "$3,919,184 in general revenue" in secs["notes"]["text"]
    assert secs["digest"]["text"].startswith("CSHB 16 would amend and revise provisions")
    # running headers ("HB 16 / House Research Organization / page 8") stripped
    assert "House Research Organization" not in secs["digest"]["text"]
    assert "page 8" not in secs["supporters_say"]["text"]


def test_section_ordinals_follow_document_order(hb16):
    parsed = hro.parse_analysis(hb16)
    order = [s["section_type"] for s in parsed["sections"]]
    assert order == [
        "subject",
        "digest",
        "supporters_say",
        "opponents_say",
        "other_opponents_say",
        "notes",
    ]
    assert [s["ordinal"] for s in parsed["sections"]] == [1, 2, 3, 4, 5, 6]


def test_background_section_hb900(hb900):
    secs = _sections(hro.parse_analysis(hb900))
    assert secs["subject"]["text"] == (
        "Prohibiting certain sexually relevant material from public school libraries"
    )
    assert secs["background"]["text"].startswith(
        'Penal Code sec. 43.21 defines "patently offensive"'
    )
    assert secs["supporters_say"]["text"].startswith("CSHB 900 would make necessary changes")
    assert secs["opponents_say"]["label_raw"] == "CRITICS SAY:"
    assert "would not adequately define the content in books" in secs["opponents_say"]["text"]


# ----------------------------------------------------------------- votes

def test_committee_vote_hb16(hb16):
    vote = hro.parse_analysis(hb16)["vote"]
    assert (vote["ayes"], vote["nays"], vote["absent"]) == (7, 0, 2)
    members = [(m["name_raw"], m["position"]) for m in vote["members"]]
    assert len(members) == 9
    assert members[:3] == [("S. Thompson", "aye"), ("Hull", "aye"), ("Allison", "aye")]
    assert ("A. Johnson", "aye") in members
    assert ("Lozano", "aye") in members  # name wrapped onto its own line
    assert ("Dutton", "absent") in members
    assert ("T. King", "absent") in members
    assert not [m for m in members if m[1] == "nay"]


def test_committee_vote_hb900(hb900):
    vote = hro.parse_analysis(hb900)["vote"]
    assert (vote["ayes"], vote["nays"], vote["absent"]) == (10, 2, 1)
    members = {m["name_raw"]: m["position"] for m in vote["members"]}
    assert len(members) == 13
    assert members["Hinojosa"] == "nay"
    assert members["Talarico"] == "nay"
    assert members["Schaefer"] == "absent"
    assert members["Cody Harris"] == "aye"


# -------------------------------------------------------------- witnesses

def test_witnesses_hb16(hb16):
    ws = hro.parse_analysis(hb16)["witnesses"]
    by_name = {w["name_raw"]: w for w in ws}
    assert len(ws) == 24

    henneke = by_name["Elizabeth Henneke"]
    assert (henneke["position"], henneke["testified"], henneke["org_raw"]) == (
        "for",
        1,
        "Lone Star Justice Alliance",
    )
    assert by_name["Nikki Pressley"]["org_raw"] == "Texas Public Policy Foundation"

    # this fixture's For group is missing the colon after "did not testify" —
    # the registered/testified split must still land
    assert by_name["Amanda List"]["testified"] == 0
    assert by_name["Amanda List"]["org_raw"] == "AList Consulting"

    # one organization shared by two names in a single entry
    assert by_name["Kristian Caballero"]["org_raw"] == "Texas Appleseed"
    assert by_name["Martin Martinez"]["org_raw"] == "Texas Appleseed"

    # unaffiliated witnesses are flagged self
    assert by_name["Thomas Parkinson"]["is_self"] is True
    assert by_name["Thomas Parkinson"]["org_raw"] is None

    toon = by_name["Jennifer Toon"]
    assert (toon["position"], toon["testified"], toon["is_self"]) == ("against", 1, True)

    rose = by_name["Lauren Rose"]
    assert (rose["position"], rose["org_raw"]) == ("on", "Texas Network of Youth Services")
    assert by_name["Eric Marin"] == {
        "name_raw": "Eric Marin",
        "org_raw": "TEA",
        "is_self": False,
        "position": "on",
        "testified": 0,
    }

    assert len([w for w in ws if w["position"] == "for" and w["testified"] == 1]) == 3
    assert len([w for w in ws if w["position"] == "for"]) == 18


def test_witnesses_hb900_anonymous_counts(hb900):
    ws = hro.parse_analysis(hb900)["witnesses"]
    anon = {(w["position"], w["testified"]): w["anonymous_count"]
            for w in ws if w.get("anonymous_count")}
    assert anon[("for", 1)] == 31
    assert anon[("against", 0)] == 79
    named = {w["name_raw"]: w for w in ws if not w.get("anonymous_count")}
    assert named["Brian Klosterboer"]["position"] == "against"
    assert named["Brian Klosterboer"]["org_raw"] == "ACLU of Texas"
    assert named["Christin Bentley"]["org_raw"] == "Republican Party of Texas"
    # witness roster spans a page break; the running header must not merge names
    assert "Daniel Dawer" in named
    assert named["Daniel Dawer"]["org_raw"] == "Educators in Solidarity"


# ------------------------------------------------------------- 1995 corpus

def test_1995_pdf_has_a_real_text_layer(hb1_1995):
    """74th Legislature (1995), Distiller-era PDF: born digital, no OCR needed."""
    text = hro.extract_text(hb1_1995)
    assert len(text) > 60000
    assert "CSHB 1 by Junell, the general appropriations bill for fiscal 1996-97" in text
    assert "HOUSE RESEARCH ORGANIZATION" in text


def test_1995_state_finance_report_degrades_gracefully(hb1_1995):
    """Not a per-bill analysis: no margin labels, so no sections — not a crash."""
    parsed = hro.parse_analysis(hb1_1995)
    assert parsed["sections"] == []
    assert parsed["witnesses"] == []
    assert parsed["vote"]["members"] == []
    assert parsed["header"]["author_raw"] is None


# --------------------------------------------------------------------- SRC

def test_parse_src_sb1577(src_sb1577):
    parsed = hro.parse_src(src_sb1577)
    assert parsed["version"] == "Enrolled"
    assert parsed["author_raw"] == "Menéndez; Schwertner"
    assert parsed["date"] == "5/10/2023"
    secs = {s["section_type"]: s["text"] for s in parsed["sections"]}
    assert set(secs) == {
        "src_header",
        "src_statement_of_intent",
        "src_rulemaking_authority",
        "src_section_by_section",
    }
    assert "Senate Research Center S.B. 1577" in secs["src_header"]
    assert secs["src_statement_of_intent"].startswith("Since its inception in 1971")
    assert "Rulemaking authority is expressly granted to the Texas Real Estate Commission" in (
        secs["src_rulemaking_authority"]
    )
    assert secs["src_section_by_section"].startswith("SECTION 1. Amends the heading")
    assert "SECTION 32. Effective date: January 1, 2024." in secs["src_section_by_section"]
    # page footers stripped
    assert "Page 1 of 7" not in secs["src_section_by_section"]
    # SRC carries no arguments/votes/witnesses at all
    assert all(not s["section_type"].startswith("supporters") for s in parsed["sections"])


# ------------------------------------------------------------------ storage

def _store(conn, hb16_bytes, session="88R", bill="HB16"):
    doc_id = f"hro:analysis:{hro.bill_id(session, bill)}"
    store_document(
        conn,
        doc_id=doc_id,
        source_family="hro",
        content=hb16_bytes,
        url=hro.analysis_url(session, bill),
        doc_type="bill_analysis",
        session_id=session,
        authority="A",
    )
    parsed = hro.parse_analysis(hb16_bytes)
    stats = hro.store_analysis(conn, session, bill, parsed, doc_id)
    conn.commit()
    return doc_id, stats


def test_store_analysis_rows(conn, hb16):
    doc_id, stats = _store(conn, hb16)
    assert stats["bill_id"] == "88R-HB16"

    row = conn.execute("SELECT * FROM hro_analysis WHERE bill_id='88R-HB16'").fetchone()
    assert row["session_id"] == "88R"
    assert row["analysis_date"] == "4/19/2023"
    assert row["committee_raw"] == "Youth Health & Safety, Select"
    assert row["committee_disposition"] == "committee substitute recommended"
    assert (row["vote_ayes"], row["vote_nays"], row["vote_absent"]) == (7, 0, 2)
    assert row["doc_id"] == doc_id

    bill = conn.execute("SELECT * FROM bill WHERE id='88R-HB16'").fetchone()
    assert (bill["bill_type"], bill["number"]) == ("HB", 16)

    types = {r["section_type"]: r["text"] for r in conn.execute(
        "SELECT section_type, text FROM hro_section WHERE bill_id='88R-HB16'")}
    assert "supporters_say" in types and "opponents_say" in types
    assert len(types["supporters_say"]) > 2000

    votes = {r["name_raw"]: r["position"] for r in conn.execute(
        "SELECT name_raw, position FROM hro_committee_vote WHERE bill_id='88R-HB16'")}
    assert len(votes) == 9
    assert votes["S. Thompson"] == "aye"
    assert votes["T. King"] == "absent"

    slips = conn.execute(
        "SELECT COUNT(*) AS n FROM witness_slip WHERE bill_id='88R-HB16'"
    ).fetchone()["n"]
    assert slips == 24
    self_slip = conn.execute(
        "SELECT * FROM witness_slip WHERE name_raw='Jennifer Toon'"
    ).fetchone()
    assert (self_slip["position"], self_slip["testified"], self_slip["is_self"]) == (
        "against", 1, 1
    )


def test_store_analysis_edges(conn, hb16):
    doc_id, _ = _store(conn, hb16)

    def has(src_type, src_id, predicate, dst_type, dst_id):
        return conn.execute(
            "SELECT 1 FROM edge WHERE src_type=? AND src_id=? AND predicate=? AND dst_type=?"
            " AND dst_id=? AND provenance='explicit' AND source_doc=?",
            (src_type, src_id, predicate, dst_type, dst_id, doc_id),
        ).fetchone()

    assert has("bill", "88R-HB16", "has_analysis", "document", doc_id)
    assert has("bill", "88R-HB16", "reported_by", "committee_name", "Youth Health & Safety, Select")
    assert has("person_name", "S. Thompson", "voted_aye", "bill", "88R-HB16")
    assert has("person_name", "Dutton", "voted_absent", "bill", "88R-HB16")
    assert has("person_name", "Elizabeth Henneke", "testified_for", "bill", "88R-HB16")
    assert has("person_name", "Amanda List", "registered_for", "bill", "88R-HB16")
    assert has("person_name", "Jennifer Toon", "testified_against", "bill", "88R-HB16")
    assert has("person_name", "Elizabeth Henneke", "represents", "org_name",
               "Lone Star Justice Alliance")
    assert has("org_name", "Texas Appleseed", "witness_for", "bill", "88R-HB16")
    assert has("argument", "88R-HB16:supporters", "supports", "bill", "88R-HB16")
    assert has("argument", "88R-HB16:opponents_say", "opposes", "bill", "88R-HB16")
    assert has("person_name", "Moody", "authored", "bill", "88R-HB16")
    assert has("person_name", "A. Johnson", "substitute_authored", "bill", "88R-HB16")


def test_store_analysis_is_idempotent(conn, hb16):
    _store(conn, hb16)
    counts = lambda: tuple(  # noqa: E731
        conn.execute(f"SELECT COUNT(*) AS n FROM {t} WHERE bill_id='88R-HB16'").fetchone()["n"]
        for t in ("hro_section", "hro_committee_vote", "witness_slip")
    )
    first = counts()
    _store(conn, hb16)
    assert counts() == first
    assert first == (6, 9, 24)


def test_store_src_rows_and_coexists_with_hro(conn, hb16, src_sb1577):
    _store(conn, hb16)
    doc_id = "src:analysis:88R-SB1577:F"
    store_document(
        conn,
        doc_id=doc_id,
        source_family="src",
        content=src_sb1577,
        url=hro.src_url("88R", "SB01577", "F"),
        doc_type="src_bill_analysis",
        session_id="88R",
        authority="A",
    )
    parsed = hro.parse_src(src_sb1577)
    stats = hro.store_src(conn, "88R", "SB1577", parsed, doc_id)
    conn.commit()
    assert stats["bill_id"] == "88R-SB1577"
    assert stats["version"] == "Enrolled"

    rows = {r["section_type"] for r in conn.execute(
        "SELECT section_type FROM hro_section WHERE bill_id='88R-SB1577'")}
    assert rows == {
        "src_header",
        "src_statement_of_intent",
        "src_rulemaking_authority",
        "src_section_by_section",
    }
    # the HRO analysis rows for the other bill are untouched
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM hro_section WHERE bill_id='88R-HB16'"
    ).fetchone()["n"] == 6
    assert conn.execute(
        "SELECT 1 FROM edge WHERE src_id='88R-SB1577' AND predicate='has_src_analysis'"
    ).fetchone()


# --------------------------------------------------------------------- live

@pytest.mark.live
def test_smoke_live(conn):
    from lobbybook.core.registry import get

    result = get("hro").smoke(conn)
    assert result.ok, result.detail
    stats = result.stats
    assert stats["sections"]["supporters_say"] > 0
    assert stats["sections"]["opponents_say"] > 0
    assert stats["witnesses"] >= 1
    assert stats["votes"] >= 1
    assert stats["src"]["sections"] >= 3
