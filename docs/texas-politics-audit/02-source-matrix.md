# B. Source Matrix — Coverage, Scores, and Priority Tiers

One row per source family. Scores (1–5) are the deep dives' scores; trace any number to
its evidence in `03-deep-dives/`. Column key: **Use** lobbyist usefulness · **Unq**
uniqueness · **Auth** authority · **Hist** historical value · **Cur** current-session
value · **Str** structure quality · **Ing** ingestion ease · **Ent** entity richness ·
**Rel** relationship richness · **Trn** training value · **Rtr** retrieval value ·
**Der** derived-intelligence potential · **Moat** competitive-moat potential.

| Source family | Verified corpus | Format | Authority | Primary lobbyist use | Ingestion | Use | Unq | Auth | Hist | Cur | Str | Ing | Ent | Rel | Trn | Rtr | Der | Moat | Tier |
|---|---|---|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|:--|
| TLO (capitol.texas.gov) | Status 1991+, text 1993+, all called sessions; statutes via tcss CDN | Flat HTML + docx + born-digital PDF; 10 RSS feeds; no API | A (B islands) | Daily bill tracking, versions, amendments, witness lists | RSS listener + URL-enumeration crawl; FTP retest | 5 | 5 | 5 | 3 | 5 | 2 | 3 | 4 | 4 | 4 | 5 | 4 | 4 | **0** |
| HRO + SRC analyses | 1995+ born-digital, incl. called sessions; Major Issues 2005+ | Deterministic PDF URLs; auth-gated DFR JSON API; WP RSS (interim) | A/B | Pre-floor brief: digest, votes, witnesses, both sides' arguments | PDF enumeration + optional API | 5 | 5 | 5 | 5 | 5 | 4 | 4 | 4 | 5 | 5 | 5 | 5 | 4 | **0** |
| House + Senate journals | House 1995+, Senate 1999+; LRL/UNT earlier; complete called-session archives | Born-digital PDF (page-cited) + anchor-less HTML; JSON day-index | A | Roll calls, amendment fates, points of order — the floor record | JSON-index poller + content-hash change detection | 5 | 5 | 5 | 4 | 5 | 4 | 3 | 4 | 4 | 4 | 5 | 4 | 3 | **0** |
| Committee records + testimony | Witness lists 1999+, minutes ≥2007+, House video 2001+, Senate A/V 1999+ | Born-digital PDF/HTML; House JSON API; HLS video + partial WebVTT captions | A/B facts; C/D content | Who's for/against; committee votes; hearing prep | JSON API + throttled tlodocs + caption/ASR pipeline | 5 | 4 | 4 | 3 | 5 | 4 | 3 | 3 | 4 | 4 | 4 | 5 | 3 | **0** |
| Texas Register + TAC | 1976+ complete via UNT (SOS purges ~1yr); TAC versions 1999+ | Templated HTML w/ diff markup + PDF; TRD IDs; UNT OAI-PMH/IIIF; weak RSS | A/B | Rule proposals, comment windows, statutory authority, commenters | Weekly crawl + UNT backfill + agency watchers; TAC sync decision | 5 | 4 | 5 | 5 | 3 | 4 | 3 | 4 | 5 | 4 | 5 | 5 | 4 | **0** |
| TEC (CF, lobby, enforcement) | CF 2000+, lobby 2005+ (totals 1993+), EAOs/orders 1992+ | Nightly bulk ZIPs w/ documented CSV schemas; registration PDF/Excel only; no API | D (disclosure); orders/AOs higher | Money, clients, rosters, compliance | Nightly bulk re-download + local diff; registration scraper | 5 | 4 | 3 | 5 | 4 | 4 | 3 | 4 | 4 | 3 | 4 | 4 | 3 | **0** |
| LBB (fiscal notes, GAA, riders) | Notes 1995+ per version; GAA to 1927 via LRL | HTML tables + text-layer PDFs (GAA >10MB); no API | A | Cost per version; riders; appropriations | Per-session crawl + large-PDF pipeline; rider parser | 5 | 4 | 5 | 5 | 5 | 4 | 3 | 4 | 4 | 4 | 4 | 5 | 4 | **0** |
| Third-party ecosystem (LRL, OpenStates, LegiScan, UNT, TLC, Wayback) | LRL 1846+ indexes; LegiScan live; OpenStates CC0 people; UNT APIs | Mixed: HTML indexes, APIs, YAML, CKAN, OAI-PMH | varies | Entity spine, backfill, redundancy | API syncs + negotiated LRL access | 5 | 4 | 4 | 5 | 4 | 3 | 3 | 5 | 4 | 3 | 4 | 4 | 4 | **0** (spine) |
| Interim charges + reports | LRL-indexed 1846+ (PDFs verified to 1935); 2026 charges live | Born-digital charge PDFs + HTML (LRL); era-variable report PDFs | A | Next session's published agenda; recommendations | LRL search backbone + chamber sites + press watch | 5 | 4 | 5 | 5 | 5 | 3 | 3 | 4 | 4 | 4 | 5 | 5 | 5 | **1** |
| Sunset Advisory Commission | Cycles to 1978; per-agency 1998+; schedule to 2036-37 | Born-digital PDFs, rigid numbering + outcome labels; no API | A (layered voices) | Agency-review threats; recommendation→law tracing | Crawler driven by the Review Grid; version capture | 5 | 5 | 5 | 4 | 5 | 4 | 4 | 4 | 5 | 4 | 5 | 5 | 4 | **1** |
| Legislator press/statements | Senate newsroom 1997+; House per-member (destroyed on turnover); caucuses thin | HTML (no RSS except Comptroller); Senate compound IDs | C | Stated positions; real-time political pulse | ~190 per-entity crawlers + turnover-archival jobs | 4 | 4 | 4 | 2 | 5 | 2 | 2 | 4 | 4 | 3 | 4 | 4 | 4 | **1** |
| Governor (EOs, calls, appointments, vetoes) | EOs 2016+ (gov site) / 1949+ (LRL); vetoes to 1939+ (LRL); appointments press-only | Ad-hoc PDFs (OCR lottery); LRL HTML index; 10-item RSS | B acts in C/E wrapping | Special-session calls; who sits on the regulator | Category pollers + LRL index + TLO reports; OCR everything | 5 | 3 | 4 | 3 | 5 | 2 | 2 | 3 | 4 | 2 | 4 | 5 | 4 | **1** |
| Texas political news | Tribune 2010+ (RSS verified); paywalled dailies/tipsheets; GDELT 1979+ metadata | RSS/sitemaps; full text license-gated | E (+C advocacy media) | Narrative, insider signal, salience | Feed listener + sitemap diff + GDELT; paywall-aware | 5 | 3 | 3 | 4 | 5 | 4 | 3 | 3 | 3 | 3 | 5 | 4 | 3 | **1** |
| AG opinions + ORLs | Opinions 1939+; RQs 1998+; ORDs 1973–2014 (dead); ORLs 1989+ (~40k/yr) | Per-doc PDFs (old=scan, new=tagged); JS-gated post-2023 portal | B-analysis (persuasive) | Agency authority; pending-RQ early warning | Bounded scrape + daily RQ poll; browser-like fetcher | 4 | 4 | 3 | 5 | 4 | 4 | 3 | 3 | 3 | 3 | 5 | 4 | 4 | **2** |
| Texas courts | SCOTX to 1840 (CourtListener); CCA 1998+; new courts 2024+ uncovered | Born-digital tagged PDFs; CourtListener JSON API; TAMES robots-blocked | A/B | Rule challenges; amici/counsel coalitions | CourtListener sync + new-court pollers; OCA conversation | 4 | 4 | 5 | 4 | 3 | 4 | 3 | 4 | 4 | 2 | 4 | 4 | 4 | **2** |
| Comptroller | CRE 2006+ (PDF+XLSX); allocation data 2002+; Socrata verified | Clean estimate files; Qlik dashboards; SODA API | A (B magazine) | Revenue headroom; the spending ceiling | Per-biennium files + Socrata sync | 5 | 5 | 5 | 4 | 5 | 4 | 3 | 3 | 3 | 3 | 4 | 4 | 3 | **2** |
| Agency strategic plans + LARs | Decentralized across ~200 agency sites; 1–2 cycles retained | Text-layer PDFs, standardized template; JS-postback LBB index | A template / B content | Agency priorities + budget asks; bill-impact in agency's voice | Search-discovery crawl; cover-page versioning | 4 | 4 | 3 | 3 | 3 | 4 | 2 | 4 | 3 | 4 | 4 | 4 | 4 | **2** |
| Party platforms + priorities | RPT PDFs 2020+ (Wayback to 1997); TDP broken/Google Docs; minors walled | Text PDFs; plank numbers reset per subsection | C | Platform-aligned/adverse framing; censures; priorities | Convention-cycle crawler + Wayback backfill | 4 | 3 | 4 | 5 | 3 | 3 | 3 | 4 | 3 | 3 | 4 | 5 | 2 | **2** |
| Campaign content | Wayback-dependent sites (decay verified); ad APIs; endorsement pages | Builder HTML; Meta API/Google BigQuery; FCC SPA | C | Promises, endorsements, ad strategy | Cycle discovery + live crawl + CDX backfill + ad APIs | 4 | 4 | 2 | 3 | 2 | 2 | 2 | 3 | 4 | 3 | 4 | 4 | 4 | **2** |

