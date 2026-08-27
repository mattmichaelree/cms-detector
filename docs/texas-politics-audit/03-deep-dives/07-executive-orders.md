# Texas Governor — Executive Orders, Proclamations, Appointments, Vetoes, Press

**Authority class:** B-operative (EOs, proclamations, special-session calls, veto
proclamations are binding legal acts) wrapped in E-class press packaging · **Priority:
Tier 1 (special-session calls + appointments), Tier 2 (rest)** · Verified by live
inspection, Aug 2026.

## 1. Corpus & coverage

- **No dedicated EO index exists on gov.texas.gov.** The news taxonomy is only Press
  Release / Appointment / Proclamation / Legislative Statement / Texanthropy — EOs post
  as press releases with ad-hoc PDF uploads (`/uploads/files/press/EO-GA-##_….pdf`).
  The one topical archive is a COVID-era page. **The authoritative structured EO index
  is LRL:** one page returns the complete run GA-01 (3/30/2016) → GA-57 (7/21/2026)
  with metadata; LRL's EO collection begins with Gov. Shivers (1949; RAS-1…RAS-6 —
  including a "RAS-1 rev," proof numbering isn't cleanly monotonic).
- **Proclamations:** live category feed (current disaster proclamations renew
  monthly-ish under identical titles). **Special-session calls verified in full** —
  both the press-prose agenda (2021, 11 items) and the signed constitutional PDF
  (2025 call; filename literally contains "UNSIGNED_DRAFT" — provenance quirk).
  **Calls are amended mid-session** (verified reporting: 2025's second special
  expanded 19 → 22 → 24 items) — model as versioned state, not a static list.
- **Vetoes:** proclamation PDFs at ad-hoc press paths + prose veto statements in the
  Legislative category; the authoritative per-bill signed/vetoed lists are **TLO
  reports** (`Reports/Report.aspx?LegSess=89R&ID=vetoedbygov`); **LRL's veto index
  runs far deeper than its EO index — per-session veto counts continuously back
  through O'Daniel (1939–41) and earlier.**
- **Appointments:** extremely high-frequency press feed (7+ posts in a 3-day window
  observed); the office states ~1,500 appointments per 4-year term; **no queryable
  appointee roster exists anywhere** — the positions page lists only the ~150
  appointable board/position types with statute cites. LRL has **no appointment doc
  type at all.** The roster must be reconstructed from press releases — a build-it-
  yourself dataset.
- **Press releases:** live RSS (10-item rolling window — insufficient alone at the
  observed cadence) + GovDelivery. LRL's curated press-release holdings (405 items
  over 11.5 Abbott years) are nowhere near exhaustive.
- robots.txt blocks GPTBot/ClaudeBot/Amazonbot/Applebot by name; the real sitemap is
  at the non-standard `/site/sitemap`; `/news/category/executive_order` and
  `/sitemap.xml` 404 (URL-guessing misses content).

## 2. Native formats (verified — the OCR lottery)

| Sample | Result |
|---|---|
| EO-GA-41 (2022) | Office-scanner PDF **with imperfect OCR** ("ofSit" artifacts) |
| EO-GA-48 (2024) | Same scanner, **zero extractable text** (pure image) |
| SB 3 veto proclamation (2025) | **Zero extractable text** (pure image) |
| Special-session call (2025) | **Born-digital, clean text**, numbered agenda items |

**Key finding: OCR presence is inconsistent and non-chronological — run your own OCR on
every governor-office PDF** (the inverse of the AG corpus, where recent = born-digital).
No RSS/bulk/API for EOs, proclamations, or appointments specifically; LRL search HTML
is structured but has no machine export.

## 3. What a lobbyist uses it for

*What's on the special-session call?* — the call constitutionally defines what the
legislature may act on (verified 2025 full text: flood infrastructure, hemp, property
tax, bail…); the *current amended* state is what matters. · *Who did the governor
appoint to my client's regulator?* — live examples observed for licensing boards and
DIR. · *Did the governor veto my bill, and what was the stated reason?* · *Which
disaster declaration suspends which rules right now?*

**Usefulness:** session monitoring HIGH (calls ARE the special-session agenda) · bill
strategy HIGH (veto/signing reasoning) · client intelligence HIGH (appointment feed →
who sits on the regulator) · political intelligence HIGH (EO/proclamation cadence
signals priorities) · relationship intelligence HIGH (patronage network) · forecasting
HIGH (calls + EO topical drift) · meeting prep HIGH · campaign intelligence MED
(appointment timing vs cycles) · regulatory monitoring MED (EOs directing agencies) ·
opposition research MED (veto record vs sponsors) · compliance MED (disaster
suspensions) · issue research MED · historical research MED (EOs to 1949; vetoes
deeper; appointments unarchived) · fiscal LOW-MED · committee LOW-MED · coalition MED.

