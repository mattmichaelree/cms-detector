# Legislator Press Releases, Newsletters & Official Statements

**Authority class:** C — official self-advocacy; quote verbatim with date and URL,
never as objective account or future-vote prediction · **Priority: Tier 1 — the
real-time positioning layer, and the source that destroys its own history** · Verified
by live inspection, Aug 2026.

## 1. Corpus & coverage

- **House (house.texas.gov):** member pages at both numeric person IDs
  (`/members/2825`) and district-number aliases (`/members/87`), with Profile/
  Legislation/Committees/**Newsletters**/**Media** tabs. **The content-destruction
  problem verified concretely:** District 87's URL now shows only Rep. Caroline Fairly;
  her predecessor Four Price (through Jan 2025) appears nowhere — the district slot is
  reassigned, not archived; only Wayback retains the prior content. No cross-member
  press feed exists (candidate URLs 404); the site is a Laravel/JS stack whose listings
  are under-indexed by search engines — naive scraping under-collects. robots open, no
  sitemap.
- **Senate (senate.texas.gov): materially deeper and more crawlable.** General newsroom
  archive with a **year dropdown 1997–2025**; dated items (`news.php?id=20250225a`);
  **per-senator press rooms** (`pressroom.php?d=7` — Bettencourt's archive runs
  2015-02-10 → 2026-08-19); per-senator **newsletter PDF archives**
  (`newsletters.php?d=7`) — with confirmed per-year holes (no 2016, 2018–22, or 2024
  newsletters for the same senator; looks like non-publication, not crawl failure).
- **Caucuses:** House Democratic Caucus press page verified (2025-01 → 2026-07);
  House Republican Caucus has a news section (2025 items verified); Freedom Caucus blog
  thin (latest surfaced: Apr 2023); MALC press link exists (archive unverified);
  **Texas Legislative Black Caucus has no self-hosted statement archive at all — its
  public presence is effectively social media.**
- **Statewide newsrooms:** Lt. Governor (ltgov.texas.gov/news — interim charges, joint
  statements, and the "Top 40 priority bills" posts; WordPress date-path permalinks);
  AG (listing driven by a client-side Cludo search widget — plain HTML fetch shows no
  items; robots blocks AI crawlers by name); **Comptroller — the best-structured:
  date-range filtering, archive to ≥2022, verified RSS + GovDelivery + a Spanish feed.**
- **RSS exists nowhere in this family except the Comptroller** (checked: House
  redirects home, Senate 404s, others unadvertised).
- **Social media is the de-facto statement channel**, especially for thin caucuses.
  X API pricing now pay-per-use (~$0.015/post write, $0.005/read; legacy tiers
  sunsetting; Enterprise ~$42k/mo — third-party-sourced, directionally reliable).
  ProPublica's Politwoops is **frozen (~2012–2023 deletions only)** — historical, not
  live.

## 2. Native formats

HTML posts everywhere; Senate newsletters PDF. Senate uses compound native IDs
(`7-20250530a` = district+date+intraday letter) — a gift; House has no confirmed
stable per-release ID (a tested ID was already dead). AG requires headless rendering
or reverse-engineering the Cludo API.

## 3. What a lobbyist uses it for

*Has this legislator publicly taken a position on my bill?* · *What does the Lt. Gov.
say his priorities are?* (the Top-40 list answers directly) · *What did the departed
member say before leaving?* (House: often unrecoverable without Wayback — verified).

**Usefulness:** current-session positioning HIGH (the real-time political-pulse layer) ·
session monitoring HIGH · bill strategy HIGH (know the stated stance before the ask) ·
political intelligence HIGH · opposition research HIGH (the statement trail is the
accountability record) · campaign intelligence HIGH (releases are live campaign
messaging) · meeting prep HIGH · relationship MED-HIGH (co-signed statements) ·
forecasting MED (priority lists) · coalition MED · committee MED (chair statements,
unorganized) · client intelligence MED · issue research MED · regulatory LOW-MED ·
historical LOW-MED (destruction problem) · fiscal LOW · compliance NONE.

