# E. Retrieval Architecture — Routing, Chunking, and Index Design

## 1. The core rule: structured first, text second

Most questions a lobbyist asks are **facts with official answers** ("what happened to my
bill," "who voted no," "when does the comment period close"). Those must be answered from
structured tables — SQL and graph traversal — with the document citation attached.
Embedding search over prose is the *wrong* tool for them: it is where session confusion,
version confusion, and bill-number collisions come from.

Vector retrieval earns its place only where meaning, not identity, is the query:
arguments, analyses, testimony themes, news narratives, "has Texas tried something like
this," "what are the arguments against."

**Router policy:** classify each query into (a) entity/event lookup → SQL/graph; (b)
argument/analysis → hybrid BM25+vector over document sections, filtered by metadata; (c)
relationship/path → graph; (d) synthesis → orchestrated multi-retrieval. Always extract
and pin `session`, `chamber`, `bill`, `date-window`, `actor` filters *before* any
similarity search runs — temporal/session filters are hard constraints, not ranking hints.

## 2. Chunking by document family (semantic sections, never blind 500-token windows)

| Family | Segmentation | Notes |
|---|---|---|
| HRO bill analysis | SUBJECT / COMMITTEE&VOTE / WITNESSES / BACKGROUND / DIGEST / SUPPORTERS SAY / OPPONENTS SAY / NOTES | The section labels are stance labels — preserve them as metadata; never mix supporter and opponent text in one chunk |
| Journals | legislative-day → entry: bill action, amendment (full text), motion, record vote (roll), point of order, statement/reason-for-vote | Chunk = one entry; metadata: chamber, date, bill(s), page range. Rolls also parse to `vote_cast` rows |
| Bill text | per SECTION of the bill (each names the statute section it amends) | Version-scoped; store diff-vs-prior-version alongside |
| Texas Register notice | agency / TAC cite / preamble (background, §-by-§ summary) / statutory authority / fiscal statements / comment instructions / rule text / (adoption) response-to-comments | Response-to-comments subdivides per commenter where structure allows |
| Committee minutes & witness lists | per bill taken up; witness list rows → structured `witness_slip`, not chunks | Minutes prose chunked per bill segment |
| Interim / Sunset reports | charge or issue → findings → recommendations (one chunk per recommendation, with its supporting-finding context pointer) | Recommendations also become structured `recommendation` rows |
| Court opinions | caption/procedural posture / facts / question presented / analysis (per issue) / holding / disposition | Holding chunks flagged; syllabus (if any) kept separate from opinion text |
| AG opinions | question presented / brief answer / analysis / conclusion | Q+conclusion pair also stored structured |
| Fiscal notes | fiscal-impact table (structured) / methodology / assumptions / agency-source notes | Table rows → structured; prose chunked |
| GAA | strategy line items (structured) + rider (one chunk per rider, numbered) | Riders are the retrieval gold in the GAA |
| Strategic plans / LARs | goal → objective → strategy → measures; LAR exceptional items each its own chunk | |
| Platforms | one chunk per plank (numbered), issue-tagged | |
| Press releases / statements | whole item (usually short); split only on multi-topic | |
| News | headline+lede stored; full text subject to licensing (see deep dive); entity/issue tags structured | |
| Hearing transcripts (ASR-generated) | speaker-turn segments grouped per bill discussion; timestamps preserved to link back to video | |

Every chunk carries: `document_version_id`, section type, ordinal, char/page span, session,
date, chamber/agency, bill/rule IDs mentioned (resolved), and authority class (A–E). The
citation the user sees is exact: journal page, Register cite, section heading.

## 3. Routing matrix

| Question class | Primary retrieval | Supporting | Never |
|---|---|---|---|
| What does HB X (session S) currently do? | SQL: bill_version (latest stage) → its section chunks | HRO/SRC analysis of that version; fiscal note | Vector search on "HB X" (collision hazard) |
| What happened to my bill yesterday? | SQL: bill_action + hearing rows in date window | Journal entry chunks; news mentions | |
| What are the arguments for/against? | HRO supporters/opponents chunks (stance-filtered) + witness testimony | Floor statements, editorials/news | Presenting either side as LobbyBook's view |
| Who opposes / supports this? | Structured witness_slip positions + registered lobby clients | Recurring-coalition signal; news; endorsements | Treating "registered against" as permanent enmity — scope by bill/date |
| How did members vote? | SQL: vote + vote_cast | Journal citation for verification; reason-for-vote statements | Model memory — always the parsed roll |
| How much does this cost? | Fiscal-note table (structured) for the right version | GAA strategy/riders; LBB reports | Prior-session fiscal notes without flagging version |
| What rule implements this statute? | Graph: statute → rule edges (authority cites) | Register preamble chunks; agency rulemaking pages | Cached TAC text without checking current status |
| Is a rule changing that affects my client? | SQL: rule_action in window × client industry/TAC-title watchlist | Preamble chunks; agency board minutes/news | |
| What happened historically on this issue? | Cross-session bill cluster (inferred — show members) → per-session outcomes | HRO analyses & session summaries; interim reports; news archive | |
| Is this from a Sunset/interim recommendation? | Graph: recommendation → bill edges; else vector match recommendation text ↔ bill text (flag as inferred) | Sunset decisions; charge text | |
| Who gave money to X? | SQL over TEC (amended-aware) | Money-map derived views | Vector anything |
| Who lobbies for Y? | SQL: lobby_registration by client/year | Roster-shift signal | Stale years without labeling the year |
| Has legislator Z taken a position? | Statement corpus filtered by person+issue (BM25+vector), sorted by date | Votes/authorship (record vs. rhetoric); platform planks | Presenting a position without its date |
| What's the press narrative? | News chunks, issue-filtered, recency-weighted | Advocacy-media flagged separately | Mixing advocacy outlets into "the press" unlabeled |
| Who should I talk to? | Graph: issue-ownership + warm-path traversal | Testimony/committee/staff history as evidence | Pure vector similarity over bios |
| What's on the special-session agenda? | Structured: proclamation items | Governor statements; news | Assuming regular-session rules of scope |

## 4. Index inventory

- **Relational (Postgres):** all structured tables in `04-knowledge-graph.md`. This is
  the system of record and answers the majority of production queries.
- **Graph:** either Postgres-native (recursive CTEs over an `edge` table) or a dedicated
  store; needed for path queries (warm paths, lineage chains). Edges carry provenance
  class + citation — the graph is *derived from* relational + extraction layers, rebuilt,
  never hand-edited.
- **Lexical (BM25):** all document sections. Critical for exact-phrase and term-of-art
  queries ("rolling average cap", "corporate practice of medicine") where embeddings blur.
- **Vector:** document sections in the *argumentative/analytical* families (HRO, testimony,
  preambles, opinions, reports, statements, news). Skip or deprioritize embedding of:
  vote rolls, action lines, contribution rows, calendars — structured data embedded as
  prose is noise that actively causes wrong answers.
- **Reranker:** cross-encoder over the merged BM25+vector candidate set, with feature
  boosts for session match, recency (query-dependent), and authority class.

## 5. Temporal and authority handling at query time

1. Resolve the query's implicit time: "currently," "last session," "in 2023" → hard
   filters on session/valid-time. If ambiguous and it matters (bill numbers!), the
   assistant asks or answers per-session explicitly.
2. Prefer the highest-authority source for any contested fact: A-record (journal, enrolled
   text, adopted rule) over B-analysis over C-claims over E-press; when C/E conflicts with
   A, surface the conflict — that conflict is itself intelligence (see promise-vs-record).
3. Every generated answer carries machine-checkable citations (document_version + span).
   Answers without a resolvable citation for a factual claim fail QA.
