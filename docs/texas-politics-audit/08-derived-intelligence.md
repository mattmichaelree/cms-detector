# H. Derived Intelligence — What LobbyBook Can Compute That No Source Exposes

The state publishes documents. It does not publish *patterns*. Every signal below is
computable from sources in this audit, exists in no government system, and maps to a
question a paying client actually asks. These are the products that make LobbyBook a moat
rather than a mirror of capitol.texas.gov.

Signals are grouped by the graph layers they join. Each entry lists: the inputs, the
computation, the lobbyist question it answers, and confidence caveats.

---

## 1. Legislative process intelligence

### 1.1 Issue persistence & momentum index
- **Inputs:** bill subjects + captions across sessions (TLO), HRO analyses, interim reports.
- **Computation:** cluster substantially-similar bills across sessions (caption embedding +
  statute-section overlap); track per-cluster: sessions attempted, furthest stage reached
  each session (referred → heard → voted out → floor → passed one chamber → enrolled),
  author turnover, witness-count trend.
- **Answers:** "What happened the last three times Texas tried this?" "Is this idea gaining
  ground or stuck?" A bill that died in committee twice but got a floor vote last session
  is fundamentally different from a first-time filing — no state site shows this.
- **Caveats:** clustering is probabilistic; surface the member bills of each cluster so the
  user can audit it.

### 1.2 Stage-transition survival model ("will this bill move?")
- **Inputs:** full bill-action histories for all bills, all sessions (TLO bulk); calendar
  placements; committee assignment; author identity; companion existence; filing date.
- **Computation:** historical transition probabilities conditioned on committee, chair,
  author party/seniority, filing week, companion status, fiscal-note size. Texas's lethal
  calendar deadlines (the House deadline cascade in May) make date-conditioned hazard
  models unusually predictive here.
- **Answers:** "Realistically, is my bill dead?" "What must happen by what date?"
- **Caveats:** present as base rates plus the specific blockers, never as a naked score.

### 1.3 Amendment success & floor-tactics profile
- **Inputs:** journals (amendments offered/adopted/tabled, points of order, record votes),
  HRO daily floor reports.
- **Computation:** per-member and per-committee rates: amendments offered vs. adopted,
  motion-to-table patterns, points of order raised/sustained (and against whose bills),
  who carries hostile amendments for whom.
- **Answers:** "If we need a floor fix, who lands amendments?" "Who kills bills on
  technicalities, and is my draft vulnerable?"

### 1.4 Companion-bill and vehicle-shopping map
- **Inputs:** TLO companion links, identical-text detection across bills, amendment text.
- **Computation:** detect same-text provisions traveling across multiple vehicles
  (companions, "ghost" amendments onto moving bills late in session).
- **Answers:** "My bill is dead — what vehicles could carry the language?" "Did my opponent
  just attach their dead bill to something moving?" Late-session amendment surveillance
  against a client's interest profile is one of the highest-value alerts in the product.

## 2. People & relationship intelligence

### 2.1 Legislator issue-ownership profile
- **Inputs:** authorship history, committee service, interim charges assigned, floor
  statements (journals), press releases, HRO analyses of their bills.
- **Computation:** per-legislator issue vector over time; flag the 2–3 members who
  demonstrably "own" each policy space (author repeatedly, chair the committee, get the
  interim charge).
- **Answers:** "Who should carry this?" "Who will take offense if we shop it elsewhere?"

### 2.2 Warm-path finder ("who should I call?")
- **Inputs:** the whole graph — committee co-service, coauthorship, staff employment
  history (where obtainable), lobbyist client rosters (TEC), donor overlap (TEC), witness
  co-appearance.
- **Computation:** weighted path search from the user's network to a target decision-maker,
  ranked by tie strength and recency.
- **Answers:** the single most-asked question in the profession. No public source computes
  it because it requires joining five disclosure systems.
- **Caveats:** donor/employment edges are inferred joins on dirty names — show provenance
  on every hop.

