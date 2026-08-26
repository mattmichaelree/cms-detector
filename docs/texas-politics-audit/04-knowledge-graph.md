# D. The Texas Political Knowledge Graph — Canonical Entities, IDs, Schema, Edge Registry

All twenty source families map into **one canonical model**, not per-source schemas. A
source's job is to contribute *documents* (immutable, cited text) and *assertions*
(structured facts extracted from those documents, each carrying provenance). The graph is
what LobbyBook reasons over; the documents are what it cites.

## 1. Design rules

1. **Documents are immutable; entities evolve.** Never edit extracted text — new versions
   are new `document_version` rows. Entity records (a person, a rule) carry time-scoped
   attributes.
2. **Every assertion has provenance class:** `explicit` (stated in the record),
   `derived` (deterministic transformation, e.g., parsed vote roll), `inferred`
   (probabilistic, e.g., entity-resolved donor identity, stance classification). Class is
   stored on the edge, surfaces in the UI, and gates what the assistant may state as fact.
3. **Bitemporal where it matters.** Facts carry `valid_from`/`valid_to` (when true in the
   world) and `observed_at`/`published_at` (when the record said so). Office tenure,
   committee membership, rule text, lobby registrations, and positions are all useless
   without this.
4. **Session is a first-class dimension.** Nearly every legislative fact is scoped to a
   `session_id` (e.g., `88R`, `88S3`). Bill numbers, committee names, and rules are only
   unique within one.
5. **Never mint an ID where the state already has one.** Preserve native IDs verbatim and
   join through a crosswalk table.

## 2. Canonical entity catalog

### People & organizations

| Entity | Key fields | Native ID sources |
|---|---|---|
| `person` | canonical name, name variants[], roles[] (time-scoped), party (time-scoped), district (time-scoped), chamber | LRL member ID; TLO member code; TEC filer ID; OpenStates person ID — crosswalked |
| `organization` | canonical name, variants[], type (agency/corp/association/nonprofit/PAC/campaign/party/local-gov/university/firm/court), industry codes[] | TEC filer/client IDs; agency codes (LBB/Comptroller 3-digit agency numbers); SOS corp file numbers (optional enrichment) |
| `role_tenure` | person, role type (legislator/chair/governor/judge/agency-head/staff/lobbyist), org/body, valid_from, valid_to | LRL service records (legislators); court rosters; appointment announcements |

`person` and `organization` are the **entity spine**. Everything else hangs off them, and
the dirtiest, highest-value work in the whole system is name resolution *into* them
(TEC donors/clients, witness-list names, rule commenters). Resolution links are always
`inferred` edges with confidence, never silent merges.

### Legislative

