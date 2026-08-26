# Committee Records — minutes, witness lists, hearing notices, video & testimony

**Authority class:** A/B for structural facts (hearing occurred, position registered,
committee vote); C/D for testimony *content* (no official transcripts exist — only
ASR-derived text) · **Priority: Tier 0 (witness lists + minutes), Tier 1 (caption/ASR
pipeline)** · Verified by live inspection, Aug 2026.

## 1. Corpus & coverage

| Record type | Verified depth |
|---|---|
| Hearing notices/schedules | Session browser to 71R (1989); live notices posted today; pre-76R docs UNVERIFIED |
| Witness lists (per meeting) | HTML verified back to **76R (1999)** (`tlodocs/76R/witlistmtg/html/…`); current 89R PDF+HTML in parallel |
| Committee minutes | HTML verified to at least 80R (2007), likely earlier; **1973–1995 minutes/testimony exist only via LRL's physical "committee minutes project"** |
| House hearing video | Archive to **77R (2001–02)** — verified a published 12/03/02 video; live streaming via JSON API |
| Senate hearing A/V | "At least the 76th (1999–2000)" per the official page; **Senate states its stream is the ONLY copy — no tape/DVD backup** (preservation risk) |
| House public comments | Launched 87R (2021); current compiled PDFs verified |

- **⚠ capitol.texas.gov robots.txt disallows `/TLODOCS/`** — the exact tree hosting
  minutes/witness lists/notices/comments — and the TLC's file-download policy states it
  **blocks "legislative data services companies" that data-mine its servers.** A
  commercial pipeline is explicitly unwelcome at volume: throttle hard, identify a UA,
  route through legal review, and prefer the House JSON API where it duplicates content.
- `ftp.legis.state.tx.us` fully unreachable during this audit (HTTP 503, TLS reset,
  FTP timeout) — design a circuit breaker; per TLO's File Downloads page the FTP tree
  offers *bill-level* witness-list rollups (a different artifact from per-meeting
  witlistmtg docs — distinction UNVERIFIED until the host returns).

## 2. Native formats (verified)

- **Witness lists:** 1999 era = plain text in `<PRE>` HTML under FOR/AGAINST/ON headers;
  2025 era = born-digital PDF (clean pdftotext), **per-meeting multi-bill documents**
  sectioned by bill, rows like `Seago, John (Self; Texas Right to Life)` — "Self" and an
  org can co-occur in one field (entity-resolution wrinkle), plus a "Registering, but
  not testifying" section itself sub-split by For/Against/On.
- **Minutes:** born-digital HTML/PDF; quorum calls, motions, adjournment, and
  **committee roll-call votes with member names** when bills are reported (verified:
  "Ayes 6 (Anchia, Parker…); Nays 3 (Capriglione, Rogers, Slawson)"). Testimony is NOT
  summarized — minutes just point to the witness list.
- **Public comments:** compiled per-meeting PDFs are **count-only** in both samples
  ("HB 7 … (867 comments received)") — whether full comment text publishes anywhere is
  UNVERIFIED; don't assume comment text is minable.
- **House JSON API (undocumented, unauthenticated, CORS-open — confirmed live by
  decompiling the site bundle):** `GET /api/GetFiledBills` · `/api/GetVideoEvents`
  (live, with HLS videoUrl + captions boolean) ·
  `/api/GetVideoEvents/{session}/{called}/published/{type}` (archive, works back to
  /77/R) · `/api/getCommitteeMeetings/{session}/{chamber}/{committeeId}` — **returns
  notice, minutes, witness-list, handouts, AND public-comments URLs in one JSON row** ·
  `/api/getMemberBills/{id}`, `/api/getMemberCommittees/{id}`. Vendor appears to be
  Granicus (inferred from an endpoint name).
