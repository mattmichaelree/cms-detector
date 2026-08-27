"""Agency strategic plans — discovery by known URL, dedup by cover vintage.

Spec: docs/texas-politics-audit/03-deep-dives/10-agency-strategic-plans.md.

Every Texas agency files a five-year strategic plan under joint OBPP/LBB
instructions, and the plans are genuinely useful: they are the agency's own
voice crediting the enacted bills that drive five years of its action. The
audit's findings about *getting* them shape this module completely:

  * **There is no central machine-readable index.** ~200 agencies publish to
    their own sites under at least three different URL conventions, and the
    LBB's own ``agency_docs.aspx`` portal drives its links through JS postbacks
    that plain HTTP cannot follow. So this connector does not pretend an index
    exists: it carries a curated :data:`SEED_PLANS` list of verified URLs plus
    :data:`SEED_INDEXES`, the per-agency listing pages that are crawlable, and
    grows one agency at a time.
  * **The filename lies about the vintage.** TEA's plan is served as
    ``lbb-strategic-plan-2024-final-2.pdf`` and its cover page reads
    ``FISCAL YEARS 2025 TO 2029 / Updated March 2025`` — verified live, and
    asserted in the tests. The dedup key is therefore
    ``(agency_code, doc_type, fy_range, cover_revision)`` read out of the
    cover page, never the filename and never the URL. Document identity stays
    on the URL (the docstore versions the bytes when a file is replaced in
    place); *plan* identity is the cover vintage.
  * **Fetches fail in ordinary ways.** The audit saw an HTTP 402 on one
    agency's LAR and a 404 on a guessed URL, so every seed carries its fetch
    outcome in ``strategic_plan_seed`` rather than vanishing.

Parsers are pure functions over bytes; every fetched artifact is stored in the
document store before it is parsed.
"""

from __future__ import annotations

import io
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from urllib.parse import urljoin

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

#: Nothing bigger than this comes over the wire. TEA's plan measured 5.76MB
#: live, so the cap is real headroom, not a formality.
MAX_DOWNLOAD = 8 * 1024 * 1024


@dataclass(frozen=True)
class SeedPlan:
    """One known-good plan URL. ``verified`` records how far it was checked:
    ``fetched`` = bytes pulled and parsed in the audit/tests; ``listed`` = the
    link came off the agency's own live index page but was not downloaded."""

    agency: str
    agency_code: str
    url: str
    doc_type: str = "strategic_plan"
    label: str | None = None
    verified: str = "listed"


#: Curated seeds. Extending coverage is a matter of appending rows here (and,
#: where an agency has one, an index page below) — deliberately the dullest
#: possible extension point, because the audit's finding is that discovery is
#: per-agency manual work with no shortcut.
SEED_PLANS: list[SeedPlan] = [
    SeedPlan(
        agency="Texas Education Agency",
        agency_code="701",
        url="https://tea.texas.gov/about-tea/government-relations-and-legal/government-relations/lbb-strategic-plan-2024-final-2.pdf",
        label="TEA Strategic Plan 2025-2029",
        verified="fetched",
    ),
    SeedPlan(
        agency="Texas Education Agency",
        agency_code="701",
        url="https://tea.texas.gov/about-tea/welcome-and-overview/2023-2027-tea-strategic-plan.pdf",
        label="TEA Strategic Plan 2023-2027",
    ),
    SeedPlan(
        agency="Texas Education Agency",
        agency_code="701",
        url="https://tea.texas.gov/about-tea/welcome-and-overview/2021-2025-tea-strategic-plan.pdf",
        label="TEA Strategic Plan 2021-2025",
    ),
    SeedPlan(
        agency="Texas Education Agency",
        agency_code="701",
        url="https://tea.texas.gov/about-tea/welcome-and-overview/tea-strategic-plan-2019-2023.pdf",
        label="TEA Strategic Plan 2019-2023",
    ),
    SeedPlan(
        agency="Texas Education Agency",
        agency_code="701",
        # Filename says 2016-21; the agency labels it 2017-2021. Second
        # independent instance of the filename-vintage trap.
        url="https://tea.texas.gov/about-tea/welcome-and-overview/2016-21-strategic-plan-signed.pdf",
        label="TEA Strategic Plan 2017-2021",
    ),
]

