# Texas Attorney General Opinions + Open-Records Rulings

**Authority class:** persuasive official legal analysis — "highly persuasive and
entitled to great weight; however, the ultimate determination… is left to the courts"
(the office's own framing, quoted verbatim) · **Priority: Tier 2** · Verified by live
inspection, Aug 2026.

## 1. Corpus & coverage

- **Opinions digitized to 1939, individually addressable.** The index publishes the
  complete numbering ledger by administration: O- (Mann, 1939–43) → V- → S- → WW- → C- →
  M- → H- → MW- → JM- → DM- → JC- (Cornyn) → GA- (Abbott-as-AG, 2002–14) → KP-
  (Paxton, KP-0001–KP-0524 live at audit) plus provisional JS-/AC- series. Even a 1943
  opinion resolves to a stable canonical URL with its own PDF.
- **Opinion requests (RQ-) — forward-looking intelligence — only go back to 1998
  online** ("prior to 1998, please file a Public Information Act request" — verbatim).
  Pending requests publish the full requestor letter *before* any answer exists.
- **Open Records Decisions (ORD-001…ORD-688):** the small, citable-as-precedent tier —
  and **no ORD has issued since June 2014**; zero Paxton-era ORDs (a verified corpus
  gap for open-records precedent).
- **Open Records Letter Rulings (ORLs):** the huge non-precedential tier — "more than
  40,000… issued in 2023" alone; legacy static archive spans 1989→2023
  (or2023-43569); **since Dec 21, 2023 (HB 3033), new ORLs live in a Salesforce "PIA
  Database" portal** — a JS shell to plain GETs; API/bulk existence UNVERIFIED.
- **Subject index:** a large controlled-vocabulary taxonomy at /opinions/categories.
- **Supersession tracker:** a maintained but self-admittedly incomplete
  overruled/modified/withdrawn list (live examples: "KP-0326 Overruled by HB 1118,
  87th Leg."; "GA-0615 Overruled by Van Houten v. City of Fort Worth (5th Cir.
  2016)").
- Platform: modern Drupal + a legacy www2 host coexist (migration artifact). Sitemap
  present. **robots.txt names ClaudeBot/ChatGPT/Perplexity/Bytespider for blocking**;
  generic automated fetchers got HTTP 402 while browser-UA requests succeeded — bot
  mitigation fingerprints tooling, not access generally.

## 2. Native formats (verified by fetch)

1943 opinion: scanned + 1998-era OCR (garbled text). 2026 opinion KP-0524: born-digital
tagged PDF, clean text, **cites its own request "(RQ-0518-KP)" in the Re: line** (the
explicit request↔opinion join). Pending RQ letters: born-digital PDFs with requestor
text + Opinion-Committee intake stamp. ORLs: born-digital one-page memoranda citing the
specific PIA exception. No RSS/bulk/API for opinions; the legacy ORL index's search is
literally a Google Custom Search box.

## 3. What a lobbyist uses it for

Verified live examples: *agency authority* (KP-0523 — whether the Chiropractic Board
can adopt a needle rule); *pending threats* (RQ-0646-KP — Senate Business & Commerce
asking about municipal authority over residential energy backup systems, published
before any answer); *local friction seeding future bills* (RQ-0651-KP — a county
auditor's purchasing dispute).

**Usefulness:** issue research HIGH · historical research HIGH (to 1939) · compliance
HIGH (ORLs are PIA compliance rulings) · regulatory monitoring HIGH (agency-authority
opinions) · session monitoring HIGH (pending RQs are live, named, forward-looking) ·
bill strategy HIGH · forecasting MED (pending RQs) · opposition research MED (who
requested a damaging opinion is on the record) · committee strategy MED
(committee-sourced RQs) · client intelligence MED · meeting prep MED · political
intelligence LOW-MED · relationship LOW · coalition LOW · fiscal LOW · campaign NONE.

## 4. Ontology & native IDs

Opinion (AG-initials + zero-padded number — **`GA-####` collides with
Governor-Abbott executive orders `GA-##`: same person, two roles; disambiguate by
entity type + date range**) · request (`RQ-####-XX`) · ORD (`ORD-###`, closed corpus) ·
ORL (`or{YYYY}{5-digit}`) · requestor (free-text office/title — no stable ID; an
entity-resolution gap) · statute citations · subject-taxonomy terms.

## 5. Edges

EXPLICIT: official→requested→RQ (named on letter + index) · RQ→answered_by→opinion
(cited inside the opinion PDF) · opinion→interprets→statute (section cites) ·
opinion→superseded_by→statute|case (the overruled list — explicit but incomplete) ·
opinion→classified_under→subject · ORL→cites_exception→PIA § ·
governmental_body→subject_of→ORL.
DERIVED: requestor-office→pattern_of_requesting→subject (aggregation).
INFERRED: opinion topic→preceded→legislation (correlational; needs bill-text matching).

## 6. Temporal semantics

Request→opinion gaps run months-to-years; a sampled RQ letter was internally dated
May 2025 but intake-stamped Aug 2026 — **trust the stamp, not the letter body**.
**Supersession is the misinformation hazard:** the office's own overruled list
disclaims completeness — LobbyBook needs its own statute/case change detection layered
on top and must badge every opinion "persuasive, not binding" + "later overruled?"
status. The ORD dead-corpus means current open-records questions resolve against
pre-2014 precedent or non-precedential ORLs — a real gap, not an ingestion bug.
Opinions can also be withdrawn post-publication (observed "Withdrawn 1/14/08").

## 7. Authority

Opinions: persuasive official analysis (class C on the task's political scale is wrong
here — treat as **B-official-analysis with legal weight**, below courts and statutes).
ORDs: same tier, citable as precedent to the Open Records Division. ORLs: explicitly
non-precedential, case-specific. RQ letters: evidentiary record only, no authority.

## 8. Ingestion

Two-track scrape: Drupal opinion/request indexes + per-PDF (bounded backfill to 1939);
legacy www2 ORL index by (AG code, year) + a to-be-solved headless pull of the
Salesforce PIA portal for post-2023 ORLs. Incremental: daily poll of /opinions +
pending-requests (email subscription as push backup); ORLs weekly (40k/yr volume).
Dedup: native numbers (ORLs by full `or{year}{seq}`). Change detection: diff the
overruled/withdrawn list, not just new numbers. Failure modes: 402 bot-mitigation
against tool-fingerprinted fetchers (use a browser-like path, respect the named-bot
robots policy — licensing conversation where needed); the RQ browse index renders
empty without JS (use the per-administration numbered pages).

## 9. Training value

Opinions have a clean **Question Presented → analysis → Conclusion** structure:
strong retrieval; strong classification (subject taxonomy = free labels; **ORLs are
near-perfect exception-classification data at 40k/year scale** — one exception per
ruling, boilerplate structure). Instruction value moderate and narrow (Texas
government-law Q&A, not general legal reasoning). **Eval caution: opinions get
overruled — a static eval can silently reward legally stale answers.**

## 10. Derived intelligence

Requestor-office × subject trends → early warning of where legal friction (and future
bills) originate · frequency of an agency's authority being questioned → pressure
indicator · overruled-list × bill text → "opinion invalidated by statute X" pipeline
(who successfully legislated around an adverse opinion) · ORL exception-citation
frequency per governmental body → agency transparency-posture scoring.

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 4 | Pending RQs + agency-authority opinions are directly actionable |
| Uniqueness | 4 | No comparable index at this depth |
| Authority | 3 | Persuasive-only; ORLs non-precedential |
| Historical value | 5 | Verified to 1939, individually addressable |
| Current-session value | 4 | Live pending-RQ pipeline |
| Structure quality | 4 | Clean Q→analysis→conclusion + explicit RQ cross-cites |
| Ingestion ease | 3 | Two platforms, bot mitigation, JS-gated post-2023 ORLs |
| Entity richness | 3 | Well-scoped documents; unresolved requestors |
| Relationship richness | 3 | Explicit but shallow citation edges |
| Training value | 3 | Classification/retrieval strong; instruction narrow; eval staleness risk |
| Retrieval value | 5 | High-precision answers to concrete legal questions |
| Derived intelligence | 4 | Requestor/subject trend mining is novel |
| Moat potential | 4 | 87-year depth + 40k/yr ORL volume is slow to replicate |
