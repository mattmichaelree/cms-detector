# Texas Political Party Platforms (RPT · TDP · minor parties)

**Authority class:** C — official advocacy documents; citable verbatim with adoption
date, never as neutral fact or as any officeholder's personal position · **Priority:
Tier 2** · Verified by live inspection + Wayback CDX, Aug 2026.

## 1. Corpus & coverage

- **RPT (texasgop.org):** the deep, self-hosted corpus. The platform page lists 2026,
  2024, 2022 as native PDFs + 2020 as a Google Drive link (note: `/platform/` now
  301-redirects to `/official-documents-2/` — QA-verified; more evidence the party's
  URLs churn); older cycles only via Wayback
  (domain captures to **1997-12-24**; a 1998 platform existed as per-plank HTML pages).
  Convention drafts live on a separate `convention.texasgop.org` subdomain
  ("2024-TEMPORARY-Platform-FINAL.pdf") superseded by the permanent file on the main
  domain — a real draft-vs-final URL hazard. Biennial cadence (even-year conventions).
- **RPT Legislative Priorities** (the ~8 ranked priorities): confirmed cycles 2020,
  2024-25, 2026-28 (top-8 picked from 15 finalists at the June 2026 convention);
  **no 2022-23 cycle found — likely gap, UNVERIFIED.**
- **RPT censures:** no indexed list — found individually (e.g., the SREC's Oct 11,
  2025 concurrence with censures of Reps. Lambert, Orr, Patterson, VanDeaver, and
  former Speaker Phelan, with the ballot PDF).
- **TDP (texasdemocrats.org): the platform page is currently broken.** `/platform`
  returns a genuine 404 (verified via headers) while the party's own resources page
  still links to it; CDX shows it live 2022-09 → 2025-01, dead since. The 2022 and
  2024 platforms were partly published as **Google Docs** linked from convention recap
  posts — the platform of record has lived off the party's own domain. A 2014 platform
  survives on a Texas Tribune static mirror.
- **Minor parties:** LP Texas and Green Party platform pages are **Cloudflare
  JS-challenge-walled (403 cf-mitigated)** — unreachable to plain crawlers; content
  known only via snippets.
- robots: RPT fully open (Yoast sitemap, no RSS); **TDP explicitly blocks ClaudeBot,
  GPTBot, and ~25 other AI crawlers** (search indexing allowed) — a compliance
  constraint; rely on Wayback for that domain or seek permission.

## 2. Native formats (verified)

RPT finals: text-layer PDFs (2024 = 48 pp, clean pdftotext) at predictable
`/wp-content/uploads/{year}/{month}/` paths; a "searchable PDF" is advertised for 2026.
No HTML edition anymore. Priorities ship as short PDF handouts/ballot exhibits +
blog-post prose. TDP: HTML (dead) + live-editable Google Docs (**no fixed hash —
change detection must be content-diff, not hash**).

## 3. What a lobbyist uses it for

*Is my ask platform-aligned or platform-adverse for a Republican member?* (plank-to-
topic matching) · *Will voting against priority #4 draw a primary?* (priorities +
censure history — the RPT censure mechanism triggers real primary consequences) ·
*Has the party formally condemned anyone connected to my issue?* (verified example:
the 2024 platform's Resolution 3 condemns the House's Paxton impeachment by name).

**Usefulness:** political intelligence HIGH · campaign intelligence HIGH (censure =
electoral vulnerability) · forecasting HIGH (priorities are a stated next-session
push) · issue research HIGH (numbered positions across ~40 topic areas) · opposition
research HIGH (censures, named condemnations) · bill strategy HIGH
(aligned/adverse framing) · historical research HIGH (Wayback to 1997) · meeting prep
MED · coalition MED · client intelligence MED · session monitoring MED · fiscal
LOW-MED · relationship LOW · committee LOW · regulatory LOW · compliance NONE.

## 4. Ontology & native IDs

