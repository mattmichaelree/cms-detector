# G. Benchmark Architecture — Measuring Whether LobbyBook Actually Understands Texas Politics

## Design principles

1. **Grade against documents, not vibes.** Every question has a gold answer *and* gold
   evidence (specific document IDs/spans from the corpora in this audit). Scoring checks
   both the answer and whether the cited evidence actually supports it.
2. **Test the failure modes of generic frontier models.** A generic LLM knows what a
   fiscal note is. It does not know what HB 1500 (88R) did versus HB 1500 (87R), who
   chairs Calendars *now*, or that a rule proposal died by withdrawal. The benchmark's
   center of gravity is time-scoped, version-scoped, Texas-procedure-specific fact.
3. **Separate retrieval-dependent from knowledge-dependent items.** Run every item in two
   modes — closed-book and with LobbyBook retrieval — so the benchmark measures the
   *system's* lift, not just the base model.
4. **Refresh by construction.** Items are generated from structured data (actions, votes,
   registrations), so each session/cycle mints a fresh test set immune to memorization.

## Categories, example questions, gold sources

### 1. Legislative procedure (Texas-specific mechanics)
- "A House bill was left pending in committee on May 6 of an odd year. What deadlines now
  govern whether it can still pass, and what are the realistic revival paths?"
- "What does a point of order under Rule 8, Section 13 target, and at what stage can it be
  raised?"
- **Gold:** House/Senate rules (adopted each session — in journals), TLO actions,
  legislative-deadline calendars. Procedure questions are the strongest pure-knowledge
  test; a wrong answer here destroys practitioner trust instantly.

### 2. Bill & version facts
- "What does the engrossed version of SB 2 (88R, 2nd called) do that the introduced
  version did not?"
- "Which committee substitute language survived into the enrolled bill?"
- **Gold:** TLO bill versions; amendment text in journals. Score citation to the *correct
  version*.

### 3. Historical issue development
- "Trace school-finance recapture fights from 2015 through the most recent session: which
  bills, which vehicles passed, what changed each time?"
- **Gold:** TLO cross-session bill clusters, HRO analyses, session summaries.

### 4. Committee jurisdiction & referral
- "A bill regulating third-party food-delivery platforms is filed in the House. Which
  referral is most likely, and what precedent referrals support that?"
- **Gold:** historical referral data (TLO), committee jurisdiction in House rules.

### 5. Fiscal analysis
- "What did the fiscal note assume about caseload growth for this program, and did the
  enacted appropriation match it?"
- **Gold:** LBB fiscal note sections; GAA strategy lines and riders.

### 6. Regulatory process
- "An agency proposed a rule on [date]. What is the latest date it can adopt without
  re-proposing, and what happened in this instance?"
- "Which TAC sections implement [session law], and are they in effect today?"
- **Gold:** Texas Register notices (proposal/adoption/withdrawal), TAC history notes.

### 7. Testimony & coalition mapping
- "Which organizations registered against this bill in committee, and which of them also
  commented on the implementing rule?"
- **Gold:** witness lists; Register adoption preambles (comment summaries).

### 8. Campaign finance
- "How much did PAC X give to members of the committee hearing this bill in the cycle
  before the session, per TEC filings?"
- **Gold:** TEC bulk data (amended-report-aware totals — items deliberately include
  filers with amendments).

### 9. Lobbying relationships
- "Who is registered to lobby for [company], on what subject categories, in the current
  registration year — and who did they represent last cycle?"
- **Gold:** TEC lobby registrations.

### 10. Current-session situational awareness (live mode only)
- "What happened to my bill yesterday?" "What's posted for hearing on my issue this week?"
- **Gold:** TLO actions + hearing postings + journals from the trailing week. This
  category is regenerated continuously during session; it measures pipeline freshness as
  much as the model.

### 11. Political positioning
- "Has Senator X publicly taken a position on [issue]? Cite the statement and date, and
  note any tension with their voting record."
