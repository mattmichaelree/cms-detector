"""Comptroller / data.texas.gov — the Socrata open-data discovery surface.

Spec: docs/texas-politics-audit/03-deep-dives/09-comptroller.md.

The audit verified that ``data.texas.gov`` is a genuine Socrata portal with a
working SODA API, and that it is **not** a LobbyBook corpus. Two live-verified
facts shape this module:

  * **It is a discovery surface, not a modelled corpus.** The domain publishes
    hundreds of datasets across every agency that bothered to load one — tax
    permit holders, mixed-beverage receipts, redistricting plan boundaries,
    school-nutrition site lists. Modelling them individually would be endless
    and mostly worthless, so rows land in a generic
    ``socrata_dataset``/``socrata_row`` staging pair and are promoted by hand
    only when a specific dataset earns it.
  * **The verified negative: TEC publishes nothing here.** Catalog queries for
    ``ethics``, ``lobby`` and ``campaign finance`` return *zero* results
    (verified live, re-verified by :func:`ComptrollerConnector.assert_no_ethics_datasets`).
    That negative is load-bearing: it stops anyone assuming the state's open
    data portal covers LobbyBook's core subjects, and it is stored in
    ``socrata_query`` on every run so the day TEC *does* start publishing here
    shows up as a diff rather than as folklore.

Two endpoints, both verified live:

  * Discovery API — ``https://api.us.socrata.com/api/catalog/v1?domains=data.texas.gov&q=…``
    returns the cross-domain catalog (metadata only).
  * SODA rows — ``https://data.texas.gov/resource/{id}.json?$limit=…`` returns
    the dataset itself.

The redistricting plan-boundary datasets are catalogued from metadata only —
the geometry payloads are large and nothing in LobbyBook consumes them yet.

Parsers are pure functions over bytes; every fetched artifact is stored in the
document store before it is parsed.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from urllib.parse import urlencode

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

#: Socrata's cross-domain Discovery API (not hosted on the domain itself).
DISCOVERY = "https://api.us.socrata.com/api/catalog/v1"
DOMAIN = "data.texas.gov"
RESOURCE = "https://data.texas.gov/resource/{dataset_id}.json"

#: The audit's verified negative. TEC's registrations and campaign finance are
#: filed on ethics.state.tx.us, and nothing about them reaches the open-data
#: portal. Every one of these must keep returning zero.
ETHICS_QUERIES = ("ethics", "lobby", "campaign finance")

#: TLC plan codes for the boundaries in force since Jan 18, 2022 (verified
#: present on the domain as separate datasets, one per chamber).
PLAN_CODES = ("H2316", "S2168", "C2193")

#: One query catches every plan dataset; the codes above are then matched out
#: of the returned names, so a new plan cycle only needs a PLAN_CODES edit.
PLAN_QUERY = "Districts Plan"

#: Socrata 4x4 dataset identifiers.
FOURBYFOUR_RE = re.compile(r"^[a-z0-9]{4}-[a-z0-9]{4}$")

#: 'Texas State House Districts Plan H2316 (Effective Jan 18, 2022)'
PLAN_NAME_RE = re.compile(r"\bPlan\s+([HSCE])(\d{2,4})\b", re.I)
PLAN_EFFECTIVE_RE = re.compile(r"\(Effective\s+([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s*\d{4})\)", re.I)

#: Plan-code letter -> the body the plan districts.
PLAN_BODIES = {
    "H": "texas_house",
    "S": "texas_senate",
    "C": "us_congress",
    "E": "sboe",
}

#: Nothing bigger than this comes over the wire. Row pages are capped by
#: ``$limit`` long before this matters; it guards a mis-sized geometry pull.
MAX_DOWNLOAD = 8 * 1024 * 1024


class EthicsDatasetsAppeared(Exception):
    """data.texas.gov started carrying ethics/lobby/campaign-finance data.

    Raised by :func:`ComptrollerConnector.assert_no_ethics_datasets`. This is
    good news, not a bug — but it means the TEC connector is no longer the only
    path to that corpus and the routing decision needs revisiting.
    """


# ------------------------------------------------------------------- URLs
def catalog_url(query: str | None = None, limit: int = 20, domain: str = DOMAIN, offset: int = 0) -> str:
    """Discovery API URL. ``query=None`` enumerates the whole domain."""
    params: list[tuple[str, str]] = [("domains", domain)]
    if query:
        params.append(("q", query))
    params.append(("limit", str(int(limit))))
    if offset:
        params.append(("offset", str(int(offset))))
    return f"{DISCOVERY}?{urlencode(params)}"


def rows_url(dataset_id: str, limit: int = 100, where: str | None = None, offset: int = 0) -> str:
    """SODA rows URL for one dataset. ``where`` is a raw SoQL ``$where`` clause."""
    if not FOURBYFOUR_RE.match(dataset_id or ""):
        raise ValueError(f"not a Socrata 4x4 dataset id: {dataset_id!r}")
    params: list[tuple[str, str]] = [("$limit", str(int(limit)))]
    if offset:
        params.append(("$offset", str(int(offset))))
    if where:
        params.append(("$where", where))
    return f"{RESOURCE.format(dataset_id=dataset_id)}?{urlencode(params)}"


def query_slug(query: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (query or "all").lower()).strip("-") or "all"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- parsers
def _catalog_entry(result: dict) -> dict:
    res = result.get("resource") or {}
    cls = result.get("classification") or {}
    meta = result.get("metadata") or {}
    return {
        "id": res.get("id"),
        "name": res.get("name"),
        "description": res.get("description"),
        "updated": res.get("updatedAt"),
        "domain": meta.get("domain"),
        "asset_type": res.get("type"),
        "attribution": res.get("attribution"),
        "category": cls.get("domain_category"),
        "permalink": result.get("permalink"),
        "columns": list(res.get("columns_field_name") or []),
    }


def parse_catalog(content: bytes) -> dict:
    """Discovery API response -> ``{'total', 'returned', 'datasets'}``.

    ``total`` is Socrata's ``resultSetSize`` — the number of *matching* assets
    on the domain, which is what makes the ethics queries' zero meaningful even
    at ``limit=10``.
    """
    payload = json.loads(content.decode("utf-8"))
    results = payload.get("results") or []
    datasets = [_catalog_entry(r) for r in results]
    return {
        "total": int(payload.get("resultSetSize") or 0),
        "returned": len(datasets),
        "datasets": datasets,
    }


def parse_rows(content: bytes) -> list[dict]:
    """SODA JSON response -> list of row dicts (one dict per record)."""
    payload = json.loads(content.decode("utf-8"))
    if isinstance(payload, dict):
        # SODA reports query errors as a JSON object, never as a list.
        raise ValueError(f"SODA error: {payload.get('message') or payload}")
    return list(payload)


def parse_plan_datasets(catalog: dict, plan_codes: tuple[str, ...] = PLAN_CODES) -> list[dict]:
    """Pick the redistricting plan-boundary datasets out of a catalog page.

    Matching is on the plan code embedded in the dataset *name* (the Discovery
    API's full-text search is fuzzy enough that a plan-code query returns
    dozens of unrelated agency datasets — verified live, 44 hits for
    'Plan H2316' of which exactly one was the plan).
    """
    wanted = {c.upper() for c in plan_codes}
    out = []
    for ds in catalog["datasets"]:
        m = PLAN_NAME_RE.search(ds.get("name") or "")
        if not m:
            continue
        code = f"{m.group(1).upper()}{m.group(2)}"
        if wanted and code not in wanted:
            continue
        eff = PLAN_EFFECTIVE_RE.search(ds["name"])
        out.append(
            {
                **ds,
                "plan_code": code,
                "body": PLAN_BODIES.get(code[0], "unknown"),
                "effective": eff.group(1) if eff else None,
            }
        )
    return out


# -------------------------------------------------------------- connector
@register
class ComptrollerConnector(Connector):
    """data.texas.gov Socrata discovery + the TEC-absence watch."""

    name = "comptroller"
    tier = 2
    cadence = "quarterly"

    DDL = """
    CREATE TABLE IF NOT EXISTS socrata_dataset (
        id          TEXT PRIMARY KEY,   -- Socrata 4x4, e.g. 'gern-2bvs'
        name        TEXT,
        description TEXT,
        updated     TEXT,               -- resource.updatedAt (ISO8601)
        domain      TEXT,
        asset_type  TEXT,               -- 'dataset' | 'filter' | 'map' | ...
        attribution TEXT,               -- publishing agency, as the portal states it
        category    TEXT,
        permalink   TEXT,
        doc_id      TEXT
    );

    CREATE TABLE IF NOT EXISTS socrata_row (
        dataset_id   TEXT NOT NULL,
        seq          INTEGER NOT NULL,
        payload_json TEXT NOT NULL,
        doc_id       TEXT,
        PRIMARY KEY (dataset_id, seq)
    );

    -- Every catalog query and its result count, so a verified negative
    -- (ethics/lobby/campaign finance = 0) is a stored fact with a date on it
    -- rather than an assertion in a docstring.
    CREATE TABLE IF NOT EXISTS socrata_query (
        query      TEXT NOT NULL,
        domain     TEXT NOT NULL,
        total      INTEGER NOT NULL,
        checked_at TEXT NOT NULL,
        doc_id     TEXT,
        PRIMARY KEY (query, domain)
    );

    CREATE INDEX IF NOT EXISTS idx_socrata_dataset_attr ON socrata_dataset(attribution);
    CREATE INDEX IF NOT EXISTS idx_socrata_row_dataset ON socrata_row(dataset_id);
    """

    # -- catalog ---------------------------------------------------------
    def search_datasets(
        self,
        conn: sqlite3.Connection,
        query: str | None = None,
        limit: int = 20,
        domain: str = DOMAIN,
        store: bool = True,
    ) -> dict:
        """One Discovery API page -> ``socrata_dataset`` rows.

        Returns the parsed catalog plus ``total`` (all matches on the domain,
        not just this page) and the stored ``doc_id``.
        """
        url = catalog_url(query, limit=limit, domain=domain)
        resp = fetcher().get(url)
        resp.raise_for_status()
        doc_id = f"comptroller:socrata:catalog:{domain}:{query_slug(query)}"
        store_document(
            conn,
            doc_id=doc_id,
            source_family="comptroller",
            content=resp.content,
            url=url,
            native_id=query_slug(query),
            doc_type="socrata_catalog",
            authority="A",
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )
        catalog = parse_catalog(resp.content)
        dbx.upsert(
            conn,
            "socrata_query",
            {
                "query": query or "",
                "domain": domain,
                "total": catalog["total"],
                "checked_at": _now(),
                "doc_id": doc_id,
            },
            ["query", "domain"],
        )
        if store:
            for ds in catalog["datasets"]:
                self._store_dataset(conn, ds, doc_id)
        conn.commit()
        return {**catalog, "query": query, "url": url, "doc_id": doc_id}

    def _store_dataset(self, conn: sqlite3.Connection, ds: dict, doc_id: str) -> None:
        if not ds.get("id"):
            return
        dbx.upsert(
            conn,
            "socrata_dataset",
            {
                "id": ds["id"],
                "name": ds.get("name"),
                "description": ds.get("description"),
                "updated": ds.get("updated"),
                "domain": ds.get("domain"),
                "asset_type": ds.get("asset_type"),
                "attribution": ds.get("attribution"),
                "category": ds.get("category"),
                "permalink": ds.get("permalink"),
                "doc_id": doc_id,
            },
            ["id"],
        )
        if ds.get("attribution"):
            dbx.add_edge(
                conn,
                "socrata_dataset",
                ds["id"],
                "published_by",
                "organization_name",
                ds["attribution"],
                "explicit",
                doc_id,
            )

    # -- rows ------------------------------------------------------------
    def fetch_rows(
        self,
        conn: sqlite3.Connection,
        dataset_id: str,
        limit: int = 100,
        where: str | None = None,
        offset: int = 0,
    ) -> dict:
        """One SODA page -> ``socrata_row`` rows (payload kept verbatim).

        Rows are staged as JSON exactly as the portal served them. Nothing here
        guesses at a schema: promotion into a modelled table is a per-dataset
        decision made once a dataset proves it is worth one.
        """
        url = rows_url(dataset_id, limit=limit, where=where, offset=offset)
        resp = fetcher().get(url)
        resp.raise_for_status()
        if len(resp.content) > MAX_DOWNLOAD:
            raise ValueError(f"{url} returned {len(resp.content)} bytes (cap {MAX_DOWNLOAD})")
        doc_id = f"comptroller:socrata:rows:{dataset_id}"
        store_document(
            conn,
            doc_id=doc_id,
            source_family="comptroller",
            content=resp.content,
            url=url,
            native_id=dataset_id,
            doc_type="socrata_rows",
            authority="A",
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )
        rows = parse_rows(resp.content)
        for i, row in enumerate(rows):
            dbx.upsert(
                conn,
                "socrata_row",
                {
                    "dataset_id": dataset_id,
                    "seq": offset + i,
                    "payload_json": json.dumps(row, sort_keys=True),
                    "doc_id": doc_id,
                },
                ["dataset_id", "seq"],
            )
        conn.commit()
        fields = sorted({k for row in rows for k in row})
        return {
            "dataset_id": dataset_id,
            "rows": len(rows),
            "fields": fields,
            "url": url,
            "doc_id": doc_id,
        }

    # -- the verified negative -------------------------------------------
    def assert_no_ethics_datasets(
        self,
        conn: sqlite3.Connection,
        queries: tuple[str, ...] = ETHICS_QUERIES,
        strict: bool = True,
    ) -> dict:
        """Re-verify that data.texas.gov carries no TEC corpus.

        The audit confirmed zero results for every query in
        :data:`ETHICS_QUERIES`. Each run records the counts in
        ``socrata_query``; with ``strict`` (the default) a non-zero count
        raises :class:`EthicsDatasetsAppeared` so the platform cannot silently
        keep believing a stale negative.
        """
        counts: dict[str, int] = {}
        found: dict[str, list[str]] = {}
        for q in queries:
            catalog = self.search_datasets(conn, q, limit=10)
            counts[q] = catalog["total"]
            if catalog["total"]:
                found[q] = [d.get("name") for d in catalog["datasets"]][:10]
        clean = not found
        report = {"queries": counts, "found": found, "clean": clean, "checked_at": _now()}
        if strict and not clean:
            raise EthicsDatasetsAppeared(
                f"data.texas.gov now returns results for {sorted(found)}: {found}"
            )
        return report

    # -- redistricting ---------------------------------------------------
    def catalogue_redistricting(
        self,
        conn: sqlite3.Connection,
        plan_codes: tuple[str, ...] = PLAN_CODES,
        limit: int = 20,
    ) -> dict:
        """Catalogue the plan-boundary datasets — **metadata only**.

        One catalog query covers every chamber; the geometry payloads are never
        downloaded (nothing in LobbyBook consumes them, and they are the only
        thing on this domain that would blow the size cap).
        """
        catalog = self.search_datasets(conn, PLAN_QUERY, limit=limit)
        plans = parse_plan_datasets(catalog, plan_codes)
        for plan in plans:
            dbx.add_edge(
                conn,
                "socrata_dataset",
                plan["id"],
                "describes",
                "redistricting_plan",
                plan["plan_code"],
                "explicit",
                catalog["doc_id"],
                span=plan.get("effective"),
            )
            dbx.add_edge(
                conn,
                "redistricting_plan",
                plan["plan_code"],
                "districts",
                "body",
                plan["body"],
                "explicit",
                catalog["doc_id"],
            )
        conn.commit()
        return {
            "query": PLAN_QUERY,
            "candidates": catalog["returned"],
            "plans": plans,
            "plan_codes": sorted({p["plan_code"] for p in plans}),
            "missing": sorted(set(plan_codes) - {p["plan_code"] for p in plans}),
            "doc_id": catalog["doc_id"],
        }

    # -- drivers ---------------------------------------------------------
    def backfill(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """backfill(queries=['comptroller', 'sales tax'], limit=50)"""
        queries = kwargs.get("queries") or ["comptroller"]
        limit = int(kwargs.get("limit", 50))
        out = {q: self.search_datasets(conn, q, limit=limit)["total"] for q in queries}
        out["_datasets"] = conn.execute(
            "SELECT COUNT(*) c FROM socrata_dataset"
        ).fetchone()["c"]
        return out

    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """Refresh the domain census, the plan catalogue, and the TEC-absence
        watch. Never raises on the watch — an appearance is reported, and the
        caller decides."""
        limit = int(kwargs.get("limit", 25))
        census = self.search_datasets(conn, None, limit=limit)
        plans = self.catalogue_redistricting(conn)
        watch = self.assert_no_ethics_datasets(conn, strict=False)
        return {
            "domain_assets": census["total"],
            "catalogued": conn.execute(
                "SELECT COUNT(*) c FROM socrata_dataset"
            ).fetchone()["c"],
            "plan_codes": plans["plan_codes"],
            "ethics_watch": watch,
        }

    # -- smoke -----------------------------------------------------------
    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """6 live requests: 1 catalog search, 3 ethics negatives, 1 plan
        catalogue, 1 rows page."""
        catalog = self.search_datasets(conn, "comptroller", limit=10)
        watch = self.assert_no_ethics_datasets(conn, strict=False)
        plans = self.catalogue_redistricting(conn)
        rows = self.fetch_rows(conn, "gern-2bvs", limit=10)

        ok = (
            catalog["returned"] >= 5
            and watch["clean"]
            and len(plans["plan_codes"]) >= 1
            and rows["rows"] >= 1
        )
        detail = (
            f"data.texas.gov: {catalog['total']} assets match 'comptroller' "
            f"({catalog['returned']} catalogued); ethics watch {watch['queries']} "
            f"(clean={watch['clean']}); plans {plans['plan_codes']} "
            f"(missing {plans['missing']}); gern-2bvs returned {rows['rows']} rows "
            f"with fields {rows['fields']}"
        )
        return SmokeResult(
            ok=ok,
            detail=detail,
            stats={
                "catalog_total": catalog["total"],
                "catalogued": catalog["returned"],
                "ethics_watch": watch,
                "plan_codes": plans["plan_codes"],
                "rows": rows["rows"],
                "requests": 6,
            },
        )
