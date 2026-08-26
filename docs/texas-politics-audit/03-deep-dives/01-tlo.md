# TLO — Texas Legislature Online (capitol.texas.gov) + bulk data + Texas statutes

**Authority class:** A (primary legislative record) with B islands (fiscal notes,
analyses) · **Priority: Tier 0 — the spine of the whole platform** · Verified by live
inspection, Aug 2026.

## 1. Corpus & coverage

- **Bill status/history from the 71st Legislature (1991); bill text from the 73rd
  (1993)** — both stated on TLO's own FAQ (capitol.texas.gov/resources/faq.aspx).
  Current through the 89th incl. called sessions.
- **Called sessions use `LegSess={number}{R|1|2|3|4}`** (e.g., `883` = 88th, 3rd Called —
  verified live; render as "88(3)"). Parsers must treat LegSess as an opaque compound key.
- **Even current bills route documents off-TLO:** conference committee reports and
  veto proclamations live at LRL (`lrl.texas.gov/scanned/88ccrs/hb0001.pdf`,
  `/scanned/vetoes/88/hb1.pdf` — verified on HB 1 88R). Pre-1991 history: LRL's
  Legislative Archive System (self-flagged "work in progress").
- **URL stability is excellent and additive:** `BillLookup/History.aspx?LegSess=&Bill=`
  and `/tlodocs/{session}/{doctype}/{format}/{billcode}{version}.{ext}` patterns stable
  for years; each version is its own file (I/H/S/E/F codes), never overwritten — good
  for point-in-time citation.
- **⚠ Bulk tree hard negative:** `ftp.legis.state.tx.us` — still named in TLO's FAQ as
  the bulk address — is **dead over HTTP(S)** (TLS reset on 443; HTTP 503 gateway
  error), and plain FTP was blocked by this environment (UNVERIFIED whether true FTP
  still works — OpenStates' scraper still cites live `ftp://…/bills/89R/billhistory/…`
  XML paths, so retest with a real FTP client from an unrestricted host before ruling
  it out). If alive, it carries bill-history XML and witness lists — the highest-value
  backfill channel.
- robots.txt disallows `/BillLookup/` and `/MyTLO/` crawling; direct `/tlodocs/` paths
  are not disallowed per what was reviewed — polite crawl either way.

## 2. Native formats (verified)

- **Bill text:** HTML (semantically flat — `<pre>`/classed `<p>`, named anchors, no
  heading hierarchy; parse caption patterns not tags), Word .docx (most versions — but
  **not universal**: 88R HB 1 states "HTML and Word versions… not available", PDF only),
  and **born-digital PDF always** (pdftotext extracted HB 1's 8–10MB
  Introduced/Enrolled cleanly; multi-column reflow is the artifact to plan for).
- **Amendments are first-class documents, not journal-only:** verified 88R HB 1's
  Amendments.aspx listing **351 amendments**, each with author, disposition
  (Adopted/Failed/Withdrawn/Tabled/Point of Order), date, and HTML+PDF links.
- **Witness lists:** per-bill and per-meeting HTML/PDF (`witlistbill`, `witlistmtg`) —
  name, self/organization, For/Against/On/Registered-not-testifying (verified fetch).
- **Fiscal notes:** HTML+PDF per bill version (LBB-authored; see the LBB deep dive).
- **Bill analyses:** HTML/PDF per version (URL convention verified; internals per the
  HRO/SRC deep dive).
- **Journals: PDF only,** on separate subdomains journals.house.texas.gov /
  journals.senate.texas.gov — the only place individual record votes appear in full.
- **RSS is real and live** (verified valid RSS 2.0, unauthenticated, despite living
  under the robots-disallowed /MyTLO/ path): ten feeds — today's filed bills (H/S),
  today's bill text, fiscal notes, bill analyses, passed bills, upcoming committee
  meetings (H/S), upcoming calendars (H/S). MyTLO per-bill alert feeds need a free
  account.
- **Statutes finding (lead resolved and corrected):** statutes.capitol.texas.gov is an
  Angular SPA whose shell returns HTTP 200 for *every* path (verified — status codes
  cannot detect missing content). Content is served from
  **`https://tcss.legis.texas.gov/resources/{Code}/htm/{Code}.{Chapter}.htm`** (+ PDF),
  a CORS-enabled static content host with real 404s, seeded by four static JSON code
  lists (`/assets/QuickCodes.json`, `StatuteCodeTree.json`…). **It is a predictable-URL
  content CDN, not a queryable JSON API** — chapter-granularity HTML with per-section
  anchors (`#11.01`), born-digital PDFs, honest Last-Modified/ETag headers (conditional
  GET works). Statute pages hyperlink each section's amending bills back into tlodocs.

## 3. What a lobbyist uses it for

The daily-use system of record: morning check of History.aspx per tracked bill; RSS for
today's text/passed bills; the fiscal note the moment it posts (a big GR number kills
bills); witness lists after hearings for the for/against roster; amendment dispositions
for exactly which floor fights were won or lost; companion tracking for whichever
chamber's vehicle is moving.

**Usefulness:** session monitoring HIGH (fastest authoritative signal; "immediate"
updates per FAQ) · bill strategy HIGH · committee strategy HIGH · meeting prep HIGH ·
issue research HIGH (subject codes like `I0746` group bills per topic) · fiscal
intelligence HIGH · opposition research MED-HIGH (witness orgs + amendment authors) ·
forecasting MED (with LobbyBook aggregation) · client intelligence MED · political
intelligence MED (record votes only when requested — see §6) · historical research MED
(1991+; LRL before) · coalition MED · relationship LOW-MED · compliance LOW ·
regulatory LOW · campaign NONE.

## 4. Ontology & native IDs

