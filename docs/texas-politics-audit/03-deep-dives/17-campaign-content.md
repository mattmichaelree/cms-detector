# Campaign Content — websites, ads, endorsements, questionnaires, mailers

**Authority class:** C (campaign/advocacy claims — attribute everything by name) ·
**Priority: Tier 2** · Verified by live inspection + Wayback CDX depth tests, Aug 2026.

## 1. Corpus & coverage

**Campaign-site lifecycle — empirically demonstrated on three real TX legislative
domains via the Wayback CDX API:**
- Winning/continuing candidate (jamestalarico.com, HD50→2026 US Senate): continuous
  full-content captures every year 2017→2026.
- Candidate who dropped out (beverlypowell.com, SD10): last full capture is the exact
  day she ended her campaign (Apr 6, 2022); every later capture is a redirect; **the
  live domain today resolves to HugeDomains — resold to a parker.**
- Losing candidate (averieforall.com, HD112 2024): full captures continue ~5 months past
  the loss, then 404s from mid-2025; live fetch today returns 503.

**Conclusion:** losing campaigns decay on a predictable curve (live → orphaned → 404 →
resold) within ~8–18 months. **No systematic public archive of Texas legislative
campaign sites exists** — Ballotpedia/Vote Smart/LRL link to *live* URLs (LRL's Powell
link now points at the parked domain). Wayback is the only backstop, and its capture
cadence is uneven — LobbyBook must crawl live sites itself each cycle.

**Ad libraries:** Meta Ad Library reachable but 403s all non-browser fetches — official
API only (ID-verified developer access; creative, bucketed spend/impressions,
demo/geo targeting, disclaimer, dates). **Google's political-ads data is a public
BigQuery dataset** (`creative_stats`: advertiser_name/id, ad_id, targeting, bucketed
impressions; 2018+, 7-year retention — verified via Google Cloud docs). FCC OPIF
(publicfiles.fcc.gov): political files cover **every** candidate request for broadcast
time (47 CFR §73.1943, verified) — but per-station scanned PDFs inside a JS SPA, no
cross-station search, and **no coverage of cable-only/streaming/digital**, which is
where modern state-race money increasingly goes. AdImpact is the commercial answer.

**Endorsements/questionnaires (verified):** Texas Right to Life PAC endorsement tool
live (segmented by office level, currently 2026 cycle — **prior cycles vanish from the
live site**; Wayback/Ballotpedia hold history); Ballotpedia per-candidate endorsement
sections + per-org roll-up pages (`Endorsements_by_Texas_Right_to_Life_PAC`); TLR PAC's
own record page (68/68 contested-House-race wins claimed for 2024); iVoterGuide's 2024
TX legislative questionnaire PDF is a citable artifact. texasvalues.org reset every
connection (UNVERIFIED). Vote411 TX guide search-sourced (UNVERIFIED by fetch).

**Mailers/opposition research — the stated gap:** no public archive of direct mail,
robocalls, or oppo documents exists anywhere. Occasional pieces surface in news photos.
Treat as a known-unknown; never imply completeness.

## 2. Native formats

Campaign sites: unstructured builder HTML (Wix/Squarespace/NationBuilder asset paths
visible in CDX digests), no RSS/APIs. Meta: API-only. Google: BigQuery SQL. FCC:
scanned PDFs in an un-automatable SPA. Endorsement/questionnaire pages: server-rendered
HTML, no bulk exports.

## 3. What a lobbyist uses it for

*What did this member promise voters?* · *Who backs them — and who dropped them?* ·
*Is my issue on their re-election radar?* (ad keywords/targeting) · *How did
TLR/TRTL/TSTA score them going into session?* — the raw material for the
promise-vs-record ledger and primary-threat analysis.

**Usefulness:** political intelligence HIGH · campaign intelligence HIGH · meeting prep
HIGH ("what did they run on" is a top-3 prep question) · coalition development HIGH
(endorsement networks) · relationship intelligence HIGH · opposition research MED-HIGH
(minus the mailer gap) · bill strategy MED ("you campaigned on X" leverage) · client
intelligence MED · issue research MED · historical research MED (lossy) · forecasting
MED (primary-threat signals) · compliance LOW-MED (FCC files, broadcast only) · fiscal
LOW · session monitoring LOW · committee LOW · regulatory NONE.