## Tier definitions and rationale

**Tier 0 — ingest immediately (critical infrastructure).** TLO + journals + HRO/SRC +
committee/witness records form the legislative spine no feature works without; the
Texas Register/TAC is the regulatory spine (and its 1-year purge makes starting *now*
materially cheaper than starting later); TEC is the money/relationship spine; LBB
fiscal notes ride along with TLO crawling; the third-party ecosystem provides the
entity spine (OpenStates people + LRL sessions + LegiScan redundancy) everything else
resolves against.

**Tier 1 — high-value next.** The forecasting layer (interim charges/reports, Sunset)
and the positioning layer (legislator statements, governor actions, news feeds).
Two carry urgency overrides: legislator communications (history is actively destroyed
on turnover — every month of delay is unrecoverable corpus) and the hearing
caption/ASR pipeline (captions only exist forward from ~Feb 2026; Senate streams are
the sole copy).

**Tier 2 — enrich after the core graph.** AG opinions, courts, Comptroller, strategic
plans/LARs, platforms, campaign content — high value but dependent on the entity spine
and bill/rule graph to reach their potential, and their cadences (biennial, per-cycle,
opinion-paced) tolerate later starts. Exception worth pulling forward opportunistically:
the two new courts' opinions (tiny volume, first-mover window).

**Tier 3 — opportunistic/specialized.** FCC political files at scale (un-automatable
SPA; AdImpact if budget allows) · social-media firehose ingestion (X API economics) ·
pre-1990 OCR backfills (journals, interim reports, early Registers beyond UNT's text
layer) · minor-party platforms (Cloudflare-walled) · trial-court dockets via re:SearchTX
(paid, bot-protected) · Politwoops-era deleted-tweet archaeology.
