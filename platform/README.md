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
| Connector | Tier | Status | Verified against live sources |
|---|---|---|---|
| `tlo` | 0 | working | 10 RSS feeds; bill history parsed (89R HB 7: caption + 12 actions) |
| `journals` | 0 | working | Vote rolls with a built-in correctness proof — 294 tallied-and-listed positions checked, 0 mismatches; 16,950 casts from one day |
| `hro` | 0 | working | Stance sections (SUPPORTERS SAY / CRITICS SAY), named committee votes, witness rosters |
| `committees` | 0 | working | 969 witness slips from one hearing, both eras; committee votes; live WebVTT caption harvest |
| `lbb` | 0 | working | Per-version fiscal notes; version trap proven on SB 2 and HB 7 |
| `register` | 0 | working | TRD notice splitter; relative comment deadlines resolved to real dates |
| `spine_sessions` | 0 | working | 117 sessions, TLO called-session codes (`883` = 88th 3rd called) |
| `spine_people` | 0 | working | 179 current legislators, 149 House member-id crosswalks |
| Tier 1/2 sources | 1–2 | in progress | tec, sunset, interim, courts, governor, news, statements |

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
  `research.txcourts.gov`.
- **Throttles** on every state host; identified `LobbyBookBot` UA by default.
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
