"""Committees connector tests.

Offline assertions are pinned to *real* values read out of the saved fixtures —
actual witness names, orgs and positions from both witness-list eras, and an
actual committee roll call — so a parser regression fails loudly instead of
silently returning an empty list.
"""

from __future__ import annotations

import pytest

from lobbybook.sources import committees as C

MODERN_PDF = "witlist_89R_C4502025082208001.pdf"      # 89R State Affairs, 8/22/2025
ERA_HTML = "witlist_76R_C5701999031812301.htm"        # 76R State Affairs, 3/18/1999
MINUTES_HTML = "minutes_87R_C3952021041608001.htm"    # 87R Pensions, 4/16/2021
MEETINGS_JSON = "committee_meetings_89_H_450.json"
VIDEOS_JSON = "video_events_89_R_committee.json"


@pytest.fixture()
def cdir(fixtures):
    return fixtures / "committees"


def _read(cdir, name: str) -> bytes:
    return (cdir / name).read_bytes()


# ------------------------------------------------------------ House JSON API


def test_committee_meetings_parser(cdir):
    meetings = C.parse_committee_meetings(_read(cdir, MEETINGS_JSON), 89)
    assert len(meetings) == 40

    first = meetings[0]
    assert first["committee_code"] == "C450"
    assert first["committee_name"] == "State Affairs"
    assert first["chamber"] == "H"
    assert first["date"] == "2025-03-05"
    assert first["scheduled_at"] == "2025-03-05T08:00"
    assert first["location"] == "JHR 140"
    assert first["hearing_id"] == "C4502025030508001"
    assert first["minutes"].endswith("/minutes/html/C4502025030508001.htm")

    by_id = {m["hearing_id"]: m for m in meetings}
    target = by_id[C.VERIFIED_WITNESS_TOKEN]
    assert target["date"] == "2025-08-22"
    assert target["witnesses"].endswith("witlistmtg/html/C4502025082208001.htm")
    assert target["handouts"] is None      # nulls stay null, not ""

    # Session codes span the whole biennium: an Aug-2026 meeting is still 89R.
    interim = by_id["C4502026081908001"]
    assert interim["date"] == "2026-08-19" and interim["session"] == "89R"
    assert all(m["session"] == "89R" for m in meetings)


def test_pdf_witness_url_derivation():
    assert C.pdf_witness_url(
        "http://capitol.texas.gov/tlodocs/89R/witlistmtg/html/C4502025082208001.htm"
    ) == "http://capitol.texas.gov/tlodocs/89R/witlistmtg/pdf/C4502025082208001.PDF"


def test_video_events_parser(cdir):
    events = C.parse_video_events(_read(cdir, VIDEOS_JSON), "89R")
    assert len(events) == 50
    top = events[0]
    assert top["id"] == 22754
    assert top["kind"] == "committee"
    assert top["title"] == "Trade, Workforce & Economic Development"
    assert top["event_date"] == "2026-08-26"          # two-digit year expands to 20xx
    assert top["video_url"].endswith("/22754/44811/index.m3u8")
    assert top["has_captions"] == 1
    assert top["session"] == "89R"
    # Captions are recent and partial — the flag is per-event, never assumed.
    assert 0 < sum(e["has_captions"] for e in events) <= len(events)


# ------------------------------------------------- witness lists, modern era


