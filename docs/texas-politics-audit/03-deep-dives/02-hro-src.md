# HRO — House Research Organization (+ companion: Senate Research Center analyses)

**Authority class:** A/B (official nonpartisan House department; near-primary facts,
reported arguments) · **Priority: Tier 0** · Verified by live inspection, Aug 2026.
Two items UNVERIFIED: the Dynamic Floor Report API's JSON payload schema (endpoints
confirmed from the app bundle; payloads are auth-gated), and Wayback cross-checks
(web.archive.org unreachable from the audit environment).

## 1. Corpus & coverage

- **Bill analyses / Daily Floor Reports back to the 74th Legislature (1995), including
  called sessions.** Verified at both ends: per-bill PDF
  https://hro.house.texas.gov/pdf/ba74r/hb0001.pdf (200) and compiled daily report
  https://hro.house.texas.gov/pdf/fr1995/950510A.pdf (200); spot checks passed for 1997,
  1999, 2001, 2003, 2005, 2007, 2009, 2011, 2019, 2023, 2025. Search UI advertises
  74th–89th at https://hro.house.texas.gov/BillAnalysis.aspx. Called-session coverage
  verified (e.g., fr2025/250828A.PDF, 89th 2nd Called).
- **Two delivery generations run in parallel:** the classic ASP.NET PDF site
  (hro.house.texas.gov — the stable, scrapable corpus) and a new Angular "Dynamic Floor
  Report" SPA (https://hro-dfr.house.texas.gov/floor-reports) rendering recent sessions
  from a JSON API. Classic per-bill/daily PDFs continue to exist for recent sessions
  (ba88r/hb0016.pdf and fr2025/250514A.PDF both verified 200).
- **Coverage is a calendar-driven subset, not per-filed-bill:** HRO analyzes bills that
  reach a House daily/supplemental calendar. Bills that die in committee, are never
  calendared, or move only in the Senate get no HRO analysis; local/consent and
  congratulatory items are generally not analyzed.
- **Other publications:** "Major Issues of the Session" 79th (2005) → 88th (2024) at
  https://hro.house.texas.gov/issues.aspx; Focus Reports (e.g., grid reliability, Feb
  2026); Interim News Briefs (INB89-1 fetched, Spring 2026); Vetoes digests; session
  Topics previews; procedure guides.
- **URL stability:** deterministic per-bill IDs (excellent) with three wrinkles: retired
  legacy host `www.hro.house.state.tx.us` still cited in old documents; `.pdf` vs `.PDF`
  case inconsistency; hand-named Major Issues files (`major87.pdf` vs
  `Major Issues 88th.pdf`).
