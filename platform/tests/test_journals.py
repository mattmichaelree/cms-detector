"""Journals connector tests.

Offline tests run against real bytes captured from the live endpoints
(fixtures/journals/), and assert real extracted values — the day count in the
89R index, an actual record-vote number, real member names including the
journal's own disambiguators.

The load-bearing assertion is ``test_tally_equals_named_yeas``: the journal
prints both a tally ("104 Yeas") and the corresponding named list, so
tally == len(names) is an internal consistency proof that the roll parser
neither dropped nor duplicated a member.
"""

from __future__ import annotations

import pytest

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.sources.journals import (
    JournalsConnector,
    day_url,
    find_bill,
    html_to_text,
    index_url,
    parse_amendments,
    parse_day,
    parse_day_index,
    parse_votes,
    segment_day,
    store_day,
    vote_id,
)

HOUSE_DAY = "89RDAY70FINAL.HTM"        # 70th day, Thursday May 22 2025, pp. 5579-5708
SENATE_DAY = "89RSJ05-21-F.HTM"        # 43rd day, Wednesday May 21 2025, pp. 2323-2365


@pytest.fixture()
def jdir(fixtures):
    return fixtures / "journals"


@pytest.fixture()
def house_day(jdir):
    return jdir.joinpath(HOUSE_DAY).read_bytes()


@pytest.fixture()
def senate_day(jdir):
    return jdir.joinpath(SENATE_DAY).read_bytes()


# ----------------------------------------------------------------- urls

def test_urls():
    assert index_url("house", "89R") == (
        "https://journals.house.texas.gov/hjrnl/89R/html/data/jrnlData.txt"
    )
    assert index_url("senate", "89R") == (
        "https://journals.senate.texas.gov/sjrnl/89R/html/data/jrnlData.txt"
    )
    assert day_url("house", "89R", "89RDAY70FINAL").endswith("/HJRNL/89R/HTML/89RDAY70FINAL.HTM")


# ----------------------------------------------------------- day index

def test_house_day_index_real_values(jdir):
    rows = parse_day_index(jdir.joinpath("house_jrnlData_89R.txt").read_bytes())
    assert len(rows) == 98  # 89R House journal files served as of capture

    first = rows[0]
    assert first["file_id"] == "89RDAY01FINAL"
    assert first["calendar_date"] == "2025-01-14"
    assert first["leg_day"] == "1st"
    assert (first["page_start"], first["page_end"]) == (1, 30)
    assert first["pdf_url"].upper().endswith("89RDAY01FINAL.PDF")

    last = rows[-1]
    assert last["file_id"] == "89RDAY81FINAL"
    assert last["calendar_date"] == "2025-06-02"
    assert last["leg_day"] == "81st"
    assert (last["page_start"], last["page_end"]) == (7921, 7954)

    by_id = {r["file_id"]: r for r in rows}
    assert by_id[HOUSE_DAY[:-4]]["calendar_date"] == "2025-05-22"
    # SUPPLEMENT/CONT files are distinct documents sharing a calendar date —
    # exactly why the dedup key is the file stem, never the date (audit §8).
    assert by_id["89RDAY61FINAL"]["calendar_date"] == "2025-05-10"
    assert by_id["89RDAY60CFINAL"]["calendar_date"] == "2025-05-10"
    assert by_id["89RDAY61SUPPLEMENT"]["leg_day"] == "61st Supplement"
    assert len({r["file_id"] for r in rows}) == len(rows)


def test_senate_day_index_real_values(jdir):
    rows = parse_day_index(jdir.joinpath("senate_jrnlData_89R.txt").read_bytes())
    assert len(rows) == 93
    assert rows[0]["file_id"] == "89RSJ01-14-F"
    assert rows[0]["calendar_date"] == "2025-01-14"
    assert rows[-1]["file_id"] == "89RSJ06-02-F"
    assert rows[-1]["leg_day"] == "49th"
    # Legislative day != calendar day (audit trap #1): a "1st Cont." sits on a
    # later calendar date than the "1st".
    conts = [r for r in rows if r["leg_day"] == "1st Cont."]
    assert conts and conts[0]["calendar_date"] > rows[0]["calendar_date"]


