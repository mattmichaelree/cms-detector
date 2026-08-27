"""Campaign connector tests.

The decay classifier is tested against all four lifecycle states because the
audit's finding is that a stored campaign URL is an actively misleading
artifact: two of its three verified domains now resolve to a reseller and a
dead server.
"""

from __future__ import annotations

import json

import httpx
import pytest

from lobbybook.sources.campaign import (
    ACTIVE,
    DEAD,
    ORPHANED,
    PARKED,
    TRTL_ORG,
    CampaignConnector,
    CdxRow,
    WaybackUnavailable,
    cdx_history,
    cdx_reachable,
    cdx_url,
    classify_decay,
    endorsement_cycle,
    fcc_opif,
    google_political_ads,
    meta_ad_library,
    parse_cdx,
    parse_endorsements,
    store_endorsements,
)

TODAY = "2026-08-26"


@pytest.fixture(scope="module")
def endorsements_html(pytestconfig) -> bytes:
    return (pytestconfig.rootpath / "fixtures" / "campaign" / "trtl_endorsements.html").read_bytes()


def cdx_fixture(pytestconfig, name: str) -> list[CdxRow]:
    path = pytestconfig.rootpath / "fixtures" / "campaign" / f"cdx_{name}_SYNTHETIC.json"
    return parse_cdx(path.read_bytes())


# ------------------------------------------------------------------ CDX API
def test_cdx_url_is_the_verified_query_shape():
    url = cdx_url("beverlypowell.com", limit=200)
    assert url.startswith("http://web.archive.org/cdx/search/cdx?url=beverlypowell.com")
    assert "matchType=domain" in url
    assert "output=json" in url
    assert "limit=200" in url
    # One capture per month: enough for a lifecycle verdict, and unbounded
    # queries were observed to reset the connection.
    assert "collapse=timestamp:6" in url


def test_parse_cdx_reads_the_field_order_from_the_header(pytestconfig):
    rows = cdx_fixture(pytestconfig, "beverlypowell")
    assert len(rows) == 45
    assert rows[0].timestamp == "20200118030405"
    assert rows[0].status == 200
    assert rows[0].date == "2020-01-18"
    assert rows[-1].status == 301
    assert all(rows[i].timestamp <= rows[i + 1].timestamp for i in range(len(rows) - 1))


def test_parse_cdx_handles_revisit_records_and_junk():
    payload = json.dumps(
        [
            ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
            ["com,x)/", "20240101000000", "http://x.com/", "text/html", "200", "AAA", "10"],
            ["com,x)/", "20240201000000", "http://x.com/", "warc/revisit", "-", "AAA", "10"],
            ["com,x)/", "notatimestamp", "http://x.com/", "text/html", "200", "AAA", "10"],
        ]
    ).encode()
    rows = parse_cdx(payload)
    assert len(rows) == 2
    assert rows[1].status is None  # '-' is "unknown", not zero and not 200
    assert parse_cdx(b"") == []
    assert parse_cdx(b"[]") == []


# ---------------------------------------------------- the decay classifier
def test_active_campaign(pytestconfig):
    """jamestalarico.com: continuous full captures 2017 -> 2026."""
    verdict = classify_decay(
        cdx_fixture(pytestconfig, "jamestalarico"), domain="jamestalarico.com", today=TODAY
    )
    assert verdict.status == ACTIVE
    assert verdict.first_capture == "2017-03-14"
    assert verdict.went_dark is None
    assert verdict.parked_target is None
    assert verdict.evidence["error_captures"] == 0


def test_orphaned_campaign(pytestconfig):
    """averieforall.com as of mid-2025: still serving 200s five months after
    the loss, nobody tending it, no error phase yet."""
    rows = [r for r in cdx_fixture(pytestconfig, "averieforall") if r.timestamp < "20250501000000"]
    verdict = classify_decay(rows, domain="averieforall.com", today=TODAY)
    assert verdict.status == ORPHANED
    assert verdict.last_full_capture == "2025-04-11"
    assert verdict.went_dark is None
    assert "still serving 200s" in verdict.note


