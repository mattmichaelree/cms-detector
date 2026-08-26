"""TEC connector tests.

Offline tests run against verbatim slices of the real bulk exports (see
fixtures/tec/PROVENANCE.txt) and assert *real* values: the 139 members and
9.13 GB uncompressed total of the live campaign-finance archive, the record
types and field order documented in CFS-ReadMe.txt, the 20 expenditure
category codes, real subject-matter codes, and the actual amendment flags on
real contribution rows. A parser that returns plausibly-shaped garbage fails
here.

Live tests are opt-in (LOBBYBOOK_LIVE=1) and bounded: the search pages are
resolved once and cached for the module, and the 17 MB lobby ZIP is the only
whole download.
"""

from __future__ import annotations

import zipfile

import pytest

from lobbybook.sources import tec

#: The CF archive's byte length when fixtures/tec/cf_zip_tail.bin was captured.
#: Absolute central-directory offsets are meaningless without it.
CF_ZIP_SIZE_AT_CAPTURE = 1_040_878_113


def _fx(fixtures, name: str) -> bytes:
    return (fixtures / "tec" / name).read_bytes()


# ------------------------------------------------------------ URL resolution
def test_resolves_cloudfront_zip_and_ignores_the_commented_out_dead_link(fixtures):
    """The CF search page carries two TEC_CF_CSV.zip hrefs: the live
    CloudFront one and a commented-out /data/search/cf/ one that 404s."""
    html = _fx(fixtures, "cf_search.html")
    found = tec.find_bulk_zip(html, "TEC_CF_CSV.zip", tec.CF_SEARCH)
    assert found["url"] == (
        "https://prd.tecprd.ethicsefile.com/public/cf/public/TEC_CF_CSV.zip"
    )
    assert "/data/search/cf/" not in found["url"]
    assert found["as_of"] == "08/25/2026"
    assert found["as_of_iso"] == "2026-08-25"
    assert found["label"] == "Campaign Finance CSV Database (As of 08/25/2026)"

    # ...and the dead link is only invisible because comments are stripped.
    raw = html.decode("utf-8", errors="replace")
    assert "/data/search/cf/TEC_CF_CSV.zip" in raw
    assert "/data/search/cf/TEC_CF_CSV.zip" not in tec.strip_comments(raw)


def test_resolves_lobby_zip(fixtures):
    found = tec.find_bulk_zip(_fx(fixtures, "lobby_search.html"), "TEC_LA_CSV.zip",
                              tec.LOBBY_SEARCH)
    assert found["url"] == (
        "https://prd.tecprd.ethicsefile.com/public/lobby/public/TEC_LA_CSV.zip"
    )
    assert found["as_of"] == "08/25/2026"


def test_missing_zip_link_is_none_not_a_guess(fixtures):
    assert tec.find_bulk_zip(b"<html><a href='/x.pdf'>x</a></html>", "TEC_CF_CSV.zip") is None


# --------------------------------------------------- ZIP central directory
def test_central_directory_of_the_real_1gb_archive(fixtures):
    """The whole point of the prober: 139 members and their offsets read out
    of 32 KB, without touching the other 1.04 GB."""
    tail = _fx(fixtures, "cf_zip_tail.bin")
    eocd = tec.parse_eocd(tail, CF_ZIP_SIZE_AT_CAPTURE)
    assert eocd["entries"] == 139
    assert eocd["cd_size"] == 8355
    assert eocd["zip64"] is False

    start = eocd["cd_offset"] - eocd["tail_start"]
    assert start >= 0, "central directory should fall inside a 32 KB tail"
    members = tec.parse_central_directory(tail[start : start + eocd["cd_size"]])
    assert len(members) == 139
    # 9.13 GB uncompressed, exactly as the audit measured.
    assert sum(m.uncompressed_size for m in members) == 9_130_153_578

    by_name = {m.name: m for m in members}
    assert by_name["expn_catg.csv"].uncompressed_size == 861
    assert by_name["expn_catg.csv"].compressed_size == 450
    assert by_name["CFS-ReadMe.txt"].uncompressed_size == 140_280
    assert all(m.method == 8 for m in members), "all members are deflate"

    # The shard families that make the corpus what it is.
    assert len([n for n in by_name if n.startswith("contribs_")]) == 103
    assert {"cont_ss.csv", "cont_t.csv"} <= set(by_name)
    assert by_name["cover.csv"].uncompressed_size > 190_000_000  # ~195 MB


