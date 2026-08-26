"""Comptroller / data.texas.gov Socrata connector tests.

Offline tests run against saved catalog and row responses and assert *real*
values — the actual 4x4 ids, the actual dataset names, the actual
``resultSetSize`` — so a parser that returns plausibly-shaped garbage fails
here. The most important test in the file asserts a **negative**: catalog
queries for ethics, lobby and campaign finance return zero. Live tests are
opt-in (LOBBYBOOK_LIVE=1) and bounded.
"""

from __future__ import annotations

import json

import pytest

from lobbybook.sources import comptroller as cpa
from lobbybook.sources.comptroller import ComptrollerConnector, EthicsDatasetsAppeared


def _load(fixtures, name: str) -> bytes:
    return (fixtures / "comptroller" / name).read_bytes()


class _Resp:
    def __init__(self, content: bytes, status: int = 200):
        self.content = content
        self.status_code = status
        self.headers: dict = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")


class _FixtureFetcher:
    """Serves the saved responses by URL shape; records every request so a
    test can assert the request budget as well as the parse."""

    def __init__(self, fixtures):
        self.dir = fixtures / "comptroller"
        self.requested: list[str] = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        if "/resource/" in url:
            return _Resp((self.dir / "rows-gern-2bvs.json").read_bytes())
        if "q=ethics" in url or "q=lobby" in url or "q=campaign" in url:
            return _Resp((self.dir / "catalog-ethics-empty.json").read_bytes())
        if "Districts" in url:
            return _Resp((self.dir / "catalog-districts-plan.json").read_bytes())
        return _Resp((self.dir / "catalog-comptroller.json").read_bytes())


@pytest.fixture()
def offline_fetch(monkeypatch, fixtures):
    fake = _FixtureFetcher(fixtures)
    monkeypatch.setattr("lobbybook.sources.comptroller.fetcher", lambda: fake)
    return fake


# ------------------------------------------------------------------- URLs
def test_url_shapes():
    assert cpa.catalog_url("ethics", 10) == (
        "https://api.us.socrata.com/api/catalog/v1?domains=data.texas.gov&q=ethics&limit=10"
    )
    assert cpa.catalog_url(None, 5) == (
        "https://api.us.socrata.com/api/catalog/v1?domains=data.texas.gov&limit=5"
    )
    assert cpa.catalog_url("campaign finance", 3).endswith("q=campaign+finance&limit=3")
    # SoQL parameter names keep their literal '$'; values are escaped.
    assert cpa.rows_url("gern-2bvs", 10) == (
        "https://data.texas.gov/resource/gern-2bvs.json?$limit=10"
    )
    assert cpa.rows_url("gern-2bvs", 5, where="appropriation_year = '2008'") == (
        "https://data.texas.gov/resource/gern-2bvs.json"
        "?$limit=5&$where=appropriation_year%20%3D%20%272008%27"
    )
    with pytest.raises(ValueError):
        cpa.rows_url("not-a-4x4-id", 5)


def test_query_slug():
    assert cpa.query_slug("campaign finance") == "campaign-finance"
    assert cpa.query_slug(None) == "all"


# ---------------------------------------------------------------- catalog
def test_parse_catalog_real_values(fixtures):
    catalog = cpa.parse_catalog(_load(fixtures, "catalog-comptroller.json"))

    # 132 assets on data.texas.gov match 'comptroller'; the page returned 10.
    assert catalog["total"] == 132
    assert catalog["returned"] == 10
    assert len(catalog["datasets"]) == 10

    by_id = {d["id"]: d for d in catalog["datasets"]}
    assert "gern-2bvs" in by_id
    obj = by_id["gern-2bvs"]
    assert obj["name"] == "Comptroller Object Numbers and Titles"
    assert obj["attribution"] == "Texas Comptroller of Public Accounts"
    assert obj["category"] == "Government and Taxes"
    assert obj["domain"] == "data.texas.gov"
    assert obj["asset_type"] == "dataset"
    assert obj["permalink"] == "https://data.texas.gov/d/gern-2bvs"
    assert obj["columns"] == [
        "appropriation_year",
        "comptroller_object_code_1",
        "comptroller_object_code",
    ]
    assert obj["description"].startswith("This file comprises the list of all objects")

    # The audit's named Comptroller datasets are all really there.
    names = {d["name"] for d in catalog["datasets"]}
    assert "Active Sales Tax Permit Holders" in names
    assert "Mixed Beverage Gross Receipts" in names
    assert "Agriculture and Timber Exemption Registrations" in names


def test_catalog_ids_are_socrata_4x4(fixtures):
    catalog = cpa.parse_catalog(_load(fixtures, "catalog-comptroller.json"))
    assert all(cpa.FOURBYFOUR_RE.match(d["id"]) for d in catalog["datasets"])