| Entity | Key fields | Native IDs |
|---|---|---|
| `session` | legislature number, type (R/called#), convene/adjourn dates | TLO session codes (`88R`, `881`–`884` style for called sessions) |
| `bill` | session, chamber, number, type (B/JR/CR/R), caption (per version), subjects[] | TLO bill ID (session+number is the natural key) |
| `bill_version` | bill, stage (introduced/committee-sub/engrossed/enrolled), text ref, date | TLO version documents |
| `bill_action` | bill, date, chamber, action code, description, journal cite | TLO action rows |
| `committee` | chamber, name (time-scoped), session-scoped roster, jurisdiction text | TLO committee codes |
| `hearing` | committee, datetime, location, type (public/formal), bills considered[] | TLO hearing notices |
| `witness_slip` | hearing, bill, person name (raw + resolved), org (raw + resolved), position (for/against/on), testified vs registered-only | witness-list PDFs (no native ID — synthesized key) |
| `amendment` | bill, chamber, number, author, disposition (adopted/tabled/withdrawn), text ref, journal cite | journal numbering per bill/reading |
| `vote` | bill/question, chamber, date, type (record/viva-voce), tallies, journal cite | journal record-vote numbers |
| `vote_cast` | vote, person, position (Y/N/PNV/absent), pair/reason-for-vote text ref | derived from journal roll text |
| `journal_entry` | chamber, legislative day, page range, entry type, text ref | chamber + session + page |

### Policy & regulatory

| Entity | Key fields | Native IDs |
|---|---|---|
| `statute_section` | code, chapter, section, text (versioned), source bills[] | statutory cite ("Gov't Code §551.001") |
| `rule` (TAC section) | title, part, chapter, section, agency, text (versioned), status | TAC cite ("22 TAC §291.33") |
| `rule_action` | rule(s), type (proposed/adopted/withdrawn/emergency/review), Register cite, dates (proposal, comment-close, adoption, effective), preamble ref | Texas Register cite ("48 TexReg 1234") |
| `ag_opinion` | number, requestor, date, question, conclusion, statutes interpreted[] | AG numbering (KP-, GA-, RQ- for requests) |
| `executive_order` | governor, number, date, subject, status | EO numbering (e.g., GA-##) |
| `court_case` | court, docket, style, dates, disposition, opinions[] | docket number; citation |
| `sunset_review` | agency, cycle, documents (SER/staff report/decisions/final results), recommendations[] | Sunset cycle + agency |
| `recommendation` | source (sunset/interim/agency), text, target agency, outcome (enacted/mgmt-action/died), outcome evidence | synthesized |
| `interim_charge` | issuer (Speaker/LtGov), committee, session-gap, text | synthesized (numbered within charge letters) |
| `fiscal_note` | bill_version, estimate table (by FY), methodology text ref | LBB per bill version |
| `appropriation` / `rider` | GAA biennium, article, agency, strategy line / rider number, amounts, text ref | GAA structure |

### Political

| Entity | Key fields | Native IDs |
|---|---|---|
| `contribution` / `expenditure` | filer (committee), counterparty (raw + resolved), amount, date, report, amended-by | TEC report + line IDs |
| `lobby_registration` | lobbyist person, client org, year, compensation range, subject categories[] | TEC lobby filer ID + year |
| `endorsement` | org → candidate, cycle, date, source doc | none (synthesized) |
| `political_position` | actor, issue, stance, statement date, validity window, source doc, provenance class | none (synthesized) |
| `platform_plank` | party, cycle, plank number, text, issues[] | plank numbers within platform |
| `news_story` | outlet, date, byline, headline, entities/issues discussed[], url | URL |

### Cross-cutting document layer

Every corpus lands here first; extraction populates the tables above.

```
document            (id, source_family, native_id, url, doc_type, published_at,
                     session_id?, retrieved_at, checksum)
document_version    (document, version_no, checksum, retrieved_at, storage_ref,
                     supersedes?)          -- PDFs replaced in place become new versions
document_section    (document_version, section_type, ordinal, heading, char span,
                     page range)           -- semantic chunks; see retrieval doc
citation_span       (assertion/edge id → document_version, char span)
issue               (id, name, parents[]; controlled vocabulary seeded from TLO subject
                     index + HRO topic headings; bills/rules/stories/positions tag into it)
```

## 3. Edge registry

Notation: `subject —predicate→ object [provenance] (source)`

### Explicit (stated in an authoritative record)
```
person —authored|coauthored|sponsored→ bill                (TLO)
bill —referred_to→ committee                               (TLO action / journal)
committee —held→ hearing; hearing —considered→ bill        (TLO)
person —testified_on|registered_position_on→ bill {for/against/on}   (witness lists)
person —offered→ amendment; amendment —amends→ bill        (journal)
bill —has_version→ bill_version; bill —companion_of→ bill  (TLO)
bill —has_fiscal_note→ fiscal_note                         (LBB via TLO)
agency —proposed|adopted|withdrew→ rule_action             (Texas Register)
rule_action —cites_authority→ statute_section              (Register preamble)
ag_opinion —answers→ request; requestor —requested→ opinion (AG)
governor —issued→ executive_order; governor —vetoed→ bill  (Gov/LRL; veto proclamations)
sunset_review —recommends→ recommendation                  (Sunset reports)
issuer —assigned→ interim_charge —to→ committee            (charge letters)
donor(raw) —contributed_to→ committee                      (TEC)
lobbyist —registered_for→ client {year, comp range, subjects} (TEC)
org —endorsed→ candidate {cycle}                           (endorsement pages)
party —adopted→ platform_plank                             (platforms)
rider —directs→ agency                                     (GAA)
```

### Derived (deterministic parsing/joins — no judgment involved)
```
person —cast_vote→ vote {Y/N/PNV}              (parsed journal rolls)
amendment —adopted_on→ date {reading}          (parsed journal actions)
bill —modifies→ statute_section                (parsed "SECTION n. Section X amended" in bill text)
rule —implements→ statute_section              (parsed authority cites)
court_case —interprets→ statute_section|rule   (citation extraction from opinions)
bill_version —differs_from→ bill_version {diff}(text diff)
contribution —amended_by→ contribution         (TEC report linkage)
hearing —has_recording→ media                  (video archive links)
committee(sessionN) —successor_of→ committee(sessionN-1)   (roster/jurisdiction mapping; verify — partly inferred after reorganizations)
```

### Inferred (probabilistic — carries confidence + must display as such)
```
name(raw) —resolves_to→ person|organization        (entity resolution)
bill —same_policy_as→ bill (cross-session cluster) (text/subject similarity)
recommendation —produced→ bill                     (interim/Sunset → bill mapping; explicit only when the bill analysis says so)
interim_charge —led_to→ bill                       (same)
actor —stated_position_on→ issue {stance}          (stance classification of statements)
news_story —discusses→ bill|issue|person           (NER + linking)
org_a —coalition_with→ org_b {issue}               (co-registration patterns)
plank —aligned_with|adverse_to→ bill               (classifier)
```

The assistant may state `explicit` and `derived` facts declaratively with a citation; it
must attribute `inferred` facts ("LobbyBook's records link…", "registrations suggest…").

## 4. Stable-ID crosswalk strategy

- **Sessions:** adopt TLO's session codes (`88R`, called sessions per TLO convention) as
  the canonical `session_id`; map LRL and OpenStates session identifiers onto them.
- **Bills:** canonical key = `session_id + bill_number` (e.g., `88R-HB1500`). Never store
  a bill number without its session.
- **People:** maintain `person_xref(person_id, system, external_id)` covering LRL member
  records, TLO author codes, TEC filer IDs, OpenStates IDs, court/judge rosters. Seed the
  legislator spine from LRL (deepest history), enrich from OpenStates people data.
- **Organizations:** seed from TEC client/filer lists + state agency list (canonical
  agency numbers); resolution table grows from witness lists and Register commenters.
- **Rules/statutes:** the citation string *is* the ID, plus a version dimension
  (`22 TAC §291.33 @ 2026-03-01`).
- **Documents:** `source_family + native_id` when the source has one (Register cite, AG
  number, EO number); URL+checksum otherwise.

## 5. What is structured vs. text vs. both

| Layer | Treatment |
|---|---|
| Actions, votes, referrals, witness slips, registrations, contributions, rule statuses, tenures | **Structured rows** — these answer "what happened" queries via SQL/graph, never via embeddings |
| Bill text, analyses, journals, preambles, opinions, reports, statements, planks, stories | **Document sections** — chunked semantically (see retrieval doc), BM25 + vector indexed, always cited by section |
| Arguments, positions, recommendations | **Both** — a structured assertion (stance, outcome) pointing at its `citation_span` |