## 4. Ontology & native IDs

Legislator · statewide official · caucus (partisan/identity/ideological) · statement
(dated, titled) · newsletter (distinct constituent-facing type) · interim charge (a
distinct Lt.-Gov-issued entity) · priority-bill list (ranked, named-bill entity).
**Critical modeling trap: the House district-number URL is an alias to whoever
currently holds the seat — model as district→currently_held_by→legislator, never as a
person key; pin statements to person IDs.**

## 5. Edges

EXPLICIT: legislator→issued→statement {date} · caucus→issued→joint_statement→
co_signed_by→legislators · lt_gov→announced→priority_list→ranks→bills ·
legislator→member_of→caucus (rosters) · district→currently_held_by→legislator
(time-varying — and the source itself fails to preserve the prior edge on turnover).
INFERRED: **legislator→stated_position_on→issue {stance} — the core value-add, and it
is an NLP inference: always carry the exact source sentence, never present extraction
as verbatim.**

## 6. Temporal semantics

Every statement is a point-in-time position. Verified misinformation mechanism: the
same URL silently becomes a different person's content (District 87) — a system
re-resolving cached content against live URLs mis-attributes or loses provenance.
Every ingested statement needs hard `published_at` + `captured_at` and person-ID
pinning. Statements also routinely predate committee substitutes that change the bill
they discuss — pair statement dates with bill-version timelines.

## 7. Authority

Class C. CAN state: "On [date], Senator X's office published a statement saying
[verbatim], sourced [URL]." MUST NOT present a release's framing as an objective
account of a bill or as a vote prediction. Statewide newsrooms carry institutional
weight but remain PR-framed (AG releases styled as victories) — same C-class handling.

## 8. Ingestion

Per-entity scheduled crawlers for ~181 member pages + caucus sites + 3 newsrooms
(no central feed exists). Cadence: daily; session-hours frequency in session.
Dedup: {office, native ID or URL, content hash}. **The single highest-value scheduled
job in the family: on every known officeholder-turnover event (election results are
known in advance), immediately archive the outgoing member's pages before the
overwrite** — plus continuous Wayback backfill for the House. Failure modes (all
observed): dead House release IDs, JS-driven listings, Cludo-gated AG newsroom,
named-bot robots blocks (AG), per-senator newsletter holes.

## 9. Training value

Retrieval + stance/topic classification (headlines often self-declare topics — natural
weak labels). Consistency evals ("did the later vote match the earlier stated
position") are constructible and valuable. Weak instruction material (promotional
prose).

## 10. Derived intelligence

Position-change detection (same actor + issue, divergent stances, both citations) ·
priority-vs-outcome conversion (did the Top-40 pass — directly checkable) · **issue
ownership by legislator** (statement share per topic) · statement-velocity spikes as a
precursor to floor action · co-signature relationship graphs. All downstream of
solving the ingestion problem — which is exactly why it's a moat.

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 4 | Core "what has this member said" workflow |
| Uniqueness | 4 | Public but so fragmented nobody aggregates it well |
| Authority | 4 | Official primary statements, self-serving framing |
| Historical value | 2 | Verified content destruction on turnover; Wayback-dependent |
| Current-session value | 5 | The real-time positioning layer LobbyBook needs most |
| Structure quality | 2 | ~190 offices, no shared schema, JS-driven House |
| Ingestion ease | 2 | No central feed, near-zero RSS, dead IDs, bot blocks |
| Entity richness | 4 | Statements, caucuses, priority lists, interim charges |
| Relationship richness | 4 | Co-signatures + caucus membership are real explicit edges |
| Training value | 3 | Stance/topic labels; weak instruction value |
| Retrieval value | 4 | High-value RAG once ingested |
| Derived intelligence | 4 | Position-change + issue-ownership + priority conversion |
| Moat potential | 4 | The sources destroy their own history — a continuously captured corpus is nearly impossible to reconstruct retroactively |
