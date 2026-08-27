# Texas House & Senate Journals

**Authority class:** A — each chamber's constitutionally mandated official proceedings
record, internally cited as precedent ("See 89 H. Jour. 4387 (2025)") · **Priority:
Tier 0 — the only source of individual roll-call votes and adopted amendment
dispositions in context** · Verified by live inspection, Aug 2026.

## 1. Corpus & coverage

- **Platforms:** journals.house.texas.gov (legacy engine at `/hjrnl/`) and
  journals.senate.texas.gov (`/sjrnl/`), each wrapped by a newer Angular shell at the
  root; all substantive data lives on the legacy paths.
- **Earliest online, verified by probing every session code:** House **74R (1995)**;
  Senate **76R (1999)** — the Senate is missing two biennia (1995, 1997) the House has.
  74R–75R are PDF-only; HTML companions begin at 76R.
- **Current era complete:** 89R + both 2025 called sessions (891, 892 = 200; 893 = 404);
  spot checks found no gaps in 87th (3 called) or 88th (4 called) session archives.
- **Pre-web:** the sites' own selector routes 1st–73rd Legislatures to LRL
  (journals 1846→present + Republic-of-Texas Congress 1836–45, incl. Senate "Secret
  Journals"); UNT Portal holds full-text-searchable subsets (House ~1929–2023, Senate
  ~1923–2013); Internet Archive/HathiTrust hold scattered volumes. LRL robots restricts
  automated PDF crawling (see the ecosystem deep dive).
- **URL stability:** the old `*.state.tx.us` journal domains are dead (verified) —
  legacy citations break. File naming varies by era (`day01.pdf` →
  `80RDAY01FINAL.PDF`), and mid-session PRELIM→FINAL churn means a day's URL is not
  append-only.

## 2. Native formats (verified)

- **HTML (76R+):** one long flowing document per legislative day (up to 1.1M chars of
  text) with **zero named anchors and zero page markers** — full-document search only;
  page-level citation is impossible from HTML.
- **PDF: born-digital at every era sampled.** 89R day: Aspose.PDF, clean extraction,
  real page-footer numbers matching the index's page ranges — the citation anchor.
  Even 1995 is born-digital (PageMaker→Distiller; TLC back-converted its print files in
  2008 — no scanning). **No PDF bookmarks/outline anywhere** (checked
  programmatically).
- **The undocumented JSON day-index — the practical ingestion hook:**
  `/hjrnl/{session}/html/data/jrnlData.txt` (and `/sjrnl/…`) returns structured
  per-day rows: calendar date, legislative-day ordinal, page range, PDF/HTML links.
  Stable in format across 74R–89R.
- **End-of-session appendixes (House):** a pre-parsed Bill-History/Authors PDF (1,387
  pages, per-bill action logs with journal page cites: "Read first time 295. Referred
  to Appropriations 295.") + a subject-index PDF — far cheaper to parse than stitching
  90+ day files. The Senate's equivalent flag was false for 89R (UNVERIFIED whether a
  Senate counterpart exists elsewhere).
- **Journals are NOT in the legislature's bulk FTP tree** (per TLO's own FAQ doc-type
  list; the tree itself was unreachable — documented, not browse-verified). No bulk
  ZIP, no API, no RSS.

## 3. What a lobbyist uses it for

All four canonical floor questions answer directly (verified with live examples):
- *Did the amendment get adopted?* — full amendment text followed by "Amendment No. 1
  was adopted by (Record 3835): 137 Yeas, 3 Nays, 1 PNV."
- *How did each member vote?* — full named Yeas/Nays/PNV/Absent lists after every
  record vote, both chambers.
- *Was a point of order raised?* — verbatim rulings with reasoning and journal-page
  precedent citations.
- *What happened to my bill yesterday?* — every reading, referral, amendment, and vote
  for the day, in order.