# -------------------------------------------- THE VERIFIED NEGATIVE
def test_ethics_catalog_response_is_empty(fixtures):
    """The audit's negative, frozen as bytes: data.texas.gov has no TEC corpus.

    ``resultSetSize`` is 0, not merely 'the first page was empty' — so this is
    a statement about the whole domain, not about pagination.
    """
    catalog = cpa.parse_catalog(_load(fixtures, "catalog-ethics-empty.json"))
    assert catalog["total"] == 0
    assert catalog["returned"] == 0
    assert catalog["datasets"] == []


def test_assert_no_ethics_datasets_offline(conn, offline_fetch):
    report = ComptrollerConnector().assert_no_ethics_datasets(conn)
    assert report["clean"] is True
    assert report["queries"] == {"ethics": 0, "lobby": 0, "campaign finance": 0}
    assert report["found"] == {}
    assert len(offline_fetch.requested) == 3

    # The negative is stored, dated, so a later run is a diff and not folklore.
    rows = {
        r["query"]: r["total"]
        for r in conn.execute("SELECT query, total FROM socrata_query")
    }
    assert rows == {"ethics": 0, "lobby": 0, "campaign finance": 0}


def test_assert_no_ethics_datasets_raises_when_tec_appears(conn, monkeypatch, fixtures):
    """If TEC ever does publish here, the platform must notice loudly."""
    payload = (fixtures / "comptroller" / "catalog-comptroller.json").read_bytes()

    class _Stub:
        def get(self, url, **kwargs):
            return _Resp(payload)

    monkeypatch.setattr("lobbybook.sources.comptroller.fetcher", lambda: _Stub())
    connector = ComptrollerConnector()
    with pytest.raises(EthicsDatasetsAppeared):
        connector.assert_no_ethics_datasets(conn)
    # strict=False reports instead of raising, for callers that want to keep going.
    report = connector.assert_no_ethics_datasets(conn, strict=False)
    assert report["clean"] is False
    assert report["queries"]["ethics"] == 132


# --------------------------------------------------------- redistricting
def test_parse_plan_datasets_real_ids(fixtures):
    catalog = cpa.parse_catalog(_load(fixtures, "catalog-districts-plan.json"))
    plans = cpa.parse_plan_datasets(catalog)

    by_code = {p["plan_code"]: p for p in plans}
    assert set(by_code) == {"H2316", "S2168", "C2193"}
    assert by_code["H2316"]["id"] == "srhv-sc4z"
    assert by_code["S2168"]["id"] == "cfti-fcdb"
    assert by_code["C2193"]["id"] == "739c-52ri"
    assert by_code["H2316"]["name"] == (
        "Texas State House Districts Plan H2316 (Effective Jan 18, 2022)"
    )
    assert by_code["H2316"]["body"] == "texas_house"
    assert by_code["S2168"]["body"] == "texas_senate"
    assert by_code["C2193"]["body"] == "us_congress"
    assert {p["effective"] for p in plans} == {"Jan 18, 2022"}


def test_plan_matching_uses_names_not_search_ranking(fixtures):
    """Socrata's full-text search is fuzzy: the same page carries superseded
    plans and unrelated agency datasets. Only names carrying a plan code are
    plans, and only the wanted codes are kept."""
    catalog = cpa.parse_catalog(_load(fixtures, "catalog-districts-plan.json"))
    everything = cpa.parse_plan_datasets(catalog, plan_codes=())
    codes = {p["plan_code"] for p in everything}
    # Superseded cycles are present and correctly excluded by PLAN_CODES.
    assert {"H2100", "S2100", "C2100", "H414", "S172", "C235", "E2100"} <= codes
    assert len(cpa.parse_plan_datasets(catalog)) == 3


def test_catalogue_redistricting_writes_datasets_and_edges(conn, offline_fetch):
    stats = ComptrollerConnector().catalogue_redistricting(conn)
    assert stats["plan_codes"] == ["C2193", "H2316", "S2168"]
    assert stats["missing"] == []

    row = conn.execute("SELECT * FROM socrata_dataset WHERE id='srhv-sc4z'").fetchone()
    assert row["name"].startswith("Texas State House Districts Plan H2316")
    assert row["domain"] == "data.texas.gov"

    edges = {
        (e["src_id"], e["predicate"], e["dst_id"])
        for e in conn.execute("SELECT * FROM edge WHERE predicate IN ('describes','districts')")
    }
    assert ("srhv-sc4z", "describes", "H2316") in edges
    assert ("H2316", "districts", "texas_house") in edges
    assert ("C2193", "districts", "us_congress") in edges
    # Metadata only: the geometry is never pulled.
    assert not any("/resource/" in u for u in offline_fetch.requested)