def test_eocd_needs_the_real_file_size(fixtures):
    """tail_start is what maps absolute offsets into the fetched slice; a
    wrong file size must not silently yield a plausible-looking directory."""
    tail = _fx(fixtures, "cf_zip_tail.bin")
    eocd = tec.parse_eocd(tail, CF_ZIP_SIZE_AT_CAPTURE)
    assert eocd["tail_start"] == CF_ZIP_SIZE_AT_CAPTURE - len(tail)
    wrong = tec.parse_eocd(tail, CF_ZIP_SIZE_AT_CAPTURE + 1_000_000)
    assert wrong["cd_offset"] - wrong["tail_start"] < 0


def test_eocd_rejects_bytes_with_no_directory():
    with pytest.raises(ValueError):
        tec.parse_eocd(b"not a zip at all", 16)


def test_local_header_offset_and_inflate_roundtrip(tmp_path):
    """Ranged extraction must read the *local* header: its name/extra lengths
    differ from the central directory's, and assuming otherwise is the classic
    off-by-a-few-bytes bug."""
    path = tmp_path / "t.zip"
    payload = b"recordType,x\nRCPT,1\n" * 500
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("a.csv", payload)
        z.writestr("b.csv", b"second member")
    blob = path.read_bytes()

    eocd = tec.parse_eocd(blob, len(blob))
    members = tec.parse_central_directory(
        blob[eocd["cd_offset"] : eocd["cd_offset"] + eocd["cd_size"]]
    )
    assert [m.name for m in members] == ["a.csv", "b.csv"]

    m = members[0]
    data_off = tec.local_data_offset(blob[m.header_offset : m.header_offset + 30], m.header_offset)
    assert data_off > m.header_offset + 30
    out = tec.inflate_member(blob[data_off : data_off + m.compressed_size], m.method)
    assert out == payload


def test_inflate_rejects_unknown_method():
    with pytest.raises(ValueError):
        tec.inflate_member(b"\x00", 99)


def test_diff_members_is_the_nightly_change_signal(fixtures):
    tail = _fx(fixtures, "cf_zip_tail.bin")
    eocd = tec.parse_eocd(tail, CF_ZIP_SIZE_AT_CAPTURE)
    start = eocd["cd_offset"] - eocd["tail_start"]
    members = tec.parse_central_directory(tail[start : start + eocd["cd_size"]])

    grown = [
        tec.ZipMember(m.name, m.method, m.compressed_size + 10,
                      m.uncompressed_size + 100, m.header_offset, m.crc32 ^ 1)
        if m.name == "contribs_01.csv" else m
        for m in members
        if m.name != "travel.csv"
    ]
    grown.append(tec.ZipMember("contribs_104.csv", 8, 1, 2, 3, 4))

    diff = tec.diff_members(members, grown)
    assert diff["changed"] == ["contribs_01.csv"]
    assert diff["removed"] == ["travel.csv"]
    assert diff["added"] == ["contribs_104.csv"]
    assert len(diff["unchanged"]) == 137