def test_dead_campaign(pytestconfig):
    """The same domain in full: 404s from mid-2025 onward."""
    verdict = classify_decay(
        cdx_fixture(pytestconfig, "averieforall"), domain="averieforall.com", today=TODAY
    )
    assert verdict.status == DEAD
    assert verdict.last_full_capture == "2025-04-11"
    assert verdict.went_dark == "2025-06-03"
    assert verdict.first_error == "2025-06-03"
    assert verdict.parked_target is None


def test_parked_campaign(pytestconfig):
    """beverlypowell.com: last full capture is the day she ended her campaign;
    everything after is a redirect, and the domain now resolves to a reseller."""
    verdict = classify_decay(
        cdx_fixture(pytestconfig, "beverlypowell"),
        domain="beverlypowell.com",
        today=TODAY,
        redirect_target="https://www.hugedomains.com/domain_profile.cfm?d=beverlypowell&e=com",
    )
    assert verdict.status == PARKED
    assert verdict.last_full_capture == "2022-04-06"  # the day the campaign ended
    assert verdict.went_dark == "2022-05-09"
    assert verdict.first_redirect == "2022-05-09"
    assert "hugedomains.com" in verdict.parked_target
    assert "resold" in verdict.note


def test_parking_detected_from_the_cdx_redirect_field():
    """No live resolution needed when CDX itself carries the redirect target."""
    header = ["urlkey", "timestamp", "original", "statuscode", "digest", "redirect"]
    rows = [header]
    rows += [
        ["com,x)/", f"2021{m:02d}01000000", "http://x.com/", "200", "AAA", "-"]
        for m in range(1, 13)
    ]
    rows += [
        ["com,x)/", f"2022{m:02d}01000000", "http://x.com/", "301", "BBB",
         "https://www.sedo.com/search/details/?domain=x.com"]
        for m in range(1, 13)
    ]
    verdict = classify_decay(parse_cdx(json.dumps(rows).encode()), domain="x.com", today=TODAY)
    assert verdict.status == PARKED
    assert "sedo.com" in verdict.parked_target


def test_redirect_tail_without_a_reseller_is_not_called_parked():
    """"Redirects somewhere" is not evidence of a sale. The verdict says so
    rather than guessing."""
    header = ["urlkey", "timestamp", "original", "statuscode", "digest", "redirect"]
    rows = [header]
    rows += [["com,y)/", f"2023{m:02d}01000000", "http://y.com/", "200", "AAA", "-"]
             for m in range(1, 13)]
    rows += [["com,y)/", f"2024{m:02d}01000000", "http://y.com/", "302", "BBB",
              "https://www.house.texas.gov/"] for m in range(1, 13)]
    verdict = classify_decay(parse_cdx(json.dumps(rows).encode()), domain="y.com", today=TODAY)
    assert verdict.status == DEAD
    assert verdict.parked_target is None
    assert "parking unconfirmed" in verdict.note


def test_no_captures_is_not_an_active_site():
    verdict = classify_decay([], domain="nothing.example", today=TODAY)
    assert verdict.status == DEAD
    assert verdict.captures == 0
    assert verdict.note == "no captures"


def test_one_stale_asset_does_not_flip_a_live_site():
    """A single 404 inside a healthy tail must not read as death."""
    header = ["urlkey", "timestamp", "original", "statuscode", "digest"]
    rows = [header]
    rows += [["com,z)/", f"2026{m:02d}01000000", "http://z.com/", "200", "AAA"]
             for m in range(1, 8)]
    rows.append(["com,z)/old.css", "20260715000000", "http://z.com/old.css", "404", "BBB"])
    verdict = classify_decay(parse_cdx(json.dumps(rows).encode()), domain="z.com", today=TODAY)
    assert verdict.status == ACTIVE


# ------------------------------------------------- Wayback honesty contract
class _BlockedFetcher:
    """Reproduces this environment's actual refusal, verbatim."""

    def get(self, url: str, **_kw) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"x-block-reason": "hostname_blocked"},
            text="Blocked by egress policy",
            request=httpx.Request("GET", url),
        )


