# LobbyBook Ingestion Platform

Working implementation of the ingestion roadmap from
[`docs/texas-politics-audit/`](../docs/texas-politics-audit/README.md): the canonical
schema, an immutable document store, a compliance-aware fetcher, the entity spine, and
one connector per audited source family.

## Quick start

```bash
cd platform
pip install httpx pydantic pdfplumber pypdf feedparser pyyaml pytest
python3 -m lobbybook.cli init-db          # creates var/lobbybook.db + var/blobs/
python3 -m lobbybook.cli sources          # list registered connectors
python3 -m lobbybook.cli smoke tlo        # one bounded live fetch per connector
python3 -m lobbybook.cli ingest tlo       # incremental (RSS feeds)
python3 -m lobbybook.cli demo 89R HB1     # end-to-end bill dossier
```

Tests: `python3 -m pytest tests/ -q` (offline, fixture-driven).
Live tests: `LOBBYBOOK_LIVE=1 python3 -m pytest -m live -q` (bounded real fetches).

## Architecture

- **`lobbybook/core/`** — `schema.sql` (canonical model from the audit's knowledge-graph
  doc; SQLite now, Postgres-portable DDL), `docstore.py` (immutable, content-addressed
  document versions — replaced-in-place PDFs become explicit history), `fetch.py`
  (compliance denylist, per-host throttles, identified UA, browser profile only where
  the audit verified bot-mitigation-vs-public-content), `registry.py` (connectors +
  per-source DDL).
- **`lobbybook/spine/`** — sessions (1846→2027), people (OpenStates canonical IDs +
  LRL/TEC crosswalks), name resolution (never silent merges; confidence + method
  recorded).
- **`lobbybook/sources/`** — one module per source family. Parsers are pure functions
  over bytes (offline-testable); connectors wire fetch → docstore → canonical rows →
  provenance-tagged edges.
- **`lobbybook/demo.py`** — the acceptance demo: a citation-bearing dossier joining
  every ingested corpus for one bill.

Three invariants, enforced in core:

1. Every fetched artifact is stored (hashed, versioned) before parsing.
2. Every graph edge carries a provenance class — `explicit`, `derived`, or `inferred` —
   and a source document. Bad classes raise.
3. Session codes are opaque (`89R`, `883`); bill keys are always session-scoped.

## Source status

<!-- STATUS_TABLE: refreshed at each wave's integration pass -->
All 20 connectors are registered and scheduled; `lobbybook smoke` runs one bounded live
fetch against each. Last full run (2026-08-26): **19 ok, 1 blocked, 0 failing.** The
"verified" column quotes that run, not a plan.