Party · platform (cycle-versioned) · section/subsection · **plank — numbered
CONTINUOUSLY 1→252 across every section and subsection, *not* restarting per
subsection (corrected during implementation; re-verified by font-geometry extraction
of the 2024 RPT PDF: 269 left-margin numbered items = Principles 1–10 + planks 1–252
+ Resolutions 1–7; the sequence returns to 1 exactly twice and only 1–10 ever repeat).
The durable ID must still be the compound {party, cycle, section, subsection, plank#},
never a bare "Plank 3" — because the three series collide with each other ("3" is a
principle, a plank and a resolution in the same document) and because subsection names
are not unique either: *Parents' Rights* appears as a subsection under BOTH Education
(p.15) and Health and Human Services (p.20)** · lettered sub-points · preamble ·
principles (a separate 1–10 list) · resolutions (separately numbered) · legislative
priorities (ranked, cycle-scoped) · censures (named legislators) · convention
committees (SD-level rosters in the PDF).
The PDF's keyword index maps to *page numbers*, not plank IDs.

## 5. Edges

EXPLICIT: party→adopted→platform{date, convention} · platform→contains→plank ·
party→adopted→resolution (named targets: RPT→condemns→Texas House {2023 impeachment};
RPT→supports→Paxton — verbatim in Resolution 3) · party→set→priority{rank, cycle} ·
SREC→censured→legislator {date}.
DERIVED: plank→section-heading topical grouping (coarse).
INFERRED: plank→states_position_on→normalized issue (NLP classification) ·
legislator vote→aligns/conflicts_with→plank (semantic matching — always shown as
inferred with both citations).

## 6. Temporal semantics

Platforms are explicitly cycle-scoped ("We, the 2024 Republican Party of Texas…") and
valid for the biennium until superseded. **Misinformation risks:** plank numbers are
cycle-scoped and renumber wholesale as planks are inserted or dropped between cycles —
"RPT Plank 3 says X" is meaningless without the cycle, and ambiguous even within one
cycle, since Principles, planks and Resolutions each carry their own "3" (cross-cycle
drift must be diffed on text, never inferred from numbering — not diffed this audit);
priorities are cycle-labeled and never evergreen; TDP's dead canonical URL means cached
copies can go silently stale with nothing live to diff against.

## 7. Authority

Class C. LobbyBook CAN state: "The RPT's 2024 platform, adopted June 7, 2024, contains
a plank stating [verbatim]." It MUST NEVER render that as "Texas Republicans believe
X," as current law, or as any individual officeholder's position — platforms are base
documents officeholders routinely deviate from.

## 8. Ingestion

Scheduled crawler keyed to convention cycles (trigger ~June of even years; 2024's
platform posted ~a week post-convention) + event-triggered watches for censures
(SREC-meeting-driven) and priority announcements. Dedup: {party, doc type, cycle,
sha256(pdf)} for RPT; content-diff for TDP Google Docs. Wayback backfill essential for
TDP (recover the dead /platform) and pre-2020 RPT. Failure modes (all observed): TDP's
live 404; the temporary-vs-permanent RPT subdomain split (don't index a
"TEMPORARY-FINAL" draft as canonical); Cloudflare walls on minor parties; TDP's
AI-crawler robots block.

## 9. Training value

Retrieval + weak-label classification: (plank text → section/subsection heading) as a
topic classifier; (resolution text → named target entities) as clean NER/relation
extraction examples. Not instruction material (manifesto prose); not an eval source
beyond verbatim lookup.

## 10. Derived intelligence

**Platform-alignment score per bill** (semantic match to nearest planks, cycle-scoped) ·
**primary-challenge-risk score** (censure status + priority-vote history — external
demand validated: Texas Scorecard's live "Consensus Priorities Project" already scores
legislators against RPT-adjacent priorities) · priority-vs-outcome conversion per
session · plank-drift diffs across cycles (rigorous alternative to trusting plank
numbers).

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 4 | Strong political/campaign intelligence; weak on bill mechanics |
| Uniqueness | 3 | Text is public and press-tracked; the edge is structuring |
| Authority | 4 | Verbatim primary source for what the party adopted (partisan by nature) |
| Historical value | 5 | Wayback to 1997/2002 + native PDFs |
| Current-session value | 3 | Biennial/static; priorities partially compensate |
| Structure quality | 3 | RPT clean; TDP broken link + Google Doc dependency |
| Ingestion ease | 3 | PDFs parse fine; numbering, Cloudflare, and robots friction |
| Entity richness | 4 | Planks, resolutions, priorities, censures, committees |
| Relationship richness | 3 | Censure/resolution edges explicit; plank→issue inferred |
| Training value | 3 | Weak-label topic classification |
| Retrieval value | 4 | Excellent "does the platform say X" RAG |
| Derived intelligence | 5 | Alignment + primary-risk scoring is proven-demanded |
| Moat potential | 2 | Raw text mirrored elsewhere; moat is linkage, not access |
