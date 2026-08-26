# I. Ingestion Roadmap — Ordered Plan with Dependencies and Cadences

Sequenced for dependency order and for the two clocks that actually matter: the
**session clock** (the 90th Legislature convenes January 2027 — the platform must be
session-ready before then) and the **decay clock** (Register purges, member-page
overwrites, sole-copy video — some corpora get cheaper never; some get impossible).

## Phase 0 — Foundations (weeks 1–4)

1. **Entity spine.** Load LRL's session list (1846→2027; ~180 static rows) as the
   canonical `session` table. Load OpenStates people YAML (CC0) as the canonical
   `person` spine; crosswalk LRL memberIDs (crawl politely per profile — HTML pages,
   not PDFs), TEC filer IDs (from the bulk export), LegiScan people IDs. Load TLC plan
   codes + district geometry (CKAN). *Everything downstream joins here.*
2. **Document store + provenance model.** Immutable `document`/`document_version` with
   checksums, capture timestamps, and authority-class tags from day one — the state's
   own history-destruction (finding #3) makes the archive itself the asset.
3. **Compliance groundwork.** Registered crawler identity + per-host throttle config;
   open the three access conversations that gate later phases: LRL (historical PDFs +
   export endpoint), OCA (TAMES court metadata), The Texan (licensing). Retest
   `ftp.legis.state.tx.us` with a real FTP client from an unrestricted host.

## Phase 1 — The legislative spine (weeks 2–10, parallel tracks)

Dependencies: Phase 0 spine. All Tier 0.

4. **TLO**: backfill bills/versions/actions/authors/subjects 73R→ (FTP XML if alive;
   else URL enumeration of /tlodocs/); stand up the ten-RSS listener + History.aspx
   action-log differ. Cadence: hourly+ in session, daily interim. Fiscal notes ride
   along (per-version URLs). Statutes: tcss.legis.texas.gov chapter crawl seeded from
   the static code-list JSON; conditional GETs weekly.
5. **Journals**: JSON day-index pollers per chamber/session; HTML+PDF fetch; segment
   parser (ALL-CAPS headers + disposition boilerplate); **vote-roll parser to
   `vote`/`vote_cast` rows with journal-page cites** — the single highest-leverage
   parser in the system. Backfill House 74R→/Senate 76R→; end-of-session appendix
   ingestion. Content-hash change detection (PRELIM→FINAL churn).
6. **Committees/testimony**: House JSON API enumeration (committees → meetings →
   linked docs); throttled tlodocs fetch of witness lists/minutes/comments; witness-slip
   parser → structured rows; TLO meetings-RSS trigger. Backfill witness lists 76R→.
7. **HRO/SRC**: per-bill PDF enumeration 74R→ + section parser (stance blocks →
   labeled chunks; VOTE → committee tallies; WITNESSES → slips); SRC per-version
   analyses via TLO paths; DFR API if credential questions resolve. Daily in session.
8. **TEC**: nightly bulk-ZIP download + local diff (amendment-aware: `infoOnlyFlag`,
   COR* rows, `_ss`/`_t` exclusion); registration PDF/Excel scraper (separate fragile
   pipeline); EAO/enforcement crawl. First entity-resolution model trains on this data
   (Phase 1 output feeds Phase 0's spine continuously).

## Phase 2 — The regulatory spine + fiscal depth (weeks 6–14)

Dependencies: statutes table (Phase 1.4) for authority-cite linking.

9. **Texas Register**: UNT OAI-PMH backfill 1976→ + trailing-12-month SOS HTML (best
   parse fidelity); Friday cron; notice splitter + field extractor (TRD, TAC cites,
   dates, authority, commenters). **Decide the TAC strategy now** (headless VIEW_TAC
   crawl vs. replay-from-adoptions vs. commercial license) — everything regulatory
   depends on versioned rule text.
10. **Agency early-warning watchers**: TCEQ pending proposals, TDI informal drafts,
    HHSC draft rules (+ expand by client demand). Weekly.
11. **LBB — GAA/riders**: large-PDF pipeline per biennium + rider extractor; LRL scans for
    pre-web history as access permits. LAR/strategic-plan discovery crawl
    (search-engine seeded) with cover-page versioning; the LAR↔GAA matcher is a
    Phase 4 derived product.
12. **Comptroller**: CRE/BRE per-biennium files + Socrata sync. Low effort, schedule
    early in a gap.

## Phase 3 — Forecasting + positioning layers (weeks 10–20)

Dependencies: bill graph (Phase 1) for linkage; entity spine mature.

13. **Interim charges/reports**: LRL search-backbone metadata enumeration (compliant
    paths) + chamber-site PDFs (1999+ House, Senate cmtes tree) + press-release
    event watch; charge↔report verbatim joiner; OCR queue for pre-1990 as LRL access
    permits. Charge-watch weekly Dec–Aug even years; report-watch weekly Oct–Feb.
14. **Sunset**: full site crawl (small); Review-Grid-driven scheduler; **stage-capture
    rule: archive every report version on publication** (staff → decisions → final
    results); recommendation/outcome parser.
15. **Legislator communications**: ~190 per-entity crawlers; Senate newsroom backfill
    (1997+); **turnover-archival job wired to election results — capture-before-
    overwrite**; continuous House Wayback backfill; Lt. Gov./AG (headless for
    Cludo)/Comptroller newsrooms. Daily; session-hours frequency in session.
16. **Governor**: category pollers + LRL EO/veto indexes + TLO disposition reports;
    OCR-everything rule; appointment parser → the reconstructed appointee roster;
    special-session-call version differ.
17. **News**: Tribune RSS + Google News sitemap listener; sitemap-diff crawlers for
    non-RSS outlets; GDELT daily; paywall-aware storage policy (metadata+links for
    unlicensed full text).
18. **Hearing transcripts**: caption harvester for `captions:true` House videos
    (HLS→VTT walker); ASR queue (Whisper-class) prioritized by committee/bill
    relevance; **cache Senate media on ingest — sole-copy risk.**

## Phase 4 — Enrichment + derived layers (weeks 16–28)

19. **Courts**: CourtListener API sync (SCOTX; CCA with freshness cross-check) +
    daily pollers for the 15th COA and Business Court listing pages; citation
    extractor → statute/rule edges; OCA data conversation for TAMES metadata.
20. **AG opinions**: bounded backfill to 1939 + daily RQ poll + overruled-list differ;
    ORL classifier pipeline; headless PIA-portal probe.
21. **Platforms + campaign layer**: convention-cycle crawler + censure/priority
    watches; campaign-domain discovery per cycle + live crawl + CDX backfill;
    Meta API / Google BigQuery ad pollers; endorsement-page crawls.
22. **Derived-intelligence builds** (per `08-derived-intelligence.md` wave order):
    momentum/survival models, coalition graphs, money maps, roster-shift detector →
    then lineage chains (bill→rule→case), conversion rates, committee indices → then
    promise-vs-record, platform alignment, narrative tracking. The LAR↔GAA and
    recommendation↔bill matchers land here.

## Standing operational rules

- **Cadences:** near-real-time = TLO RSS, hearing postings (in session) · nightly =
  TEC ZIPs, news feeds, member/newsroom crawls · weekly = Register, agency watchers,
  statutes headers, interim/Sunset in their seasons · per-event = election-turnover
  archival, convention cycles, special-session calls · biennial = platforms, GAA,
  strategic plans.
- **Dedup keys** (per deep dives): TLO `(LegSess, bill, docType, version)` · journals
  `(chamber, session, filename stem)` · committees `C###YYYYMMDDHHMM##` · Register TRD ·
  TEC `reportInfoIdent`+line ID · Sunset `(agency, cycle, docType, stage)` · HRO
  `{leg}{sess}:{bill}` · statements `(office, native ID/URL, hash)`.
- **Change detection is content-hash by default** — replaced-in-place PDFs are the norm
  (journals, Sunset, ltgov charge PDFs, TAC), and header-based detection provably
  misses regenerations.
- **Every failure mode observed in this audit gets a circuit breaker**: Akamai 403
  bursts (SOS), dead FTP, SPA-200-for-everything (statutes), JS-only portals (Appian,
  Salesforce, Cludo), OCR-lottery PDFs (governor), bot-mitigation fingerprinting (AG),
  named-bot robots blocks (respect + license).