#: Agency listing pages that ARE crawlable with plain HTTP (unlike the LBB
#: portal). One page per agency; each yields that agency's retained cycles.
SEED_INDEXES: list[tuple[str, str, str]] = [
    (
        "Texas Education Agency",
        "701",
        "https://tea.texas.gov/about-tea/welcome-and-overview/tea-strategic-plan",
    ),
]

#: The five statewide-mandated rubric categories every action item is
#: justified against (verified verbatim in TEA's plan).
STATEWIDE_OBJECTIVES = (
    "Accountable to tax and fee payers",
    "Efficient",
    "Effective",
    "Attentive to customer service",
    "Transparent",
)

_ORDINAL_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_MONTHS = {
    m[:3].lower(): i + 1
    for i, m in enumerate(
        "January February March April May June July August September October "
        "November December".split()
    )
}

# ----------------------------------------------------------------- regexes
# Cover page. 'FISCAL YEARS 2025 TO 2029' — the true vintage, and the only
# place it appears.
FY_RANGE_RE = re.compile(
    r"FISCAL\s+YEARS?\s+(\d{4})\s*(?:TO|THROUGH|[-‐-―])\s*(\d{4})", re.I
)
# 'Updated March 2025' / 'Revised: June 3, 2024'
REVISION_RE = re.compile(
    r"\b(Updated|Revised|Amended|Revision)\s*:?\s*([A-Za-z]{3,9})\.?\s*(\d{1,2})?\s*,?\s*(\d{4})", re.I
)
COVER_DATE_RE = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s*(\d{4})\b")

GOAL_RE = re.compile(
    r"^\s*Strategic\s+(?:Priority|Goal)\s+"
    r"(One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|\d{1,2})\s*[:.]\s*(\S.*?)\s*$",
    re.I | re.M,
)
MISSION_RE = re.compile(
    r"^\s*(?:Agency\s+)?Mission(?:\s+Statement)?\s*$\n(.*?)"
    r"(?=^\s*(?:Agency\s+)?(?:Vision|Values|Philosophy|Goals?|Operational|Table of Contents)\b|\Z)",
    re.I | re.M | re.S,
)
VISION_RE = re.compile(
    r"^\s*(?:Agency\s+)?Vision(?:\s+Statement)?\s*$\n(.*?)"
    r"(?=^\s*(?:Agency\s+)?(?:Mission|Values|Philosophy|Goals?|Operational|Table of Contents)\b|\Z)",
    re.I | re.M | re.S,
)

BILL_RE = re.compile(
    r"\b(House Bill|Senate Bill|House Joint Resolution|Senate Joint Resolution|HB|SB|HJR|SJR)"
    r"\s*\.?\s*(\d{1,4})\b",
    re.I,
)
# '(88th Regular Legislative Session)' / '87th Legislature'
SESSION_LONG_RE = re.compile(
    r"\(?\s*(\d{2,3})(?:st|nd|rd|th)\s+"
    r"(Regular|First Called|Second Called|Third Called|Fourth Called|"
    r"1st Called|2nd Called|3rd Called|4th Called)?\s*"
    r"Legislat(?:ive\s+Session|ure)\s*\)?",
    re.I,
)
# ', 88-R' / '(88-R)'
SESSION_SHORT_RE = re.compile(r"\(?\b(\d{2,3})\s*[-‐-―]\s*(R|[1-4])\b\)?", re.I)
# '... in the 87th legislative session, the legislature allocated ... HB 1525'
SESSION_LEADING_RE = re.compile(r"\b(\d{2,3})(?:st|nd|rd|th)\s+legislat\w*\s+session", re.I)

BILL_TYPES = {
    "house bill": "HB", "senate bill": "SB",
    "house joint resolution": "HJR", "senate joint resolution": "SJR",
    "hb": "HB", "sb": "SB", "hjr": "HJR", "sjr": "SJR",
}
_CALLED_SEQ = {
    "first called": "1", "1st called": "1", "second called": "2", "2nd called": "2",
    "third called": "3", "3rd called": "3", "fourth called": "4", "4th called": "4",
}