def test_witness_pdf_modern_real_values(cdir):
    wl = C.parse_witness_list(_read(cdir, MODERN_PDF))
    assert wl.era == "modern"
    assert wl.committee == "State Affairs Committee"
    assert wl.date_raw.startswith("August 22, 2025")
    assert wl.bills() == ["HB7", "SB8"]               # per-meeting, multi-bill
    assert len(wl.rows) == 969

    rows = {(r["bill"], r["name_raw"]): r for r in wl.rows}

    # The Self + org co-occurrence: BOTH flags set, not one or the other.
    seago = rows[("HB7", "Seago, John")]
    assert seago["is_self"] == 1
    assert seago["org_raw"] == "Texas Right to Life"
    assert seago["position"] == "for" and seago["testified"] == 1

    # Org only, no Self.
    milligan = rows[("HB7", "Milligan, Maureen")]
    assert milligan["is_self"] == 0
    assert milligan["org_raw"] == "Teaching hospitals of Texas"
    assert milligan["position"] == "on" and milligan["testified"] == 0

    # Self only.
    assert rows[("HB7", "Howell, Todd")] == {
        "bill": "HB7", "name_raw": "Howell, Todd", "org_raw": None, "is_self": 1,
        "position": "for", "channel": "testified", "testified": 1, "city": None,
    }

    # Nested parentheses inside the affiliation survive intact.
    assert rows[("SB8", "Wilmore Crumrine, Michael")]["org_raw"] == (
        "Lesbian and Gay Peace Officers Association (LGPOA)"
    )
    # A surname with no given name still parses.
    assert rows[("HB7", "Aderholt")]["is_self"] == 1

    # 'Against' opposite of the same org string on the same bill.
    assert rows[("HB7", "Wright, Kyleen")]["org_raw"] == "Texans for Life"
    assert rows[("HB7", "Wright, Kyleen")]["position"] == "against"
    assert rows[("HB7", "Furnace, Samantha")]["org_raw"] == "Texas Right to Life"
    assert rows[("HB7", "Furnace, Samantha")]["position"] == "for"

    hb7 = [r for r in wl.rows if r["bill"] == "HB7"]
    assert sum(1 for r in hb7 if r["testified"]) == 30
    assert sum(1 for r in hb7 if not r["testified"]) == 411
    assert {r["position"] for r in wl.rows} == {"for", "against", "on"}
    # The 'Registering, but not testifying' state is sticky across page breaks:
    # 'Against:' repeats on every continuation page and must not flip it back.
    assert all(not r["testified"] for r in hb7 if r["channel"] == "registered")


# --------------------------------------------------- witness lists, 1999 era


def test_witness_html_1999_real_values(cdir):
    wl = C.parse_witness_list(_read(cdir, ERA_HTML))
    assert wl.era == "1999"
    assert wl.committee == "State Affairs Committee"
    assert wl.date_raw == "March 18, 1999-12:30P"
    assert wl.bills()[:4] == ["SB29", "SB239", "SB411", "SB483"]
    assert len(wl.rows) == 122

    rows = {(r["bill"], r["name_raw"]): r for r in wl.rows}

    hubbarth = rows[("SB29", "Hubbarth, William")]
    assert hubbarth["org_raw"] == "Justice for All"
    assert hubbarth["position"] == "for" and hubbarth["city"] == "Austin"

    gladden = rows[("SB29", "Gladden, Greg")]
    assert gladden["org_raw"] == "ACLU of Texas" and gladden["position"] == "against"

    # Org wrapped across two physical lines at a deep indent.
    dudley = rows[("SB29", "Dudley, Harold K. Jr.")]
    assert dudley["org_raw"] == "Texas Department of Mental Health & Mental Retardation"
    assert dudley["position"] == "on" and dudley["city"] == "Austin"

    # 'Self & Other Crime Victims' — Self plus an org in one field again.
    day = rows[("SB29", "Day, Patricia A.")]
    assert day["is_self"] == 1 and day["org_raw"] == "Other Crime Victims"
    assert day["testified"] == 0 and day["channel"] == "registered"

    # 'Written materials submitted' is a third channel, also non-testifying.
    mitchell = rows[("SB29", "Mitchell, Beth")]
    assert mitchell["channel"] == "written" and mitchell["testified"] == 0
    assert mitchell["position"] == "against"

    # City wrapped onto the continuation line.
    assert rows[("SB884", "Tucker, Jeffrey A.")]["city"] == "Houston"

    # A bill whose only rows are registrations still gets its section.
    sb770 = [r for r in wl.rows if r["bill"] == "SB770"]
    assert len(sb770) == 2 and all(r["position"] == "on" and not r["testified"] for r in sb770)


