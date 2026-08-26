# A. Executive Findings

The seventeen discoveries that should shape LobbyBook's architecture, ranked by how much
they change the build. Every item was verified by live inspection (details and URLs in
the deep dives).

## The structural findings

**1. Texas publishes no structured roll-call vote data. Anywhere.** Individual member
votes exist only as prose inside House/Senate journal HTML/PDFs — and only when a
record vote was requested (most floor votes are unrecorded voice votes). LRL, OpenStates,
and LegiScan all reconstruct votes by scraping the same fragile journal text; OpenStates'
scraper code documents inconsistent phrasing, duplicates, and a skipped session. A
rigorously parsed, journal-page-cited vote database is therefore not a commodity — it's
a moat, and every "how did members vote" feature must treat vendor vote data as
provisional against the journal itself.

**2. House hearing video now carries harvestable auto-captions — the beginning of a
testimony-transcript corpus nobody else has.** Texas produces no official transcripts of
hearings or floor debate (confirmed via two law-library guides). But the House's HLS
streams embed WebVTT subtitle tracks (real timestamped ASR text, verified by fetching
.vtt segments), rolling out since ~Feb 2026 (~8% of 89R committee videos so far, trending
up). Combined with the House's undocumented, unauthenticated JSON API (committees,
meetings, video events, witness/minutes/comments URLs in one row — verified live), the
"what was actually said" layer is buildable: harvest free captions where present,
Whisper-class ASR for the rest, prioritized by relevance. The Senate states its stream is
the *only* copy of its hearings — no tape backup — so caching is preservation.

**3. The state destroys its own history; LobbyBook's immutable archive is itself the
product.** Verified instances: House member pages are overwritten on turnover (District
87's URL now shows only the successor; the predecessor's content survives only in
Wayback) · the SOS purges the Texas Register from its own site after ~1 year and its 2025
portal migration killed every legacy TAC deep link · TDP's canonical platform URL is a
live 404 · losing campaigns' domains decay to parking within ~18 months · Sunset
replaces report versions in place · journals' "FINAL" PDFs get silently regenerated
months later. And no state entity web-archives the Legislature's own site (TSLAC's TRAIL
covers executive agencies; legislative records belong to LRL, which runs no crawl) — the
Internet Archive is the de-facto preservation layer. Continuous capture-before-overwrite
jobs (member pages on election results, report stages on publication) are among the
highest-value scheduled tasks in the system.

**4. The compliance landscape is real and must be designed for, not around.** Named
AI-crawler blocks verified at: LRL (also disallows all PDFs sitewide, while exposing an
`exportproc.cfm` that proves an export mechanism exists), the Texas Democratic Party, the
AG's office, gov.texas.gov, and The Texan. capitol.texas.gov disallows `/TLODOCS/` (the
tree holding witness lists/minutes) and the TLC's policy page says it blocks
"legislative data services companies" that data-mine. TAMES (court records) is
`Disallow: /`. The correct posture: use the sanctioned channels that exist (TLO RSS,
House JSON API, TEC bulk ZIPs, UNT APIs, LegiScan), throttle and identify everywhere
else, and open licensing/access conversations with LRL, OCA (courts), and The Texan
rather than scraping into a ban.

**5. The famous bulk channel is half-dead; the sanctioned machine-readable surface is
richer than expected.** `ftp.legis.state.tx.us` — still named in TLO's own FAQ — is dead
over HTTP(S) (TLS reset / 503 verified); true-FTP status unverified from this
environment (OpenStates still cites live ftp:// XML paths — retest with a real FTP
client before ruling it out). Meanwhile the verified sanctioned surface includes: ten
live TLO RSS feeds, the House JSON API, journals' undocumented per-session JSON
day-indexes, TEC's nightly-rebuilt bulk ZIPs (1GB/9.13GB, fully documented schemas),
UNT's OAI-PMH/IIIF APIs for the complete 1976+ Texas Register and 1920s+ journals,
data.texas.gov's SODA API, TLC's redistricting CKAN portal, and LegiScan push
replication.

## The corpus findings

**6. HRO is the crown-jewel training corpus.** Born-digital and text-extractable across
the entire 1995–2026 range (even 1995 has a full text layer — no OCR anywhere), with a
rigid section structure whose SUPPORTERS SAY / OPPONENTS SAY blocks are ~30 years of
professionally written, pre-labeled stance arguments, plus named committee votes and
structured witness rosters per analysis. The SRC complement is version-stamped per bill
stage and includes a RULEMAKING AUTHORITY section that hooks directly into the
regulatory lineage graph.

