# Interim Charges & Interim Committee Reports

**Authority class:** A (Speaker/Lt. Governor directives; committee reports — none of it
enacted law; see §7) · **Priority: Tier 1** · Verified by live inspection, Aug 2026.

## 1. Corpus & coverage

- **Canonical aggregator — LRL Legislative Reports database:**
  https://lrl.texas.gov/committees/lrlhome.cfm (search POSTs to
  /committees/search.cfm). Session dropdown verified **1st Legislature (1846) → 89th
  (2025)**; searchable by session, chamber, subject, keyword (titles AND charge text);
  toggle between reports and charges. **Indexing is by the legislature that ORDERED the
  study, not the one receiving the report** — key join semantic.
- **Verified archive depth by probe:** 1935 (44th) returns ~20 reports with PDFs at
  `https://lrl.texas.gov/scanned/interim/{leg}/{callnum}.pdf`; probes at 60th (1967),
  70th (1987), 77th (2001), 88th (2023) all returned full-text PDFs. Pre-1935 items
  claimed by LRL ("back to 1846" via journals), earliest UNVERIFIED by direct fetch.
- **Current interim (89th→90th):** 56 committees' charges already loaded in LRL (Aug
  2026). Primary publishers: House charges
  https://www.house.texas.gov/pdfs/speaker/F-Interim-Charges-3.25.pdf (Speaker Burrows,
  Mar 2026); Senate charges https://www.ltgov.texas.gov/2026-interim-charges/ →
  /wp-content/uploads/2026/03/2026-Interim-Charges.pdf — **released in rolling rounds**
  (Jan 30, Mar 27 = 74 cumulative, +7 on Jul 27, each with a dated press release).
- **Chamber-site report archives:** House interim reports back to the 76th (1999) at
  https://house.texas.gov/committees/reports/interim (PDFs at
  `/pdfs/committees/reports/interim/{NN}interim/House-Committee-on-{Name}-Interim-Report-{YYYY}.pdf`);
  Senate at `https://senate.texas.gov/cmtes/{leg}/c{code}/c{code}_InterimReport_{YYYY}.pdf`
  (some 2024 reports filed under `/cmtes/89/` — don't key on the path's legislature
  number).
- **Completeness caveat (stated by LRL):** some committees study/monitor without filing a
  report — charge coverage is a superset of report coverage.
- **No API/JSON/CSV/RSS found.** The LRL search POST endpoint (form-encoded, parseable
  HTML with cmteID/chargeID/subjectID) is the closest thing to an API.

## 2. Native formats (verified by fetch + extraction)

- **2026 charges:** born-digital PDFs, clean text. House: numbered charges per committee;
  **every committee's charge 1 is a "Monitoring" charge enumerating specific 89th-session
  bills to oversee** (e.g., "including: • HB 43…"). Senate: titled bullet charges naming
  bills ("Monitor rulemaking related to Senate Bill 6, 89th Legislature…"). Bill cites
  inside charge text are explicit and extractable.
- **Charges in LRL render as HTML full text** on committee pages (verified
  https://lrl.texas.gov/committees/cmtesDisplay.cfm?cmteID=12155 — charges verbatim +
  membership) — the only non-PDF form of charge text anywhere.
- **Reports — era-dependent quality (all fetched):** 1935 = image-only scan, zero text
  layer; 1967 = garbage OCR; 1987 = usable OCR; 2001 = clean text; 2024 = fully
  born-digital (371K chars). Bands: pre-1970s OCR-rescue; 1970s–90s noisy; 2000s+ clean.