| Connector | Tier | Cadence | Status | Verified against live sources |
|---|---|---|---|---|
| `spine_sessions` | 0 | static | working | 117 sessions, TLO called-session codes (`883` = 88th 3rd called) |
| `spine_people` | 0 | monthly | working | 179 current legislators, 179 tenures, House member-id crosswalks |
| `tlo` | 0 | hourly in session | working | 10 RSS feeds; bill history parsed (89R HB 1) |
| `journals` | 0 | daily in session | working | 98 House days indexed; one day yields 113 record votes / 16,950 casts; every tallied-and-listed vote re-checked (89R-H-R3009: 147 reported == 147 named) |
| `hro` | 0 | daily in session | working | 88R HB 16: 6 sections (SUPPORTERS SAY 2,675c / CRITICS SAY 333c), 24 witnesses, 9 committee votes; SRC analyses too |
| `committees` | 0 | hourly in session | working | 969 witness slips from one hearing across 2 bills; 41/524 videos captioned, WebVTT cues harvested |
| `lbb` | 0 | daily in session | working | 89R SB 2: 8 of 15 shared cells differ between Introduced and Engrossed — the version trap, quantified |
| `register` | 0 | weekly (Friday) | working | Aug 21 2026 issue: 8 notices, 14 authority cites |
| `tec` | 0 | nightly | working | 1.04 GB campaign-finance ZIP mapped via 2 MB of ranged reads: 139 members, 9.13 GB uncompressed, 105 contribution shards |
| `governor` | 1 | daily | working | 8 appointments parsed from the feed, 7 edges |
| `statements` | 1 | daily | working | 406 statements for one senator, 401 with native compound IDs |
| `news` | 1 | hourly | working | 20 dated+titled Tribune items, canonical URLs verified; `the_texan` declared blocked, not scraped |
| `sunset` | 1 | review cycle | working | 24 cycles; 55 recommendations for one agency |
| `interim` | 1 | interim season | working | 186 charges across 35 committees; 26 monitoring charges naming 76 bills |
| `ag` | 2 | daily | working | Opinion ledger back to Gerald Mann (O-0001 → O-5740); pending requests to RQ-0653-KP |
| `courts` | 2 | weekly | working | CourtListener freshness measured, not assumed (SCOTX 341-day lag); Business Court 123 entries |
| `comptroller` | 2 | quarterly | working | Socrata live; the audit's negative finding re-confirmed — ethics/lobby/campaign-finance searches all return 0 |
| `stratplans` | 2 | biennial | working | TEA: filename says 2024, cover says FY 2025-2029 — 171 pages, 4 goals, 19 bill citations, 8 session-qualified |
| `campaign` | 2 | election cycle | working | One PAC endorsement slate: 74 rows, 74 candidates, 74 explicit edges |
| `platforms` | 2 | convention cycle | **source blocked** | Parsers pass against the captured 2024 RPT PDF, but texasgop.org now Cloudflare-challenges every path except `robots.txt` — under our bot UA *and* a browser UA — despite robots.txt reading `Disallow:` (see the deep dive). Reported as `blkd`, never as an empty corpus |

A blocked source is reported distinctly from a broken one: `smoke` prints `[blkd]` and
does not fail the run, because a source refusing us is not a bug we can fix in a parser.
Only `[FAIL]` means the connector is wrong.

### End-to-end demo

`python3 -m lobbybook.cli demo 89R HB7` joins four source families for one real
bill and surfaces intelligence no single source exposes:

* **the version trap, quantified** — General Revenue estimates of −$33.7M (As
  Introduced) vs −$64.6M (Committee Report). Citing "the fiscal note" without a
  version code misstates the bill by ~$31M.
* **a 16:1 registration lean** (26 for / 413 against), labelled a mobilization
  signal rather than a vote count.
* **coalition structure** visible in the most-represented organizations.

## Compliance posture

The audit found named AI-crawler blocks and anti-data-mining policies across several
Texas sources. This platform's stance, enforced in `core/fetch.py`:

- **Hard denylist** (raises before any bytes move): `lrl.texas.gov` PDFs/doc/txt and its
  export endpoint; `search.txcourts.gov` (TAMES, robots `Disallow: /`);
  `research.txcourts.gov`. The txcourts patterns are **subdomain-tolerant on purpose** —
  CourtListener's pre-2015 Texas backfill serves every `download_url` from
  `www.search.txcourts.gov`, which a bare hostname anchor let through (20/20 records in
  the captured fixture), so a naive full-text fetcher would have walked into TAMES
  unblocked.
- **Throttles** on every state host, honouring a declared `Crawl-delay` where one exists;
  identified `LobbyBookBot` UA by default.
- **A CDN challenge is a verdict, not a retryable error.** `403` with `cf-mitigated` or a
  Cloudflare `server` header returns immediately instead of burning four requests on a
  host that will keep refusing, and the connector reports the source as blocked.
- **Bounded sampling, never enumeration**, against `capitol.texas.gov/tlodocs` (robots
  disallows bulk crawling; TLC policy blocks data-mining firms). Production-scale
  backfills there should follow the access conversations flagged in the audit roadmap.
- Sanctioned channels preferred wherever they exist: TLO RSS, the House JSON API, TEC
  bulk ZIPs, UNT OAI-PMH, CourtListener, Socrata.

## What is deliberately stubbed

Keyed or gated integrations ship as documented stubs, not fake scrapers: LegiScan sync
(API key), Meta Ad Library (verified developer access), post-2023 AG ORL portal
(Salesforce SPA), TAC full-text versioning (build-vs-license decision), bulk ASR
transcription (compute budget). Each stub says what unblocks it.
