# Sunset Advisory Commission

**Authority class:** A (official commission of the Legislature; layered internal voices —
see §7) · **Priority: Tier 1** · Verified by live inspection, Aug 2026.

## 1. Corpus & coverage

- **Cycle index:** https://www.sunset.texas.gov/review-cycles — all 24 cycles from
  1978–81 (66th–67th Leg.) through 2024–25 (89th), each at a stable-but-opaque Drupal
  `/node/{id}` URL (2024-25 = /node/204). Drupal 10; no sitemap.xml (404); permissive
  robots.txt; **no API/JSON/CSV/RSS anywhere** — HTML + PDF only.
- **Tiered depth:** 1978–~1987 cycle-level only (e.g., "Final Report to the 66 Leg
  1978.pdf"; 1986-87 has "Summary of Recommendations" + "Analysis of Legislative Action" —
  the ancestor of today's Final Results). **Per-agency documents from ~1998 →** (TDCJ
  agency page carries every review since 1998; HHSC similar). Pre-1990s PDFs likely scans
  (text layer UNVERIFIED).
- **Current cycle (2026–27, 90th Leg.):** 16 entities under review incl. HHSC, DFPS,
  DSHS, TWC (https://www.sunset.texas.gov/reviews-and-reports); month-by-month timeline:
  https://www.sunset.texas.gov/public/uploads/2026-08/90th%20Review%20Grid.pdf.
- **Forward schedule to 2036–37** (major forecasting asset):
  https://www.sunset.texas.gov/reviews-and-reports/future-reviews-year — five future
  cycles (2028-29 includes TEA, PUC, RRC, TxDOT). Subject to change each session.
- **Per-agency archive:** A–Z slug directory
  (https://www.sunset.texas.gov/reviews-and-reports/agencies) including abolished
  agencies with predecessor/successor lineage notes.
- **URL fragility:** two upload-path generations; human-typed filenames with spaces and
  even a leading tilde (`~Final%20Results...`). Archive binaries on ingest.

## 2. Native formats (verified by fetch + text extraction)

- **Staff Report with Final Results** (TDCJ, Jul 2025, ~190pp, born-digital, clean
  extraction): front matter explains the three report stages (Staff Report → with
  Commission Decisions → with Final Results); per-agency "Issue N" chapters;
  "Recommendation N.N" numbering (135 found); explicit **"Change in Statute" vs
  "Management Action"** typing; Final Results names the enacting bill and authors
  verbatim ("Senate Bill 2405 Parker (Canales)"); **machine-parsable per-recommendation
  outcomes**: "Recommendation 1.1, Adopted as Modified — …", "1.2, Not Adopted — …".
- **Final Results of Sunset Reviews 2024-25** (cycle roll-up): aggregate scorecard ("78
  percent of statutory recommendations… 57 percent of funding recommendations… 100
  statutory provisions, seven funding recommendations, 106 management directives") plus a
  per-entity bill/authors/fiscal-impact table.
- **Compliance Report** (Jan 2025, "Implementation of 2023 Sunset Recommendations"):
  per-entity status table — Implemented / In Progress / Partially / Not Implemented —
  closing the loop from enactment to actual agency behavior.
- **Self-Evaluation Reports (SERs):** agency-authored questionnaires posted ~18 months
  pre-session (TDCJ SER Sep 2023; HHSC SER Apr 2026 upload for the current cycle).
- **Public comments:** paginated HTML index (name, title, org, city) with one PDF per
  comment, e.g. https://www.sunset.texas.gov/reviews-and-reports/agencies/comments/30354.
  Anonymous submissions allowed.

## 3. What a lobbyist uses it for

- *"Is this bill a Sunset bill / which provisions came from Sunset?"* — Final Results
  names the bill + author per agency and labels every recommendation's outcome.
- *"My client's regulator is under review — what are the threats?"* — SER + staff-report
  issues are the threat map; the Review Grid gives hearing timing; comment rosters show
  who else is mobilized.
- *"What will the 2027 session do to agency X?"* — the pre-session staff report with
  commission decisions is effectively the draft bill outline.
- *"Which agencies face existential review through 2037?"* — future-reviews page.

**Usefulness:** bill strategy HIGH (recommendations are pre-written bill provisions) ·
session monitoring HIGH (Sunset bills are must-pass vehicles) · regulatory monitoring
HIGH (compliance tracking) · client intelligence HIGH (SER = the agency confessional) ·
issue research HIGH · forecasting HIGH (schedule to 2036-37 is literal future-agenda
disclosure) · meeting prep HIGH · opposition research MED-HIGH (comment rosters) ·
historical research MED-HIGH · political intelligence MED (commission decisions vs staff
recs reveal member positions) · committee strategy MED · coalition MED · fiscal MED
(per-recommendation 2yr/5yr impacts) · compliance MED · relationship LOW-MED · campaign
LOW.

## 4. Ontology & native IDs

Agency/entity (URL slug; ~130 under jurisdiction; lineage for abolished/merged) · review
(slug × cycle) · cycle (node ID + biennium + legislature) · Issue N · Recommendation N.N
{type: statute/management/funding} {outcome: Adopted/Adopted-as-Modified/Not-Adopted}
{implementation: Implemented/In-Progress/Partial/Not} · document type (SER / Staff Report /
w-Commission-Decisions / w-Final-Results / Report to Legislature / cycle Final Results /
Compliance Report / public comment) · commenter (name/title/org/city; numeric comment-index
ID) · Sunset bill (number + authors) · commission member (chamber, role).

## 5. Edges

EXPLICIT: commission→reviewed→agency{cycle} · review→produced→documents ·
issue→contains→recommendation · recommendation→{adopted|modified|rejected}_by→legislature
(per-recommendation labels) · sunset_review→produced→bill (named with authors) ·
recommendation→implementation_status (compliance report) · agency→self_assessed_in→SER ·
commenter→commented_on→review · legislator→authored→sunset_bill /
→sits_on→commission · agency→scheduled_for_review→future_cycle · non-Sunset
bill→carries→recommendation when named ("HB 150… includes Sunset Commission
recommendations").
DERIVED: recommendation→enacted_in→bill_section (text alignment against the enrolled
bill) · implementation→rule/action linkage.
INFERRED: recommendation→bill mapping where not named; commenter coalition networks.

## 6. Temporal semantics

Fixed biennial pipeline (verified against 2024-25 artifacts): SER ~Sept odd year → staff
report + hearings even year → commission decisions late even year → Report to Legislature
~Feb of session → Final Results ~Jul of session → Compliance Report ~Jan two years later.
**Traps:** documents are versioned *in place* — agency pages replace "Staff Report" with
later stages and the intermediate versions can disappear (capture each stage on
publication or lose the staff-vs-commission delta); cycle label vs legislature vs
publication year span three calendar years; limited-scope/special reviews break the
12-year default cadence; abolition transfers functions (track entity lineage).

## 7. Authority

Class A source with four distinct internal voices that must never be collapsed: staff
recommendation (advisory opinion) ≠ commission decision (proposal of a 12-member
legislative commission) ≠ enacted statute (the only law) ≠ compliance assessment (staff
evaluation). SER = the agency speaking about itself (self-interested primary source);
public comments = third-party advocacy (lowest authority, highest political signal).

## 8. Ingestion

Scheduled crawler + PDF pipeline; no API. Discovery via /review-cycles → 24 node pages,
A–Z agency directory, current-cycle page, future-reviews page; comment indexes paginated
HTML. Backfill: low thousands of PDFs (trivial volume). Cadence: weekly during the review
year, daily in Oct–Jan decision season and Jun–Jul Final Results window — **drive the
scheduler from the Review Grid PDF, which pre-announces when each agency's documents
land.** Dedup: (agency_slug, cycle, doc_type, version_stage) + binary hash (in-place
replacement!). Change detection: agency-page HTML diff + new `/public/uploads/{YYYY-MM}/`
folders. Failure modes: hand-typed filenames, unguessable node IDs, vanishing
intermediate versions, renames/abolitions breaking slug joins, PDF-only structure.

## 9. Training value

**Exceptional natural labels at modest volume:** every recommendation since ~2013
carries type + outcome + later implementation status — a complete state-published
supervised set for "will this recommendation become law?" and calibration. Instruction
tuning: (SER + issues) → decision summaries; recommendation → plain-language explanation.
Eval: recommendation→bill mapping with the gold answer printed in Final Results. Caveat:
tens of reviews per biennium — high quality, low volume.

## 10. Derived intelligence

Adoption rate by recommendation type/agency/domain/commission composition (trendable to
1987 via "Analysis of Legislative Action") · **modification rate (Adopted-as-Modified
share) as a lobbying-effectiveness proxy — comparing staff report vs commission decisions
vs final action isolates where a provision was killed or softened** · implementation
lag/compliance score per agency · threat forecast (years-to-next-review × historical
issue severity) · commenter network maps · claimed vs enacted fiscal deltas. Sunset
itself publishes the anchor stats (78%/57% in 2024-25) — LobbyBook extends them across
agencies and decades.

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 5 | Pre-writes the must-pass agenda for every agency's existential moment |
| Uniqueness | 5 | No other source publishes recommendation-level outcomes |
| Authority | 5 | Official commission of the Legislature |
| Historical value | 4 | Cycle-level to 1978; per-agency only to ~1998 |
| Current-session value | 5 | HHSC/DFPS/DSHS/TWC reviews live now |
| Structure quality | 4 | Rigid numbering + outcome labels, but locked in PDF |
| Ingestion ease | 4 | Small, crawlable, stable; no API, messy filenames |
| Entity richness | 4 | Agencies, recommendations, bills, commenters, members |
| Relationship richness | 5 | Explicit recommendation→decision→bill→implementation chain |
| Training value | 4 | Superb labels, modest volume |
| Retrieval value | 5 | Direct answers to "why does this statute exist" |
| Derived intelligence | 5 | Adoption/modification/compliance rates are straight computation |
| Moat potential | 4 | Public data; the structured recommendation→outcome graph is the moat |