def test_parse_affiliation_variants():
    assert C.parse_affiliation("Self") == (1, None)
    assert C.parse_affiliation("Texas Right to Life") == (0, "Texas Right to Life")
    assert C.parse_affiliation("Self; Texas Right to Life") == (1, "Texas Right to Life")
    assert C.parse_affiliation("Self & Other Crime Victims") == (1, "Other Crime Victims")
    assert C.parse_affiliation("Catholic Diocese of Fort Worth, Texas Catholic Conference") == (
        0, "Catholic Diocese of Fort Worth, Texas Catholic Conference"
    )


# ----------------------------------------------------------------- minutes


def test_minutes_record_votes_real_values(cdir):
    votes = C.parse_minutes(_read(cdir, MINUTES_HTML))
    assert len(votes) == 6

    # Every tally must equal the number of names actually listed.
    for v in votes:
        assert v["n_ayes"] == len(v["ayes"]), v
        assert v["n_nays"] == len(v["nays"]), v
        assert v["n_pnv"] == len(v["pnv"]) and v["n_absent"] == len(v["absent"])

    by_bill = {}
    for v in votes:
        by_bill.setdefault(v["bill"], []).append(v)

    split = by_bill["HB4108"][0]
    assert split["n_ayes"] == 6 and split["n_nays"] == 3
    assert split["ayes"] == ["Anchia", "Parker", "Muñoz, Jr.", "Perez", "Stephenson", "Vo"]
    assert split["nays"] == ["Capriglione", "Rogers", "Slawson"]
    assert "moved that HB 4108" in split["question"]

    unanimous = by_bill["HB4131"][0]
    assert unanimous["n_ayes"] == 9 and unanimous["nays"] == []

    # One bill, two record votes in one meeting (reconsidered) → distinct rows.
    assert [v["occurrence"] for v in by_bill["HB4307"]] == [1, 2]
    assert by_bill["HB4307"][0]["n_ayes"] == 8
    assert by_bill["HB4307"][1]["n_ayes"] == 9


def test_minutes_narrative_tally_format():
    """The alternate 'Ayes 6 (…); Nays 3 (…)' phrasing also parses."""
    text = (
        b"<html><body><p>The chair moved that HB 12 be reported favorably. "
        b"The motion prevailed by the following record vote: "
        b"Ayes 6 (Anchia, Parker, Perez, Stephenson, Vo, Turner); "
        b"Nays 3 (Capriglione, Rogers, Slawson)</p></body></html>"
    )
    votes = C.parse_minutes(text)
    assert len(votes) == 1
    v = votes[0]
    assert v["bill"] == "HB12"
    assert v["n_ayes"] == len(v["ayes"]) == 6
    assert v["n_nays"] == len(v["nays"]) == 3
    assert v["nays"] == ["Capriglione", "Rogers", "Slawson"]


# ------------------------------------------------------------ HLS / WebVTT


def test_hls_master_and_playlist(cdir):
    tracks = C.parse_hls_master(_read(cdir, "hls_master.m3u8"))
    assert len(tracks) == 1
    assert tracks[0] == {
        "uri": "index_2_0.m3u8",
        "name": "English",
        "language": "en",
        "group_id": "subtitles",
        "default": False,
    }
    segments = C.parse_hls_playlist(_read(cdir, "hls_subtitles.m3u8"))
    assert segments[:2] == ["index_2_0_345.vtt", "index_2_0_346.vtt"]
    assert all(s.endswith(".vtt") for s in segments)


def test_hls_master_without_subtitles():
    master = (
        "#EXTM3U\n"
        '#EXT-X-STREAM-INF:BANDWIDTH=100,RESOLUTION=1280x720,CODECS="avc1"\n'
        "index_1.m3u8\n"
    )
    assert C.parse_hls_master(master) == []


def test_vtt_parser(cdir):
    cues = C.parse_vtt(_read(cdir, "captions_sample.vtt"))
    assert len(cues) == 3
    assert cues[0] == {
        "start_ts": "00:00:12.000",
        "end_ts": "00:00:15.500",
        "text": ">> The chair calls Judge Angela Williams to the witness table.",
    }
    assert cues[1]["start_ts"] == "00:00:15.500"
    # Cue payload tags are stripped; the numeric cue id is not text.
    assert cues[2]["text"] == "Members, the bill is left pending."