# ------------------------------------------------------------- the readmes
def test_cfs_readme_record_types(fixtures):
    """The record layout spec is the contract every shard must satisfy."""
    records = tec.parse_readme_records(_fx(fixtures, "CFS-ReadMe.txt"))
    names = [r["record_name"] for r in records]
    for expected in (
        "AssetData", "CandidateData", "ContributionData", "CoverSheet1Data",
        "CoverSheet2Data", "CoverSheet3Data", "CreditData", "DebtData",
        "ExpendData", "ExpendCategory", "FilerData", "FinalData", "LoanData",
        "PledgeData", "SpacData", "TravelData",
    ):
        assert expected in names
    # The summary table at the top of the file lists 16 record types, but the
    # detail section documents 17: ExpendRepayment has a layout and no entry
    # in the listing. Trusting the listing would lose a record type.
    assert len(records) == 17
    assert "ExpendRepayment" in names

    contribs = next(r for r in records if r["record_name"] == "ContributionData")
    assert contribs["length"] == 1426
    assert contribs["files"] == ["contribs_##.csv", "cont_ss.csv", "cont_t.csv"]
    assert len(contribs["fields"]) == 37
    # The readme states the double-count rule itself.
    assert "to avoid creating duplicates" in contribs["description"]
    assert "re-reported on the next regular campaign finance report" in contribs["description"]

    fields = {f["name"]: f for f in contribs["fields"]}
    assert fields["infoOnlyFlag"]["description"].startswith("Superseded by other report")
    assert (fields["infoOnlyFlag"]["start"], fields["infoOnlyFlag"]["length"]) == (80, 1)
    assert (fields["contributionAmount"]["start"], fields["contributionAmount"]["length"]) == (430, 12)
    assert fields["filerIdent"]["description"] == "Filer account #"


def test_readme_names_files_the_archive_does_not_ship(fixtures):
    """Documentation drift, measured rather than assumed: the readme's summary
    table names returns.csv and final.csv; the live archive ships neither
    (finals.csv is the real name). An ingester that trusts the readme's file
    list would look for members that are not there."""
    tail = _fx(fixtures, "cf_zip_tail.bin")
    eocd = tec.parse_eocd(tail, CF_ZIP_SIZE_AT_CAPTURE)
    start = eocd["cd_offset"] - eocd["tail_start"]
    shipped = {m.name for m in tec.parse_central_directory(
        tail[start : start + eocd["cd_size"]]
    )}
    readme = _fx(fixtures, "CFS-ReadMe.txt").decode("utf-8", errors="replace")
    assert "returns.csv" in readme and "returns.csv" not in shipped
    assert "final.csv" in readme and "final.csv" not in shipped
    assert "finals.csv" in shipped


def test_contribs_header_matches_the_documented_field_order(fixtures):
    """A shard whose columns drifted from the spec would be silently
    mis-parsed by position; assert the two agree."""
    records = tec.parse_readme_records(_fx(fixtures, "CFS-ReadMe.txt"))
    documented = [
        f["name"] for f in next(
            r for r in records if r["record_name"] == "ContributionData"
        )["fields"]
    ]
    header = _fx(fixtures, "contribs_sample.csv").split(b"\n", 1)[0].decode().strip().split(",")
    assert header == documented


def test_lobby_readme_records_and_the_drop_semantics(fixtures):
    """LobbyLAR-ReadMe.txt has no Start column at all — the field-table parser
    must read its own header, not assume the CF layout."""
    data = _fx(fixtures, "LobbyLAR-ReadMe.txt")
    records = tec.parse_readme_records(data)
    names = [r["record_name"] for r in records]
    assert names == [
        "CoverSheetLaData", "IndividualReportingData", "SubjectMatterData",
        "DocketData", "TransportationData", "FoodBeverageData",
        "EntertainmentData", "GiftData", "AwardMementoData", "EventData",
    ]
    sub = next(r for r in records if r["record_name"] == "SubjectMatterData")
    assert sub["files"] == ["LaSub.csv"]
    assert [f["name"] for f in sub["fields"]][:6] == [
        "recordType", "formTypeCd", "reportTypeCd", "reportInfoIdent",
        "applicableYear", "filerIdent",
    ]
    # The divergent amendment convention, stated by TEC itself.
    text = data.decode("utf-8", errors="replace")
    assert "superseded by corrected reports is not included" in text


def test_lasub_header_matches_the_documented_field_order(fixtures):
    records = tec.parse_readme_records(_fx(fixtures, "LobbyLAR-ReadMe.txt"))
    documented = [
        f["name"] for f in next(
            r for r in records if r["record_name"] == "SubjectMatterData"
        )["fields"]
    ]
    header = _fx(fixtures, "LaSub_sample.csv").split(b"\n", 1)[0].decode().strip().split(",")
    assert header == documented