def test_unreachable_cdx_raises_instead_of_returning_no_history(monkeypatch):
    """"No captures" and "could not ask" are different facts."""
    import lobbybook.sources.campaign as mod

    monkeypatch.setattr(mod, "fetcher", lambda: _BlockedFetcher())
    with pytest.raises(WaybackUnavailable) as exc:
        cdx_history("beverlypowell.com")
    assert "403" in str(exc.value)
    assert "hostname_blocked" in str(exc.value)

    reachable, reason = cdx_reachable("beverlypowell.com")
    assert reachable is False
    assert "hostname_blocked" in reason


def test_transport_failure_is_also_reported_not_swallowed(monkeypatch):
    import lobbybook.sources.campaign as mod

    class _Reset:
        def get(self, url: str, **_kw):
            raise httpx.ConnectError("Recv failure: Connection reset by peer")

    monkeypatch.setattr(mod, "fetcher", lambda: _Reset())
    with pytest.raises(WaybackUnavailable) as exc:
        cdx_history("jamestalarico.com")
    assert "transport error" in str(exc.value)


def test_smoke_falls_back_to_endorsements_when_wayback_is_blocked(conn, monkeypatch, endorsements_html):
    """The documented fallback, exercised without touching the network."""
    import lobbybook.sources.campaign as mod

    class _Mixed:
        def get(self, url: str, **_kw) -> httpx.Response:
            if "web.archive.org" in url:
                return _BlockedFetcher().get(url)
            return httpx.Response(200, content=endorsements_html,
                                  request=httpx.Request("GET", url))

    monkeypatch.setattr(mod, "fetcher", lambda: _Mixed())
    result = CampaignConnector().smoke(conn)
    assert result.ok, result.detail
    assert result.stats["path"] == "endorsements"
    assert result.stats["wayback_reachable"] is False
    assert "hostname_blocked" in result.stats["wayback_error"]
    assert result.stats["endorsements"] == 74


# ------------------------------------------------------------ endorsements
def test_endorsement_page_is_cycle_scoped(endorsements_html):
    assert endorsement_cycle(endorsements_html) == 2026
    rows = parse_endorsements(endorsements_html)
    # Every row carries the cycle it was scraped for: the live page shows only
    # the current one, so an undated endorsement row would be unrecoverable.
    assert {row.cycle for row in rows} == {2026}


def test_endorsements_parse_real_candidates(endorsements_html):
    rows = parse_endorsements(endorsements_html)
    assert len(rows) == 74
    assert {row.org_raw for row in rows} == {TRTL_ORG}
    by_position = {row.position: row.candidate_raw for row in rows}
    assert by_position["Governor"] == "Greg Abbott"
    assert by_position["Lt. Governor"] == "Dan Patrick"
    assert by_position["Attorney General"] == "Mayes Middleton"
    assert by_position["Congressional District 9"] == "Briscoe Cain"
    assert by_position["HD 10"] == "Brian Harrison"
    assert by_position["SD 28"] == "Charles Perry"


def test_statewide_endorsements_span_every_county(endorsements_html):
    """The page is county-keyed; a statewide endorsement appears under all 209
    counties and must be folded into one row, not 209."""
    rows = {row.position: row for row in parse_endorsements(endorsements_html)}
    assert len(rows["Governor"].counties) == 209
    assert len(rows["HD 10"].counties) == 1


def test_office_is_derived_because_the_sites_own_bucket_is_unreliable(endorsements_html):
    """TRTL files HD/SD races under 'local' and leaves its 'legislature'
    bucket empty, so the normalized office is derived from the position
    label rather than trusted from the page."""
    rows = {row.position: row for row in parse_endorsements(endorsements_html)}
    assert rows["HD 10"].office_level == "local"
    assert rows["HD 10"].office == "state_house"
    assert rows["SD 28"].office == "state_senate"
    assert rows["Congressional District 9"].office == "us_house"
    assert rows["Governor"].office == "statewide_executive"