- **Alternate access:** TLO surfaces the HRO PDF on each bill's page under "Additional
  Documents"; LRL holds bill-file copies; Interim News also lives on WordPress
  (https://txhronews.wordpress.com) with real RSS.

## 2. Native formats (verified)

- **Per-bill analysis PDF:** `https://hro.house.texas.gov/pdf/ba{leg}{sess}/{bill}.pdf`
  (lowercase session, 4-digit zero-padded bill). ba88r/hb0016.pdf: 9pp, born-digital
  (Word for Microsoft 365), full text layer.
- **Compiled Daily Floor Report PDF:** `/pdf/fr{YYYY}/{YYMMDD}{A-D}.pdf` (letter = part).
  Cover carries steering-committee roster + report number ("86th Legislature, Number 68").
- **Born-digital across the entire 1995–2026 range — no scanned years found.** Even 1995
  (Distiller 2.1) and 1999 (PDFWriter from WordPerfect) carry 100–150K-char text layers.
  The whole archive text-mines without OCR. New-pipeline PDFs are rendered by
  Aspose.Words from the DFR data.
- **Canonical section structure (verified in extracted text):** left-margin labels
  `SUBJECT:` · `COMMITTEE:` (+ disposition) · `VOTE:` (named committee ayes/nays/absent) ·
  `SENATE VOTE:` (Senate bills only, with named nays) · `WITNESSES:` (For/Against/On +
  "Registered, but did not testify") · `BACKGROUND:` · `DIGEST:` · `SUPPORTERS SAY:` ·
  **`CRITICS SAY:` / `OTHER CRITICS SAY:` — or `OPPONENTS SAY:` / `OTHER OPPONENTS
  SAY:`** · `NOTES:` (often LBB fiscal figures).
  **Correction (verified during implementation, Aug 2026):** the opposing-argument
  label is not always "OPPONENTS." Extracting left-margin words by x-position from
  88R HB 16 and HB 900 shows `CRITICS SAY:` and `OTHER CRITICS SAY:` — HRO's wording
  when no organized opposition registered. Any stance-label pipeline must accept both
  families and normalize them, or it silently drops the con side of those analyses.
  **Digest-only entries** (uncontested/late-session Senate bills) omit the argument
  sections — verified in fr2019/190517B.pdf. Parser gotcha: "SUPPORTERS SAY" wraps to two
  physical lines in extraction.
- **Dynamic Floor Report JSON API:** base `https://hro-services-public.house.texas.gov/api/v1`
  with endpoints recovered from the app bundle: `/sessions`,
  `/dynamicFloorReports?Legislature=&Session=`, `/legacyFloorReports`,
  `/calendarDetails/{id}`, `/billAnalysisContents/?legislature=&session=&billNumber=`,
  `/billAnalysisContents/{id}/witnesses` (witnesses separately addressable). Auth: JWT via
  `POST /authentication/jwt` using a service principal embedded in the SPA. Payload
  schema UNVERIFIED. If credentialed, this is the highest-value path — structured content
  with no PDF parsing.
- **RSS:** only Interim News (https://txhronews.wordpress.com/feed/, verified). No sitemap
  on the classic host.

## 3. What a lobbyist uses it for

The single best pre-vote intelligence document in Texas: one document delivers the plain-
English digest, the named committee vote, the full witness roster for/against, and both
sides' actual arguments — pre-written, neutral, citable. Workflows: brief a member on
tomorrow's floor fight in minutes (SUPPORTERS/OPPONENTS SAY verbatim); reconstruct who
testified against a client's bill (WITNESSES); whip-count from committee splits (VOTE);
fiscal exposure (NOTES); a decade's argument history per issue (Major Issues + floor
reports).

**Usefulness:** session monitoring HIGH · bill strategy HIGH · committee strategy HIGH ·
opposition research HIGH · issue research HIGH · historical research HIGH · meeting prep
HIGH · current-session floor work HIGH · coalition development MED-HIGH (witness
alignment) · client intelligence MED · political intelligence MED · relationship
intelligence MED · fiscal MED · forecasting MED (Topics previews; recurring argument
patterns) · regulatory monitoring LOW · compliance LOW · campaign NONE.

## 4. Ontology & native IDs

Bill (join key `{leg}{sess}+{type}{number}`, e.g., 88R HB 16 — the crosswalk to TLO) ·
analysis (URL-deterministic ID; DFR `billAnalysisContents/{id}`) · daily floor report
(`{YYMMDD}{A-D}` + in-doc number) · legislators (name strings — need resolution to member
IDs) · committee + disposition · witness (name + org + stance + testified/registered
flag) · organizations (affiliation strings) · vote events (committee tally; referenced
Senate floor vote) · stance-labeled argument blocks · SUBJECT free text + Major Issues
subject taxonomy · fiscal-note references · publications (Focus/INB/Major Issues/Vetoes).

## 5. Edges

EXPLICIT: bill→has_analysis · bill→scheduled_on→floor_report(date) · bill→reported_by→
committee · legislator→voted_aye/nay/absent (committee, named) · bill→authored_by
(header, incl. "CSHB 16 by A. Johnson" substitute authorship) · witness→testified_
{for/against/on}→bill · witness→represents→org · witness→mode{testified|registered-only} ·
argument→{supports|opposes}→bill (pre-labeled stance text) · senate_bill→passed_senate→
tally+named nays · bill→companion_of→bill (where stated) · bill→fiscal_estimate (NOTES).
DERIVED: org→{supported|opposed}→bill (from its witnesses' stance) · bill→issue area
(Major Issues chapter placement).
INFERRED: org↔org co-testimony coalitions · legislator alignment clusters · recurring
argument frames across sessions.

## 6. Temporal semantics

Analysis is dated to its floor-calendar day. **Critical version trap, stated on every HRO
cover: the analysis reflects the bill "as reported by House committee and first
considered by the House" — it does NOT reflect floor amendments, engrossed/enrolled text,
or Senate changes.** WITNESSES reflect the still-earlier committee hearing; VOTE is the
committee vote, not the floor vote. Contrast SRC/TLO bill analyses, which are re-issued
per version and version-stamped (verified "Enrolled" on SB 1577). Treat HRO as the
pre-floor snapshot; diff against enrolled text for what actually became law.

## 7. Authority

Facts (committee disposition, tallies, witness rosters, digest, fiscal figures): state as
fact with attribution to HRO. **SUPPORTERS SAY / OPPONENTS SAY are reported arguments,
not HRO's position — always attribute as "supporters argued…"** DIGEST is a neutral
summary, not statutory text. Aspose-era machine-rendered PDFs carry no authority loss.

## 8. Ingestion

Two lanes + publications:
1. **Backfill (classic PDFs, 1995→present):** enumerate `/pdf/ba{leg}{sess}/{bill}.pdf`
   per session (404 = not analyzed, normal) and `/pdf/fr{YYYY}/{YYMMDD}{A-D}.pdf`. Prefer
   per-bill PDFs (clean dedup); split daily compilations on the
   "HOUSE RESEARCH ORGANIZATION bill analysis" header when needed. Section parser keys on
   fixed margin labels (handle line-wrap + digest-only variants).
2. **Current (DFR API):** if credentialed — sessions → floor reports → calendarDetails →
   billAnalysisContents + /witnesses. Brittle if the app rotates its embedded credential.
3. **Publications:** Interim News via WordPress RSS; Focus/Major Issues/Vetoes by scraping
   index pages.
Cadence: daily during session (poll LatestFloorReport.aspx / dynamicFloorReports; multiple
parts on heavy days); weekly interim. Dedup key: `{leg}{sess}:{billType}{num}` (analyses);
PDF path/INB number (publications). Change detection: text hash; a new committee
substitute can yield a new analysis — key on bill + committee-report version. Failure
modes: `.pdf/.PDF` case, legacy hostname links, compilation splitting, unguessable Major
Issues filenames, auth-gated undocumented API.

## 9. Training value

The standout natural-label corpus in the whole audit:
- **SUPPORTERS SAY vs OPPONENTS SAY → stance/argument classifier** — pre-labeled,
  professionally written, balanced pro/con argument text, 30 years deep.
- SUBJECT lines + Major Issues chapters → Texas-specific issue classifier.
- WITNESSES For/Against/On → org-stance labels.
- VOTE tallies → member-position modeling.
- NOTES → fiscal-figure extraction (NER).
- Digest-only vs full analysis → contestedness classifier.
Instruction tuning: HRO's neutral house style is the quality target for "summarize this
bill," "extract the pro/con arguments," "list who testified." Eval: DIGEST/arguments as
gold for faithfulness; HRO (pre-floor) vs SRC (enrolled) pairs for version-drift evals.

## 10. Derived intelligence

Recurring argument-frame library (cluster arguments across sessions; who deploys "local
control" vs "unfunded mandate") · issue persistence/cyclicity from 15 sessions of Major
Issues · organization power maps (witness activity × outcomes, co-testimony coalition
graph) · member alignment clusters from committee votes · per-bill contestedness index
(argument length, Against-witness count, vote margin) → floor-difficulty predictor ·
opposition-effectiveness metric (whose opposition correlates with stalls) · HRO-vs-enrolled
drift metric (how much bills change after the House floor).

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 5 | The fastest, richest pre-floor brief in Texas |
| Uniqueness | 5 | Stance-labeled arguments + named votes + witnesses, combined, free, nowhere else |
| Authority | 5 | Official nonpartisan House department |
| Historical value | 5 | Born-digital and text-searchable 1995→present, called sessions included |
| Current-session value | 5 | Daily calendar coverage during session |
| Structure quality | 4 | Rigid parseable labels; PDF quirks, digest-only variance, auth-gated JSON |
| Ingestion ease | 4 | Deterministic URLs, no OCR; compilation splitting + undocumented API |
| Entity richness | 4 | Bills, members, committees, witnesses, orgs, arguments; names need resolution |
| Relationship richness | 5 | Explicit vote/witness/stance/companion edges + strong inferred graphs |
| Training value | 5 | Gold stance pairs + issue taxonomy + org-stance, decades deep |
| Retrieval value | 5 | Canonical bill-analysis RAG corpus |
| Derived intelligence | 5 | Frames, coalitions, contestedness, drift — all computable |
| Moat potential | 4 | Raw source is public; the parsed, ID-resolved 30-year graph is the moat |

---

## Companion: Senate Research Center (SRC) bill analyses

Structurally different and hosted on TLO, not an HRO-style site. Produced per Senate rule
for every bill taken up on the Senate floor; **re-issued and version-stamped per bill
version** (Introduced → Committee Report → Engrossed → Enrolled — verified
capitol.texas.gov/tlodocs/88R/analysis/pdf/SB01577F.pdf, born-digital, "Enrolled").
Structure (verified): AUTHOR'S/SPONSOR'S STATEMENT OF INTENT · PURPOSE · RULEMAKING
AUTHORITY · SECTION BY SECTION ANALYSIS · SUMMARY OF COMMITTEE CHANGES. **No arguments,
no votes, no witnesses** — neutral intent + technical section-by-section. Selected SRC
analyses on TLO from the 74th (1995) forward.

Complementarity: HRO = the fight (arguments/votes/witnesses, House floor, committee-
reported snapshot); SRC = the intent and mechanics (per-version, Senate side, includes
RULEMAKING AUTHORITY — a direct hook into the Register lineage graph). LobbyBook needs
both; both are linked from each TLO bill page.