# Page furniture: 'tea.texas.gov 3', a bare page number, 'Page 12 of 171'.
FOOTER_RE = re.compile(
    r"^\s*(?:\S+\.(?:gov|org|com|edu|us)\s*\|?\s*\d{0,4}|\d{1,4}|Page\s+\d{1,4}(?:\s+of\s+\d{1,4})?)\s*$",
    re.I,
)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------- parsers
def extract_pages(pdf_bytes: bytes) -> list[str]:
    """PDF bytes -> per-page text, page furniture stripped.

    Footers are removed before anything else runs: 'tea.texas.gov 3' otherwise
    lands inside the vision statement, which is exactly the field a citation
    would quote.
    """
    import pdfplumber

    out: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            lines = (page.extract_text() or "").splitlines()
            out.append("\n".join(ln for ln in lines if not FOOTER_RE.match(ln)))
    return out


def _norm_month(word: str) -> int | None:
    return _MONTHS.get((word or "")[:3].lower())


def parse_cover(cover_text: str) -> dict:
    """Cover page text -> the true vintage.

    The audit's version trap in one function: ``fy_range`` and
    ``cover_revision`` are the plan's identity, and they exist nowhere but
    here — not in the URL, not in the filename, not in the HTTP headers.
    """
    rec: dict = {
        "fy_start": None, "fy_end": None, "fy_range": None,
        "cover_revision": None, "cover_revision_raw": None, "cover_date": None,
    }
    fy = FY_RANGE_RE.search(cover_text)
    if fy:
        rec["fy_start"], rec["fy_end"] = int(fy.group(1)), int(fy.group(2))
        rec["fy_range"] = f"{fy.group(1)}-{fy.group(2)}"

    rev = REVISION_RE.search(cover_text)
    if rev:
        month = _norm_month(rev.group(2))
        year = rev.group(4)
        day = rev.group(3)
        rec["cover_revision_raw"] = " ".join(rev.group(0).split())
        if month and day:
            rec["cover_revision"] = f"{year}-{month:02d}-{int(day):02d}"
        elif month:
            rec["cover_revision"] = f"{year}-{month:02d}"
        else:
            rec["cover_revision"] = year

    # The base issue date ('JUNE 1, 2024'), distinct from the revision.
    for m in COVER_DATE_RE.finditer(cover_text):
        if rev and m.start() >= rev.start():
            continue
        month = _norm_month(m.group(1))
        if month:
            rec["cover_date"] = f"{m.group(3)}-{month:02d}-{int(m.group(2)):02d}"
            break
    return rec


def filename_vintage(url: str) -> dict:
    """Years implied by the filename — the thing you must NOT dedup on.

    Returned so the mismatch can be *asserted* rather than assumed:
    ``lbb-strategic-plan-2024-final-2.pdf`` -> ``{'label': '2024', 'years': [2024]}``,
    ``2016-21-strategic-plan-signed.pdf``  -> ``{'label': '2016-2021', 'years': [2016, 2021]}``.
    """
    base = url.rsplit("/", 1)[-1].split("?")[0]
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", base)
    rng = re.search(r"\b(19|20)(\d{2})\s*[-_]\s*(?:(19|20))?(\d{2})\b", stem)
    if rng:
        start = int(f"{rng.group(1)}{rng.group(2)}")
        end_prefix = rng.group(3) or rng.group(1)
        end = int(f"{end_prefix}{rng.group(4)}")
        if 1990 <= end <= 2100 and end >= start:
            return {"label": f"{start}-{end}", "years": [start, end], "basename": base}
    years = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", stem)]
    return {
        "label": "-".join(str(y) for y in years) or None,
        "years": years,
        "basename": base,
    }


def parse_mission_vision(text: str) -> dict:
    def _grab(pat: re.Pattern) -> str | None:
        m = pat.search(text)
        if not m:
            return None
        body = " ".join(m.group(1).split())
        return body or None

    return {"mission": _grab(MISSION_RE), "vision": _grab(VISION_RE)}


