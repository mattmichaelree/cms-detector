# Texas Political / Government News

**Authority class:** E (journalism) with a hard C/E classification problem for advocacy
media — score per-outlet, never as a family · **Priority: Tier 1 (metadata/feeds), full
text license-gated** · Verified by live inspection, Aug 2026.

## 1. Corpus & coverage (verified per outlet)

- **Texas Tribune** — the anchor corpus: sitemap index with 12 numbered post-sitemaps
  spanning 2010 (site launched Nov 2009) through `lastmod: 2026-08-25`; Google News
  sitemap confirms same-day publication; **live RSS 2.0 feed verified**
  (`https://feeds.texastribune.org/feeds/main/`: dc:creator bylines, pubDate, multiple
  category tags, guid, hourly update frequency). One of the cleanest dated
  digital-native political corpora in Texas. Republishing is free CC-style with canonical
  URL + tracking pixel (search-sourced; the /republish/ page itself 403'd — UNVERIFIED by
  fetch). No bulk API — sitemap+RSS is the sanctioned path.
- **Texas Monthly** — 403'd every fetch (paywall/bot protection); the biennial Best/Worst
  Legislators franchise is real (2023 names corroborated) but mechanics UNVERIFIED.
- **Quorum Report** — $325/yr subscription insider tipsheet, online since 1998
  (search-sourced, UNVERIFIED by fetch). **Capitol Inside** reachable; subscription.
- **The Texan (thetexan.news)** — robots.txt verified: **explicitly disallows essentially
  every named AI/LLM crawler** (GPTBot, ClaudeBot, anthropic-ai, CCBot, PerplexityBot,
  Google-Extended, Bytespider…) while allowing search crawlers; year-sharded TownNews
  sitemaps 2019→2025. Treat as a licensing conversation, not a scraping target.
- **Texas Scorecard** — standard WordPress robots (no AI blocks); sitemaps from Jan 2019
  (the Empower Texans rebrand) through `lastmod: 2026-08-26`.
- **Texas Observer** — robots verified (crawl-delay 10, sitemap present). **KUT, DMN,
  Houston Chronicle, Statesman, Spectrum** — reachable; paywall specifics untested this
  session.
- **Bulk discovery layers:** GDELT verified (Event DB 1979→, GKG entity/theme extraction
  Apr 2013→, 2.0 updates every 15 min; free CSV/BigQuery) — **metadata/entities, not
  full text**. Common Crawl index host unreachable from this environment
  (UNVERIFIED-due-to-network, not presumed down).

## 2. Native formats

Tribune: RSS 2.0 + clean sitemaps + WordPress guid IDs. The Texan/Scorecard/Observer:
standard CMS sitemap indexes (RSS presence unchecked). GDELT: tab-delimited CSV/
BigQuery with native `GLOBALEVENTID`/`GKGRECORDID`. **Copyright line:** store full text
only where licensed (Tribune's republish grant); for paywalled outlets store
headline+URL+snippet+pubDate and link out. GDELT/Common Crawl solve discovery, not
full-text storage.

## 3. What a lobbyist uses it for

*What does the press think the controversy is?* · *Is my member getting hammered or
praised?* (Best/Worst) · *What's the insider chatter?* (Quorum Report/Capitol Inside —
exactly the paywalled tipsheet function) · *Is this outlet reporting or campaigning?*
(the Scorecard/Texan classification problem).