def test_day_index_pre_80r_naming():
    """76R rows carry id='1stDay' and lowercase day01 hrefs in HTML-then-PDF
    order; the file stem must come from the href, not the grid id."""
    payload = (
        b'{"page":"1","total":1,"records":"2","rows":['
        b'{"id":"1stDay","cell":["Tuesday, January 12,1999","1999-01-12","1999-01-01",'
        b'"1st Day","001-020","<a href=\\"/hjrnl/76r/html/day01.htm\\">HTML</a>&nbsp;'
        b'<a href=\\"/hjrnl/76r/pdf/day01.pdf\\">PDF</a>"]}]}'
    )
    rows = parse_day_index(payload)
    assert rows[0]["file_id"] == "day01"
    assert rows[0]["page_start"] == 1 and rows[0]["page_end"] == 20
    assert rows[0]["html_url"] == "/hjrnl/76r/html/day01.htm"


# -------------------------------------------------------------- text

def test_hard_return_splits_header(house_day):
    text = html_to_text(house_day)
    # <br class="hardReturn"> must become a newline or the two header lines
    # weld into "RULES SUSPENDEDADDITIONAL SPONSORS AUTHORIZED".
    assert "SUSPENDEDADDITIONAL" not in text
    assert "SB 31 - RULES SUSPENDED\nADDITIONAL SPONSORS AUTHORIZED" in text


def test_find_bill_strips_committee_substitute():
    assert find_bill("CSSB 379, as amended, was passed to third reading") == "SB379"
    assert find_bill("HOUSE BILL 1275 ON THIRD READING") == "HB1275"
    assert find_bill("The motion prevailed.") is None


# ---------------------------------------------------------- segmenter

def test_segment_day_house(house_day):
    segments = segment_day(html_to_text(house_day))
    kinds = {s.kind for s in segments}
    assert {"bill_action", "point_of_order", "statement_of_vote", "message"} <= kinds
    assert any(s.header == "SB 11 ON SECOND READING" for s in segments)

    # A point of order / leave of absence interrupts a bill's consideration;
    # the segments after it must still resolve to the same bill and reading.
    sb11 = [s for s in segments if s.bill == "SB11"]
    assert len(sb11) > 3
    assert all(s.reading == "second" for s in sb11)


# -------------------------------------------------- vote roll (House)

def test_house_record_vote_3200(house_day):
    votes = {v.record_no: v for v in parse_votes(html_to_text(house_day), "house")}
    assert "3200" in votes
    v = votes["3200"]
    assert v.bill == "SB269"
    assert v.question.startswith("SB 269 was passed by (Record 3200)")
    assert v.tallies == {"yea": 104, "nay": 37, "pnv": 3}

    by_pos: dict[str, list[str]] = {}
    for name, pos in v.casts:
        by_pos.setdefault(pos, []).append(name)
    # name_raw exactly as printed, disambiguators intact
    assert "Bell, C." in by_pos["yea"] and "Bell, K." in by_pos["yea"]
    assert by_pos["pnv"] == ["Mr. Speaker", "Morales Shaw", "Vasut(C)"]  # (C) = in the chair
    assert by_pos["absent_excused"] == ["Gervin-Hawkins", "LaHood"]
    assert by_pos["absent"] == ["Capriglione", "Dutton", "Flores", "Orr"]


def test_tally_equals_named_yeas(house_day):
    """The correctness proof: reported tally == number of names parsed."""
    votes = {v.record_no: v for v in parse_votes(html_to_text(house_day), "house")}
    v = votes["3200"]
    yea_names = [n for n, pos in v.casts if pos == "yea"]
    assert v.tallies["yea"] == 104
    assert len(yea_names) == 104
    assert len(set(yea_names)) == 104          # no duplicates
    assert v.tallies["nay"] == len([n for n, p in v.casts if p == "nay"]) == 37
    assert v.tallies["pnv"] == len([n for n, p in v.casts if p == "pnv"]) == 3