## 4. Ontology & native IDs

Executive order (`GA-##` — **collides with AG-opinion `GA-####` from Abbott's earlier
role; composite key (issuer-role, governor, number) required**) · proclamation (**no
native ID at all** — title + date only; renewals reuse identical titles) · veto
statement/proclamation (natural key = bill + session) · appointment (**no native ID**;
appointee name + position + date + URL slug) · LRL keys (`governorID`, `govDocType`:
5=EO, 9=veto, 15=press, 1/2=proclamations) — stable, useful, library-assigned.

## 5. Edges

EXPLICIT: governor→issued→EO (filed with SOS — stamp on the document) ·
governor→called→special_session{numbered agenda items} · call→amended_by→proclamation ·
governor→appointed→person→to→board (per press release) · governor→vetoed→bill
(proclamation + statement) · governor→signed→bill (via TLO reports).
DERIVED: proclamation(t)→renews→proclamation(t−1) (same title, new date — no explicit
pointer) · the aggregate appointee roster (reconstructed, no native DB).
INFERRED: EO topical cluster→precedes→statute.

## 6. Temporal semantics

Letter date vs SOS filing stamp vs effective clause can all differ (verified on
EO-GA-41) — extract all three. **Renewal-chain trap:** monthly same-title disaster
proclamations must be chained, not collapsed or treated as independent. **Mutable
special-session agendas:** diff the current item list against ingested versions — the
original PDF is not the agenda. **Cross-role GA-number collision** is itself a
temporal-scoping trap (2002–14 = AG opinions; 2015+ = EOs).

## 7. Authority

EOs, disaster proclamations (Gov't Code ch. 418 powers), special-session calls (Tex.
Const. art. III §40 — constitutionally exclusive agenda control), veto proclamations
(art. IV §14): **binding operative acts — class B**, presented as
binding-and-enforceable, in explicit contrast to AG opinions' persuasive-only framing
despite the shared "GA" numbering coincidence. Veto *statements* and appointment
*announcements*: political communication (C/E) wrapping a B-class act — surface the
distinction. Press releases generally: C/E.

## 8. Ingestion

Three-source blend: gov.texas.gov category pages + RSS + GovDelivery (discovery;
RSS window too small alone — poll categories directly, daily minimum) · LRL search
pages for authoritative EO/veto sequencing + historical governors · TLO reports for
definitive bill dispositions. Backfill: EOs bounded (few hundred since 1949);
appointments effectively unbounded and reconstructable only from press text. Dedup:
EO by (governor, number); proclamations/appointments need minted keys (title+date hash
/ URL slug). Change detection: amended special-session agendas; OCR everything.
Failure modes: named-bot robots blocks (compliant crawl path or licensing), nonstandard
sitemap, image-only PDFs, LRL PDF-crawl restriction (source PDFs from gov.texas.gov,
never LRL paths).

## 9. Training value

Mostly retrieval. Classification: coarse category taxonomy + LRL's 11-way doc types.
Veto statements pair as (bill purpose → veto rationale) — usable but one-sided
executive framing, label accordingly. Weak eval material (actions, not graded
analysis).

## 10. Derived intelligence

Policy-attention time series by domain (verified observable: GA-50…GA-54 all issued the
same day, Jan 29, 2025 — a single-day border-policy burst) · **the reconstructed
appointee roster + patronage network graph (cross-referenced with TEC donations)** —
genuinely novel, nobody publishes it · veto-friction index by session/sponsor/party
(LRL counts verified: 21 vetoes in 2019 vs 58 in 2017) · disaster-renewal intensity by
region for affected-sector clients.

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 5 | Calls + appointment feed are immediately actionable |
| Uniqueness | 3 | Documents public; nobody assembles the EO+proclamation+appointment+veto graph |
| Authority | 4 | Binding legal acts (vs. persuasive AG opinions) |
| Historical value | 3 | EOs to 1949; vetoes deeper; appointments unarchived |
| Current-session value | 5 | Multiple posts daily; calls define special sessions |
| Structure quality | 2 | No native IDs for proclamations/appointments; OCR lottery; no EO index |
| Ingestion ease | 2 | Three disjoint sources, image PDFs, robots constraints |
| Entity richness | 3 | EOs/vetoes clean; proclamations/appointments unstructured |
| Relationship richness | 4 | Appointment→board and veto→bill edges high-value once reconstructed |
| Training value | 2 | Retrieval-first corpus |
| Retrieval value | 4 | High-precision "what did the governor do" |
| Derived intelligence | 5 | Patronage networks + attention time series are novel |
| Moat potential | 4 | Reconstructing rosters and renewal chains is real engineering |
