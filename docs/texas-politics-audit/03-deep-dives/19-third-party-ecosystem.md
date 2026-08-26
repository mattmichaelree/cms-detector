# Cross-Cutting: LRL, OpenStates, LegiScan, Open-Data & Archive Ecosystems

**Role:** historical backbone + entity spine + redundancy layer for every first-party
source · **Priority: Tier 0 (entity spine + LegiScan/OpenStates), Tier 1 (archives)** ·
Verified by live inspection, Aug 2026.

## 1. Legislative Reference Library (lrl.texas.gov)

- **⚠ robots.txt is a real compliance blocker (verified):** individually disallows
  ClaudeBot/anthropic-ai/GPTBot/CCBot/Perplexity/etc. with `Disallow: /`, and the
  wildcard rules block `/*.pdf`, `/*.doc`, `/*.txt` sitewide plus the
  `/legis/billsearch/exportproc.cfm` export endpoint (whose existence proves an internal
  export mechanism). Practical path: human-triggered pulls or negotiated access
  (lrl.service@lrl.state.tx.us) — never a live crawler.
- **Members database** (Texas Legislators: Past & Present): verified live profile
  (`memberDisplay.cfm?memberID=5746`) with chamber, district, party, counties, exact
  service dates, and per-legislature committee assignments. **`memberID` is a stable
  dereferenceable numeric person ID** — the deepest-history person key in the ecosystem.
  Coverage stated 1876→present (pre-1876 UNVERIFIED). No export/API.
- **Journals:** digitized 1846–2026 + Republic of Texas Congress (1836–45, incl. Senate
  secret journals); 89th+ link out to journals.house/senate.texas.gov (HTML), 88th and
  earlier are scanned PDFs; no LRL full-text search.
- **Other databases (all verified):** interim reports (indexed under the *ordering*
  legislature — join-key gotcha), governors/executive-orders (EO collection starts with
  Shivers, 1949+, self-declared "not comprehensive"), vetoes by session + overrides,
  constitutional amendments (1879+), **complete sessions list 1846→90th (2027) with exact
  dates** (the canonical session spine), redistricting bibliography (pointers; geometry
  lives at TLC), appropriations bills to 1927.
- Self-flags incompleteness for older bill files. Zero programmatic access.

## 2. OpenStates (openstates.org / pluralpolicy.com)

- **Actively maintained** — scraper repo commits dated the day before this audit;
  GPL-3.0 code, **CC0 people data** (github.com/openstates/people, `data/tx/…`).
- TX scrapers are downstream of the state's own systems (ftp.legis.state.tx.us
  bill-history XML + witness lists; TLO History.aspx) — a normalization layer, not an
  independent archive.
- **API v3** (v3.openstates.org, X-API-KEY): jurisdictions/people (incl. geo lookup)/
  bills/committees/events. Current rate limits not published (2018 tier numbers are
  historical — UNVERIFIED as current).
- **Bulk:** per-session CSV/JSON (JSON includes full bill text), legislator YAML/CSV,
  district JSON, full Postgres dumps at open.pluralpolicy.com/data/; bills/votes update
  monthly.
- **⚠ The vote finding (verified in code):** `scrapers/tx/votes.py` reconstructs roll
  calls by parsing journal HTML because **Texas publishes no structured roll-call feed
  anywhere**. Code comments document inconsistent tally phrasing, rendering artifacts,
  duplicate records, and a skipped session. Every downstream vendor inherits this same
  weak primary source — vote counts are provisional until checked against the journal
  itself.

## 3. LegiScan (legiscan.com)

- (Bot-blocked to plain fetch; verified via alternate fetcher.) **API:** JSON; Public
  tier free, key required, **30,000 queries/month**; paid Pull tiers 100k–250k; **Push
  tier replicates the national DB every 4 hours (15 minutes optional)** — the only
  near-real-time replication offer in the ecosystem.
- **Datasets:** weekly per-state-session snapshots (CSV Basic or full JSON: bills +
  votes + people), free login to download. Licensing: **CC BY 4.0 (API) vs CC BY-SA 4.0
  (datasets)** — the ShareAlike clause on bulk datasets needs counsel review before
  commercial redistribution. Also advertises a ~350GB legislative text training corpus
  under separate licensing.
- TX current through the 89th (verified). Stable numeric people IDs
  (`legiscan.com/TX/people/…/id/23184`).

## 4. data.texas.gov (Socrata)

- 1,470 datasets domain-wide (Discovery API, verified). **Hard negative finding:
  q=ethics → 0; q=lobby → 0; q=campaign finance → 0. TEC publishes nothing here** — its
  bulk data lives only on TEC's own infrastructure. Never assume this portal represents
  "the state's open data" for LobbyBook's core subjects.
- What IS here: **redistricting plan boundaries as Socrata datasets using TLC plan codes
  verbatim** (Plan H2316, S2168, C2193 + 2010-cycle plans); Comptroller "State
  Expenditures by County" per FY 2007–2024; election-adjacent series. SODA API verified
  live (`/resource/{id}.json?$limit=…`).

## 5. Internet Archive / Wayback + TSLAC

- **Wayback holds deep, systematic capitol.texas.gov coverage** — CDX API verified
  (`cdx/search/cdx?url=capitol.texas.gov&matchType=domain` → 1,150 result pages ≈ order
  of 100k+ captured URLs; directional, not exact). Usable for point-in-time bill-page
  reconstruction via standard CDX queries.