- **Report structure (verified, 88th Senate NR&ED):** transmittal letter → signature page
  **with individual member dissent/qualification letters** → TOC reproducing each charge
  **verbatim** (string-for-string match to LRL's charge records — deterministic join) →
  per-charge Introduction / Background / Testimony / Conclusion / Recommendations.
- **LRL metadata per report:** committee+session, doc type, clickable subjectIDs
  (controlled vocabulary spanning the archive), library call number ("L1836.88 N219E"),
  page count, charge list.

## 3. What a lobbyist uses it for

- *"What will next session's agenda be?"* — the 2026 charge lists ARE the pre-announced
  2027 agenda, 10–14 months early. Highest-signal forward document in Texas politics.
- *"What did the committee recommend on my issue?"* — Recommendations sections,
  subject-searchable to the 19th century.
- *"Is my issue getting an interim hearing, and before whom?"* — charge assignment names
  the committee, hence the members to brief.
- *"Where did this bill come from?"* — trace bill → interim recommendation → charge.
  Monitoring charges explicitly name enacted bills under oversight — implementation-fight
  intelligence.
- Getting testimony into an interim hearing is the cheapest path into a report's
  Testimony/Recommendations — the reports document who succeeded.

**Usefulness:** forecasting HIGH (charge→bill conversion is the core predictive signal) ·
session monitoring HIGH (the interim is the between-session session) · bill strategy
HIGH · committee strategy HIGH (incl. new select committees — 2026: Governmental
Oversight, Health Care Affordability, General Aviation) · political intelligence HIGH
(Speaker-vs-Lt.Gov. priority divergence; dissent letters expose splits) · issue research
HIGH · historical research HIGH · meeting prep HIGH · regulatory monitoring MED-HIGH
(monitoring charges track rulemaking) · client intelligence MED · opposition research
MED · coalition MED · relationship MED · fiscal LOW-MED · campaign LOW-MED · compliance
LOW.

## 4. Ontology & native IDs

Committee (LRL **cmteID**, spanning standing/select/joint per session; Senate site codes
c510/c610/…; House name-slugs) · interim charge (LRL **chargeID**; issuer, ordering
legislature, assigned committee(s), type study/monitoring, release round/date) · interim
report (LRL call number; doc type Report vs Supporting; submission date) · subject (LRL
**subjectID** controlled vocabulary across ~90 years) · findings/recommendations
(positional, derivable) · members (rosters per committee-session; dissent authors) ·
legislature/session (1–89).

## 5. Edges

EXPLICIT: speaker/lt_gov→issued→charge · charge→assigned_to→committee
(chargeID↔cmteID) · committee→studied→charge→reported_in→report (TOC verbatim match) ·
charge→monitors→enacted_bill (named bills in monitoring charges) ·
member→dissented_from→report · report→tagged_with→subjectID. LRL's bill search
cross-references committee reports for some bills (coverage UNVERIFIED) — partially
EXPLICIT charge→bill.
DERIVED: report→contains→recommendation (section parsing; reliable post-2000) ·
witness/org→testified_on→charge (Testimony-section NER).
INFERRED: **interim_charge→led_to→bill — the highest-value edge, published nowhere.**
Derive via recommendation-text ↔ filed-bill similarity + author-is-committee-member +
subject match + session adjacency; always displayed as inferred with evidence.

## 6. Temporal semantics

Verified biennial pipeline: session ends Jun odd year → charges Jan–Jul even year
(Senate in rolling rounds) → hearings through even year → reports Nov–Jan straddling the
boundary → next session convenes Jan odd year. **Traps:** LRL indexes by ordering
legislature (the "88th" interim reports serve the 89th session — normalize to
(ordering_leg, receiving_leg=+1)); Senate charge PDFs accrete across rounds and are
replaced in place (ingest each press release); reports trickle over ~3 months and some
committees never file (absence ≠ inactivity); Senate paths inconsistent across
`/cmtes/88/` vs `/cmtes/89/`.

## 7. Authority

Class A, five distinct voices: charge = the Speaker's/Lt. Governor's personal directive
(leadership intent, not chamber consensus) · findings/recommendations = signed committee
majority (non-binding) · dissent letters = individual positions · testimony summaries =
the committee's characterization of third parties (don't present as witnesses' verbatim
views) · LRL subject tags = professional librarian curation. Nothing here is law until
matched to a passed bill.

## 8. Ingestion