def test_vtt_parser_on_live_segment(cdir):
    """A real harvested HLS subtitle segment (ASR output, cue settings, '>>')."""
    cues = C.parse_vtt(_read(cdir, "captions_live_segment.vtt"))
    assert len(cues) == 3
    assert cues[0]["start_ts"] == "01:09:17.146"
    assert cues[0]["end_ts"] == "01:09:23.706"
    assert cues[0]["text"].startswith(">> The Committee on Trade, Workforce and Economic Development")
    assert "X-TIMESTAMP-MAP" not in " ".join(c["text"] for c in cues)


def test_vtt_parser_handles_empty_segment():
    """Most captioned videos open with a cue-less segment — not an error."""
    assert C.parse_vtt(b"WEBVTT\tX\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:180000\n\n") == []


# ------------------------------------------------------------ storage layer


def test_store_meeting_and_witnesses_roundtrip(conn, cdir):
    meetings = C.parse_committee_meetings(_read(cdir, MEETINGS_JSON), 89)
    target = next(m for m in meetings if m["hearing_id"] == C.VERIFIED_WITNESS_TOKEN)
    hid = C.store_meeting(conn, target)
    assert hid == C.VERIFIED_WITNESS_TOKEN

    committee = conn.execute("SELECT * FROM committee").fetchone()
    assert committee["id"] == "89R-H-C450" and committee["name"] == "State Affairs"
    hearing = conn.execute("SELECT * FROM hearing WHERE id=?", (hid,)).fetchone()
    assert hearing["committee_id"] == "89R-H-C450"
    assert hearing["scheduled_at"] == "2025-08-22T08:00"

    wl = C.parse_witness_list(_read(cdir, MODERN_PDF))
    stats = C.store_witness_list(conn, hid, "89R", wl)
    assert stats["slips"] == 969 and stats["bills"] == 2

    n = conn.execute("SELECT COUNT(*) n FROM witness_slip WHERE hearing_id=?", (hid,)).fetchone()["n"]
    assert n == 969
    row = conn.execute(
        "SELECT * FROM witness_slip WHERE hearing_id=? AND name_raw='Seago, John'", (hid,)
    ).fetchone()
    assert row["bill_id"] == "89R-HB7" and row["is_self"] == 1
    assert row["org_raw"] == "Texas Right to Life" and row["position"] == "for"

    assert {r["bill_id"] for r in conn.execute("SELECT bill_id FROM hearing_bill WHERE hearing_id=?", (hid,))} == {
        "89R-HB7", "89R-SB8"
    }

    # person→testified/registered edges are explicit; org rollups are derived.
    explicit = conn.execute(
        "SELECT predicate FROM edge WHERE src_type='person_name' AND src_id='Seago, John'"
    ).fetchone()
    assert explicit["predicate"] == "testified_for"
    derived = conn.execute(
        "SELECT * FROM edge WHERE src_type='org_name' AND src_id='Texas Right to Life' "
        "AND dst_id='89R-HB7'"
    ).fetchall()
    assert derived and all(d["provenance"] == "derived" for d in derived)
    assert {d["predicate"] for d in derived} == {"registered_position_on_for"}

    # Re-ingesting the same document must not double the slips.
    C.store_witness_list(conn, hid, "89R", wl)
    n2 = conn.execute("SELECT COUNT(*) n FROM witness_slip WHERE hearing_id=?", (hid,)).fetchone()["n"]
    assert n2 == 969


def test_store_witnesses_keeps_1999_cities(conn, cdir):
    C.store_meeting(
        conn,
        {
            "committee_code": "C570", "committee_name": "State Affairs", "chamber": "S",
            "session": "76R", "date": "1999-03-18", "start": "12:30",
            "scheduled_at": "1999-03-18T12:30", "location": None, "canceled": False,
            "hearing_id": "C5701999031812301",
        },
    )
    wl = C.parse_witness_list(_read(cdir, ERA_HTML))
    C.store_witness_list(conn, "C5701999031812301", "76R", wl)
    row = conn.execute(
        "SELECT w.name_raw, w.org_raw, c.city FROM witness_slip w "
        "JOIN witness_slip_city c ON c.witness_slip_id = w.id "
        "WHERE w.name_raw='Hubbarth, William'"
    ).fetchone()
    assert row["org_raw"] == "Justice for All" and row["city"] == "Austin"