**7. Witness lists are gold-standard stance labels at scale — and the entity-resolution
problem is the central investment.** Every registration is a real-world revealed
position (For/Against/On + registered-but-not-testifying), verified back to 1999. But
witnesses and organizations have no IDs anywhere ("Texas Right to Life" and "Texans for
Life" appear as different orgs in one document; "Self; Org" co-mingles), TEC donors are
free-text (verified same-company-two-spellings on adjacent rows), and rule commenters
and statement issuers are strings too. One shared person/org resolution layer feeds
every high-value feature: coalitions, money maps, warm paths, org footprints.

**8. The between-sessions paper trail is a published forecast of the next session.**
Interim charges (issued 10–14 months pre-session; 2026's monitoring charges explicitly
name the enacted bills under oversight) → interim reports (charge text reproduced
verbatim — a deterministic join, indexed by LRL back to 1846) → Sunset (per-
recommendation outcome labels: Adopted/Modified/Not Adopted, plus implementation status,
plus a review schedule published through 2036-37) → the Lt. Governor's priority-bill
lists and RPT's ranked legislative priorities. Charge→bill and recommendation→law
conversion rates are computable, published nowhere, and are the platform's headline
predictive features.

**9. Fiscal documents are version-scoped and deliberately un-joined.** A distinct
fiscal note exists for every bill version (verified: six for one bill), so citing "the
fiscal note" without a version code misstates numbers. And the fiscal lifecycle — LAR
request → GAA appropriation/rider → fiscal note → BRE/CRE certification — shares no IDs
across any documents; the description/amount matching layer that joins it is the
hardest and most defensible derived asset in the fiscal stack.

**10. TEC's bulk data is excellent and booby-trapped.** Nightly full rebuilds (no
deltas) with genuinely documented schemas — but campaign-finance flags superseded rows
in place (`infoOnlyFlag` + correction affidavits) while the lobby export silently drops
them; special-session/daily-pre-election tables exist specifically because naive
summing double-counts; registration client/compensation data has no bulk path at all
(PDF/Excel scraping); personal financial statements are not online, period; and local
(city/county/school) filers are entirely absent by design.

**11. Two brand-new courts are invisible to the standard legal-data supply chain.**
The 15th Court of Appeals and the Texas Business Court (operational since late 2024,
~100+ opinions with their own citation scheme) are absent from CourtListener. Daily
polling of two txcourts.gov listing pages makes LobbyBook a first mover on the corpus
covering statewide business/state litigation — precisely the cases lobbying clients
care about.

**12. Identifier traps are pervasive enough to be a product requirement.** Bill numbers
reuse across sessions and reset per called session; session codes (`89R`) span the
whole biennium including interim hearings a year after sine die; `GA-####` means an
Abbott AG opinion in 2002–14 and an Abbott executive order in 2015+; plank numbers
restart within every platform subsection every cycle; TAC text mutates silently; AG
opinions get overruled with an admittedly incomplete tracker; House district URLs are
aliases to whoever holds the seat. Session-scoped, version-scoped, role-scoped keys
aren't hygiene — they're the difference between a trustworthy product and a dangerous
one, and they're exactly where generic LLMs fail (see the benchmark's adversarial set).

## The opportunity findings

**13. The entity spine is solvable with existing pieces.** OpenStates people data (CC0,
cross-session stable) as the canonical person key, cross-walked to LRL memberIDs
(deepest history, verified dereferenceable), TEC 8-digit filer IDs, and LegiScan IDs;
LRL's complete 1846→2027 session list as the canonical session table (~180 static
rows); TLC plan codes for districts (already shared verbatim by three sources);
`(session, chamber, number)` for bills.

**14. Regulatory intelligence has a verified early-warning ladder.** Agency informal
drafts (TCEQ/TDI/HHSC pages, confirmed) → Register proposal (with statutory authority
naming the enacting bill — verified linkage) → adoption with named commenters and
per-comment agency responses → four-year rule reviews telegraphing rewrites. Register
TRD numbers + clean underline/strikethrough diff markup make the lifecycle
machine-parseable; adoption preambles are a commenter-influence dataset hiding in
plain sight.

**15. Governor appointments are a build-it-yourself patronage dataset.** ~1,500
appointments per four-year term exist only as individual press releases — no roster, no
database, not even an LRL document type. Reconstructed and joined to TEC giving, it's a
relationship-intelligence asset no one else has.

**16. Naturally labeled training data is abundant; generative fine-tuning is mostly
unnecessary.** The corpus yields free labels at scale — HRO stance pairs, witness
positions, TLO subject codes, amendment dispositions, journal action boilerplate,
Register proposal→outcome, Sunset recommendation→outcome, ORL exception citations,
endorsement lists — which fund extraction models, classifiers, and a domain reranker.
Facts stay in retrieval; the model learns Texas procedure and document genres, not
statuses.

**17. What no source provides: the connective tissue.** Every high-value question a
lobbyist actually asks — who should I call, who opposes this, is this from a Sunset rec,
where's the rulemaking, is this promise consistent with the record — requires joining
three to five of these corpora on entities and time. The state will never build that
join. That is the product.