## 4. Ontology & native IDs

Candidate · campaign (domain, cycle, **status: active/ended/orphaned/parked**) ·
campaign page (URL, capture date, content hash) · ad (Meta `ad_archive_id`, Google
`advertiser_id`/`ad_id`; bucketed spend/impressions, targeting, disclaimer) ·
endorsement (org × candidate × cycle) · org (typed advocacy/PAC/nonpartisan) ·
position/promise (text, issue, source page, date) · survey response · broadcast station
(FCC `facility_id`) · political-file record · Ballotpedia candidate slugs.

## 5. Edges

EXPLICIT: candidate→ran_in→race · org→endorsed→candidate {cycle} ·
ad→sponsored_by→candidate/org (disclaimer field) · candidate→scored_by→org (surveys).
DERIVED: candidate→promised→position (NLP over site text) · ad→attacks/promotes→
candidate (creative NLP) · campaign→went_dark→date (CDX status transitions — the
demonstrated 200→404→parked signal).
INFERRED: coalition peers via shared endorsers · promise_kept/broken (cross-family join
against votes — always presented as documented comparison).

## 6. Temporal semantics

Everything is **cycle-scoped with silently expiring validity**: a 2022 position is not a
2026 position; live endorsement pages show only the current cycle; **dead campaign URLs
actively mislead** (two of three tested domains now resolve to a reseller and a dead
server). Rules: timestamp every claim with capture date + applicable cycle; never
resolve a stored campaign URL live without checking Wayback first.

## 7. Authority

Class C throughout — self-interested by design (campaign sites), advertiser-self-
disclosed (ad libraries), agenda-carrying orgs (TRTL/TLR/TSTA/TAB), aligned voter
guides (iVoterGuide/Texas Values) vs. charter-nonpartisan civic guides (LWV/Vote411 —
still C, not journalism). **Attribute every claim to its issuer by name; never launder
a promise or a rating into neutral-voiced fact.**

## 8. Ingestion

(1) **Discovery layer** each cycle: seed candidate domain lists from filings,
Ballotpedia, endorsement rolls. (2) **Live crawler**: weekly in the final 90 days,
monthly otherwise — don't rely on Wayback's uneven cadence. (3) **Wayback CDX
backfill**: paginate with `limit`+`resumeKey` (unbounded queries reset — observed);
CDX `digest` gives content-hash dedup free. (4) **Ad APIs**: Meta official API +
Google BigQuery daily. (5) **FCC OPIF**: manual spot-checks or AdImpact budget line —
not automatable today. Dedup: (domain, normalized URL, content hash). Change detection:
hash diffs + specifically flag `200→404` and `200→30x-to-external` transitions (the
campaign-ended signals). Failure modes: bot-hardening everywhere (403s/resets
confirmed), JS-only FCC SPA, domain resale poisoning stored links.

## 9. Training value

Retrieval + classification. Endorsement lists are near-perfect natural labels
(org × candidate → endorsed, with org lean as a feature) for alignment classifiers; ad
targeting metadata feeds "who is this campaign reaching" models. Weak for instruction
tuning (persuasive prose) and eval (no clean ground truth).

## 10. Derived intelligence

Promise-vs-vote ledger (with legislative records) · endorsement network graphs across
cycles · **primary-threat index** (an incumbent losing a historically reliable
endorsement is an early vulnerability signal) · campaign-site decay as an
"is this person still politically active" pruning signal.

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 4 | Direct answers to promises/backers |
| Uniqueness | 4 | Nobody systematically archives TX campaign sites |
| Authority | 2 | All class C, self-interested by design |
| Historical value | 3 | Good where captured; demonstrably lossy |
| Current-session value | 2 | Cycle-bound, stale mid-session |
| Structure quality | 2 | Unstructured builder HTML, few APIs |
| Ingestion ease | 2 | Bot-hardening, JS SPAs, flaky CDX |
| Entity richness | 3 | Candidates/orgs/endorsements/ads well-formed |
| Relationship richness | 4 | Endorsement graphs directly usable |
| Training value | 3 | Strong classification labels, weak otherwise |
| Retrieval value | 4 | High-value grounding for campaign history |
| Derived intelligence | 4 | Promise tracking + coalition graphs are novel |
| Moat potential | 4 | Live-crawl + Wayback backfill + endorsement graph is expensive to replicate |
