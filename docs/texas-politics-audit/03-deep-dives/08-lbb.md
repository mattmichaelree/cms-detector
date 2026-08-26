# Legislative Budget Board (LBB) — fiscal notes, GAA & riders, Fiscal Size-Up

**Authority class:** A (fiscal notes are statutorily mandated nonpartisan estimates,
Gov't Code ch. 314; the GAA and its riders are enacted law) · **Priority: Tier 0
(fiscal notes) / Tier 1 (GAA-rider structuring)** · Verified by live inspection, Aug 2026.

## 1. Corpus & coverage

- **Fiscal notes live on TLO, not lbb.texas.gov.** Verified URL pattern:
  `https://capitol.texas.gov/tlodocs/{session}/fiscalnotes/{html|pdf}/{BillID}{VersionCode}.{htm|pdf}`
  (working examples: HB00796I.htm, SB00002I.htm, SB00002E.htm for 89R). **A distinct
  fiscal note exists for every bill version** — verified on HB 2 (89R): Introduced, House
  Committee Report, Engrossed, Senate Committee Report, Senate Amendments Printing, and
  Enrolled each separately linked from the bill's Text.aspx page. Coverage sampled back
  to the 74th (1995): SB01443I.htm resolves.
- **GAA:** `lbb.texas.gov/Documents/GAA/General_Appropriations_Act_{biennium}.pdf` —
  verified live for 2012-13 through 2026-27. Deeper history: **LRL archives appropriations
  bills back to 1927-29** (https://lrl.texas.gov/legis/approBills.cfm, verified).
- **Fiscal Size-Up:** current at lbb.texas.gov/FSU.aspx (+ interactive fsu.lbb.texas.gov);
  archive depth UNVERIFIED.
- **ABEST** (the structured goals/strategies/performance-measure system every agency files
  into): **no public query interface found** — the machine-readable version of the budget
  structure is effectively not public.
- **Contracts database:** contracts.lbb.texas.gov (searchable, $50k+ threshold); no bulk
  export found.
- **agency_docs.aspx portal** (index of LAR/strategic-plan/operating-budget submissions):
  links are JS postbacks, not stable URLs — a confirmed scraping obstacle.

## 2. Native formats (verified)

Fiscal notes: real HTML with a structured fiscal-implications table (SB 2's table
extracted cleanly: FY2026–2030 columns, per-fund dollar rows) + parallel PDF. GAA/riders:
genuine text layer confirmed by extracting a rider packet verbatim
(`Documents/Appropriations_Bills/87/Initial_Dockets/Article09_Rider.pdf` — numbered
sections like "Sec. 6.08. Benefits Paid Proportional by Method of Finance"). **The full
GAA PDF exceeds 10MB fetch limits — needs a large-PDF pipeline.** No CSV/JSON/XLSX/API
anywhere in LBB's own systems; interactive Qlik-style graphics only.

## 3. What a lobbyist uses it for

- *"What will this bill cost — and did the number change between committee substitute and
  engrossed?"* (per-version notes; SB 2's note showing costs growing to ~$4.8B by FY2030
  is a live example of a fiscal note as an advocacy/opposition data point).
- *"What strings are attached to the agency's money?"* — riders are where implementation
  policy hides (e.g., contract-reporting-threshold riders constraining procurement).
- *"Where is money allocated for this program?"* — GAA strategy lines by agency/article.

**Usefulness:** fiscal intelligence HIGH · session monitoring HIGH · bill strategy HIGH ·
committee strategy HIGH (Appropriations/Finance workflows) · client intelligence HIGH ·
opposition research HIGH · issue research HIGH · historical research HIGH · meeting prep
HIGH · regulatory monitoring MED · political intelligence MED · compliance MED ·
forecasting MED · coalition LOW · relationship LOW · campaign LOW.

## 4. Ontology & native IDs

Bill · bill version · fiscal note · source agency (3-digit agency codes, e.g., 701=TEA,
304=Comptroller — confirmed in fiscal-note source lists) · GAA → Article (I–X + Art. IX
general provisions) → Strategy → Rider (numbered sections) · fund (GR, Foundation School
Fund…) · appropriation · performance measure (goal/objective/outcome/output/efficiency) ·
contract · biennium. IDs: `{session}+{bill}+{version code}` for fiscal notes; article/
strategy/rider numbers within a biennium's GAA.

## 5. Edges

EXPLICIT: bill→has_version→bill_version (TLO) · bill_version→has_fiscal_note ·
fiscal_note→estimates_impact_to→fund (table rows) · fiscal_note→cites→source_agency ·
GAA→contains→article→strategy→rider.
DERIVED: rider→constrains/directs→agency (typing the relationship from rider text) ·
LAR exceptional item→funded_as→GAA appropriation (**no shared ID — description/amount
matching; see the strategic-plans deep dive**).
INFERRED: fiscal-note magnitude→predicts→passage difficulty.

## 6. Temporal semantics

Biennium = two FYs (Sept 1–Aug 31). **Version trap verified concretely:** SB 2's
Introduced and Engrossed fiscal notes are separate files with different figures — citing
"the SB 2 fiscal note" without a version code misstates the number. Three time-lagged
layers per program: requested (LAR, ~18 months pre-biennium) → appropriated (GAA) →
actual (ABEST reports, non-public).

## 7. Authority

Fiscal notes: A (mandated nonpartisan estimate — but still an *estimate*; present as
"LBB estimated," never as observed cost). GAA/riders: A (enacted law). Fiscal Size-Up: A
(official descriptive). Contracts DB: B (agency-self-reported aggregation).

## 8. Ingestion

Per-session crawl of TLO bill lists → per-bill Text.aspx → predictable per-version
fiscal-note URLs (clean backfill to 1995). Incremental: poll during session — new notes
appear at each committee/floor stage. Dedup: (session, bill, version code). GAA: one
large-PDF pipeline per biennium + LRL scans for pre-web history; rider extraction is
page-level parsing (no per-rider index exists anywhere — building one IS the product).
Failure modes: >10MB PDFs; JS-postback portal; no API anywhere.

## 9. Training value

Bill text → fiscal-impact class (direction/magnitude) regression pairs from decades of
notes · riders as short instruction-tuning units ("what does Rider X require before the
agency can spend?") · fiscal-note methodology sections for extraction training. The
LAR-vs-GAA outcome label (see strategic plans) is the strongest label pair in the fiscal
stack.

## 10. Derived intelligence

**Rider diffing across biennia** (emerging/eroding policy fights, rider survival) ·
ask-vs-appropriated ratios per agency (political-capital score) · fiscal-note accuracy
retrospectives (note projections vs. later Size-Up/CRE actuals, by bill type) —
calibrates how much to trust a new note, an argument nobody can currently make with
citations · program funding trajectories across GAAs.

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 5 | Fiscal notes + riders are the two most operationally decisive documents in the process |
| Uniqueness | 4 | Fiscal notes unique; GAA text is law available elsewhere |
| Authority | 5 | Statutory estimates + enacted law |
| Historical value | 5 | GAA lineage to 1927 (LRL); notes to 1995 |
| Current-session value | 5 | Per-version notes are the fastest-moving fiscal signal in session |
| Structure quality | 4 | Real HTML tables + text-layer PDFs; no cross-document IDs |
| Ingestion ease | 3 | Predictable URLs but oversized PDFs + JS portal |
| Entity richness | 4 | Bills, agencies, funds, riders, strategies |
| Relationship richness | 4 | Version-linked notes + rider→agency; LAR↔GAA is manual |
| Training value | 4 | Cost-impact pairs + rider instruction units |
| Retrieval value | 4 | Clean text supports RAG well |
| Derived intelligence | 5 | Rider tracking + ask-vs-got deltas + note-accuracy retrospectives |
| Moat potential | 4 | Version-aware note tracking + biennium rider diffing is rarely done well |