### 2.3 Voting-bloc and defection analysis
- **Inputs:** journal record votes (all sessions), party/caucus membership.
- **Computation:** member-agreement matrices, cluster detection (e.g., rural R vs.
  leadership R blocs), per-member defection profile (on what issues do they break?).
- **Answers:** "What's our realistic floor count?" "Which Republicans peel off on eminent
  domain?" Roll-call data exists only inside journal prose — structuring it at scale is
  itself a moat.

### 2.4 Member-transition and institutional-memory tracker
- **Inputs:** LRL member service history, committee rosters per session, election results,
  staff directories over time (archived).
- **Computation:** who replaced whom, committee-seat lineage, "freshman on the committee
  that regulates your industry" alerts, staff moving between offices/agencies/lobby shops.
- **Answers:** "Who inherited my issue when the chair retired?" "My old contact's chief of
  staff now works where?"

## 3. Money & influence intelligence

### 3.1 Lobbying-roster shift detector
- **Inputs:** TEC lobby registrations (annual, with clients and subject categories).
- **Computation:** diff rosters year-over-year around each issue/industry: who staffed up,
  which firms gained/lost which clients, new entrants before a session.
- **Answers:** "Who is the opposition hiring?" "Which firm is building a practice in my
  space?" Registration data is public; the *delta* analysis is not published anywhere.

### 3.2 Money-map around a bill
- **Inputs:** TEC contributions, bill authors/committee members, contribution dates,
  session calendar.
- **Computation:** contributions from affected-industry donors to the members positioned
  on a bill, with timing relative to filing/hearings (Texas bans giving during the
  regular-session window — the December pre-session surge is where the signal lives).
- **Answers:** "Who funds the members deciding my issue?" — framed strictly as
  disclosure-derived correlation, never causation.

### 3.3 Organization political-footprint profile
- **Inputs:** TEC (PAC giving + lobby spend), witness lists, rule comments, endorsements,
  news mentions.
- **Computation:** one page per organization: what it lobbies on, testifies on, funds,
  endorses, and says — across all disclosure systems.
- **Answers:** "Who exactly am I up against?" "Which orgs are natural coalition partners?"
  This join is LobbyBook's core object and exists nowhere else.

### 3.4 Recurring-coalition detector
- **Inputs:** witness lists (position labels), rule-comment rosters, coalition letters in
  bill files, endorsement co-occurrence.
- **Computation:** orgs that repeatedly register the same position on the same bills/rules;
  bipartite clustering into durable coalitions and opposing blocs per issue space.
- **Answers:** "Who showed up together the last three times?" "Whose call sheet do I
  borrow?"

## 4. Legislative → regulatory → judicial lineage

### 4.1 Implementation tracker (bill → rule → litigation)
- **Inputs:** enrolled bills (statute sections amended), Texas Register proposals/adoptions
  (statutory-authority citations), court dockets/opinions citing the statute or rule.
- **Computation:** lineage chains: session law → TAC sections implementing it → cases
  challenging either; per-chain status and lag.
- **Answers:** "The bill passed — where is the rulemaking?" "Which rulemaking came out of
  last session's SB X?" "Is the rule my client relies on under attack?"

### 4.2 Regulatory-implementation lag & agency-behavior profile
- **Inputs:** the lineage chains above, per agency.
- **Computation:** median time from effective date to proposed rule to adopted rule, by
  agency; adoption-vs-withdrawal rates; how often adoptions change from proposals
  (comment responsiveness).
- **Answers:** "When will HHSC actually act?" "Is commenting at this agency worth it?"

### 4.3 Recommendation-conversion rates (Sunset & interim)
- **Inputs:** Sunset staff reports/decisions/final results; interim reports; subsequent
  bills.
- **Computation:** per-recommendation outcome tracking (enacted / management action /
  died), conversion rates by agency, committee, and recommendation type; forward index of
  pending recommendations not yet legislated.
- **Answers:** "Is this proposal coming out of a Sunset recommendation — and do those
  usually pass?" "What's already teed up for next session?"

