# Texas Register + Texas Administrative Code (state agency rules)

**Authority class:** A (adopted rule text = law; official state journal) / B (proposals,
preambles, fiscal statements) · **Priority: Tier 0** · Verified by live inspection, Aug 2026.

## 1. Corpus & coverage

- **Official weekly Register** (Fridays, ~5pm CT): https://www.sos.state.tx.us/texreg/index.shtml.
  Current issue verified: Vol. 51, No. 34 (Aug 21, 2026), pages 5487–5592 — pagination is
  continuous per annual volume (volume = year − 1975).
- **⚠ The SOS's own archive is a rolling ~1-year window.** HTML archive
  (https://www.sos.state.tx.us/texreg/archive/index.shtml) and PDF archive
  (https://www.sos.state.tx.us/texreg/pdf/backview/index.shtml) both reached back only to
  Sept 2025 at inspection. Verified empirically that a Google-indexed March 2025 archive
  URL now returns "file not found" — **archive URLs expire while search engines still
  index them.** Continuous harvesting is mandatory, not optional.
- **Complete 1976–present archive lives at UNT**, the SOS's official permanent-access
  partner: https://texashistory.unt.edu/explore/collections/TR/ — verified **3,813 issues**
  from Vol. 1, No. 1 (Jan 6, 1976) through Aug 2026, with OAI-PMH, IIIF, ATOM feeds, and
  full-text OCR search.
- **Searchable Register database (2000–present)** and **current + historical TAC
  (1999–present)** live in a new Appian JS portal
  (https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=SEARCH_TEXAS_REGISTER,
  `?interface=VIEW_TAC`, `?interface=SEARCH_TAC`). Contents UNVERIFIED directly — the
  portal is a JS-only SPA with no documented API.
- **⚠ URL-stability rupture:** the 2025 migration to the Appian portal broke every legacy
  deep link (`texreg.sos.state.tx.us/public/readtac$ext...` now redirects to the portal
  landing page with parameters dropped — verified). Decades of third-party citations point
  at nothing. Assume it can happen again.
- Pre-1999 TAC versions: print only (Texas State Law Library back to 1979; before that,
  "contact the agency" — per https://guides.sll.texas.gov/texas-law/administrative-rules).
- Open-meetings notices left the Register in Nov 1998; now posted within ~5 minutes of
  filing, but only inside the JS portal (per https://www.sos.state.tx.us/open/index.shtml).
- robots.txt effectively empty; no sitemap found; Register annual indexes UNVERIFIED
  (fetch 403'd).

## 2. Native formats (verified)

- **HTML edition:** one TOC per issue + one HTML file *per Register section per TAC
  title* (e.g., `/texreg/archive/August212026/Proposed Rules/19.EDUCATION.html`), with
  multiple notices concatenated per file, addressed by `#n` anchors. Paths contain literal
  spaces (URL-encode) and at least one observed backslash path — parser hazards.
- **Amendment markup is clean, machine-parseable diff semantics** (verified in raw HTML):
  additions in `<u>` underline; deletions bracketed and struck (`[<s>old text</s>]`).
  This yields an auto-generated before/after edit corpus.
- **PDF edition:** whole-issue PDF + per-section PDFs per issue (e.g., `0814is.pdf`,
  `0814prop.pdf`). Tables & graphics ship as separate per-document PDFs named by TRD
  number (e.g., `202603256-1.pdf`).
- **RSS:** https://www.sos.state.tx.us/texreg/texreg.xml — verified but whole-issue-level
  only (3 items, no per-rule granularity). **Email alerting** via GovDelivery supports
  agency-filtered notices (rule numbers, action type, issue date).
- **UNT API:** OAI-PMH (`oai_dc`, `untl`), IIIF manifests, ATOM new-item feeds, ARK
  identifier lists, OpenSearch full text — verified at
  https://texashistory.unt.edu/explore/collections/TR/api/.
- No official bulk TAC or Register dump exists (none found). No Word downloads observed.
  The portal's "Public Document Request" TAC-chapter download feature: UNVERIFIED
  (inside the JS portal).

## 3. What a lobbyist uses it for

The canonical answers to: *Did an agency quietly propose a rule affecting my client? When
does the comment window close? What statutory authority do they claim? Who commented last
time and did the agency budge?*

Verified mechanics that make those workflows real:
- Every proposal states the comment window verbatim ("begins August 21, 2026, and ends
  September 21, 2026" — typically ~31 days) and hearing-request deadlines.
- Every proposal/adoption carries a dedicated **STATUTORY AUTHORITY** section, frequently
  with explicit bill linkage — e.g., a TEA proposal implementing "House Bill 2, 89th
  Legislature, 2025," citing the sections HB 2/HB 121/SB 260 amended (verified).
- **Adoption preambles name commenters** and pair each comment with the agency's response
  and whether text changed (verified examples: Dow Chemical, Fermi America, Last Energy,
  X-energy on a TANEO rule; TAHP and TMA on TDI rules). This is coalition and
  influence-mapping data hiding in preambles.
- **Pre-Register early-warning layer confirmed at three agencies:** TCEQ "Pending
  Proposals" + rule-project PDFs (tceq.texas.gov/rules/pendprop.html), TDI informal draft
  rules, HHSC draft-rule comment pages. Monitoring the agency layer buys weeks-to-months
  of lead time before formal proposal.

**Usefulness:** regulatory monitoring HIGH (canonical) · compliance HIGH · client
intelligence HIGH · issue research HIGH · historical research HIGH · forecasting MED-HIGH
(rule reviews telegraph rewrites) · fiscal MED (per-proposal fiscal + growth-impact
statements) · coalition MED (commenter lists) · opposition MED · meeting prep MED · bill
strategy MED (implementation tracing) · session monitoring LOW-MED · political LOW-MED
(appointments + AG-request notices per issue) · committee LOW · relationship LOW (named
agency contacts) · campaign NONE.

## 4. Ontology & native IDs

Agencies · TAC citations (Title/Part/Chapter/Subchapter/Section, e.g. "19 TAC §61.1010") ·
Register documents with **TRD numbers** (`TRD-202603360` = TRD-YYYY + 5-digit sequence;
globally unique per document — the natural dedup key) · Register citations ("51 TexReg
4080" — permanent) · action types (proposed/adopted/withdrawn/emergency/emergency-renewal/
review-proposed/review-adopted) · statutory authorities · enacting bills · named
commenters · named fiscal officers and contact persons · agency-side rule-project numbers
(e.g., TCEQ `2026-011-335-WS`) · governor appointments · AG opinion-request summaries ·
"In Addition" notices (agreed orders, license applications, rate ceilings) · UNT ARK IDs
for historical issues.

## 5. Edges

EXPLICIT: agency→files→document (TRD header) · proposal→proposes_amendment_of→TAC§ ·
adoption→adopts→proposal (cites the proposal's TexReg cite verbatim — verified) ·
withdrawal→withdraws→proposal (incl. Gov't Code §2001.027 auto-withdrawal) ·
emergency_renewal→renews→emergency_rule · rule→authorized_by→statute ·
rule→implements→bill (where stated) · org→commented_on→proposal ·
rule_review→reviews→chapter.
DERIVED: agency→responded_to→commenter {accepted/rejected} (Comment/Response pairs) ·
bill→rule linkage at corpus scale (text extraction) · proposal→becomes→TAC text version
(join adoption effective date to TAC snapshots) · agency project number↔TRD matching.
INFERRED: client-industry exposure via TAC-chapter taxonomy · commenter co-occurrence
coalitions.

## 6. Temporal semantics

Full lifecycle timestamps are stated per notice (verified): agency **filing date** (~11
days pre-publication) → **publication** → **comment window** → earliest-possible adoption
(20 days post-publication) → **auto-withdrawal at 6 months** if not adopted (§2001.027) →
adoption filing + **effective date** (20 days after filing unless statute says otherwise).
Emergency rules: immediate effect, 120 days + one 60-day renewal (verified a renewal
notice with expiry date). Four-year rule-review cycle (§2001.039).

**Structural misinformation risks:**
1. TAC text mutates silently — any ingested rule text must carry an as-of date; historical
   text reconstructable to 1999 via the portal, to 1976 only by replaying Register
   amendments from UNT scans.
2. **Rules adopted *without changes* are not republished** — final text must be composed
   from the proposal + the adoption notice. The Register alone does not contain the final
   text of every rule.
3. Dead legacy URLs + the rolling 1-year purge mean stale links can point at nothing — or
   at cached superseded text.

## 7. Authority

Adopted/codified TAC text: **A** (binding law; note SOS "does not interpret or enforce").
Adoption preambles + comment responses: **A/B** (legally required official analysis,
citable). Proposals + fiscal/growth-impact statements: **B** (official, non-final,
self-assessed). Emergency rules: **A** while alive. Appointments/AG-request notices: **A**
for the fact of the action. Agency pre-Register drafts: **C** (explicitly non-final).
UNT scans: authentic (official partnership); OCR text lower fidelity — cite the image.

## 8. Ingestion

**Hybrid: weekly scheduled crawl + UNT API backfill + agency-layer watchers.**
- *Backfill:* (1) UNT via OAI-PMH/ARK enumeration for 1976–present (clean, API-supported);
  (2) sos.state.tx.us HTML for the trailing 12 months (best parse fidelity — diff markup
  preserved); (3) the 2000+ Appian search DB only if headless-browser automation proves
  worth it (fragile; prefer UNT for anything past the HTML window).
- *Incremental:* Friday cron keyed off the RSS/archive-index diff; fetch HTML section
  files + graphics PDFs by TRD.
- *TAC sync* is the hard part: no bulk source. Options: headless crawl of VIEW_TAC
  (brittle, throttled), reconstruct current text by replaying adoptions onto a baseline,
  or license from a commercial republisher. Decide early; everything regulatory hangs off
  having versioned TAC text.
- *Dedup key:* TRD number; secondary (issue date, section, TAC cite).
- *Failure modes observed live:* intermittent Akamai 403s mid-crawl (backoff + UA
  hygiene); hhs.texas.gov hard-403s datacenter IPs; spaces/backslashes in paths; the
  portal migration precedent; open-meetings data JS-only.

## 9. Training value

Retrieval-first corpus. Natural labels: action type by section; **proposal→outcome**
(adopted-with-changes / without-changes / withdrawn) as a real prediction task with
decades of examples; comment stance from agency summaries; review outcomes. Extraction
tasks: statutory-authority cites, bill→rule linkage, fiscal fields, commenter lists; the
underline/strike markup is an auto-labeled edit-understanding dataset. Strong eval
material: deterministic deadlines/TRD lookups and which-text-was-in-force-on-date-D
temporal questions.

## 10. Derived intelligence

Legislation→regulation lag per agency/bill (verified linkage exists: HB 2 (2025) → TEA
proposal Aug 2026) · agency rulemaking velocity + emergency-rule usage + auto-withdrawal
rate (dysfunction signal) · **comment-influence index** (share of adoptions changed in
response to comments, per agency and per commenter) · client exposure map (industry → TAC
chapters → open windows + review calendar) · the early-warning ladder (informal draft →
pending proposal → proposal → adoption) · automated regulatory docket (every deadline
machine-extractable) · commenter co-occurrence coalition network.

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 5 | Authoritative record of every rulemaking, with deadlines and named commenters |
| Uniqueness | 4 | Sole official source; commercial republishers mirror TAC text |
| Authority | 5 | Adopted rules are law |
| Historical value | 5 | Unbroken 1976–present via UNT (with API); TAC versions to 1999 |
| Current-session value | 3 | Implementation phase, not session play-by-play |
| Structure quality | 4 | Templated notices, TRD IDs, clean diff markup; concatenated files and path hazards |
| Ingestion ease | 3 | Weekly HTML easy; 1-year purge, Akamai 403s, no bulk TAC, JS-only portal |
| Entity richness | 4 | Agencies, rules, statutes, bills, commenters, officials, projects |
| Relationship richness | 5 | Proposal↔adoption↔withdrawal, rule→statute→bill, org→comment→response all explicit |
| Training value | 4 | Natural outcome labels + extraction tasks; parsing investment needed |
| Retrieval value | 5 | Canonical citable answers for compliance/rulemaking |
| Derived intelligence | 5 | Lag metrics, influence scoring, early-warning ladder, docket calendar |
| Moat potential | 4 | Public raw data, but the composed asset (versioned TAC + commenter graph + agency pre-filing layer) is hard to replicate |
