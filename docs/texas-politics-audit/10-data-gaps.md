# J. Data Gaps — What a Texas Lobbyist Needs That These Sources Don't Provide

Even with all twenty families ingested, real workflows hit walls. Naming the walls matters:
some can be bought, some can be built, some must be honestly labeled "we don't know."

## 1. Gaps with acquisition paths

| Gap | Why it matters | Where to get it |
|---|---|---|
| **Staff-level data** (committee clerks, chiefs of staff, policy analysts — and their job movements) | The people who actually draft, schedule, and gatekeep. "Who should I talk to?" is often a staffer answer | No comprehensive public roster with history. Options: Texas Legislative Council–published directories (point-in-time), archived capitol directories via Wayback, LinkedIn monitoring (ToS-constrained), the commercial *Texas Capitol Directory* (Hargrove), phone-book scraping of house.texas.gov/senate.texas.gov office pages each session. Build a time-scoped `staff_tenure` table from repeated snapshots — nobody else maintains the history |
| **Floor debate transcripts** | Journals record actions, not words; the argument that killed a bill on the floor is only in the video | House/Senate video archives + ASR transcription pipeline (own build; significant but tractable cost). Prioritize: floor sessions on final passage days + major calendars |
| **Committee hearing transcripts** | Same — witness lists say who; only audio says what | Same ASR pipeline over committee broadcast archives |
| **Local campaign finance** (city/county/school candidates file locally, not with TEC) | Local officials become legislators; local fights become state preemption fights | Per-jurisdiction portals (Houston, Dallas, San Antonio, Austin publish PDFs/portals of varying quality); ingest top-10 cities + fast-growing suburbs opportunistically |
| **Federal layer for Texas delegation** | Clients rarely stop at the state line | FEC API, Congress.gov API, LDA lobbying filings — well-structured, add when product demands |
| **Election results, precinct-level** | Primary-threat modeling, district political texture | Texas Legislative Council / data.capitol.texas.gov election returns by district; county clerk canvasses; OpenElections project |
| **District demographics/economics** | "How does this play in the member's district" | Census/ACS by legislative district; TLC redistricting data (shapefiles + demographics) |
| **State contracts & procurement detail** | Who profits from a program; vendor politics | Comptroller contract listings + LBB contracts database; per-agency procurement pages; TxSmartBuy |
| **Appointee database with history** | Boards/commissions decide quasi-legislative questions | Governor's appointments press releases (build the table ourselves); Senate Nominations committee records for confirmations |
| **Dark-money / 501(c)(4) activity** | Influence that TEC never sees | IRS 990s (ProPublica Nonprofit Explorer API), FCC political files for broadcast buys, Meta/Google ad libraries. Partial by design — label the incompleteness |

## 2. Gaps that are structural (label, don't fake)

- **Mailers and opposition files.** Direct mail, push polls, and oppo books are private.
  No archive exists. LobbyBook can hold what surfaces in news coverage and litigation
  exhibits, and could crowdsource scans from users — but must never imply completeness.
- **The genuinely private layer:** text threads, caucus-room agreements, leadership
  handshakes, who actually asked for the amendment. The documentary record shows outcomes
  and registrations, not intentions. LobbyBook's positioning must be "the complete
  *documentary* memory" — the tool that makes the human lobbyist's private knowledge more
  valuable, not a claimed replacement for it.
- **Why-it-died causality.** A bill's death is recorded; its cause usually isn't. Momentum
  and survival models must present base rates and documented events, never invented
  narrative causes.
- **Social media completeness.** X/Facebook are primary statement channels; API access is
  expensive/unstable and archives are partial. Ingest what's licensable, snapshot
  officials' accounts where terms allow, and treat absence of a post as no evidence.
- **Paywalled insider press** (Quorum Report, etc.). License it or link out; don't scrape.

## 3. Product implications

1. Ship a **coverage manifest** the assistant can consult: for every corpus, what years,
   chambers, and record types are ingested — so "not in my records" beats a confident
   wrong answer.
2. Build **staff, appointee, and local-finance tables ourselves** from snapshot-diffing —
   these are the highest-value proprietary gap-fills and nobody sells them well.
3. Treat the ASR transcript layer as the single biggest unlock ranked against cost:
   it converts two "gap" rows into first-class corpora that almost no competitor has.