# ------------------------------------------------------ expenditure codebook
def test_expenditure_categories(fixtures):
    """expn_catg.csv is 21 lines: a header plus the closed 20-code
    expenditure vocabulary."""
    raw = _fx(fixtures, "expn_catg.csv")
    assert len(raw.decode().strip().splitlines()) == 21
    cats = tec.parse_expn_catg(raw)
    assert len(cats) == 20
    by_code = {c["code"]: c["label"] for c in cats}
    assert by_code["FOOD"] == "Food/Beverage Expense"
    assert by_code["POLLING"] == "Polling Expense"
    assert by_code["TRAVELIN"] == "Travel In District"
    assert by_code["TRAVELOUT"] == "Travel Out of District"
    assert by_code["DONATIONS"] == (
        "Contributions/Donations Made By Candidate/Officeholder/Political Committee"
    )
    assert cats[0] == {"code": "ACCOUNT", "label": "Accounting/Banking"}


def test_expend_categories_load(conn, fixtures):
    n = tec.TECConnector().load_expend_categories(conn, _fx(fixtures, "expn_catg.csv"))
    assert n == 20
    row = conn.execute(
        "SELECT label FROM tec_expend_category WHERE code='CREDITCARD'"
    ).fetchone()
    assert row["label"] == "Credit Card Payment"


# ------------------------------------------------------------- contributions
def test_schedule_tagging_from_filename():
    assert tec.schedule_for("contribs_01.csv") == "main"
    assert tec.schedule_for("contribs_103.csv") == "main"
    assert tec.schedule_for("cont_ss.csv") == "ss"
    assert tec.schedule_for("cont_t.csv") == "t"
    assert tec.schedule_for("/tmp/x/cont_t.csv") == "t"
    assert tec.schedule_for("returns.csv") == "main"


def test_filer_ids_are_eight_digit_zero_padded():
    assert tec.filer_id("13805") == "00013805"
    assert tec.filer_id("00010883") == "00010883"
    assert tec.filer_id("") is None


def test_parse_real_contribution_rows(fixtures):
    rows = tec.parse_contribs(_fx(fixtures, "contribs_sample.csv"), "contribs_01.csv")
    assert len(rows) == 140
    first = rows[0]
    assert first == {
        "id": 100000001,
        "filer_id": "00010883",
        "report_id": "730",
        "contributor_raw": "JAMES H. LYTAL",
        "employer_raw": "THE EL PASO ENERGY CORPORATION",
        "amount": 90.0,
        "date": "2000-05-30",
        "superseded": 0,
        "schedule": "main",
        "form_type": "MPAC",
        "sched_form_type": "A1",
        "filer_type": "MPAC",
        "received_dt": "2000-07-05",
        "is_correction": 0,
        "source_file": "contribs_01.csv",
    }
    # infoOnlyFlag='Y' is a real superseded row, not an inference.
    superseded = {r["id"]: r for r in rows if r["superseded"]}
    assert 100000004 in superseded
    assert superseded[100000004]["contributor_raw"] == "JANICE ALPERIN"
    assert superseded[100000004]["amount"] == 1500.0
    # COR* form types are correction affidavits.
    corrections = [r for r in rows if r["is_correction"]]
    assert corrections and all(r["form_type"].startswith("COR") for r in corrections)
    assert 100000012 in {r["id"] for r in corrections}


def test_entity_contributors_use_the_organization_name(fixtures):
    rows = tec.parse_contribs(_fx(fixtures, "cont_ss_sample.csv"), "cont_ss.csv")
    entity = next(r for r in rows if r["id"] == 100035843)
    assert entity["contributor_raw"] == (
        "Microsoft Corporation Political Action Committee"
    )
    assert entity["filer_id"] == "00013805"
    assert entity["amount"] == 250.0
    assert entity["schedule"] == "ss"
    assert entity["form_type"] == "COHSS"


def test_daily_pre_election_rows_are_tagged_t(fixtures):
    rows = tec.parse_contribs(_fx(fixtures, "cont_t_sample.csv"), "cont_t.csv")
    assert {r["schedule"] for r in rows} == {"t"}
    row = next(r for r in rows if r["id"] == 100034887)
    assert row["form_type"] == "DAILYCCOH"
    assert row["contributor_raw"] == "Texas Parent PAC"
    assert row["amount"] == 902.51
    assert row["date"] == "2014-05-22"