- **🔑 The headline discovery — harvestable auto-captions:** the House HLS master
  playlist for a completed hearing embeds an English **WebVTT subtitle track**; fetching
  `.vtt` segments returned real timestamped ASR text ("The chair calls Judge Angela
  Williams…"). It is machine-generated (visible ASR artifacts), unsupported/undocumented
  (videoUrl → master .m3u8 → subtitle .m3u8 → .vtt), and **recent + partial**:
  `captions:true` first appears ~Feb 2026 and covers only ~8% of 89R published committee
  videos so far — trending up, not retroactive. Senate confirms captions on live and
  archived video; VTT harvestability there UNVERIFIED.
- **No official transcripts exist** — confirmed via two independent law-library
  legislative-history guides ("no official transcription of either committee hearings or
  floor debates… commission a private entity").

## 3. What a lobbyist uses it for

*Who testified against HB 7 and which orgs backed them?* · *Who registered a position
without testifying?* (the quiet-signal list) · *How did the committee vote break down?* ·
*Who shows up on this issue session after session?* · *When is my hearing?* (RSS +
JSON API).

**Usefulness:** bill strategy HIGH · committee strategy HIGH (votes-by-member + swing
patterns) · session monitoring HIGH · client intelligence HIGH · opposition research
HIGH · issue research HIGH · meeting prep HIGH · coalition development HIGH
(For/Against groupings + registering-only lists) · political intelligence MED-HIGH ·
derived forecasting MED · historical research MED (solid to ~1999) · relationship MED ·
compliance MED · campaign LOW · fiscal LOW · regulatory LOW.

## 4. Ontology & native IDs

Committee (`C###`, e.g., C450 = House State Affairs; house.texas.gov numeric IDs appear
to match — inferred, not documented) · hearing (the `C###YYYYMMDDHHMM##` filename token —
a natural unique key) · bill (+ session) · **witness — NO native ID; free-text
name+city+org, the weakest-identified, highest-value entity in the family** ·
organization (free text, "Self" co-mingled) · position enum (For/Against/On/
Registering-not-testifying×{F/A/O}) · member (names in rolls; house member_bill_code as
a join key) · video event (numeric id, status live/published, type, CloudFront URL) ·
session code.

## 5. Edges

EXPLICIT: committee→held→hearing · hearing→considered→bill ·
person→testified_on{position}→bill@hearing · person→registered_only{position}→bill ·
member→voted{aye/nay}→bill (in committee, only when reported — "left pending" bills
never generate a vote record) · hearing→has→minutes/witness-list/video/comments (one
JSON row).
DERIVED: org→registered_position_on→bill (rollup of person rows sharing an org string —
the source records positions per *person*) · video→yields→caption transcript (HLS/VTT
walking).
INFERRED: person↔person identity across hearings/sessions (pure fuzzy matching; real
collision and fragmentation risk — "Texas Right to Life" vs "Texans for Life" appear as
*different* orgs on the same side in one list) · org↔org normalization.

## 6. Temporal semantics

Posting-vs-hearing lead time (statutory minimums; verified a 2-day in-session example) ·
comment compilations lag hearings ~2 days · **trap: session codes span the whole
biennium including the interim** — verified `89R`-labeled hearings in Aug 2026, 1+ year
after sine die; never map a session code to a calendar window · video `live`→`published`
transition kills the singular GetVideoEvent/{id} endpoint (404) — key on the plural
archive listing · one hearing can contain two outcomes for one bill (verified: failed
vote, then reconsidered and passed same meeting) · documents are "subject to revision"
post-posting — hash on re-fetch.

## 7. Authority

Structural facts (hearing, registration, position, vote tally): near-primary — state as
fact. Testimony *content* from captions: machine-generated, lossy, unofficial — always
labeled as ASR-derived attribution, never "the record says." Public comments: the source
itself disclaims editorial control — attributed opinion; only counts verified
harvestable. Plus the §1 compliance posture (robots + anti-data-mining policy) as a
standing operational constraint.

## 8. Ingestion

**Hybrid: House JSON API first, throttled tlodocs fetch for linked documents, HLS/VTT
walker for captions, RSS as the trigger.**
- Backfill: enumerate committee IDs per session (scrape committee lists — no
  "all committees ever" endpoint found) → getCommitteeMeetings per committee →
  fetch linked docs; video archive via the published listings back to 77R.
- Incremental: poll TLO RSS (`upcomingmeetingshouse/senate` — verified live) hourly in
  session, daily in interim; after each hearing date, poll for witness list (same/next
  day), minutes and comments (1–3 days).
- Dedup: the `C###YYYYMMDDHHMM##` token. Change detection: content hashes.
- **Transcription strategy: harvest free embedded VTT wherever captions:true; Whisper-
  class ASR as the fallback for the uncaptioned majority (all Senate, all pre-2026),
  prioritized by committee/bill relevance, cached aggressively — the Senate stream is
  the only copy in existence.**

## 9. Training value

**The headline natural-label pair of the audit: (bill text/caption, org) → registered
position {for/against/on}** — gold-labeled by real-world registration behavior at
scale, no annotation needed; invertible into "which orgs will oppose this bill" —
a differentiated LobbyBook model. Second pairing once ASR lands: caption snippet at a
witness's timestamp → registered position (training signal + alignment QA). Minutes'
formulaic language teaches Texas procedural vocabulary. Clean factual-recall evals
("how did committee Y vote on bill Z").

## 10. Derived intelligence

Witness networks (person↔org↔bill↔committee; recurring "super-witnesses") · recurring
coalitions (verified visible in one list: TRTL/Alliance for Life/Texans for Life
clustered For; Planned Parenthood/Texas Impact/medical associations Against) · org
appearance frequency by issue/committee · committee attention allocation ·
**mobilization-campaign detection** (spikes in registering-only volume or comment counts
— 867/1,879 in samples — quantify organized pushes as alerts) · swing-member analysis
from committee rolls.

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 5 | "Who's for/against my bill" is the core workflow |
| Uniqueness | 4 | Exists structured only here or resold by paid vendors |
| Authority | 4 | Primary structural record; testimony content is ASR-derived |
| Historical value | 3 | Digital to ~1999/2001; earlier is physical archive only |
| Current-session value | 5 | Live JSON API + RSS near-real-time |
| Structure quality | 4 | Consistent born-digital documents; free-text names, no witness IDs |
| Ingestion ease | 3 | JSON API is a gift; robots/ToS risk, flaky FTP, unsupported caption path |
| Entity richness | 3 | Committee/hearing/bill fine; the key entity (witness/org) unidentified |
| Relationship richness | 4 | Position-labeled edges + committee rolls are unusually rich |
| Training value | 4 | The stance-label pairing is genuinely strong |
| Retrieval value | 4 | Clean documents, minimal preprocessing |
| Derived intelligence | 5 | Coalitions, mobilization spikes, attention analytics |
| Moat potential | 3 | Public and resold; the moat is entity resolution + the caption pipeline |
