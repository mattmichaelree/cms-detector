-- LobbyBook canonical schema (SQLite dialect, kept Postgres-portable).
-- Design rules (docs/texas-politics-audit/04-knowledge-graph.md):
--   * documents are immutable; entities evolve with valid_from/valid_to
--   * every derived assertion carries a provenance class and a citation
--   * session-scoped composite keys everywhere a Texas identifier demands it

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- documents
CREATE TABLE IF NOT EXISTS document (
    id            TEXT PRIMARY KEY,          -- '<source_family>:<native id or url hash>'
    source_family TEXT NOT NULL,
    native_id     TEXT,
    url           TEXT,
    doc_type      TEXT,
    session_id    TEXT,
    published_at  TEXT,
    authority     TEXT,                      -- A/B/C/D/E per the audit
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS document_version (
    id          INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES document(id),
    version_no  INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    blob_path   TEXT NOT NULL,              -- relative path under the blob root
    http_etag   TEXT,
    http_last_modified TEXT,
    UNIQUE (document_id, sha256)
);

-- ------------------------------------------------------------------- spine
CREATE TABLE IF NOT EXISTS session (
    id          TEXT PRIMARY KEY,            -- TLO convention: '89R', '891'..'894'
    legislature INTEGER NOT NULL,
    seq         INTEGER NOT NULL DEFAULT 0,  -- 0 = regular, N = Nth called
    convened    TEXT,
    adjourned   TEXT,
    label       TEXT,
    approximate INTEGER NOT NULL DEFAULT 0   -- 1 = dates formulaic, pending LRL refresh
);

CREATE TABLE IF NOT EXISTS person (
    id             TEXT PRIMARY KEY,         -- canonical (OpenStates id when known)
    canonical_name TEXT NOT NULL,
    sort_name      TEXT
);

CREATE TABLE IF NOT EXISTS person_xref (
    system      TEXT NOT NULL,               -- 'openstates' | 'lrl' | 'tec' | 'legiscan' | ...
    external_id TEXT NOT NULL,
    person_id   TEXT NOT NULL REFERENCES person(id),
    PRIMARY KEY (system, external_id)
);

CREATE TABLE IF NOT EXISTS person_name (
    person_id TEXT NOT NULL REFERENCES person(id),
    name_raw  TEXT NOT NULL,
    source    TEXT,
    PRIMARY KEY (person_id, name_raw)
);

CREATE TABLE IF NOT EXISTS role_tenure (
    id         INTEGER PRIMARY KEY,
    person_id  TEXT NOT NULL REFERENCES person(id),
    role       TEXT NOT NULL,                -- 'rep' | 'sen' | 'governor' | 'chair' | ...
    body       TEXT,
    district   TEXT,
    party      TEXT,
    valid_from TEXT,
    valid_to   TEXT,
    source_doc TEXT REFERENCES document(id)
);

CREATE TABLE IF NOT EXISTS organization (
    id             TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    org_type       TEXT                      -- agency|corp|association|nonprofit|pac|campaign|party|local_gov|university|firm|court
);

CREATE TABLE IF NOT EXISTS org_xref (
    system      TEXT NOT NULL,
    external_id TEXT NOT NULL,
    org_id      TEXT NOT NULL REFERENCES organization(id),
    PRIMARY KEY (system, external_id)
);

CREATE TABLE IF NOT EXISTS org_name (
    org_id   TEXT NOT NULL REFERENCES organization(id),
    name_raw TEXT NOT NULL,
    source   TEXT,
    PRIMARY KEY (org_id, name_raw)
);

-- ------------------------------------------------------------- legislative
CREATE TABLE IF NOT EXISTS bill (
    id         TEXT PRIMARY KEY,             -- '89R-HB1'
    session_id TEXT NOT NULL REFERENCES session(id),
    bill_type  TEXT NOT NULL,                -- HB SB HJR SJR HCR SCR HR SR
    number     INTEGER NOT NULL,
    caption    TEXT,
    UNIQUE (session_id, bill_type, number)
);

CREATE TABLE IF NOT EXISTS bill_version (
    id         INTEGER PRIMARY KEY,
    bill_id    TEXT NOT NULL REFERENCES bill(id),
    stage_code TEXT NOT NULL,                -- I/H/S/E/F per TLO version letters
    stage_name TEXT,
    date       TEXT,
    doc_id     TEXT REFERENCES document(id),
    UNIQUE (bill_id, stage_code)
);

CREATE TABLE IF NOT EXISTS bill_action (
    id          INTEGER PRIMARY KEY,
    bill_id     TEXT NOT NULL REFERENCES bill(id),
    seq         INTEGER NOT NULL,
    date        TEXT,
    chamber     TEXT,
    description TEXT NOT NULL,
    action_code TEXT,
    journal_cite TEXT,
    UNIQUE (bill_id, seq)
);

CREATE TABLE IF NOT EXISTS bill_author (
    bill_id   TEXT NOT NULL REFERENCES bill(id),
    name_raw  TEXT NOT NULL,
    role      TEXT NOT NULL,                 -- author|coauthor|sponsor|cosponsor
    person_id TEXT REFERENCES person(id),
    PRIMARY KEY (bill_id, name_raw, role)
);

CREATE TABLE IF NOT EXISTS bill_subject (
    bill_id      TEXT NOT NULL REFERENCES bill(id),
    subject_code TEXT,
    subject_text TEXT NOT NULL,
    PRIMARY KEY (bill_id, subject_text)
);

CREATE TABLE IF NOT EXISTS bill_companion (
    bill_id      TEXT NOT NULL REFERENCES bill(id),
    companion_id TEXT NOT NULL,
    PRIMARY KEY (bill_id, companion_id)
);

CREATE TABLE IF NOT EXISTS committee (
    id          TEXT PRIMARY KEY,            -- '89R-H-C450' (session-scoped)
    session_id  TEXT REFERENCES session(id),
    chamber     TEXT,
    native_code TEXT,                        -- 'C450'
    name        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hearing (
    id           TEXT PRIMARY KEY,           -- tlodocs token 'C4502026081908001' when known
    committee_id TEXT REFERENCES committee(id),
    scheduled_at TEXT,
    location     TEXT,
    kind         TEXT,
    notice_doc   TEXT REFERENCES document(id),
    minutes_doc  TEXT REFERENCES document(id),
    witness_doc  TEXT REFERENCES document(id),
    comments_doc TEXT REFERENCES document(id)
);

CREATE TABLE IF NOT EXISTS hearing_bill (
    hearing_id TEXT NOT NULL REFERENCES hearing(id),
    bill_id    TEXT NOT NULL,
    PRIMARY KEY (hearing_id, bill_id)
);

CREATE TABLE IF NOT EXISTS witness_slip (
    id         INTEGER PRIMARY KEY,
    hearing_id TEXT REFERENCES hearing(id),
    bill_id    TEXT,
    name_raw   TEXT NOT NULL,
    org_raw    TEXT,
    is_self    INTEGER NOT NULL DEFAULT 0,
    position   TEXT NOT NULL,                -- for|against|on
    testified  INTEGER NOT NULL DEFAULT 1,   -- 0 = registered only
    person_id  TEXT REFERENCES person(id),
    org_id     TEXT REFERENCES organization(id)
);

CREATE TABLE IF NOT EXISTS amendment (
    id          INTEGER PRIMARY KEY,
    bill_id     TEXT NOT NULL REFERENCES bill(id),
    chamber     TEXT,
    reading     TEXT,
    number      TEXT,
    author_raw  TEXT,
    disposition TEXT,                        -- adopted|failed|withdrawn|tabled|point_of_order
    action_date TEXT,
    journal_cite TEXT,
    doc_id      TEXT REFERENCES document(id),
    UNIQUE (bill_id, chamber, reading, number)
);

CREATE TABLE IF NOT EXISTS vote (
    id         TEXT PRIMARY KEY,             -- '89R-H-R4167' (record no) or synthesized
    session_id TEXT REFERENCES session(id),
    chamber    TEXT NOT NULL,
    bill_id    TEXT,
    record_no  TEXT,
    date       TEXT,
    question   TEXT,
    yeas       INTEGER,
    nays       INTEGER,
    pnv        INTEGER,
    absent     INTEGER,
    journal_cite TEXT,
    doc_id     TEXT REFERENCES document(id)
);

CREATE TABLE IF NOT EXISTS vote_cast (
    vote_id   TEXT NOT NULL REFERENCES vote(id),
    name_raw  TEXT NOT NULL,
    position  TEXT NOT NULL,                 -- yea|nay|pnv|absent|absent_excused
    person_id TEXT REFERENCES person(id),
    PRIMARY KEY (vote_id, name_raw)
);

CREATE TABLE IF NOT EXISTS fiscal_note (
    id           INTEGER PRIMARY KEY,
    bill_id      TEXT NOT NULL REFERENCES bill(id),
    version_code TEXT NOT NULL,
    date         TEXT,
    doc_id       TEXT REFERENCES document(id),
    summary      TEXT,
    UNIQUE (bill_id, version_code)
);

CREATE TABLE IF NOT EXISTS fiscal_estimate (
    fiscal_note_id INTEGER NOT NULL REFERENCES fiscal_note(id),
    fiscal_year    INTEGER NOT NULL,
    fund           TEXT NOT NULL,
    amount         REAL,
    PRIMARY KEY (fiscal_note_id, fiscal_year, fund)
);

-- ----------------------------------------------------------- regulatory / legal
CREATE TABLE IF NOT EXISTS rule_action (
    trd           TEXT PRIMARY KEY,          -- 'TRD-202603360'
    agency_raw    TEXT,
    agency_org_id TEXT REFERENCES organization(id),
    action_type   TEXT NOT NULL,             -- proposed|adopted|withdrawn|emergency|emergency_renewal|review_proposed|review_adopted
    tac_cite      TEXT,
    register_cite TEXT,
    issue_date    TEXT,
    filed_date    TEXT,
    comment_end   TEXT,
    effective     TEXT,
    adopts_trd    TEXT,
    proposal_pub_date TEXT,           -- adoptions name the date their proposal published
    doc_id        TEXT REFERENCES document(id)
);

CREATE TABLE IF NOT EXISTS rule_authority (
    trd          TEXT NOT NULL REFERENCES rule_action(trd),
    statute_cite TEXT NOT NULL,
    PRIMARY KEY (trd, statute_cite)
);

CREATE TABLE IF NOT EXISTS rule_commenter (
    id       INTEGER PRIMARY KEY,
    trd      TEXT NOT NULL REFERENCES rule_action(trd),
    name_raw TEXT NOT NULL,
    org_id   TEXT REFERENCES organization(id),
    response TEXT
);

CREATE TABLE IF NOT EXISTS ag_opinion (
    number  TEXT PRIMARY KEY,               -- 'KP-0524'
    ag_code TEXT,
    date    TEXT,
    request_number TEXT,
    summary TEXT,
    status  TEXT NOT NULL DEFAULT 'active', -- active|overruled|modified|withdrawn
    status_note TEXT,
    doc_id  TEXT REFERENCES document(id)
);

CREATE TABLE IF NOT EXISTS ag_request (
    number        TEXT PRIMARY KEY,          -- 'RQ-0651-KP'
    date          TEXT,
    requestor_raw TEXT,
    doc_id        TEXT REFERENCES document(id)
);

CREATE TABLE IF NOT EXISTS executive_action (
    id       TEXT PRIMARY KEY,               -- 'EO:abbott:GA-57' | minted for proclamations
    kind     TEXT NOT NULL,                  -- eo|proclamation|special_session_call|veto
    governor TEXT,
    number   TEXT,
    date     TEXT,
    title    TEXT,
    bill_id  TEXT,
    renews_id TEXT,
    doc_id   TEXT REFERENCES document(id)
);

CREATE TABLE IF NOT EXISTS appointment (
    id           INTEGER PRIMARY KEY,
    governor     TEXT,
    appointee_raw TEXT NOT NULL,
    position     TEXT,
    board        TEXT,
    announced    TEXT,
    url          TEXT,
    person_id    TEXT REFERENCES person(id),
    UNIQUE (appointee_raw, board, announced)
);

CREATE TABLE IF NOT EXISTS court_opinion (
    id         TEXT PRIMARY KEY,             -- courtlistener cluster id or 'txcourts:<slug>'
    court      TEXT NOT NULL,
    docket     TEXT,
    style      TEXT,
    date_filed TEXT,
    citation   TEXT,
    kind       TEXT,                         -- majority|dissent|concurrence|per_curiam|memorandum|order
    doc_id     TEXT REFERENCES document(id)
);

CREATE TABLE IF NOT EXISTS opinion_cite (
    opinion_id TEXT NOT NULL REFERENCES court_opinion(id),
    cite_type  TEXT NOT NULL,                -- statute|rule|case
    cite       TEXT NOT NULL,
    PRIMARY KEY (opinion_id, cite_type, cite)
);

-- ------------------------------------------------------------- oversight
CREATE TABLE IF NOT EXISTS sunset_review (
    id         TEXT PRIMARY KEY,             -- '<agency_slug>:<cycle>'
    agency_raw TEXT NOT NULL,
    cycle      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sunset_recommendation (
    id             INTEGER PRIMARY KEY,
    review_id      TEXT NOT NULL REFERENCES sunset_review(id),
    number         TEXT,                     -- '1.1'
    rec_type       TEXT,                     -- statute|management|funding
    text           TEXT,
    outcome        TEXT,                     -- adopted|adopted_modified|not_adopted
    implementation TEXT,                     -- implemented|in_progress|partial|not_implemented
    bill_id        TEXT,
    doc_id         TEXT REFERENCES document(id)
);

CREATE TABLE IF NOT EXISTS interim_charge (
    id            INTEGER PRIMARY KEY,
    ordering_leg  INTEGER NOT NULL,
    issuer        TEXT,                      -- speaker|lt_governor
    committee_raw TEXT,
    charge_no     TEXT,
    charge_type   TEXT,                      -- study|monitoring
    text          TEXT NOT NULL,
    doc_id        TEXT REFERENCES document(id)
);

CREATE TABLE IF NOT EXISTS interim_report (
    id            TEXT PRIMARY KEY,          -- lrl call number or minted
    ordering_leg  INTEGER,
    committee_raw TEXT,
    title         TEXT,
    doc_id        TEXT REFERENCES document(id)
);

-- -------------------------------------------------------------- political
CREATE TABLE IF NOT EXISTS contribution (
    id           INTEGER PRIMARY KEY,        -- TEC contributionInfoId
    filer_id     TEXT NOT NULL,              -- TEC 8-digit filerIdent
    report_id    TEXT NOT NULL,
    contributor_raw TEXT,
    employer_raw TEXT,
    amount       REAL,
    date         TEXT,
    superseded   INTEGER NOT NULL DEFAULT 0,
    schedule     TEXT                        -- main|ss|t (double-count guard)
);

CREATE TABLE IF NOT EXISTS lobby_registration (
    id         INTEGER PRIMARY KEY,
    filer_id   TEXT NOT NULL,
    year       INTEGER NOT NULL,
    lobbyist_raw TEXT,
    client_raw TEXT,
    comp_low   REAL,
    comp_high  REAL,
    comp_exact REAL,
    subjects   TEXT
);

CREATE TABLE IF NOT EXISTS statement (
    id        TEXT PRIMARY KEY,              -- '<office>:<native id or url hash>'
    office    TEXT NOT NULL,
    actor_raw TEXT,
    person_id TEXT REFERENCES person(id),
    title     TEXT,
    published TEXT,
    captured  TEXT NOT NULL,
    url       TEXT,
    doc_id    TEXT REFERENCES document(id)
);

CREATE TABLE IF NOT EXISTS platform_plank (
    id         INTEGER PRIMARY KEY,
    party      TEXT NOT NULL,
    cycle      INTEGER NOT NULL,
    section    TEXT,
    subsection TEXT,
    number     TEXT,
    text       TEXT NOT NULL,
    doc_id     TEXT REFERENCES document(id),
    UNIQUE (party, cycle, section, subsection, number)
);

CREATE TABLE IF NOT EXISTS endorsement (
    id        INTEGER PRIMARY KEY,
    org_raw   TEXT NOT NULL,
    candidate_raw TEXT NOT NULL,
    cycle     INTEGER,
    date      TEXT,
    url       TEXT,
    org_id    TEXT REFERENCES organization(id),
    person_id TEXT REFERENCES person(id),
    UNIQUE (org_raw, candidate_raw, cycle)
);

CREATE TABLE IF NOT EXISTS news_item (
    url       TEXT PRIMARY KEY,
    outlet    TEXT NOT NULL,
    title     TEXT,
    published TEXT,
    byline    TEXT,
    categories TEXT,
    full_text_licensed INTEGER NOT NULL DEFAULT 0,
    doc_id    TEXT REFERENCES document(id)
);

-- ------------------------------------------------------------------ graph
CREATE TABLE IF NOT EXISTS edge (
    id         INTEGER PRIMARY KEY,
    src_type   TEXT NOT NULL,
    src_id     TEXT NOT NULL,
    predicate  TEXT NOT NULL,
    dst_type   TEXT NOT NULL,
    dst_id     TEXT NOT NULL,
    provenance TEXT NOT NULL CHECK (provenance IN ('explicit','derived','inferred')),
    confidence REAL,
    source_doc TEXT REFERENCES document(id),
    span       TEXT
);

-- NULL source_doc must still dedup (SQLite treats NULLs as distinct in UNIQUE
-- constraints), hence the expression index instead of a table constraint.
CREATE UNIQUE INDEX IF NOT EXISTS idx_edge_unique
    ON edge(src_type, src_id, predicate, dst_type, dst_id, COALESCE(source_doc, ''));

CREATE INDEX IF NOT EXISTS idx_edge_src ON edge(src_type, src_id, predicate);
CREATE INDEX IF NOT EXISTS idx_edge_dst ON edge(dst_type, dst_id, predicate);
CREATE INDEX IF NOT EXISTS idx_action_bill ON bill_action(bill_id);
CREATE INDEX IF NOT EXISTS idx_witness_bill ON witness_slip(bill_id);
CREATE INDEX IF NOT EXISTS idx_vote_bill ON vote(bill_id);
CREATE INDEX IF NOT EXISTS idx_contrib_filer ON contribution(filer_id);
CREATE INDEX IF NOT EXISTS idx_docver_doc ON document_version(document_id);