def parse_goals(text: str) -> list[dict]:
    """Strategic priorities/goals, deduped by ordinal.

    Plans list their goals twice — once in the table of contents with dot
    leaders and a page range, once as a body heading. The body heading wins
    (the TOC truncates), and the leaders are stripped either way.
    """
    found: dict[int, dict] = {}
    for m in GOAL_RE.finditer(text):
        raw = m.group(1).lower()
        ordinal = _ORDINAL_WORDS.get(raw) or (int(raw) if raw.isdigit() else None)
        if ordinal is None:
            continue
        title = re.sub(r"[\s.]*\.{3,}[\s.]*[\d–-]*\s*$", "", m.group(2)).strip(" .")
        title = " ".join(title.split())
        if not title:
            continue
        prev = found.get(ordinal)
        # A word-ordinal heading is the body form; digits are the TOC form.
        if prev is None or (not raw.isdigit() and prev["from_toc"]):
            found[ordinal] = {"ordinal": ordinal, "title": title, "from_toc": raw.isdigit()}
    return [
        {"ordinal": g["ordinal"], "title": g["title"]}
        for g in sorted(found.values(), key=lambda g: g["ordinal"])
    ]


def _session_code(leg: str, kind: str | None) -> str:
    seq = _CALLED_SEQ.get((kind or "").strip().lower())
    return f"{leg}{seq}" if seq else f"{leg}R"


def mine_bill_citations(text: str, window: int = 90, back_window: int = 170) -> list[dict]:
    """Enacted-bill citations, session-qualified where the plan qualifies them.

    A plan names bills three ways, all verified in TEA's:
    ``House Bill 3 (86th Regular Legislative Session)``, ``HB 1605 (88-R)``,
    and bare ``HB3``. Only the first two are self-qualifying, so the session is
    read from a window *after* the number; failing that, from the nearest
    preceding "Nth legislative session" phrase, which is marked
    ``session_source='leading'`` and downgraded to derived provenance because
    the plan did not put them together.

    Unqualified citations are kept unresolved on purpose: TEA's plan cites
    **two different HB 3s** (86R's school finance act and 88R's school-safety
    act), so guessing a session for a bare 'HB3' would fabricate an edge.
    """
    flat = " ".join(text.split())
    out: list[dict] = []
    for m in BILL_RE.finditer(flat):
        btype = BILL_TYPES.get(m.group(1).lower())
        if not btype:
            continue
        number = int(m.group(2))
        fwd = flat[m.end(): m.end() + window]
        session, source = None, None

        long_m = SESSION_LONG_RE.search(fwd)
        short_m = SESSION_SHORT_RE.search(fwd[:24])
        if long_m and long_m.start() <= 3:
            session, source = _session_code(long_m.group(1), long_m.group(2)), "trailing"
        elif short_m:
            code = short_m.group(2).upper()
            session = f"{short_m.group(1)}{'R' if code == 'R' else code}"
            source = "trailing"
        else:
            back = flat[max(0, m.start() - back_window): m.start()]
            lead = list(SESSION_LEADING_RE.finditer(back))
            if lead:
                session, source = f"{lead[-1].group(1)}R", "leading"

        out.append(
            {
                "bill_type": btype,
                "number": number,
                "session_id": session,
                "session_source": source,
                "bill_id": f"{session}-{btype}{number}" if session else None,
                "bill_key": f"{session or '?'}-{btype}{number}",
                "raw": m.group(0),
                "context": flat[max(0, m.start() - 60): m.end() + 120].strip(),
            }
        )
    return out


