# Texas Court Decisions (SCOTX · CCA · Courts of Appeals · Business Court · federal layer)

**Authority class:** A (published SCOTX/CCA), B (published COA; 15th COA), with Texas-
specific precedential wrinkles — see §7 · **Priority: Tier 2** · Verified by live
inspection, Aug 2026.

## 1. Corpus & coverage

| Court | Official online | Depth | Bulk/alternate |
|---|---|---|---|
| SCOTX | Per-hand-down-date pages, `txcourts.gov/supreme/orders-opinions/YYYY/…` (verified June 19, 2026 orders page: decided causes, grants, mandamus settings, petition denials, all PDF-linked); primarily Friday releases | CourtListener `tex` reaches back to **1840**; 32,562 cases (live API query) | CourtListener |
| CCA | Searchable DB since Apr 2004 (search.txcourts.gov `coa=coscca`); HTML archive 1998–2004; rolling hand-down list | 1998+ official | CourtListener `texcrimapp` 73,260 cases — but most recent record was **~11 months stale at fetch** (⚠ don't trust CourtListener for CCA freshness) |
| 1st–14th COAs | Per-court opinion pages + unified TAMES search | Varies; Justia claims 1997+ (self-disclaimed incomplete) | ⚠ 3rd COA "recently released" page served 2020-dated content — use TAMES, not landing pages, as the freshness signal |
| **15th COA** (statewide business/state-litigation appeals; operational Sept 1, 2024) | Via shared case search `coa=coa05`; no dedicated opinions path (404) | Too new for depth | **Absent from CourtListener** (`texctapp15` 404s) — confirmed gap |
| **Texas Business Court** (statewide trial court, Oct 2024+) | https://www.txcourts.gov/businesscourt/opinions/ — verified chronological list Jan 2025–Aug 2026, own cite style ("2026 Tex. Bus. 60"), ~100+ opinions; 5 of 11 divisions operational | New | **Absent from CourtListener**; SMU CGI tracks it manually (their dashboard 403'd — UNVERIFIED) |
| Federal (5th Cir., TX districts) | PACER ($0.10/page); CourtListener/RECAP mirror (crowd-sourced, incomplete by design) | `ca5` to 1891 | CourtListener docket alerts |

- **Caselaw Access Project:** confirmed wound down its own search/API (Sept 2024, per
  Harvard LIL); corpus now hosted inside CourtListener; static through ~2020 — one-time
  historical backfill only, never a live feed.
- texas.public.law is a **statutes** site, not case law, despite the name (verified).
- **robots.txt (verified via curl):** www.txcourts.gov allows opinion pages but declares a
  **720-second crawl-delay** (compliant full-site crawling impractical — poll listing
  pages instead); **search.txcourts.gov (TAMES) is `Disallow: /`** — automated scraping is
  off the table; pursue an Office of Court Administration data arrangement instead.
  re:SearchTX (research.txcourts.gov) hard-403'd all fetches — bot-protected; treat as
  manual/on-demand only (its paid tiers UNVERIFIED).
- URL stability: Umbraco `/media/{id}/{slug}.pdf` asset paths are stable once issued; the
  durable per-case anchor is the TAMES case page (`Case.aspx?cn=…&coa=…`, verified live).

## 2. Native formats (verified)

- **Opinion PDFs are born-digital and tagged** — a live 3rd COA order PDF verified as PDF
  1.7 with StructTreeRoot, embedded fonts, clean `pdftotext` extraction. No OCR needed for
  the modern corpus.
- **CourtListener REST API v4** verified live (`/api/rest/v4/search/?court=tex`): JSON
  with caseName, court, dateFiled, docketNumber, citeCount, judge/panel, and nested
  opinions[] (author_id, joined_by_ids, per_curiam, type, sha1, cites, download_url).
  Search JSON carries snippets only, not full text — full text via the opinion-detail
  endpoint/PDF (detail endpoint UNVERIFIED).
- **⚠ Corrected during implementation — the search endpoint carries no citation at all.**
  The audit read the reporter/LEXIS cites off the *cluster detail* shape; the search
  response exposes only `lexisCite` and `neutralCite`, and **both are empty on 60/60
  records across three live responses spanning 2014→2025** — not merely on fresh
  hand-downs awaiting a reporter assignment. A reporter citation can therefore never be a
  required key or a join key on this feed; the opinion id is the only durable handle.
- **⚠ `court_id` is not trustworthy provenance on the older backfill.** The Dec-2014
  `court=tex` slice is 20/20 *criminal* matters SCOTX has no jurisdiction over —
  `AP-76,936`, ten `WR-…` writs, six `PD-…` petitions, and COA dockets like
  `10-14-00110-CR`. Derive the deciding court from the docket-number grammar and
  cross-check `court_id`; never key authority off `court_id` alone.
- **TAMES case pages** (HTML only; no API/RSS): verified a live SCOTX case showing
  parties, multiple attorneys with firms, **amici curiae (PhRMA, U.S. Chamber)**, full
  chronological docket, and downloadable petition/briefs/opinions/oral-argument audio.
  Site states data refreshes nightly, not real-time.
- Business Court: PDF-only with paragraph pincites; staff summaries explicitly
  non-authoritative.

## 3. What a lobbyist uses it for

- *"Did a court just strike the rule my client relies on?"* — §2001.038 rule challenges
  (exclusive Travis County venue; verified the district court may transfer such cases
  directly to the 15th COA for "prompt, authoritative determination").
- *"Which firms/AGs/amici are litigating this issue?"* — TAMES attorney + amicus fields
  are coalition-alignment data.
- *"What litigation may alter the policy environment?"* — pending appellate + Business
  Court dockets; federal challenges concentrated in single-judge divisions (verified
  reporting on Amarillo/Wichita Falls forum patterns).

**Usefulness:** regulatory monitoring HIGH · client intelligence HIGH · opposition
research HIGH (amici + counsel) · issue research HIGH · political intelligence MED-HIGH
(AG posture, forum shopping, 15th COA build-out) · forecasting MED-HIGH ·
historical research MED-HIGH · meeting prep MED · coalition MED · relationship MED ·
compliance MED · bill strategy MED (drafting around judicial vulnerabilities) · session
monitoring LOW · committee LOW · campaign LOW · fiscal LOW.

## 4. Ontology & native IDs

Court · case/docket · opinion (majority/dissent/concurrence/per curiam/memorandum/order) ·
judge · party (petitioner/respondent/relator…) · attorney · firm · amicus org · originating
trial court+judge · statute/rule cited · citation record · oral-argument media · briefs.
IDs (verified): SCOTX docket `25-0127`; COA `03-19-00801-CR` (court-year-sequence-type);
CCA `PD-0836-24`, `WR-…`; reporter cites (`683 S.W.2d 378`); `2026 Tex. Bus. 60`;
CourtListener docket_id/cluster_id/opinion id + sha1; PACER numbers federally.

## 5. Edges

EXPLICIT: case→decided_by→court · judge→authored/joined/dissented→opinion ·
party→represented_by→attorney/firm · amicus→filed_brief_in→case (interest-group
alignment!) · case→appealed_from→trial_court_case · case→cites→case (CourtListener
citation graph).
DERIVED: **case→interprets/cites→statute|rule via citation parsing over full text — the
single most valuable and most labor-intensive edge for LobbyBook** ·
case→invalidates/upholds→rule (outcome-language parsing on top of the citation edge —
partially INFERRED; nothing structurally flags "rule struck").
INFERRED: case→enables→subsequent same-statute litigation · forum-shopping
classification.

## 6. Temporal semantics

dateFiled is clean and structured everywhere. Traps: the opinion-to-mandate gap (holding
can change through rehearing; only visible via docket-event parsing); **the Shepardizing
problem — CourtListener exposes citeCount but no "still good law" flag.** Citing an
overruled holding is the misinformation hazard of this corpus: gate every "case X holds Y"
statement behind a recency/subsequent-history check, and present single-opinion citations
as provisional.

## 7. Authority

A: published SCOTX/CCA. B: published/precedential COA (district-binding) and 15th COA
(statewide within its exclusive jurisdiction). **Texas wrinkle (verified): civil
memorandum opinions issued after Jan 1, 2003 DO have precedential value under TRAP 47
— do not mis-model them as "unpublished = non-precedential."** Pre-2003 "do not publish"
civil and unpublished criminal opinions: no precedential value (a sampled PDF carried the
"Do Not Publish" caption). Business Court opinions: first-instance persuasive signal, not
binding precedent. Procedural orders/denials: administrative. Holding-vs-dicta is tagged
nowhere — an NLP layer, always displayed as derived.

## 8. Ingestion

- **Primary:** CourtListener API v4 sync for SCOTX (+CCA with a freshness cross-check
  against the live hand-down lists). Dedup: cluster_id/opinion id; change detection: sha1.
  CourtListener saved-search alerts for near-real-time; PACER/RECAP docket alerts
  federally.
- **Gap-fill (a first-mover edge):** daily poll of txcourts.gov listing pages for the
  **15th COA and Business Court** — the market-leading aggregator doesn't index them.
  Respect the crawl-delay by polling only listing pages and fetching new `/media/{id}/`
  PDFs.
- **Never scrape TAMES** (robots `Disallow: /`) — the attorney/party/amicus/docket layer
  needs an OCA data-sharing arrangement; until then, manual pulls for hot cases.
- Failure modes: new-court blind spots; CourtListener CCA lag; stale per-court landing
  pages; memorandum opinions without reporter cites (citation-matching ambiguity).

## 9. Training value

Honest call: **low for legal-reasoning instruction tuning** — general appellate reasoning
is already well covered in frontier pretraining. Genuinely novel/under-covered: the
**Business Court + 15th COA corpora (post-2024, low-volume, post-cutoff)**. Useful label
pairs: opinion text → disposition class; question-presented → holding retrieval pairs;
amicus signatory → stance labels. Best use: retrieval grounding + classification
(outcome, authority class, subsequent-history tagging).

## 10. Derived intelligence

Rule-survival rate under §2001.038 by agency/subject (segmented by Travis County vs 15th
COA transfer) · litigation-risk index per policy area (pending-case velocity joined to
bills/rules) · statute-to-litigation lag (effective date → first challenge) ·
forum-concentration index (single-judge-division filings) · Business Court caselaw growth
curve by division/subject as an early-warning migration signal.

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 4 | Strong for regulatory/client/opposition work; weak on session-day work |
| Uniqueness | 4 | First-mover opening on the 15th COA/Business Court corpus |
| Authority | 5 | Primary legal text |
| Historical value | 4 | SCOTX to 1840 via CourtListener; COA depth uneven |
| Current-session value | 3 | Courts react after the fact; live rule-challenge tracking still matters |
| Structure quality | 4 | Clean structured metadata (TAMES, CourtListener); text PDF-only but born-digital |
| Ingestion ease | 3 | Easy API for old courts; scraping constraints + gap-filling for the new ones |
| Entity richness | 4 | Judges, parties, counsel, amici, trial courts — verified live |
| Relationship richness | 4 | Citation/authorship/representation/amicus explicit; statute edges derived |
| Training value | 2 | Reasoning already covered; value is narrow new corpora + retrieval pairs |
| Retrieval value | 4 | Born-digital PDFs + metadata; citator-gap caveat |
| Derived intelligence | 4 | Rule-survival, risk indices, forum metrics computable |
| Moat potential | 4 | Structuring the unindexed new courts is a concrete, defensible edge |