- **Gold:** press releases/statements corpus, journal votes; graded on attribution
  discipline (stated-position ≠ fact).

### 12. Agency behavior
- "Is [agency] under Sunset review this cycle, what did staff recommend, and what did the
  commission decide?"
- **Gold:** Sunset staff report, decision material, final results.

### 13. Judicial / regulatory impact
- "What litigation currently threatens the rule my client operates under, and what has
  the court actually held so far?"
- **Gold:** court opinions/dockets; Register (rule status). Grade heavily on not
  overstating holdings.

### 14. Multi-hop research
- "Which Sunset recommendation from the last cycle became statute, which agency rule
  implements it, and who testified on the bill?" (Sunset → bill → rule → witness list —
  four corpora.)
- **Gold:** the full lineage chain; score partial credit per verified hop.

### 15. "Who should I talk to?"
- "My client needs a rural-water fix. Who are the 3 right members/staff, and why?"
- **Gold:** expert-panel-validated answers (see below) with graph evidence (authorship,
  committee, interim charge, district).

### 16. Client-impact synthesis
- "Here is a client profile (industry, regulators, districts). Summarize this week's
  relevant activity and rank by threat."
- **Gold:** constructed weekly snapshots with a labeled relevance/threat rubric; graded
  on recall of the planted-relevant items and precision against distractors.

## Adversarial set (where generic LLMs predictably fail)

Build these deliberately; they are the marketing demo and the regression suite:

| Trap | Construction | Example |
|---|---|---|
| Bill-number reuse | Same number, different sessions, different topics | "What does HB 3 do?" — must ask/resolve session (public-school finance 86R vs. election integrity 87R2 vs. later reuse) |
| Wrong-session bleed | Ask about session N with distractor facts from N−1 prominent online | Committee chair questions across a speakership change |
| Version confusion | Introduced vs. engrossed vs. enrolled differ materially | "Does the bill preempt local ordinances?" where only the introduced version did |
| Amendment aliasing | Floor amendment gutted the caption's promise | Caption says one thing; adopted floor substitute does another |
| Office-holder change | "The Speaker," "the chair," "the AG" resolved to the wrong era | Any question spanning 2021–2025 leadership churn |
| Committee reorganization | Renamed/split committees across sessions | "What did House Public Health do with this?" when jurisdiction moved |
| Superseded rule text | TAC section amended since the popular secondary sources were written | Rule-citation questions where current text differs from cached web copies |
| Amended TEC reports | Original filing widely reported; amendment changed totals | Contribution-total questions |
| Advocacy-vs-record conflict | Press release claims X; journal vote shows Y | "Did the member vote to cut program Z?" |
| Similar-name entities | Two members with near-identical names; PACs with sound-alike names | Attribution questions |
| Dead-but-revived language | Bill died; identical text passed inside another vehicle | "Did the legislature pass X?" — correct answer is "yes, via SB Y §12" |

## Gold-answer production

- **Programmatic items (~70%):** generated from structured tables (actions, votes,
  registrations, Register statuses) with templated questions — cheap, regenerable each
  session, objectively gradable.
- **Expert items (~30%):** commissioned from former staffers/lobbyists for procedure,
  "who to talk to," and synthesis categories; answers require cited evidence; double-keyed
  and adjudicated.
- **Grading:** exact-match/structured grading where possible; rubric-based LLM-judge with
  evidence-verification for prose answers (judge must confirm each cited span exists and
  supports the claim); abstention credit — "not determinable from the record / needs
  session disambiguation" is the *correct* answer for some items, and the benchmark must
  reward it.

## Reported metrics

Per category and overall: answer accuracy; **citation validity** (cited doc exists,
supports claim); **temporal correctness** (right session/version/officeholder); abstention
quality; and closed-book vs. retrieval-mode delta (LobbyBook's measurable lift over the
base model and over a generic-frontier-model-with-web-search baseline).