Three-legged: (a) **LRL search.cfm as the backbone index** — enumerate sessions 1–89 ×
{reports, charges}, parse cmteID/chargeID/subjectID/call numbers from result HTML
(verified working unauthenticated); (b) chamber sites for freshest PDFs; (c)
ltgov.texas.gov + house.texas.gov press pages for charge releases (event-driven).

**⚠ Compliance flag (verified):** https://lrl.texas.gov/robots.txt disallows `/*.pdf`
for all agents, carries Cloudflare content signals `ai-train=no, use=reference`, and
names AI crawlers (ClaudeBot, GPTBot, CCBot…) as disallowed. Bulk PDF crawling of LRL is
restricted by robots policy. Mitigations: prefer chamber-site PDFs where they exist
(1999+ House, Senate cmtes tree), use LRL for metadata/search under its permitted
signals, and seek LRL permission for the historical PDF backfill (it is a
service-oriented library). Route through legal review before the deep backfill.

Backfill: ~90 sessions × 20–60 items ≈ low thousands of PDFs + OCR pre-1990. Cadence:
charge-watch weekly Dec–Aug of even years; report-watch weekly Oct–Feb; LRL re-sync
monthly. Dedup: (ordering_leg, cmteID, doc_type, call_number|pdf_basename); charges by
chargeID. Change detection: diff LRL result sets, diff `{NN}interim/` listings, hash the
growing ltgov PDF. Failure modes: robots restrictions, ColdFusion query quirks,
committee renames across sessions (use cmteID lineage), no-report committees, OCR debt.

## 9. Training value

Charge→report verbatim alignment = perfect pairs for "given this charge and testimony,
draft findings and recommendations" instruction data · **charge→bill conversion labels
(constructible): label each charge by whether a matching bill was filed/passed next
session — ~90 years of biennia = a large weak-supervision set for agenda forecasting** ·
charge typing (study/monitoring/investigation) · LRL subjectID vocabulary = a free
labeled taxonomy across the archive · verifiable retrieval evals ("which committee
received this charge?"). Caution: testimony summaries are paraphrase — don't train
models to quote them as witness statements.

## 10. Derived intelligence

**Charge→legislation conversion rate** by committee/chamber/issuer/topic — the master
forecasting statistic, computable and published nowhere · probabilistic 2027 bill list
from the 80+ 2026 charges scored by historical conversion propensity · leadership
divergence index (House-vs-Senate charge overlap: 2026 both on water/AI/health costs;
House-only: data centers, New Mexico county secession) → inter-chamber friction
predictor · issue longevity curves (consecutive interims charged before passage) ·
committee productivity metrics (filed/not, length, recommendation counts, dissent
frequency) · monitoring-charge graph (enacted bill → oversight committee → friction
signals) · witness/org frequency per issue.

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 5 | Charges are the published future agenda; reports are the draft policy |
| Uniqueness | 4 | Public but scattered across four sites; the assembled pipeline exists nowhere |
| Authority | 5 | Speaker/Lt. Governor and standing committees |
| Historical value | 5 | Indexed to 1846; PDFs verified to 1935 |
| Current-session value | 5 | 2026 charges live; reports land Nov 2026–Jan 2027 |
| Structure quality | 3 | Charges clean; report internals committee-idiosyncratic; OCR debt |
| Ingestion ease | 3 | Small and enumerable, but ColdFusion scraping + LRL robots restrictions |
| Entity richness | 4 | Real native IDs: cmteID, chargeID, subjectID |
| Relationship richness | 4 | Charge↔committee↔report explicit; charge→bill inferred (the valuable one) |
| Training value | 4 | Aligned charge/report corpus + constructible conversion labels |
| Retrieval value | 5 | "What has the Legislature studied about X since 1935" — answerable here alone |
| Derived intelligence | 5 | Conversion rates and agenda forecasting are headline features |
| Moat potential | 5 | 90-year charge→report→bill linkage: expensive to build, compounds every biennium |