def test_naive_sum_double_counts_and_the_schedule_tag_prevents_it(fixtures):
    """The engineered trap, proven end to end.

    contribs_rereport_synthetic.csv is the three real cont_t transactions as
    they appear when re-reported on the next regular report (see
    fixtures/tec/PROVENANCE.txt — new report/line-item IDs are fabricated,
    everything identifying the transaction is real). Summing every
    contribution file counts those dollars twice; summing schedule='main'
    counts them once.
    """
    daily = tec.parse_contribs(_fx(fixtures, "cont_t_sample.csv"), "cont_t.csv")
    rereported = tec.parse_contribs(
        _fx(fixtures, "contribs_rereport_synthetic.csv"), "contribs_02.csv"
    )
    assert len(rereported) == 3
    assert {r["schedule"] for r in rereported} == {"main"}

    key = lambda r: (r["filer_id"], r["date"], r["amount"])  # noqa: E731
    daily_by_key = {key(r): r for r in daily}
    pairs = [r for r in rereported if key(r) in daily_by_key]
    assert len(pairs) == 3, "every synthetic re-report must match a real daily row"
    # Same transactions, different line-item IDs — dedup by ID cannot catch it.
    assert not ({r["id"] for r in rereported} & {r["id"] for r in daily})

    duplicated = round(sum(r["amount"] for r in rereported), 2)
    assert duplicated == 6902.51

    everything = daily + rereported
    dup_keys = {key(r) for r in rereported}
    both_copies = [r for r in everything if key(r) in dup_keys]
    assert len(both_copies) == 6, "three transactions, two copies each"

    # Naive: every contribution file summed together. The three transactions
    # land in the total twice - once as filed on the daily pre-election
    # report, once as re-reported on the regular one.
    naive_share = round(sum(r["amount"] for r in both_copies), 2)
    assert naive_share == round(2 * duplicated, 2) == 13805.02

    # Tagged: schedule='main' keeps exactly one copy of each.
    tagged_share = round(
        sum(r["amount"] for r in both_copies if r["schedule"] == "main"), 2
    )
    assert tagged_share == duplicated == 6902.51

    naive_total = round(sum(r["amount"] or 0.0 for r in everything), 2)
    tagged_total = tec.countable_total(everything, include_superseded=True)
    assert naive_total - tagged_total == round(
        sum(r["amount"] for r in daily), 2
    ), "everything outside 'main' is dropped, re-reports included"
    assert tagged_total == duplicated  # only the 'main' copies survive


def test_countable_total_also_drops_superseded_rows(fixtures):
    rows = tec.parse_contribs(_fx(fixtures, "contribs_sample.csv"), "contribs_01.csv")
    with_superseded = tec.countable_total(rows, include_superseded=True)
    without = tec.countable_total(rows)
    assert with_superseded == 11960.54
    assert without == 5031.28
    assert without < with_superseded


def test_contribution_loader_writes_canonical_and_amendment_rows(conn, fixtures):
    c = tec.TECConnector()
    stats = c.load_contributions(conn, _fx(fixtures, "contribs_sample.csv"), "contribs_01.csv")
    assert stats["rows"] == 140
    assert stats["schedule"] == "main"
    assert stats["superseded"] == 62
    assert stats["corrections"] == 26

    row = conn.execute("SELECT * FROM contribution WHERE id=100000004").fetchone()
    assert row["filer_id"] == "00010883"
    assert row["superseded"] == 1
    assert row["schedule"] == "main"

    meta = conn.execute(
        "SELECT * FROM tec_contribution_meta WHERE id=100000012"
    ).fetchone()
    assert meta["form_type"] == "CORPAC"
    assert meta["is_correction"] == 1
    assert meta["source_file"] == "contribs_01.csv"

    edge = conn.execute(
        "SELECT * FROM edge WHERE src_type='contributor_name' AND dst_id='00010883' LIMIT 1"
    ).fetchone()
    assert edge["provenance"] == "explicit"