**Usefulness:** session monitoring HIGH (same-day feeds) · political intelligence HIGH ·
bill strategy HIGH (coalition dynamics + floor drama surface here first) · issue
research HIGH · historical research HIGH (Tribune 2010+) · meeting prep HIGH ("what's
the narrative on this member") · retrieval-grounding HIGH · regulatory monitoring MED ·
forecasting MED (reporters' whip-count reads) · fiscal MED · client intelligence MED ·
campaign intelligence MED · committee MED · relationship MED (reporter/beat patterns) ·
opposition MED · coalition LOW-MED · compliance LOW.

## 4. Ontology & native IDs

Story (headline, URL, pubDate, bylines, categories, outlet) · outlet (**typed with
authority_class + ownership + business model** — the load-bearing field) · reporter ·
newsletter · scorecard entry (Best/Worst → legislator × verdict × year) · GDELT
event/GKG records (native IDs) · Tribune WordPress guids.

## 5. Edges

EXPLICIT: story→published_by→outlet · story→written_by→reporter (dc:creator verified) ·
story→tagged→category (live examples: "Courts," "Attorney General's Office," "Ken
Paxton") · scorecard→rates→legislator · story→republished_by→outlet (where the
canonical/pixel convention is honored).
DERIVED: story→discusses→person/bill/agency (NER; GDELT does a cheap first pass at
scale) · republish detection via text similarity.
INFERRED: outlet→authority_class (editorial judgment — see §7) · reporter→covers_beat.

## 6. Temporal semantics

pubDate is the best-behaved timestamp in the whole audit. The risk is **staleness and
correction drift**, not link death: a 2023 story about a bill's status is frozen at that
moment — never present as current without "as of"; corrections may not reach an ingested
copy. The three-way check (campaign claim × official record × contemporaneous coverage)
is a LobbyBook-native capability no single source provides.

## 7. Authority — the classification problem

E: Tribune, Observer, KUT, Spectrum, the dailies, Texas Monthly. **C-behind-E:** Texas
Scorecard is organizationally the news arm of the Empower Texans Foundation
(501(c)(3)), linked to the (c)(4) and PAC (verified via multiple trackers) — attribute
as "Texas Scorecard, published by the Empower Texans Foundation." The Texan presents as
straight news, is professionally staffed, widely characterized as
conservative-oriented. **Rule: never assign class E by reputation — verify each
outlet's corporate structure and disclose advocacy linkage in the attribution string.**

## 8. Ingestion

Feed listener (Tribune RSS hourly + Google News sitemap) · sitemap-diff crawler for
non-RSS outlets (poll sitemap lastmod, fetch new URLs) · GDELT daily/15-min pull as
discovery/cross-validation, not text · paywall-aware fetcher (full text only where
licensed; metadata+link otherwise). Dedup: (outlet, canonical URL) + story hash for
republish detection. Failure modes observed: hard 403s to non-browser fetchers
(Tribune subpages, Texas Monthly), The Texan's policy-level AI ban (resolve with the
publisher, don't route around).

## 9. Training value

Retrieval + classification (outlet→authority class; story→issue tags with RSS
categories as free labels). Full-text instruction/eval use is capped by the same
copyright constraint — don't train on text you shouldn't store.

## 10. Derived intelligence

Narrative tracking (cluster stories per issue across outlets; GDELT first pass) ·
coverage-volume spikes as salience/leading indicator for floor fights · the
**advocacy-vs-journalism framing gap** on the same vote as a surfaced signal ·
cross-family fusion: stories quoting campaign promises feed the promise-consistency
pipeline.

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 5 | Daily working tool for narrative/session intelligence |
| Uniqueness | 3 | The TX outlet mix is the value-add, not aggregation |
| Authority | 3 | Mixed by design — must be scored per-outlet |
| Historical value | 4 | Tribune's verified 2010+ depth |
| Current-session value | 5 | Same-day RSS/sitemap freshness verified |
| Structure quality | 4 | Clean RSS/sitemaps where present |
| Ingestion ease | 3 | Tribune easy; bot blocks + a policy-level AI ban elsewhere |
| Entity richness | 3 | Thinner ontology than disclosure sources |
| Relationship richness | 3 | Mostly NER-derived |
| Training value | 3 | Retrieval/classification; copyright-capped |
| Retrieval value | 5 | The best narrative-grounding source in the audit |
| Derived intelligence | 4 | Narrative tracking + framing-gap analysis |
| Moat potential | 3 | Feeds are replicable; the fusion with campaign/official records is the moat |
