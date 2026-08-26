# Texas Ethics Commission (TEC) — campaign finance, lobbying, PFS, enforcement

**Authority class:** D in the task's taxonomy (regulated disclosure — self-reported under
penalty, not government-verified; enforcement orders and advisory opinions are official
interpretations) · **Priority: Tier 0** · Verified by live inspection incl. byte-range
analysis of the live bulk files, Aug 2026.

## 1. Corpus & coverage

| Corpus | Depth | Access |
|---|---|---|
| Campaign finance (electronic) | **Jul 1, 2000 →** live (sampled rows filed Jan 2026) | Bulk CSV ZIP + search UI, https://www.ethics.state.tx.us/search/cf/ |
| Campaign finance (paper era, pre-2000) | Not digitized into the CSV product | — |
| Lobby activity (electronic detail) | **Feb 2005 →** current | Bulk CSV ZIP |
| Lobby activity (paper, 1993–2005) | Cover-sheet totals only in `LaCvr.csv` | — |
| Lobby registration (clients + comp bands) | Full client/comp via search 2016+; static year-range lists to 2011; "updated daily" | **PDF/Excel only — no bulk CSV exists** |
| Personal financial statements | **Not published online at all** (verified: platform says open-records request required); only PFS *delinquency* is public | — |
| Advisory opinions (EAO) | 1992 → present, numbered, native HTML digests | /opinions/ |
| Enforcement orders | 1992 → present — but dismissals and de-minimis findings stay confidential (selection-biased corpus) | /enforcement/ |

**Confirmed coverage gaps:** local filers (city/county/school candidates) file with local
authorities, not TEC — TEC's own disclaimer says so verbatim; total gap for that
population. Pre-2016 registration client dates/comp bands lost to a 2015 data migration.

**Platform state:** legacy front end on EOL software (Apache 2.4.6/PHP 5.4 — verified
headers) that intermittently 404s documented paths, while bulk delivery runs on a modern
AWS/CloudFront stack (prd.tecprd.ethicsefile.com → CloudFront). **ethics.texas.gov
already resolves behind HTTP 401 basic auth — a staged domain migration to watch.** No
robots.txt, no sitemap, **no API of any kind.**

## 2. Native formats (verified in depth)

**Campaign-finance bulk ZIP** (`TEC_CF_CSV.zip`, labeled "As of 08/25/2026"):
**1.04 GB compressed / 9.13 GB uncompressed, 139 files** — central directory read via
ranged HTTP request and parsed; sample rows decoded from targeted byte ranges. Contents:
`filers.csv` (master filer index) · `cand.csv` (direct-expenditure targets, joined to
expenditures via `expendInfoId`) · `cover.csv`/`cover_ss.csv`/`cover_t.csv` (cover
sheets/totals; cover.csv alone 195 MB) · `purpose.csv` (Cover Sheet 3) · `spacs.csv` ·
`contribs_01–103.csv` (~104 shards) · `cont_ss.csv`/`cont_t.csv` (special-session /
daily-pre-election kept separate **specifically to avoid duplicates**) ·
`expend_01–13.csv` · `expn_t.csv` · `expn_catg.csv` (21 expenditure categories) ·
pledges/loans/debts/credits/travel/assets/finals · `CFS-ReadMe.txt` (full fixed-width
record-layout spec, 16 record types) · `CFS-Codes.txt` (593-line code glossary). A
separate PDF format spec is also published.

**Lobby-activity bulk ZIP** (`TEC_LA_CSV.zip`): 17.2 MB / 137 MB, 11 files —
`LaCvr.csv` (82 MB cover totals) · `LaSub.csv` (coded subject matter, e.g. 74=State
Finances) · per-schedule files (transportation/food/entertainment/gifts/awards/events) ·
`LaI4E.csv` with `onbehalfName` (the closest thing to a lobbyist→client link in activity
data). **Mixed exact/range amounts confirmed at field level** (`activityExactAmount` vs
`activityAmountRangeLow/High`; entertainment rows observed range-only, food rows exact).

**Registration compensation is in inflation-indexed bands**, not exact dollars
(2025 bands cited as <$22,240 … ≥$1,112,200 — UNVERIFIED secondary).

**Nightly full rebuild, no deltas:** both ZIPs carry "As of [yesterday]" labels,
same-day Last-Modified headers (CF 10:35 GMT, Lobby 05:39 GMT — two independent jobs),
and ~04:16 local internal timestamps. Ingestion must re-download and diff locally.

## 3. What a lobbyist uses it for

*Who gave money to this legislator?* (contribs shards by filerIdent) · *Who funds the
opposition PAC?* (spacs → filers → contribs) · *Who are my competitor's clients?*
(registration lists / LaI4E) · *Which lobbyists work orgs affected by my bill?* (subject
codes + registration — coarse topical, needs an external bill↔topic map) · *Am I
compliant?* (delinquent lists + own filing history — TEC is the system of record).

**Usefulness:** client intelligence HIGH · political intelligence HIGH · opposition
research HIGH · campaign intelligence HIGH · relationship intelligence HIGH · meeting
prep HIGH · compliance HIGH · historical research HIGH · fiscal (cash-on-hand) HIGH ·
session monitoring MED · bill strategy MED · committee strategy MED · issue research MED ·
coalition MED · forecasting LOW-MED · regulatory monitoring NONE.

## 4. Ontology & native IDs