**Usefulness:** session monitoring HIGH · political intelligence HIGH (roll calls,
colloquy, procedural attacks — all attributable) · opposition research HIGH (quotable
verbatim debate + named nays) · bill strategy HIGH (exact procedural posture) ·
historical research HIGH (the chamber's own precedent record) · issue research MED-HIGH ·
meeting prep MED · client intelligence MED · relationship MED (who yields to whom, who
moves for whom) · coalition MED · forecasting MED (procedural-tactic patterns) · fiscal
LOW-MED · compliance LOW-MED · committee LOW-MED (referral dates only) · campaign LOW ·
regulatory NONE.

## 4. Ontology & native IDs

Legislature · session (`89R`, `891`…; bill numbering resets per called session) ·
**legislative day ≠ calendar day** (ordinal + "Cont." continuations) · **journal page —
the true citation anchor** ("89 H. Jour. 4387 (2025)"; exists only in the PDF) ·
journal file (filename stem `89RDAY81FINAL`, `89RSJ06-02-F`, with SUPPLEMENT/CONT
variants as distinct documents) · bill/resolution · motion · amendment (numbered per
bill) · **record vote — sequential numeric ID in the House ("Record 4167"); the sampled
Senate day reported tallies without a numbered ID** (chamber format difference) ·
member (surname+initial disambiguation "Bell, C."/"Bell, K." — a usable resolution
key) · committee · point of order + ruling · message (numbered per day) · statement of
vote · conference committee (chair + conferees) · bill-history index entries.

## 5. Edges

EXPLICIT: member→present/absent→day · amendment→offered_by→member /
→amends→bill / →adopted|failed_on→record_vote · **member→voted{Y/N/PNV/absent}→
record_vote (named lists)** · member→raised→point_of_order + officer→ruled ·
bill→referred_to→committee (dated/paginated) · chamber→message→chamber ·
member→statement_of_vote→record_vote · conference_committee→appointed_for→bill ·
bill→history_cites→journal_pages (appendix).
DERIVED: member↔member agreement matrices · amendment success rates · voting-bloc
clusters · floor-participation scores.
INFERRED: alliances (co-authorship + amendment support patterns) · topic-level
opposition profiles · procedural-tactic intent.

## 6. Temporal semantics — verified traps

1. **Legislative day ≠ calendar day**: verified a "6th Day" dated July 18 and its "6th
   Cont." dated July 25 — recess, not adjournment. Ordering by calendar date misorders
   events.
2. **Bill numbers reset per called session** — HB 1 in 89R ≠ HB 1 in 891.
3. **Bill state is stitched across many day-files** — no single document holds a bill's
   floor history except the end-of-session appendix.
4. **"FINAL" online ≠ legally final**: the served day-81 PDF was regenerated ~10 months
   after the session day (CreationDate 2026-04-15 for a 2025-06-02 day); the site's own
   disclaimer says content is revisable until the permanent journal publishes. Diff
   content, not headers.

## 7. Authority

Class A. Distinguish inside the record: **fact-of-the-record** (motions, votes, adopted
text, rulings — definitive) vs. **attributed content embedded in the record** (floor
colloquy, statements of vote — the fact that X said Y is class A; the truth of Y is
attributed speech). Note: capitol.texas.gov robots disallows /BillLookup/, /Reports/,
/Help/ — TLO's vote-lookup deep-links into journal pages rather than hosting an
independent vote DB (confirmed once; not a standing scrape target).

## 8. Ingestion

Poll the per-session JSON day-index for new/changed rows → fetch HTML (light, full
text) + PDF (authoritative page numbers) → segment on the journal's regular ALL-CAPS
headers (POINT OF ORDER, MESSAGE FROM THE SENATE, STATEMENT OF VOTE…) and the
boilerplate disposition sentence ("was adopted by (Record ####): …"). Grab the
end-of-session appendix PDFs when they publish. Backfill: direct for 1995/1999→;
earlier requires an LRL/UNT licensed or human-mediated path (assume scans + OCR).
Cadence: daily during session. **Dedup: (chamber, session, filename stem)** — never
(chamber, session, calendar date). **Change detection: content hash — the same
filename gets silently regenerated.** Failure modes: PRELIM→FINAL swaps, dead legacy
domains, no bulk channel, robots-restricted historical archives.

## 9. Training value

High retrieval + eval value (unambiguous named-vote ground truth for closed-book
factual evals). Natural labels: the regular boilerplate → **legislative-action
classifier** (action line → ADOPTED/FAILED/POSTPONED/WITHDRAWN/POO_SUSTAINED…) and
vote-line text → (member, vote) pairs for name-normalization/NER (the journal's own
"Bell, C." disambiguation is the label). Instruction value moderate (dense
parliamentary prose needs curation).

## 10. Derived intelligence

Voting-bloc/agreement matrices · amendment success by author/party/subject ·
**point-of-order win rate per member (parliamentary-skill index)** · time-in-stage
analysis · attendance patterns · statement-of-vote frequency (post-hoc optics
management signal) · procedural-tactic mining (which rules get invoked by whom against
which bill types) for forecasting floor fights.

## 11. Scores (1–5)

| Dimension | Score | Why |
|---|---|---|
| Lobbyist usefulness | 5 | Answers the highest-frequency floor questions with page-cited authority |
| Uniqueness | 5 | Named roll calls + amendment dispositions exist authoritatively only here |
| Authority | 5 | Constitutional record, internally cited as precedent |
| Historical value | 4 | To 1846 in principle; pre-1995/99 robots-restricted or scattered scans |
| Current-session value | 5 | Complete, day-granular, both chambers, all called sessions |
| Structure quality | 4 | Regular boilerplate + real JSON index; no HTML anchors, no PDF bookmarks |
| Ingestion ease | 3 | No bulk/API; undocumented index; PRELIM→FINAL churn forces content hashing |
| Entity richness | 4 | Members, amendments, votes, motions, rulings, messages, conferees |
| Relationship richness | 4 | Rich explicit edges; cross-day stitching required |
| Training value | 4 | Action-classifier labels + clean eval ground truth |
| Retrieval value | 5 | Verbatim, page-cited, dense with exactly what lobbyists query |
| Derived intelligence | 4 | Bloc analysis, procedural forecasting |
| Moat potential | 3 | Public and partially repackaged; the derived layer is the moat |
