# Agency Strategic Plans & Legislative Appropriations Requests (LARs)

**Authority class:** A for the mandated template; B for the content (agency-authored,
advocacy-framed self-assessment) · **Priority: Tier 2** · Verified by live inspection,
Aug 2026.

## 1. Corpus & coverage

- Every agency files a **5-year strategic plan** and, each even year, a **LAR** for the
  next biennium, under joint Governor's Office (OBPP) + LBB instructions (the 89R
  Strategic Plan Instructions PDF confirmed to exist on gov.texas.gov — content
  unparsed/UNVERIFIED; LBB's LAR Detailed Instructions + example LAR template verified on
  lbb.texas.gov).
- **Publication is decentralized to each agency's own site** — verified live examples:
  TEA (2023-2027 and an updated 2025-2029 plan), Comptroller, DIR, TSBPA, TREC/TALCB,
  THECB — with **three different URL conventions across the first three agencies
  checked**. No centralized archive; agencies typically retain only 1–2 prior cycles.
- LBB's agency_docs.aspx indexes submissions by biennium/article but via JS postbacks —
  not crawlable with plain HTTP (confirmed obstacle).
- **LAR access friction observed directly:** the AG's posted LAR PDF returned HTTP 402;
  a guessed TEA LAR URL 404'd. LAR structure/existence confirmed via LBB's template and
  TEA's listing page.

## 2. Native formats (verified)

100% PDF with genuine text layers — TEA's 2025-2029 plan extracted cleanly, including
numeric targets ("By 2030, at least 60% of Texans will have a degree, certificate, or
other postsecondary credential of value"). The standardized internals (verified verbatim
from TEA's TOC): mission/vision/values → strategic priorities/goals → action items, each
justified against **five statewide-mandated rubric categories** ("Accountable to tax and
fee payers," "Efficient," "Effective," "Attentive to customer service," "Transparent") →
Supplemental Schedules A–H (A: Budget Structure — mirrors the agency's GAA
goal/objective/strategy hierarchy; B: Measure Definitions; C: HUB Plan; D: Statewide
Capital Plan; F: Workforce Plan; H: Customer Service Report). The structured version of
this content lives in LBB's non-public ABEST system — only the PDF narrative is public.

## 3. What a lobbyist uses it for

- **Agency's-own-voice bill impact:** plans explicitly credit enacted bills as the basis
  for five years of agency action (TEA's plan cites HB 3 86R, HB 1605/HB 1416/HB 1926/
  SB 30 88R by name — verified). Direct evidence for "did my bill change what the agency
  does," client reporting, and opposition research on an agency's claimed
  accomplishments.
- **What the agency wants next:** LAR exceptional items are the agency's new-money asks —
  regulated industries need these before they become law.
- **Priority drift:** comparing consecutive plan cycles shows which goals survived,
  changed, or vanished.

**Usefulness:** client intelligence HIGH · regulatory monitoring HIGH · opposition
research HIGH · issue research HIGH · historical research HIGH · meeting prep HIGH ·
session monitoring MED · bill strategy MED · committee strategy MED · political
intelligence MED · fiscal MED · compliance MED · forecasting MED · coalition LOW ·
relationship LOW · campaign NONE.

## 4. Ontology & native IDs

Agency (3-digit code) · strategic plan (FY range + cover-page revision date) · strategic
priority/goal → action item · the 5 statewide objectives (fixed labels — free
classification rubric) · supplemental schedules A–H · LAR → base request + exceptional
items · performance measures.

## 5. Edges

EXPLICIT: agency→files→plan/LAR (mandated) · plan→cites→enacted_bill (verbatim citations
in text) · plan→contains→Schedule A budget structure.
DERIVED: Schedule A→mirrors→GAA strategy structure (same hierarchy, **no shared ID**) ·
**LAR exceptional item→funded_as→GAA appropriation — the most valuable and least
automatable edge in the fiscal stack: requires description/amount matching, no key
joins exist.**
INFERRED: goal persistence/drift classifications across cycles.

## 6. Temporal semantics

Plans are nominally 5-year but revised mid-cycle — verified: TEA's cover reads "FISCAL
YEARS 2025 TO 2029, Updated March 2025" while the filename says "2024-final-2." **Version
trap: the true vintage is only in cover-page text, not the URL or filename.** LARs filed
even years for the biennium starting the following September. Same three-layer lifecycle
as LBB: requested → appropriated → actual.

## 7. Authority

Template: A (imposed by statute/joint instruction). Content: B — every action item is
self-assessment against the mandated rubric, not independent audit. Frame as "the agency
states/plans," never as validated performance.

## 8. Ingestion

No central machine-readable index — requires crawling ~150–200 agency sites with
heterogeneous URL conventions, or search-engine discovery
(`site:agency.texas.gov filetype:pdf "strategic plan"` — the method that worked in this
audit). Dedup: (agency code, doc type, FY range, **cover-page revision date**) — filename
alone is unreliable. Change detection must diff cover-page text, not just hashes.
Failure modes observed: JS-postback portal, 402/404 on LAR fetches, per-agency chaos.

## 9. Training value

Each plan yields ~20 natural units (goals × rubric justifications) for goal→statewide-
objective classification — the source labels itself. **The LAR-requested vs.
GAA-appropriated amount per agency/strategy is the strongest natural label pair in the
fiscal stack** ("did the ask succeed") — but it requires solving the §5 matching problem
first.

## 10. Derived intelligence

Cross-cycle goal-persistence tracking (agency priority drift) · LAR-ask vs. appropriated
diffing as a per-agency political-capital score · mining agencies' own bill citations as
a retrospective on which enacted bills the agency itself says mattered — a distinctive
complement to the LBB record · exceptional-item early warning for regulated industries.

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 4 | Agency self-assessed priorities + budget asks; LAR access friction is real |
| Uniqueness | 4 | Agency's-own-voice narrative exists nowhere else |
| Authority | 3 | A-class template, B-class self-reported content |
| Historical value | 3 | 1–2 cycles retained per agency; no central archive |
| Current-session value | 3 | Informs, doesn't drive, in-session action |
| Structure quality | 4 | Highly standardized template verified across agencies |
| Ingestion ease | 2 | ~200 disparate sites, JS portal, failed fetches observed |
| Entity richness | 4 | Standardized goal/strategy/measure hierarchy |
| Relationship richness | 3 | Internally rich; GAA/LAR links need manual matching |
| Training value | 4 | Self-labeled rubric pairs + the LAR-vs-GAA outcome label |
| Retrieval value | 4 | Clean structured PDF text |
| Derived intelligence | 4 | Priority-drift + ask-vs-got are hard-to-replicate signals |
| Moat potential | 4 | Sustained multi-agency crawling most competitors won't build |