def dedupe_citations(citations: list[dict], resolve: bool = True) -> list[dict]:
    """Collapse repeats to one row per (bill_type, number, session).

    With ``resolve`` (the default), an unqualified mention is folded into the
    qualified one **only when the document qualifies that bill number with
    exactly one session** — ``session_source`` becomes ``'document'`` and the
    edge drops to derived provenance. TEA's plan is the reason for the
    restriction: it cites HB 3 as both 86R (school finance) and 88R (school
    safety), so its bare ``HB3`` mentions stay unresolved, while ``HB 3906``,
    qualified only as 86R, safely folds in.
    """
    qualified_sessions: dict[str, set[str]] = {}
    for c in citations:
        if c["session_id"]:
            qualified_sessions.setdefault(f"{c['bill_type']}{c['number']}", set()).add(
                c["session_id"]
            )

    merged: dict[str, dict] = {}
    for c in citations:
        cite = dict(c)
        if resolve and not cite["session_id"]:
            sessions = qualified_sessions.get(f"{cite['bill_type']}{cite['number']}", set())
            if len(sessions) == 1:
                session = next(iter(sessions))
                cite.update(
                    session_id=session,
                    session_source="document",
                    bill_id=f"{session}-{cite['bill_type']}{cite['number']}",
                    bill_key=f"{session}-{cite['bill_type']}{cite['number']}",
                )
        rec = merged.get(cite["bill_key"])
        if rec is None:
            merged[cite["bill_key"]] = {**cite, "mentions": 1}
        else:
            rec["mentions"] += 1
            # Prefer the strongest qualification we saw for this bill.
            rank = {"trailing": 3, "leading": 2, "document": 1, None: 0}
            if rank[cite["session_source"]] > rank[rec["session_source"]]:
                rec.update(session_source=cite["session_source"], context=cite["context"])
    return sorted(
        merged.values(), key=lambda c: (c["session_id"] or "zzz", c["bill_type"], c["number"])
    )


def parse_plan(content: bytes, url: str | None = None) -> dict:
    """A plan PDF -> cover vintage, mission/vision, goals, bill citations.

    Pure over bytes. ``url`` is optional and used only to report the filename
    vintage alongside the cover vintage; nothing about the plan's identity
    depends on it.
    """
    pages = extract_pages(content)
    cover = parse_cover(pages[0] if pages else "")
    if not cover["fy_range"]:
        # A few agencies push the vintage onto an inside cover.
        for page in pages[1:3]:
            more = parse_cover(page)
            if more["fy_range"]:
                cover = {**cover, **{k: v for k, v in more.items() if v}}
                break
    text = "\n".join(pages)
    rec: dict = {
        **cover,
        **parse_mission_vision(text),
        "goals": parse_goals(text),
        "citations": dedupe_citations(mine_bill_citations(text)),
        "pages": len(pages),
        "statewide_objective_blocks": len(
            re.findall(r"Support Each Statewide Objective", text, re.I)
        ),
    }
    if url:
        fn = filename_vintage(url)
        rec["filename_vintage"] = fn["label"]
        rec["filename_disagrees"] = filename_disagrees(fn, cover)
    return rec


def filename_disagrees(fn: dict, cover: dict) -> bool:
    """True when the filename's years are not the cover's FY range.

    Both TEA files tested disagree — one says 2024 for a FY2025-2029 plan, the
    other says 2016-21 for a plan the agency labels 2017-2021. This is the
    reason the dedup key ignores filenames.
    """
    if not cover.get("fy_range"):
        return True
    return sorted(fn.get("years") or []) != [cover["fy_start"], cover["fy_end"]]


def plan_key(agency_code: str, doc_type: str, fy_range: str | None, cover_revision: str | None) -> str:
    """The dedup key the audit demands: cover vintage, never the filename."""
    return f"{agency_code}:{doc_type}:{fy_range or 'unknown'}:{cover_revision or 'original'}"