def test_store_minutes_votes_roundtrip(conn, cdir):
    C.store_meeting(
        conn,
        {
            "committee_code": "C395", "committee_name": "Pensions, Investments & Financial Services",
            "chamber": "H", "session": "87R", "date": "2021-04-16", "start": "08:00",
            "scheduled_at": "2021-04-16T08:00", "location": "E2.030", "canceled": False,
            "hearing_id": "C3952021041608001",
        },
    )
    votes = C.parse_minutes(_read(cdir, MINUTES_HTML))
    stats = C.store_minutes_votes(conn, "C3952021041608001", "87R", "H", "2021-04-16", votes)
    assert stats["votes"] == 6

    v = conn.execute("SELECT * FROM vote WHERE id='CMTE-C3952021041608001-HB4108'").fetchone()
    assert v["yeas"] == 6 and v["nays"] == 3 and v["bill_id"] == "87R-HB4108"
    assert v["chamber"] == "H" and v["date"] == "2021-04-16"

    casts = conn.execute(
        "SELECT name_raw, position FROM vote_cast WHERE vote_id=? ORDER BY position, name_raw",
        ("CMTE-C3952021041608001-HB4108",),
    ).fetchall()
    assert len(casts) == 9
    assert {c["name_raw"] for c in casts if c["position"] == "nay"} == {
        "Capriglione", "Rogers", "Slawson"
    }

    # The reconsidered second vote on the same bill gets its own id.
    assert conn.execute(
        "SELECT COUNT(*) n FROM vote WHERE bill_id='87R-HB4307'"
    ).fetchone()["n"] == 2
    assert conn.execute(
        "SELECT 1 FROM vote WHERE id='CMTE-C3952021041608001-HB4307-2'"
    ).fetchone()

    edges = conn.execute(
        "SELECT COUNT(*) n FROM edge WHERE predicate LIKE 'voted_%_in_committee'"
    ).fetchone()["n"]
    assert edges > 0


def test_store_video_events_and_captions(conn, cdir):
    events = C.parse_video_events(_read(cdir, VIDEOS_JSON), "89R")
    stats = C.store_video_events(conn, events)
    assert stats["events"] == 50 and stats["captioned"] > 0
    row = conn.execute("SELECT * FROM video_event WHERE id=22754").fetchone()
    assert row["has_captions"] == 1 and row["kind"] == "committee"

    cues = C.parse_vtt(_read(cdir, "captions_live_segment.vtt"))
    assert C.store_caption_segments(conn, 22754, cues) == 3
    C.store_caption_segments(conn, 22754, cues)     # idempotent
    n = conn.execute("SELECT COUNT(*) n FROM caption_segment WHERE video_id=22754").fetchone()["n"]
    assert n == 3


def test_harvest_captions_skips_uncaptioned(conn):
    """No network call at all when the API says the video has no captions."""
    r = C.CommitteesConnector().harvest_captions(
        conn, {"id": 1, "video_url": "https://example.invalid/x.m3u8", "has_captions": 0}
    )
    assert r["captions"] is False and r["cues"] == 0
    r = C.CommitteesConnector().harvest_captions(conn, {"id": 2, "video_url": None, "has_captions": 1})
    assert r["captions"] is False and r["reason"] == "no videoUrl"


def test_connector_registered():
    from lobbybook.core.registry import get, names

    assert "committees" in names()
    c = get("committees")
    assert c.tier == 0 and c.name == "committees"


# ---------------------------------------------------------------- live


@pytest.mark.live
def test_committees_live_smoke(conn):
    from lobbybook.core.registry import get

    r = get("committees").smoke(conn)
    assert r.ok, r.detail
    assert r.stats["witness_slips"] >= 5
    assert set(r.stats["positions"]) <= {"for", "against", "on"}
    assert r.stats["meetings"] > 0 and r.stats["video_events"] > 0