def test_totals_query_separates_naive_from_publishable(conn, fixtures):
    c = tec.TECConnector()
    for source, name in (
        ("contribs_sample.csv", "contribs_01.csv"),
        ("cont_ss_sample.csv", "cont_ss.csv"),
        ("cont_t_sample.csv", "cont_t.csv"),
        ("contribs_rereport_synthetic.csv", "contribs_02.csv"),
    ):
        c.load_contributions(conn, _fx(fixtures, source), name)

    totals = c.totals(conn)
    assert totals["rows_by_schedule"] == {"main": 143, "ss": 140, "t": 140}
    assert totals["naive_total"] == 996346.71
    assert totals["main_total"] == 18863.05
    assert totals["countable_total"] == 11933.79
    # The re-reported shards carry the bulk of the naive figure.
    assert totals["naive_total"] > 50 * totals["countable_total"]


def test_loader_is_idempotent(conn, fixtures):
    c = tec.TECConnector()
    data = _fx(fixtures, "contribs_sample.csv")
    c.load_contributions(conn, data, "contribs_01.csv")
    c.load_contributions(conn, data, "contribs_01.csv")
    assert conn.execute("SELECT COUNT(*) c FROM contribution").fetchone()["c"] == 140


# --------------------------------------------------------------- lobby export
def _lobby_zip(tmp_path, fixtures):
    """A stand-in for TEC_LA_CSV.zip built from verbatim member slices, so the
    offline half of the sync is exercised without a 17 MB download."""
    path = tmp_path / "TEC_LA_CSV.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("LobbyLAR-ReadMe.txt", _fx(fixtures, "LobbyLAR-ReadMe.txt"))
        z.writestr("LaSub.csv", _fx(fixtures, "LaSub_sample.csv"))
        z.writestr("LaCvr.csv", _fx(fixtures, "LaCvr_sample.csv"))
    return path


def test_parse_lasub_real_subject_codes(fixtures):
    rows = tec.parse_lasub(_fx(fixtures, "LaSub_sample.csv"))
    assert len(rows) == 200
    first = rows[0]
    assert first["id"] == 100000679
    assert first["filer_id"] == "00010017"
    assert first["filer_name"] == "Kleinworth, Thomas W. (Mr.)"
    assert first["applicable_year"] == 2002
    assert first["subject_code"] == "74"
    assert first["subject_label"] == "State Finances"
    assert first["form_type"] == "LA-A4"

    labels = {r["subject_code"]: r["subject_label"] for r in rows}
    assert labels["29"] == "Education"
    assert labels["59"] == "Open Records And Open Meetings"
    assert labels["11"] == "Business And Commerce"
    # Codes are the coarse topical vocabulary the audit describes (~100 codes
    # corpus-wide); a 200-row slice already shows dozens.
    assert len(labels) >= 40


def test_parse_lacvr_cover_totals(fixtures):
    rows = tec.parse_lacvr(_fx(fixtures, "LaCvr_sample.csv"))
    assert len(rows) == 120
    first = rows[0]
    assert first["report_id"] == "4544"
    assert first["filer_id"] == "00010007"
    assert first["applicable_year"] == 1993
    assert first["report_type"] == "LOBBYACTJAN"
    assert first["filed_dt"] == "1993-01-04"
    assert first["total_food"] == 0.0
    # 1993 paper-era rows have no reporting period at all.
    assert first["period_start"] is None

    with_food = next(r for r in rows if r["report_id"] == "310246")
    assert with_food["total_food"] == 64.2
    assert with_food["period_start"] == "2006-04-01"
    assert with_food["period_end"] == "2006-04-30"