def test_footnote_markers_are_stripped_from_names(endorsements_html):
    rows = [row for row in parse_endorsements(endorsements_html) if row.starred]
    assert rows, "expected at least one asterisked endorsement"
    assert all(not row.candidate_raw.endswith("*") for row in rows)
    assert "Alex Kim" in {row.candidate_raw for row in rows}


def test_store_endorsements_writes_rows_races_and_explicit_edges(conn, endorsements_html):
    rows = parse_endorsements(endorsements_html)
    store_endorsements(conn, rows, doc_id=None)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM endorsement").fetchone()["c"] == 74
    edge = conn.execute(
        "SELECT * FROM edge WHERE predicate='endorsed' AND dst_id='Greg Abbott'"
    ).fetchone()
    assert edge["src_id"] == TRTL_ORG
    assert edge["provenance"] == "explicit"
    assert edge["span"] == "Governor"
    race = conn.execute(
        "SELECT * FROM endorsement_race WHERE candidate_raw='Brian Harrison'"
    ).fetchone()
    assert race["office"] == "state_house" and race["position"] == "HD 10"

    store_endorsements(conn, rows, doc_id=None)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM endorsement").fetchone()["c"] == 74


def test_decay_verdict_is_stored_with_derived_edges(conn, pytestconfig):
    verdict = classify_decay(
        cdx_fixture(pytestconfig, "beverlypowell"),
        domain="beverlypowell.com",
        today=TODAY,
        redirect_target="https://www.hugedomains.com/domain_profile.cfm?d=beverlypowell&e=com",
    )
    CampaignConnector().record_verdict(
        conn, verdict, candidate_raw="Beverly Powell", cycle=2022, doc_id=None
    )
    conn.commit()
    row = conn.execute("SELECT * FROM campaign_site WHERE domain='beverlypowell.com'").fetchone()
    assert row["status"] == PARKED
    assert row["last_full_capture"] == "2022-04-06"
    preds = {
        r["predicate"]: r
        for r in conn.execute("SELECT * FROM edge WHERE src_type='campaign_site'")
    }
    # The 200 -> 30x transition is inferred from capture statuses, not stated.
    assert preds["went_dark"]["provenance"] == "derived"
    assert preds["went_dark"]["dst_id"] == "2022-05-09"
    assert preds["resold_to"]["provenance"] == "derived"


# ------------------------------------------------------------- ad libraries
def test_meta_stub_names_the_credential():
    with pytest.raises(NotImplementedError) as exc:
        meta_ad_library("HD112")
    message = str(exc.value)
    assert "Ad Library API" in message
    assert "ads_archive" in message
    assert "ID verification" in message
    assert "403" in message


def test_google_stub_names_the_dataset_and_the_credential():
    with pytest.raises(NotImplementedError) as exc:
        google_political_ads("TX")
    message = str(exc.value)
    assert "bigquery-public-data.google_political_ads" in message
    assert "creative_stats" in message
    assert "service account" in message and "BigQuery Job User" in message


def test_fcc_stub_explains_why_it_is_not_automatable():
    with pytest.raises(NotImplementedError) as exc:
        fcc_opif("facility_id")
    message = str(exc.value)
    assert "publicfiles.fcc.gov" in message
    assert "AdImpact" in message


# -------------------------------------------------------------------- live
@pytest.mark.live
def test_campaign_live_smoke(conn):
    from lobbybook.core.registry import get

    result = get("campaign").smoke(conn)
    assert result.ok, result.detail
    if result.stats["wayback_reachable"]:
        assert result.stats["path"] == "wayback_cdx"
        assert result.stats["captures"] >= 5
        assert result.stats["status"] in {ACTIVE, ORPHANED, DEAD, PARKED}
    else:
        # Recorded, not faked: this environment blocks web.archive.org.
        assert result.stats["path"] == "endorsements"
        assert result.stats["wayback_error"]
        assert result.stats["cycle"] == 2026
        assert result.stats["endorsements"] >= 20
        assert result.stats["endorsed_edges"] >= 20