- **Institutional gap (verified):** TSLAC's TRAIL/Archive-It program web-archives
  *executive-branch agency* sites; per HB 4181/HB 1962 (86th), *legislative* electronic
  records belong to LRL — which runs no web-archiving program. **The Internet Archive's
  opportunistic crawl is, in practice, the only systematic preservation layer for the
  Legislature's own website.** LobbyBook's own immutable document store becomes part of
  the answer here.

## 6. Portal to Texas History (UNT)

- **APIs verified:** OAI-PMH (`oai_dc` + `untl`, no key), IIIF manifests per item, RSS/
  Atom for new additions. Bulk-harvest limits UNVERIFIED.
- **Legislative holdings verified:** Senate Journals collection — 261 items, 38th (1923)
  → 83rd (2013); House Journals — 356 items, 41st (1929) → 88th (2023); both full-text
  searchable (which LRL's own PDFs are not). Texas Register complete 1976→present (see
  the Register deep dive). Curated subsets, not complete substitutes for LRL holdings.

## 7. Academic / civic datasets

- **TLC Capitol Data Portal (data.capitol.texas.gov, CKAN — verified):** the first-party
  home for redistricting geometry + elections: VTD shapefiles (e.g., VTDs_22G.zip),
  precinct and school-district boundaries, every redistricting plan (down to
  litigation-stage demonstrative maps) with shapefiles + district election-analysis
  PDFs; **election returns joinable to VTD geometry via VTDKEY**; CKAN API present
  (exact shape UNVERIFIED).
- **Shor-McCarty ideal points** (Harvard Dataverse, doi:10.7910/DVN/GZJOT3): ~24,716
  state legislators, 1993–2020; peer-validated; post-2020 update UNVERIFIED. Slow-moving
  ideology enrichment layer.
- **Klarner state legislative election returns 1967–2012** (Dataverse; structure
  UNVERIFIED) — historical elections backbone.
- **Texans for Public Justice (tpj.org):** still active but thinly staffed (verified:
  part-time $20/hr database-specialist posting). Narrative PDFs derived from TEC data —
  an analysis layer to cite, never a data source to ingest.

## 8. GitHub ecosystem (verified via web pages; API proxy-blocked)

Live and professional: **openstates/openstates-scrapers** and **openstates/people**
only. TEC-specific tooling is thin: `texastribune/tx_lobbying` archived/dead since 2018;
IRE's `accountability_datacleaning` TX tree active through Jan 2024 then doc-only
touches (2025–26); `tx_tecreports` (PyPI) currency UNVERIFIED. Build TEC parsing
in-house; don't depend on any of these.

## A. Recommended roles

| Layer | Source | Note |
|---|---|---|
| Pre-2009 historical backfill | LRL (negotiated/manual) + Wayback CDX | Only 1846-continuity party + the only TLO snapshot archive; never a live crawler |
| People entity spine | **OpenStates people YAML (CC0) as canonical**, cross-walked to LRL memberID + LegiScan IDs | Only openly licensed, session-stable ID system |
| Current-session live feed | LegiScan Push/Pull primary; OpenStates bulk as independent QA diff | 4h/15min replication vs monthly bulk |
| Roll-call votes | OpenStates scrape as primary; journal HTML as ground truth for anything high-stakes | Same weak primary underneath every vendor |
| District geometry | TLC Capitol Data Portal shapefiles; Socrata mirrors as second query surface | Plan codes natively shared — no crosswalk needed |
| Journal full-text (1920s–2010s) | UNT Portal (OAI-PMH/IIIF) | Only full-text-searchable machine-accessible slice |
| Ideology layer | Shor-McCarty | Refresh only on new Dataverse releases |
| Skip | data.texas.gov for ethics/lobby/CF (verified empty); dead GitHub repos; TPJ as data | Confirmed negative results |

## B. Entity-spine strategy

- **People:** OpenStates person ID = internal canonical key (CC0, designed for
  cross-session stability); attach LRL `memberID` and LegiScan people IDs as xrefs
  ("stable in practice, not by contract").
- **Districts:** key on TLC plan code + district (`PLANH2316-092`) — the one identifier
  three independent sources already share verbatim.
- **Sessions:** LRL's session list (1846→2027 with dates) is canonical; map OpenStates
  and LegiScan session labels onto it via a ~180-row static lookup.
- **Bills:** `(session_id, chamber, bill_number)` composite — consistent across TLO,
  LRL, OpenStates, LegiScan once sessions are normalized.

## C. Risks

Licensing fragmentation (CC0 vs GPL code vs CC BY vs **CC BY-SA on LegiScan bulk** —
legal review before redistribution) · single-maintainer decay demonstrated across the
TEC tooling ecosystem · **the structural roll-call gap: LRL, OpenStates, and LegiScan
all reconstruct votes from the same journal HTML — three scrapers, one weak primary;
vote features inherit that fragility undiversified** · LRL robots policy names AI
crawlers explicitly — compliance is a design requirement, not a nicety · no state
entity web-archives the Legislature's site (Wayback is the de-facto archive) · the
data.texas.gov negative result: absence there proves nothing about existence.