def test_load_lobby_zip_offline(conn, tmp_path, fixtures):
    path = _lobby_zip(tmp_path, fixtures)
    stats = tec.TECConnector().load_lobby_zip(conn, path, as_of="2026-08-25")

    assert stats["members"] == 3
    assert stats["readme"] == "LobbyLAR-ReadMe.txt"
    assert stats["record_types"] == 10
    assert stats["subjects"]["loaded"] == 200
    assert stats["covers"]["loaded"] == 120

    doc = conn.execute(
        "SELECT doc_type FROM document WHERE id='tec:lobby:member:LobbyLAR-ReadMe.txt'"
    ).fetchone()
    assert doc["doc_type"] == "tec_bulk_member"

    row = conn.execute(
        "SELECT subject_label FROM tec_lobby_subject WHERE subject_code='74' LIMIT 1"
    ).fetchone()
    assert row["subject_label"] == "State Finances"

    cover = conn.execute(
        "SELECT source_category, total_food FROM tec_lobby_cover WHERE report_id='310246'"
    ).fetchone()
    assert cover["total_food"] == 64.2
    assert cover["source_category"] == "UNKNOWN"

    # Manifest snapshot for the lobby archive.
    members = conn.execute(
        "SELECT name FROM tec_bulk_member WHERE archive='lobby' ORDER BY name"
    ).fetchall()
    assert [m["name"] for m in members] == ["LaCvr.csv", "LaSub.csv", "LobbyLAR-ReadMe.txt"]

    rec = conn.execute(
        "SELECT files, field_count FROM tec_record_type "
        "WHERE archive='lobby' AND record_name='SubjectMatterData'"
    ).fetchone()
    assert rec["files"] == "LaSub.csv"
    assert rec["field_count"] == 18


def test_lobby_load_cap_is_recorded(conn, tmp_path, fixtures):
    """A capped load must be legible as capped, or a downstream count looks
    like a complete one."""
    path = _lobby_zip(tmp_path, fixtures)
    stats = tec.TECConnector().load_lobby_zip(conn, path, lacvr_cap=25, lasub_cap=1000)
    assert stats["covers"] == {"loaded": 25, "rows_read": 26, "cap": 25, "truncated": True}
    assert stats["subjects"]["truncated"] is False

    state = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM tec_load_state")}
    assert state["LaCvr.csv:cap"] == "25"
    assert state["LaCvr.csv:loaded"] == "25"
    assert state["LaCvr.csv:truncated"] == "1"
    assert state["LaSub.csv:truncated"] == "0"


def test_registrations_derived_from_subjects_leave_comp_null(conn, tmp_path, fixtures):
    """Registration clients and compensation bands have no bulk path at all,
    so those columns must stay NULL rather than be filled with a guess."""
    tec.TECConnector().load_lobby_zip(conn, _lobby_zip(tmp_path, fixtures))
    row = conn.execute(
        "SELECT * FROM lobby_registration WHERE filer_id='00010017' AND year=2002"
    ).fetchone()
    assert row["lobbyist_raw"] == "Kleinworth, Thomas W. (Mr.)"
    assert row["client_raw"] is None
    assert row["comp_low"] is None and row["comp_high"] is None and row["comp_exact"] is None
    codes = row["subjects"].split(",")
    assert "74" in codes and "29" in codes
    assert codes == sorted(codes)


def test_var_dir_refuses_to_stage_downloads_in_fixtures(monkeypatch, tmp_path):
    monkeypatch.setenv("LOBBYBOOK_VAR", str(tmp_path / "fixtures"))
    with pytest.raises(ValueError, match="fixtures"):
        tec.var_dir()
    monkeypatch.setenv("LOBBYBOOK_VAR", str(tmp_path / "var"))
    assert tec.var_dir().is_dir()