# ------------------------------------------------------------------ rows
def test_parse_rows_real_values(fixtures):
    rows = cpa.parse_rows(_load(fixtures, "rows-gern-2bvs.json"))
    assert len(rows) == 25
    assert rows[0] == {
        "appropriation_year": "2008",
        "comptroller_object_code": "3000",
        "comptroller_object_code_1": "REVENUE BUDGET",
    }
    codes = {r["comptroller_object_code"] for r in rows}
    assert "3001" in codes and "3002" in codes
    # The audit's note that the 3000 series is revenue holds in the real data.
    assert all(r["comptroller_object_code"].startswith("3") for r in rows)


def test_parse_rows_rejects_soda_error_object():
    err = json.dumps({"error": True, "message": "Invalid SoQL query"}).encode()
    with pytest.raises(ValueError, match="Invalid SoQL query"):
        cpa.parse_rows(err)


def test_fetch_rows_stages_payloads_verbatim(conn, offline_fetch):
    stats = ComptrollerConnector().fetch_rows(conn, "gern-2bvs", limit=25)
    assert stats["rows"] == 25
    assert stats["fields"] == [
        "appropriation_year",
        "comptroller_object_code",
        "comptroller_object_code_1",
    ]

    staged = conn.execute(
        "SELECT payload_json FROM socrata_row WHERE dataset_id='gern-2bvs' AND seq=0"
    ).fetchone()
    assert json.loads(staged["payload_json"])["comptroller_object_code_1"] == "REVENUE BUDGET"
    assert conn.execute(
        "SELECT COUNT(*) c FROM socrata_row WHERE dataset_id='gern-2bvs'"
    ).fetchone()["c"] == 25


# ------------------------------------------------- document-store contract
def test_catalog_is_stored_before_it_is_parsed(conn, offline_fetch):
    ComptrollerConnector().search_datasets(conn, "comptroller", limit=10)
    doc = conn.execute(
        "SELECT * FROM document WHERE id='comptroller:socrata:catalog:data.texas.gov:comptroller'"
    ).fetchone()
    assert doc["doc_type"] == "socrata_catalog"
    assert doc["source_family"] == "comptroller"
    assert doc["url"].startswith("https://api.us.socrata.com/api/catalog/v1")
    assert conn.execute(
        "SELECT COUNT(*) c FROM document_version WHERE document_id=?", (doc["id"],)
    ).fetchone()["c"] == 1


def test_search_datasets_records_publisher_edges(conn, offline_fetch):
    ComptrollerConnector().search_datasets(conn, "comptroller", limit=10)
    edge = conn.execute(
        "SELECT * FROM edge WHERE src_id='gern-2bvs' AND predicate='published_by'"
    ).fetchone()
    assert edge["dst_id"] == "Texas Comptroller of Public Accounts"
    assert edge["provenance"] == "explicit"


def test_refetching_identical_bytes_adds_no_version(conn, offline_fetch):
    c = ComptrollerConnector()
    c.search_datasets(conn, "comptroller", limit=10)
    c.search_datasets(conn, "comptroller", limit=10)
    assert conn.execute(
        "SELECT COUNT(*) c FROM document_version WHERE document_id LIKE 'comptroller:socrata:catalog:%'"
    ).fetchone()["c"] == 1


def test_connector_registration():
    from lobbybook.core import registry

    assert "comptroller" in registry.names()
    connector = registry.get("comptroller")
    assert (connector.tier, connector.cadence) == (2, "quarterly")


# ------------------------------------------------------------ live tests
# Live budget for this file: 9 requests (smoke 6 + the ethics watch 3).
@pytest.mark.live
def test_live_smoke(conn):
    """6 live requests: catalog search, 3 ethics negatives, plan catalogue, rows."""
    result = ComptrollerConnector().smoke(conn)
    assert result.ok, result.detail
    assert result.stats["catalog_total"] >= 5
    assert result.stats["catalogued"] >= 5
    assert result.stats["rows"] >= 1
    # All three current plan codes are really on the domain, metadata only.
    assert result.stats["plan_codes"] == ["C2193", "H2316", "S2168"]

    plan_ids = {
        r["id"]
        for r in conn.execute(
            "SELECT id FROM socrata_dataset WHERE name LIKE '%Districts Plan%'"
        )
    }
    assert {"srhv-sc4z", "cfti-fcdb", "739c-52ri"} <= plan_ids
    # Rows staged verbatim from the live portal, ids still 4x4.
    assert all(
        cpa.FOURBYFOUR_RE.match(r["id"])
        for r in conn.execute("SELECT id FROM socrata_dataset")
    )


@pytest.mark.live
def test_live_ethics_queries_are_still_empty(conn):
    """3 live requests. The whole point of this connector: if this test ever
    fails, TEC started publishing to data.texas.gov and the routing decision
    in the audit needs revisiting."""
    report = ComptrollerConnector().assert_no_ethics_datasets(conn, strict=False)
    assert report["queries"] == {"ethics": 0, "lobby": 0, "campaign finance": 0}, report["found"]
    assert report["clean"] is True