**Session** (`LegSess` — the most load-bearing ID in the system) · **bill**
(`(LegSess, type, number)`) · **bill version** (letter codes I/H/S/E/F; E not directly
sampled) · **amendment** (chamber+reading+sequence) · legislators (name strings as
author/coauthor/sponsor/conferee — no numeric member ID surfaced; resolve against the
LRL/OpenStates spine) · committee (name + structured schedule codes like
`C4502026081908001`, partially decoded) · hearing · witness · fiscal note · analysis ·
**subject codes** (controlled vocabulary, cross-session) · journal (chamber+session+date
PDF + page cites) · statute code/chapter/section (`TX.11.01` anchors) · veto
proclamations (at LRL).

## 5. Edges

EXPLICIT: bill→filed_by/coauthored/sponsored→legislator · bill→has_version ·
version→amended_by→amendment · amendment→authored_by + disposition ·
bill→referred_to→committee · committee→voted→bill (aggregate tally) ·
bill→companion_of→bill · bill→classified_under→subject · witness→position→bill@hearing ·
bill→has_fiscal_note · bill→signed_by/vetoed_by→governor (action log).
DERIVED: **bill→enacted_as→statute sections — assembled from statute pages' outbound
amending-bill links (the reverse graph doesn't exist natively)** · org→supports/opposes→
bill rollups from witness lists.
INFERRED: legislator alliance patterns from co-authorship · passage likelihood.

## 6. Temporal semantics — four dangerous traps (all verified)

1. **Version ambiguity:** "HB 1" without a version is meaningless; Introduced vs
   Enrolled differ enormously, and **line-item vetoes modify effective law without
   changing the Enrolled PDF** — the veto proclamation is a separate document at a
   separate domain that must be joined in.
2. **Codification lag:** statutes.capitol.texas.gov moves in "current through" cutoff
   jumps — it can lag bills everyone knows passed. Never treat the statutes site as
   always-current; reconcile against recently enrolled text.
3. **Record-vote absence ≠ uncontroversial:** individual votes appear only when a
   record vote was requested (TLO's own findvoteinfo.aspx guidance). Most floor votes
   are unrecorded voice votes — never infer unanimity from absence.
4. **Session-code collisions:** `883` is a session, not a number to do arithmetic on.

Explicit timestamps: filed/action/effective dates in action logs; per-version fiscal-note
dates; journal date+page anchors; statute "current through" + honest HTTP Last-Modified
(two distinct change signals — ingest both).

## 7. Authority

Bill text, actions, journals, amendments, witness lists: A — state as fact. Fiscal notes
and analyses: B — always attributed ("LBB estimated"). Codified statutes: operative law
but **no official publisher exists** (Texas State Law Library guidance) — a Legislative
Council compilation; the enrolled bill controls on divergence. RSS: A (mechanical).

## 8. Ingestion

**Hybrid: FTP-retest backfill → URL-enumeration crawl → RSS listener + action-log
diffing.**
- Backfill: retest true FTP first (bill-history XML would save enormous parsing); else
  enumerate `/tlodocs/{session}/{doctype}/{format}/…` by bill number per session, 73R→
  (status pages 71R→).
- Incremental: poll the ten RSS feeds hourly-or-better during session (cheapest
  authoritative "what changed today"); reconcile via History.aspx action-log diffs for
  what RSS misses (amendments, committee votes). Interim: daily.
- Statutes: crawl tcss resources per code (seed from the static JSON code lists),
  conditional GETs for change detection; weekly sufficient, daily header checks cheap.
- Dedup: `(LegSess, billType, number, docType, versionLetter)`; `(code, chapter)` for
  statutes.
- Failure modes: dead FTP web tier; SPA 200-for-everything trap (scrape tcss, not the
  shell hosts); PDF-only large bills; multi-column reflow; journal PDFs need
  page-anchored extraction; robots on /BillLookup/ (prefer /tlodocs/ + RSS).

## 9. Training value

Retrieval-first (the grounding corpus for the whole platform). Native label pairs:
bill text→subject code (topic classifier) · amendment→disposition (amendment-success
model) · witness org→position (stance labels) · version pairs→diff/edit understanding ·
fiscal-note text→impact category. Bill analyses as plain-English-summary instruction
pairs. Action logs as unambiguous factual-QA eval material ("on what date did HB 1 pass
the Senate?").

## 10. Derived intelligence

Bill velocity/momentum from action-log timestamps · author influence (pass rates
cross-session) · witness-list coalition graphs · committee "graveyard" risk indices by
subject · fiscal-note severity trends · **codification-lag tracker (which enacted
amendments aren't yet reflected in the public statutes — a product the state itself
doesn't offer)** · amendment-fight heatmaps (351 amendments on one budget bill).

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 5 | Core daily-use tool of the profession |
| Uniqueness | 5 | Authoritative bill/version/amendment/witness granularity exists nowhere else |
| Authority | 5 | Primary record (B islands attributed) |
| Historical value | 3 | 1991/1993 forward; LRL owns everything earlier |
| Current-session value | 5 | Immediate updates + live RSS |
| Structure quality | 2 | Predictable URLs, but flat HTML, SPA-fallback statutes, no real API |
| Ingestion ease | 3 | Easy targeted scraping; FTP uncertainty + PDF journals add friction |
| Entity richness | 4 | Bills, versions, amendments, witnesses, committees, subjects, statutes |
| Relationship richness | 4 | Rich explicit edges; person-level vote edges gap (record-vote-only) |
| Training value | 4 | Multiple native label pairs + grounding corpus |
| Retrieval value | 5 | Exactly the citable primary text RAG needs |
| Derived intelligence | 4 | Momentum, coalitions, codification-lag tracker |
| Moat potential | 4 | Texas-specific modeling generic legal databases won't replicate |