def test_every_house_tally_matches_its_named_list(house_day):
    votes = parse_votes(html_to_text(house_day), "house")
    assert len(votes) == 112                    # 111 record votes + the quorum roll call
    assert sum(len(v.casts) for v in votes) == 16800
    checked = 0
    for v in votes:
        for _pos, (reported, named) in v.tally_check().items():
            assert reported == named, (v.record_no, _pos, reported, named)
            checked += 1
    assert checked == 294                       # every tallied+listed position on the day


def test_house_quorum_roll_call(house_day):
    votes = {v.record_no: v for v in parse_votes(html_to_text(house_day), "house")}
    quorum = votes["3193"]
    assert quorum.tallies == {}                 # announced, not tallied
    assert len(quorum.casts) == 150
    assert quorum.casts[0] == ("Mr. Speaker(C)", "present")


# -------------------------------------------------- vote roll (Senate)

def test_senate_votes(senate_day):
    votes = parse_votes(html_to_text(senate_day), "senate")
    assert len(votes) == 82
    hb1275 = [v for v in votes if v.bill == "HB1275"]
    assert len(hb1275) == 2

    suspend, passage = hb1275
    assert suspend.record_no is None            # the Senate prints no record number
    assert suspend.tallies == {"yea": 27, "nay": 4}
    yeas = [n for n, p in suspend.casts if p == "yea"]
    assert len(yeas) == 27 == suspend.tallies["yea"]
    assert "A. Hinojosa" in yeas and "J. Hinojosa" in yeas   # surname disambiguation
    assert [n for n, p in suspend.casts if p == "nay"] == [
        "Hagenbuch", "Hughes", "Middleton", "Parker",
    ]
    # "(Same as previous roll call)" reuses the preceding named lists.
    assert passage.same_as_previous
    assert passage.casts == suspend.casts


def test_senate_partial_lists_are_not_mismatches(senate_day):
    """Near-unanimous Senate votes print only the minority list; that is a
    formatting fact, so tally_check reports nothing for the unlisted side."""
    votes = parse_votes(html_to_text(senate_day), "senate")
    partial = [
        v for v in votes if v.tallies.get("yea") == 30 and v.tallies.get("nay") == 1 and v.casts
    ]
    assert partial
    v = partial[0]
    assert [n for n, p in v.casts if p == "nay"] == ["Hall"]
    assert "yea" not in v.tally_check()
    for _pos, (reported, named) in v.tally_check().items():
        assert reported == named
    for v in votes:
        for _pos, (reported, named) in v.tally_check().items():
            assert reported == named


# ---------------------------------------------------------- amendments

def test_house_amendments(house_day):
    amendments = parse_amendments(html_to_text(house_day), "house")
    assert len(amendments) == 24
    by_key = {(a["bill"], a["number"]): a for a in amendments}

    tabled = by_key[("SB1188", "8")]
    assert tabled["author_raw"] == "J. Jones"
    assert tabled["disposition"] == "tabled"    # via "moved to table" + "prevailed"
    assert tabled["record_no"] == "3231"
    assert tabled["reading"] == "second"

    adopted = by_key[("SB379", "1")]
    assert adopted["author_raw"] == "Gerdes"
    assert adopted["disposition"] == "adopted"

    record_adopted = by_key[("SB1188", "1")]
    assert record_adopted["disposition"] == "adopted"
    assert record_adopted["record_no"] == "3224"

    assert {a["disposition"] for a in amendments} <= {"adopted", "failed", "tabled", None}


def test_senate_amendments(senate_day):
    amendments = parse_amendments(html_to_text(senate_day), "senate")
    assert amendments
    hb114 = [a for a in amendments if a["bill"] == "HB114"]
    assert hb114 and hb114[0]["author_raw"] == "Blanco"   # offer line precedes the head
    assert hb114[0]["disposition"] == "adopted"           # 'deemed to have voted "Yea"'
    assert all(a["chamber"] == "S" for a in amendments)


# -------------------------------------------------------------- storage