# -------------------------------------------------------- member-change diff
def test_member_changes_across_snapshots(conn, fixtures):
    tail = _fx(fixtures, "cf_zip_tail.bin")
    eocd = tec.parse_eocd(tail, CF_ZIP_SIZE_AT_CAPTURE)
    start = eocd["cd_offset"] - eocd["tail_start"]
    members = tec.parse_central_directory(tail[start : start + eocd["cd_size"]])
    c = tec.TECConnector()
    listing = {
        "url": "https://example.invalid/TEC_CF_CSV.zip",
        "size": CF_ZIP_SIZE_AT_CAPTURE,
        "members": members,
        "count": len(members),
        "uncompressed_total": sum(m.uncompressed_size for m in members),
    }
    doc_id, changed = c.store_member_listing(conn, "cf", listing, "2026-08-24")
    assert doc_id == "tec:cf:members" and changed is True
    assert c.member_changes(conn, "cf")["snapshots"] == ["2026-08-24"]

    night2 = [
        tec.ZipMember(m.name, m.method, m.compressed_size + 1,
                      m.uncompressed_size + 9, m.header_offset, m.crc32 ^ 7)
        if m.name == "cover.csv" else m
        for m in members
    ]
    c.store_member_listing(conn, "cf", {**listing, "members": night2}, "2026-08-25")
    diff = c.member_changes(conn, "cf")
    assert diff["changed"] == ["cover.csv"]
    assert diff["snapshots"] == ["2026-08-24", "2026-08-25"]
    assert len(diff["unchanged"]) == 138


# --------------------------------------------------------------- live tests
_URLS: dict | None = None


def _live_urls():
    """Resolved once per module: 2 live requests total, not 2 per test."""
    global _URLS
    if _URLS is None:
        _URLS = tec.TECConnector().resolve_bulk_urls()
    return _URLS


@pytest.mark.live
def test_live_smoke(conn):
    """5 live requests: two search pages, two HEADs, one ranged tail read."""
    result = tec.TECConnector().smoke(conn)
    assert result.ok, result.detail
    assert result.stats["members"] >= 130
    assert result.stats["cf_size"] > 900_000_000
    assert result.stats["lobby_size"] < 64 * 1024 * 1024
    assert result.stats["uncompressed_total"] > 8_000_000_000
    assert result.stats["has_double_count_shards"] is True
    assert result.stats["requests"] <= 10
    # The ranged probe must stay tiny relative to the archive.
    assert result.stats["bytes_read"] < result.stats["cf_size"] / 100
    for key in ("cf_as_of", "lobby_as_of"):
        assert result.stats[key] and "/" in result.stats[key]
    assert result.stats["cf_url"].endswith("/TEC_CF_CSV.zip")


@pytest.mark.live
def test_live_ranged_member_extraction(conn):
    """4 live requests: HEAD + tail probe + 2 ranged reads for one member.

    Proves the primitive that makes a 1 GB nightly archive usable: pulling a
    named member out of it without downloading the rest.
    """
    urls = _live_urls()
    c = tec.TECConnector()
    head = c.probe(urls["cf"]["url"])
    listing = c.probe_central_directory(urls["cf"]["url"], head["size"])
    results = c.ingest_cf_members(
        conn, listing, names=("expn_catg.csv",), as_of=urls["cf"]["as_of_iso"]
    )
    assert results["expn_catg.csv"]["ok"], results["expn_catg.csv"]
    assert results["expn_catg.csv"]["categories"] == 20
    row = conn.execute(
        "SELECT label FROM tec_expend_category WHERE code='TRAVELOUT'"
    ).fetchone()
    assert row["label"] == "Travel Out of District"


@pytest.mark.live
def test_live_lobby_zip_sync(conn, tmp_path):
    """1 HEAD + one 17 MB download, then a full offline load."""
    urls = _live_urls()
    stats = tec.TECConnector().sync_lobby_zip(
        conn, url=urls["lobby"]["url"], as_of=urls["lobby"]["as_of_iso"],
        path=tmp_path / "TEC_LA_CSV.zip", lacvr_cap=2000,
    )
    assert stats["zip_bytes"] < 64 * 1024 * 1024
    assert stats["members"] == 11
    assert stats["record_types"] == 10
    assert stats["subjects"]["loaded"] > 200_000
    assert stats["covers"] == {
        "loaded": 2000, "rows_read": 2001, "cap": 2000, "truncated": True
    }
    codes = conn.execute(
        "SELECT COUNT(DISTINCT subject_code) c FROM tec_lobby_subject"
    ).fetchone()["c"]
    assert codes >= 80
    label = conn.execute(
        "SELECT subject_label FROM tec_lobby_subject WHERE subject_code='74' LIMIT 1"
    ).fetchone()["subject_label"]
    assert label == "State Finances"