# -------------------------------------------------------- index discovery
_A_RE = re.compile(r"<a\b[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def discover_plan_urls(content: bytes, base_url: str) -> list[dict]:
    """An agency listing page -> candidate plan PDFs.

    Works only where an agency actually publishes a listing page in plain HTML.
    The LBB's own portal does not (JS postbacks), which is the whole reason
    :data:`SEED_PLANS` exists.
    """
    html = content.decode("utf-8", errors="replace")
    seen: set[str] = set()
    out: list[dict] = []
    for m in _A_RE.finditer(html):
        href = unescape(m.group(1)).strip()
        if ".pdf" not in href.lower():
            continue
        label = " ".join(unescape(_TAG_RE.sub(" ", m.group(2))).split())
        blob = f"{href} {label}".lower()
        if "strategic plan" not in label.lower() and "strategic-plan" not in href.lower():
            continue
        if "customer service" in blob or "survey" in blob:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        fy = re.search(r"\b((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})\b", label)
        out.append(
            {
                "url": url,
                "label": label or None,
                "label_fy_range": f"{fy.group(1)}-{fy.group(2)}" if fy else None,
                "filename_vintage": filename_vintage(url)["label"],
            }
        )
    return out


# -------------------------------------------------------------- connector
@register
class StratPlansConnector(Connector):
    """Curated-seed strategic-plan ingestion, deduped on cover vintage."""

    name = "stratplans"
    tier = 2
    cadence = "biennial"

    DDL = """
    -- Plan identity is the COVER vintage. Two files with different names and
    -- different bytes are the same plan if the cover says so; one filename
    -- reused across cycles is not.
    CREATE TABLE IF NOT EXISTS strategic_plan (
        id             TEXT PRIMARY KEY,   -- '<agency_code>:<doc_type>:<fy_range>:<cover_revision>'
        agency         TEXT,
        agency_code    TEXT,
        doc_type       TEXT,
        fy_start       INTEGER,
        fy_end         INTEGER,
        fy_range       TEXT,
        cover_revision TEXT,
        cover_date     TEXT,
        filename_vintage  TEXT,            -- what the URL claims (kept to prove it lies)
        filename_disagrees INTEGER,
        mission        TEXT,
        vision         TEXT,
        pages          INTEGER,
        url            TEXT,
        doc_id         TEXT,
        UNIQUE (agency_code, doc_type, fy_range, cover_revision)
    );

    CREATE TABLE IF NOT EXISTS strategic_plan_goal (
        id      INTEGER PRIMARY KEY,
        plan_id TEXT NOT NULL,
        ordinal INTEGER,
        title   TEXT,
        UNIQUE (plan_id, ordinal)
    );

    CREATE TABLE IF NOT EXISTS strategic_plan_bill (
        id             INTEGER PRIMARY KEY,
        plan_id        TEXT NOT NULL,
        bill_key       TEXT NOT NULL,      -- '88R-HB1605' | '?-HB3' when unqualified
        bill_type      TEXT,
        number         INTEGER,
        session_id     TEXT,               -- NULL when the plan did not qualify it
        bill_id        TEXT,
        session_source TEXT,               -- 'trailing' | 'leading' | NULL
        mentions       INTEGER,
        context        TEXT,
        UNIQUE (plan_id, bill_key)
    );

    -- Seeds and their fetch outcomes, so a 402/404 is recorded coverage data
    -- rather than a silently missing agency.
    CREATE TABLE IF NOT EXISTS strategic_plan_seed (
        url         TEXT PRIMARY KEY,
        agency      TEXT,
        agency_code TEXT,
        doc_type    TEXT,
        label       TEXT,
        status      INTEGER,
        size_bytes  INTEGER,
        checked_at  TEXT,
        plan_id     TEXT,
        note        TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_plan_agency ON strategic_plan(agency_code);
    CREATE INDEX IF NOT EXISTS idx_plan_bill_key ON strategic_plan_bill(bill_key);
    """

    # -- ingestion -------------------------------------------------------
    def ingest_plan(
        self,
        conn: sqlite3.Connection,
        seed: SeedPlan,
        content: bytes | None = None,
    ) -> dict:
        """One seed -> one ``strategic_plan`` row plus goals, bills, edges.

        Pass ``content`` to ingest bytes already in hand (that is how the
        offline tests exercise the whole write path). Otherwise the URL is
        size-probed, fetched, stored, and only then parsed.
        """
        status: int | None = None
        size: int | None = None
        if content is None:
            probe = fetcher().head(seed.url)
            status = probe.status_code
            declared = probe.headers.get("Content-Length")
            size = int(declared) if declared and declared.isdigit() else None
            if status >= 400:
                return self._record_seed(conn, seed, status, size, None, f"HEAD {status}")
            if size is not None and size > MAX_DOWNLOAD:
                return self._record_seed(conn, seed, status, size, None, "too_large")
            resp = fetcher().get(seed.url)
            status = resp.status_code
            if status != 200:
                return self._record_seed(conn, seed, status, size, None, f"GET {status}")
            content = resp.content
            size = len(content)
            if size > MAX_DOWNLOAD:
                return self._record_seed(conn, seed, status, size, None, "too_large")

        doc_id = f"stratplans:{seed.doc_type}:{seed.agency_code}:{filename_vintage(seed.url)['basename']}"
        _, changed = store_document(
            conn,
            doc_id=doc_id,
            source_family="stratplans",
            content=content,
            url=seed.url,
            native_id=seed.agency_code,
            doc_type=seed.doc_type,
            authority="B",  # agency-authored self-assessment; template is A
        )
        parsed = parse_plan(content, url=seed.url)
        plan_id = self.store_plan(conn, seed, parsed, doc_id)
        self._record_seed(conn, seed, status or 200, size or len(content), plan_id, None)
        conn.commit()
        return {
            "plan_id": plan_id,
            "doc_id": doc_id,
            "changed": changed,
            "url": seed.url,
            "size_bytes": size or len(content),
            **{
                k: parsed[k]
                for k in (
                    "fy_range", "cover_revision", "cover_revision_raw", "cover_date",
                    "filename_vintage", "filename_disagrees", "mission", "vision", "pages",
                )
            },
            "goals": parsed["goals"],
            "citations": parsed["citations"],
        }

    def _record_seed(
        self,
        conn: sqlite3.Connection,
        seed: SeedPlan,
        status: int | None,
        size: int | None,
        plan_id: str | None,
        note: str | None,
    ) -> dict:
        dbx.upsert(
            conn,
            "strategic_plan_seed",
            {
                "url": seed.url,
                "agency": seed.agency,
                "agency_code": seed.agency_code,
                "doc_type": seed.doc_type,
                "label": seed.label,
                "status": status,
                "size_bytes": size,
                "checked_at": _now(),
                "plan_id": plan_id,
                "note": note,
            },
            ["url"],
        )
        conn.commit()
        if plan_id:
            return {"plan_id": plan_id, "url": seed.url, "status": status}
        return {"skipped": note, "url": seed.url, "status": status, "size_bytes": size}

    def store_plan(
        self, conn: sqlite3.Connection, seed: SeedPlan, parsed: dict, doc_id: str
    ) -> str:
        plan_id = plan_key(
            seed.agency_code, seed.doc_type, parsed["fy_range"], parsed["cover_revision"]
        )
        dbx.upsert(
            conn,
            "strategic_plan",
            {
                "id": plan_id,
                "agency": seed.agency,
                "agency_code": seed.agency_code,
                "doc_type": seed.doc_type,
                "fy_start": parsed["fy_start"],
                "fy_end": parsed["fy_end"],
                "fy_range": parsed["fy_range"],
                "cover_revision": parsed["cover_revision"],
                "cover_date": parsed["cover_date"],
                "filename_vintage": parsed.get("filename_vintage"),
                "filename_disagrees": int(bool(parsed.get("filename_disagrees"))),
                "mission": parsed["mission"],
                "vision": parsed["vision"],
                "pages": parsed["pages"],
                "url": seed.url,
                "doc_id": doc_id,
            },
            ["id"],
        )
        dbx.add_edge(
            conn, "agency_code", seed.agency_code, "files", seed.doc_type, plan_id,
            "explicit", doc_id,
        )
        for goal in parsed["goals"]:
            dbx.upsert(
                conn,
                "strategic_plan_goal",
                {"plan_id": plan_id, "ordinal": goal["ordinal"], "title": goal["title"]},
                ["plan_id", "ordinal"],
            )
        for cite in parsed["citations"]:
            dbx.upsert(
                conn,
                "strategic_plan_bill",
                {
                    "plan_id": plan_id,
                    "bill_key": cite["bill_key"],
                    "bill_type": cite["bill_type"],
                    "number": cite["number"],
                    "session_id": cite["session_id"],
                    "bill_id": cite["bill_id"],
                    "session_source": cite["session_source"],
                    "mentions": cite.get("mentions", 1),
                    "context": cite["context"],
                },
                ["plan_id", "bill_key"],
            )
            if cite["bill_id"]:
                dbx.add_edge(
                    conn, seed.doc_type, plan_id, "cites", "bill", cite["bill_id"],
                    # The plan names the bill AND its session: explicit. When the
                    # session came from a preceding sentence it is our inference
                    # about adjacency, so it is only derived.
                    "explicit" if cite["session_source"] == "trailing" else "derived",
                    doc_id,
                    span=cite["raw"],
                )
            else:
                dbx.add_edge(
                    conn, seed.doc_type, plan_id, "cites", "bill_number",
                    f"{cite['bill_type']}{cite['number']}", "explicit", doc_id,
                    span=cite["raw"],
                )
        return plan_id

    # -- discovery -------------------------------------------------------
    def discover(self, conn: sqlite3.Connection, agency: str, agency_code: str, index_url: str) -> dict:
        """Crawl one agency listing page and record the plan URLs it offers."""
        resp = fetcher().get(index_url)
        resp.raise_for_status()
        doc_id = f"stratplans:index:{agency_code}"
        store_document(
            conn,
            doc_id=doc_id,
            source_family="stratplans",
            content=resp.content,
            url=index_url,
            native_id=agency_code,
            doc_type="strategic_plan_index",
            authority="A",
        )
        found = discover_plan_urls(resp.content, index_url)
        known = {s.url for s in SEED_PLANS}
        for cand in found:
            seed = SeedPlan(
                agency=agency, agency_code=agency_code, url=cand["url"], label=cand["label"]
            )
            existing = conn.execute(
                "SELECT plan_id FROM strategic_plan_seed WHERE url=?", (cand["url"],)
            ).fetchone()
            if existing is None:
                self._record_seed(conn, seed, None, None, None, "discovered")
        conn.commit()
        return {
            "agency": agency,
            "index_url": index_url,
            "found": found,
            "urls": [c["url"] for c in found],
            "new": [c["url"] for c in found if c["url"] not in known],
            "doc_id": doc_id,
        }

    # -- drivers ---------------------------------------------------------
    def backfill(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """backfill(agency_code='701', limit=2) — walk the seed list."""
        code = kwargs.get("agency_code")
        limit = int(kwargs.get("limit", len(SEED_PLANS)))
        seeds = [s for s in SEED_PLANS if code is None or s.agency_code == code][:limit]
        results = [self.ingest_plan(conn, s) for s in seeds]
        ingested = [r for r in results if r.get("plan_id")]
        return {
            "seeds": len(seeds),
            "ingested": len(ingested),
            "skipped": [r for r in results if not r.get("plan_id")],
            "plans": [r["plan_id"] for r in ingested],
        }

    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """Re-crawl the index pages; ingest anything the seed list has not seen."""
        out = []
        for agency, code, url in SEED_INDEXES:
            out.append(self.discover(conn, agency, code, url))
        return {
            "indexes": len(out),
            "discovered": sum(len(o["found"]) for o in out),
            "new": [u for o in out for u in o["new"]],
        }

    # -- smoke -----------------------------------------------------------
    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """3 live requests: the TEA index page, a HEAD on the current plan, and
        the plan itself."""
        index = self.discover(conn, *SEED_INDEXES[0])
        seed = SEED_PLANS[0]
        plan = self.ingest_plan(conn, seed)
        if not plan.get("plan_id"):
            return SmokeResult(ok=False, detail=f"{seed.url}: {plan.get('skipped')}", stats=plan)

        qualified = [c for c in plan["citations"] if c["session_id"]]
        ok = bool(plan["fy_range"]) and len(plan["citations"]) >= 1 and plan["filename_disagrees"]
        detail = (
            f"{seed.agency}: filename says {plan['filename_vintage']!r} but the cover says "
            f"FY {plan['fy_range']} / {plan['cover_revision_raw']!r} "
            f"(plan_id {plan['plan_id']}); {plan['pages']} pages, "
            f"{len(plan['goals'])} goals, {len(plan['citations'])} bill citations "
            f"({len(qualified)} session-qualified: "
            f"{[c['bill_key'] for c in qualified][:8]}); "
            f"index page offered {len(index['found'])} plan URLs"
        )
        return SmokeResult(
            ok=ok,
            detail=detail,
            stats={
                "plan_id": plan["plan_id"],
                "fy_range": plan["fy_range"],
                "cover_revision": plan["cover_revision"],
                "filename_vintage": plan["filename_vintage"],
                "goals": len(plan["goals"]),
                "citations": len(plan["citations"]),
                "qualified": [c["bill_key"] for c in qualified],
                "index_urls": index["urls"],
                "requests": 3,
            },
        )
