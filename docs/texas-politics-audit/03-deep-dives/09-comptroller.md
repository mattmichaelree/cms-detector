# Texas Comptroller of Public Accounts

**Authority class:** A (BRE/CRE are the constitutionally binding revenue estimates;
collections/expenditures are raw government records) / B (Fiscal Notes magazine) ·
**Priority: Tier 2** · Verified by live inspection, Aug 2026.

## 1. Corpus & coverage

- **Certification Revenue Estimate (CRE):** archive verified **2006-07 → 2026-27** at
  https://comptroller.texas.gov/transparency/reports/certification-revenue-estimate/,
  with mid-biennium "revised" editions (2018-19, 2020-21, 2022-23). Current biennium
  ships as **PDF + XLSX data file** (both verified live).
- **Biennial Revenue Estimate (BRE):** pre-session estimate that sets the Art. VIII §22
  constitutional spending ceiling. Real numbers verified via releases: 89th-Leg BRE =
  $194.6B (Jan 2025); Oct 2025 CRE revised to ~$203.6B against $198.97B enacted GR-related
  spending. Exact standalone BRE file path UNVERIFIED this pass.
- **Fiscal Notes magazine** (plain-language economic explainers): HTML archive to 2015
  (https://comptroller.texas.gov/economy/fiscal-notes/about/archive.php), still
  publishing.
- **Transparency tools:** the old "Where the Money Goes/Comes From" tools are replaced by
  a **Qlik dashboard** (bivisual.cpa.texas.gov, ~10 years of data; download formats
  UNVERIFIED). The Comptroller "Databases" page lists ~17 query-only web tools (sales/
  franchise tax status, CMBL vendor directory, State Contracts Master Index via
  txsmartbuy, State Payments Issued — login required, pensions, unclaimed property) —
  almost none bulk-downloadable.
- **Sales tax allocation:** https://mycpa.cpa.state.tx.us/allocation/ — quarterly
  city/county/MSA/industry data back to **2002**, plus monthly allocation reports.
- **data.texas.gov is a genuine Socrata portal with a working SODA API** — verified by
  live call (`https://data.texas.gov/resource/mmev-jnp9.json?$limit=3` returned JSON).
  Comptroller datasets present: active franchise taxpayers, sales-tax permit holders,
  mixed-beverage receipts, hotel tax permits, ag/timber exemptions. **No lobbying or
  campaign-finance datasets live there** (that's TEC).

## 2. Native formats (verified)

CRE: PDF + XLSX. Fiscal Notes: HTML. Dashboards: proprietary Qlik embeds (not
API-accessible). data.texas.gov: standard Socrata (JSON verified; CSV/XML standard).
The 17 "databases": HTML search results, not files.

## 3. What a lobbyist uses it for

The master workflow is **"is there headroom?"** — verified concretely: the 89th began
with a $194.6B ceiling and ended with $203.6B certified, ~$9B of mid-course headroom —
exactly the number that drives late-session supplemental appropriations and rider
strategy. The Comptroller is also an *operational agency* when new law routes programs
through it (verified: SB 2's ESA program is Comptroller-administered), making its
rulemaking a regulatory-monitoring target. Sales-tax-by-city and franchise-status data
support local economic-development advocacy and competitor research.

**Usefulness:** fiscal intelligence HIGH · forecasting HIGH · session monitoring HIGH
(headroom drives what can pass) · bill strategy HIGH · political intelligence HIGH (the
BRE is a political event) · regulatory monitoring HIGH (when Comptroller administers
programs) · issue research HIGH · historical research HIGH · compliance MED · meeting
prep MED · client intelligence MED · committee strategy MED · opposition research MED ·
coalition LOW · relationship LOW · campaign LOW.

## 4. Ontology & native IDs

Revenue estimate (BRE/CRE per biennium + revision date) · fund (incl. Economic
Stabilization Fund) · tax type · taxpayer/permit holder (permit numbers) · vendor/payee
(CMBL IDs) · contract · expenditure transaction (Comptroller object codes) · local
jurisdiction · biennium.

## 5. Edges

EXPLICIT: BRE→sets_ceiling_for→biennium (Art. VIII §22) · CRE→supersedes/certifies→BRE ·
expenditure→paid_to→vendor / →from_fund→fund · allocation→paid_to→city.
DERIVED: bill→routes_program_through→Comptroller (from fiscal-note/bill text).
INFERRED: revenue-trend deltas→indicate→available headroom (present as analysis, not
fact).

## 6. Temporal semantics

BRE = single pre-session point estimate; CRE = end-of-session certification, sometimes
revised mid-biennium; monthly collections track actuals continuously. **Version trap:**
BRE, CRE, and monthly actuals are three distinct numbers routinely conflated as "how much
money Texas has" — always name which estimate, which revision, which date.

## 7. Authority

BRE/CRE: A (constitutionally binding estimate — but an estimate; frame as "the
Comptroller certified/estimated"). Collections/expenditure records: A. Fiscal Notes
magazine: B (Comptroller-authored explainer framing).

## 8. Ingestion

CRE/BRE: predictable per-biennium URLs, trivial backfill (~20 files). data.texas.gov:
standard Socrata incremental sync. The Qlik dashboards and login/search-only databases
are the bottleneck — scraping automation or a data-sharing request. Dedup: (biennium,
revision date) for estimates; (agency, vendor, date, amount, object code) for
transactions.

## 9. Training value

Mostly retrieval + eval. Twenty years of estimate-vs-actual pairs = a clean numeric-
forecasting eval set. Fiscal Notes magazine = good RAG explainer corpus. Vendor/taxpayer
data = entity-classification scale, weak for instruction tuning.

## 10. Derived intelligence

BRE-vs-CRE "revenue surprise" signal predicting supplemental-appropriations activity ·
sales-tax-by-city trends as leading indicators for local-economy advocacy ·
vendor-payment concentration (procurement dependency) flags · joining Comptroller-
administered program data to the bills that created them (ESA-style lineage).

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 5 | BRE/CRE headroom is the master constraint on every fiscal ask |
| Uniqueness | 5 | Nothing else sets the constitutional ceiling |
| Authority | 5 | Constitutionally binding estimate + raw fiscal records |
| Historical value | 4 | CRE verified to 2006-07; allocation data to 2002 |
| Current-session value | 5 | Drives real-time "can this get funded" |
| Structure quality | 4 | Clean PDF+XLSX estimates; weak proprietary dashboards |
| Ingestion ease | 3 | Easy files + Socrata; hard query-only tools |
| Entity richness | 3 | Rich tax/vendor entities; thin legislative entities |
| Relationship richness | 3 | Mostly tabular, lightly linked |
| Training value | 3 | Forecasting evals; little instruction value |
| Retrieval value | 4 | Clean text/tables |
| Derived intelligence | 4 | Revenue-surprise + trend signals genuinely predictive |
| Moat potential | 3 | Numbers are public and widely reported; moat is speed/synthesis |