def _store(conn, chamber, file_id, raw, day):
    code = "H" if chamber == "house" else "S"
    doc_id = f"journals:{code}:89R:{file_id}"
    dbx.ensure_session(conn, "89R")
    store_document(
        conn,
        doc_id=doc_id,
        source_family="journals",
        content=raw,
        doc_type="journal_day_html",
        session_id="89R",
        authority="A",
    )
    stats = store_day(conn, chamber, "89R", file_id, parse_day(raw, chamber), doc_id, day)
    conn.commit()
    return doc_id, stats


def test_store_day_writes_votes_casts_edges(conn, house_day):
    day = {"calendar_date": "2025-05-22", "page_start": 5579, "page_end": 5708}
    doc_id, stats = _store(conn, "house", "89RDAY70FINAL", house_day, day)
    assert stats == {"votes": 112, "casts": 16800, "amendments": 24}

    row = conn.execute("SELECT * FROM vote WHERE id='89R-H-R3200'").fetchone()
    assert row["bill_id"] == "89R-SB269"
    assert (row["yeas"], row["nays"], row["pnv"]) == (104, 37, 3)
    assert row["absent"] == 6            # 4 absent + 2 absent/excused, from the lists
    assert row["journal_cite"] == "89 H. Jour. 5579-5708 (2025)"
    assert row["doc_id"] == doc_id
    assert row["date"] == "2025-05-22"

    named = conn.execute(
        "SELECT COUNT(*) AS n FROM vote_cast WHERE vote_id='89R-H-R3200' AND position='yea'"
    ).fetchone()["n"]
    assert named == row["yeas"] == 104   # the same proof, through the database

    assert conn.execute(
        "SELECT COUNT(*) AS n FROM vote_cast WHERE name_raw='Bell, C.'"
    ).fetchone()["n"] > 0

    edges = conn.execute(
        """SELECT COUNT(*) AS n FROM edge
           WHERE predicate='cast_vote' AND src_type='person_name' AND dst_type='vote'
             AND provenance='explicit' AND source_doc=?""",
        (doc_id,),
    ).fetchone()["n"]
    assert edges == 16800

    amd = conn.execute(
        "SELECT * FROM amendment WHERE bill_id='89R-SB1188' AND number='8'"
    ).fetchone()
    assert amd["disposition"] == "tabled" and amd["author_raw"] == "J. Jones"
    assert amd["journal_cite"] == "89 H. Jour. 5579-5708 (2025)"


def test_store_day_is_idempotent(conn, house_day):
    day = {"calendar_date": "2025-05-22", "page_start": 5579, "page_end": 5708}
    _store(conn, "house", "89RDAY70FINAL", house_day, day)
    counts = lambda t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]  # noqa: E731
    before = (counts("vote"), counts("vote_cast"), counts("edge"), counts("amendment"))
    _store(conn, "house", "89RDAY70FINAL", house_day, day)
    assert (counts("vote"), counts("vote_cast"), counts("edge"), counts("amendment")) == before


def test_senate_vote_ids_are_synthesized(conn, senate_day):
    day = {"calendar_date": "2025-05-21", "page_start": 2323, "page_end": 2365}
    _store(conn, "senate", "89RSJ05-21-F", senate_day, day)
    ids = [
        r["id"] for r in conn.execute("SELECT id FROM vote WHERE chamber='S' ORDER BY id LIMIT 3")
    ]
    assert ids[0].startswith("89R-S-89RSJ05-21-F-")
    assert vote_id("89R", "senate", None, "89RSJ05-21-F", 7) == "89R-S-89RSJ05-21-F-007"
    assert vote_id("89R", "house", "3200", "x", 1) == "89R-H-R3200"
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM vote WHERE chamber='S' AND record_no IS NULL"
    ).fetchone()["n"] == 82


def test_journal_day_table_registered(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(journal_day)")}
    assert {"chamber", "session_id", "file_id", "calendar_date", "leg_day", "doc_id"} <= cols


# ------------------------------------------------------------------ live

@pytest.mark.live
def test_smoke_live(conn):
    result = JournalsConnector().smoke(conn)
    assert result.ok, result.detail
    stats = result.stats
    assert stats["days_indexed"] >= 90
    assert stats["votes"] >= 1
    assert stats["casts"] >= 50
    assert stats["top_yeas_reported"] == stats["top_yeas_named"]