### 4.4 Expected-agenda model (pre-session forecast)
- **Inputs:** interim charges + reports, Sunset schedule, party platforms and RPT
  legislative priorities, Lt. Gov./Speaker statements, pre-filed bills, news narratives.
- **Computation:** convert the between-session paper trail into a forecast agenda with
  provenance (charge → expected bill; platform plank → expected fight), then score
  conversion after the session.
- **Answers:** "What is next session actually going to be about, and where does my client
  sit in it?" This is the product a good lobbyist sells in even-numbered years.

## 5. Positioning & narrative intelligence

### 5.1 Promise-vs-record ledger
- **Inputs:** campaign positions (archived sites, questionnaires, ads), platform planks,
  press releases vs. votes, authorship, witness alignment.
- **Computation:** per-member alignment table: stated position → subsequent recorded
  behavior, with citations both directions; strictly presented as documented comparison
  (correlation, not judgment).
- **Answers:** opposition research and persuasion prep: "Where is this member's stated
  position soft or in tension with their record?"

### 5.2 Position-change detector
- **Inputs:** dated statements, votes, platform cycles.
- **Computation:** same actor + same issue + divergent stance across time windows → flagged
  with both citations.
- **Answers:** "Has the member moved on this since the primary?"

### 5.3 Platform-alignment scoring for bills
- **Inputs:** party platform planks + RPT legislative priorities, bill text/subjects.
- **Computation:** classify each bill as platform-aligned / platform-adverse / platform-
  silent per party; flag "platform-adverse for the majority party" bills a client supports
  (these need different strategies).
- **Answers:** "Is my ask primary-safe for the members I need?"

### 5.4 Narrative tracker
- **Inputs:** Texas political press + advocacy media, dated.
- **Computation:** cluster coverage into storylines per issue; track frame adoption
  (whose language wins), volume spikes vs. legislative events.
- **Answers:** "What does the press think the controversy is, and is that congealing into
  the frame the committee will hear?"

## 6. Committee & institutional intelligence

### 6.1 Committee power & centrality index
- **Inputs:** referral counts, pass-through rates, calendar success of reported bills,
  chair tenure, jurisdiction breadth (all from TLO/journals).
- **Computation:** per-committee: share of major-issue bills, kill rate, average time to
  hearing, chair discretion metrics (never-heard rate for minority-party bills).
- **Answers:** "What does referral to this committee mean for survival odds?" "Is this
  chair a gatekeeper or a conveyor?"

### 6.2 Agency-attention shift detector
- **Inputs:** Texas Register activity volume by agency/chapter, strategic plans, LAR
  asks, Sunset filings, news.
- **Computation:** rulemaking-volume time series with anomaly detection; new-chapter
  activity as an early signal of policy movement.
- **Answers:** "Is TDLR quietly gearing up on my client's industry?"

### 6.3 Fiscal-note accuracy retrospective
- **Inputs:** LBB fiscal notes vs. subsequent appropriations/actuals (LBB/Comptroller
  reports).
- **Computation:** where estimates ran high/low by agency and program type.
- **Answers:** arms a lobbyist to argue "LBB overestimated this category the last four
  times" — an argument nobody can currently make with citations.

---

## Build order (which signals unlock first)

| Wave | Signals | Why |
|---|---|---|
| With Tier-0 data alone (TLO + journals + witness lists + TEC) | 1.1, 1.2, 1.4, 2.1, 2.3, 3.1, 3.2, 3.3, 3.4 | Pure joins over structured Tier-0 corpora |
| After regulatory + oversight layers land | 4.1, 4.2, 4.3, 6.1, 6.2 | Need Register/TAC lineage + Sunset/interim structuring |
| After positioning layer lands | 4.4, 5.1–5.4, 6.3 | Need platforms, statements, campaign archive, news |

Two disciplines apply to every signal: (1) every derived claim carries its input citations
and its provenance class (explicit / derived / inferred) so users can audit it; (2)
money-adjacent signals are always phrased as disclosed-record correlations — LobbyBook
reports patterns, it does not allege quid pro quo.