Filer (**8-digit zero-padded `filerIdent`**, one namespace across COH/JCOH/GPAC/MPAC/
SPAC/LOBB/party/speaker types — verified) · candidate/officeholder · committees (SPAC
rows carry their supported candidate's filer ID explicitly) · treasurer/chair (embedded
attributes, not IDs) · donor (freetext name/employer/occupation, **no persistent ID**;
optional `contributorPacFein` for PAC donors) · lobbyist (LOBB filer) · client (freetext
only) · payee (freetext) · report (`reportInfoIdent` — 5–7-digit legacy vs 9-digit
post-migration values reveal the platform migration) · line items
(`contributionInfoId`/`expendInfoId`/… global sequential IDs) · subject-matter codes ·
expenditure categories · EAO numbers · enforcement docket numbers.

## 5. Edges

EXPLICIT: filer→files→report · line_item→belongs_to→filer/report ·
direct_expenditure→benefits→candidate (`expendInfoId` join to cand.csv) ·
**SPAC→supports→candidate (`candidateFilerIdent` carried directly)** ·
lobbyist→reports_activity_for→onbehalf entity (LaI4E).
DERIVED: GPAC→supports/opposes→target — **not explicit**: purpose.csv names targets as
freetext with no filer ID; name-join required · donor aggregation by raw name string.
INFERRED: **donor A = donor B — the central entity-resolution challenge, observed live:
`"American Pharmacies, Inc."` and `"American Pharmacies"` as employer strings on adjacent
rows with no linking ID** · lobbyist↔client↔CF cross-corpus identity (registration lives
in PDFs with no shared ID) · employer→industry coding (none exists) · PAC donor-overlap
networks · any money→legislative-action claim (never state as causation).

## 6. Temporal semantics

`contributionDt`/`expendDt` (transaction) vs `receivedDt` (TEC receipt) vs `filedDt`
(filing, later for corrections) vs `periodStartDt`/`periodEndDt` (report scope) vs
`electionDt`/`dueDt` (context). **Two engineered traps, both verified:**
1. **Double-counting:** daily-pre-election and special-session transactions live in
   separate `_t`/`_ss` tables because they are re-reported on the next regular report —
   naive summing across shards double-counts.
2. **Divergent amendment semantics:** CF flags superseded rows in place
   (`infoOnlyFlag` on every record type + `COR*` correction-affidavit form types) while
   the lobby export **silently drops superseded originals**. Citing an original CF
   figure later revised by a correction affidavit is the misinformation hazard —
   always resolve the correction chain.

## 7. Authority

Disclosures (CF, lobby activity, registration): regulated self-reports — phrase as
"*[filer] reported [amount] to the TEC*," never "*received*." Commission orders:
adjudicated findings (citable as findings, selection-biased corpus). Advisory opinions:
official interpretation of ethics law. Third-party cleanups (Transparency USA,
FollowTheMoney): downstream copies — inherit all limits plus transformation risk.

## 8. Ingestion

Bulk download both ZIPs nightly; **resolve the ZIP URL from the search-page HTML rather
than hardcoding paths** (legacy front end 404s static paths while CloudFront stays
healthy). Stream the shards (9 GB uncompressed). Dedup: `reportInfoIdent` + line-item
ID; consult `infoOnlyFlag`; exclude `_ss`/`_t` from totals. Change detection = local
diff of ID/flag state; a row flipping to superseded or a new COR* row is an
amendment event worth surfacing to users who saw the original number. Registration
(clients/comp) has **no bulk path** — scrape the daily-updated PDF/Excel year lists; a
structurally separate, fragile pipeline. Watch the ethics.texas.gov migration.

## 9. Training value

Entity-resolution training pairs minable at scale (co-occurring name variants under the
same filer/date window as weak positives) · expenditure-category (21) and
subject-matter (~100) codes as supervised labels for freetext description classifiers ·
advisory opinions as self-contained ethics-law Q&A instruction pairs · commission orders
as a small "was there a violation" eval set. Otherwise retrieval-first.

## 10. Derived intelligence

Money networks (donor↔PAC↔candidate, post-resolution) · lobbying roster shifts around
issues (subject-code churn per lobbyist/client/year) · donor overlap between PACs ·
client exposure indices (summed comp bands as spend-intensity proxy) · **contribution
timing vs the legislative calendar** (session blackout/surge windows — directly
computable from contributionDt × electionDt/dueDt) · compliance-risk scoring
(delinquency history + filedDt-vs-dueDt patterns).

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 5 | The client/comp/registration + campaign-money system of record |
| Uniqueness | 4 | Sole primary source; third parties are downstream copies |
| Authority | 3 | Self-reported disclosure, not verified fact; orders/opinions higher |
| Historical value | 5 | CF to 2000, lobby to 2005 (totals 1993), EAOs/orders to 1992 |
| Current-session value | 4 | Nightly rebuild ≈ live; lacks bill/committee context by design |
| Structure quality | 4 | Genuinely documented schemas + codebooks; 139 shards, two amendment conventions |
| Ingestion ease | 3 | No API, 9 GB nightly full rebuild, no deltas, registration has no bulk path |
| Entity richness | 4 | Filers, committees, lobbyists, clients, payees, coded categories |
| Relationship richness | 4 | Strong explicit FK joins; the best edges (lobbyist↔client, GPAC targets, donor dedup) are derived/inferred |
| Training value | 3 | Entity-resolution pairs + coded labels; thin instruction value outside EAOs |
| Retrieval value | 4 | Citable to exact report/line-item ID |
| Derived intelligence | 4 | Money networks, timing, exposure indices — once resolution is solved |
| Moat potential | 3 | Raw feed is public and copied; the moat is LobbyBook's entity resolution + cross-corpus linking |
