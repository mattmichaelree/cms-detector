"""Sunset Advisory Commission — reviews, documents and recommendation outcomes.

Spec: docs/texas-politics-audit/03-deep-dives/11-sunset.md.

Three facts from the audit shape this module:

  * **The recommendation is the unit of value.** Every Sunset staff report
    numbers its proposals ``N.N`` and types them (*Change in Statute* vs
    *Management Action*); the Final Results version of the same report
    re-prints each one with the Legislature's verdict —
    ``Recommendation 1.1, Adopted as Modified — …`` / ``1.2, Not Adopted — …``.
    That is a state-published, machine-parsable outcome label per proposal,
    and nothing else in Texas politics publishes one.
  * **One PDF carries three voices.** A "Staff Report with Final Results"
    concatenates the Final Results summary, the Sunset Commission's decisions,
    and the original staff report — so the *same* recommendation number appears
    two or three times with different wording and sometimes different outcomes.
    Collapsing them would destroy the staff→commission→legislature delta the
    audit calls the lobbying-effectiveness proxy, so every occurrence is kept
    in ``sunset_recommendation_stage`` and only the latest stage is promoted to
    the headline ``sunset_recommendation`` row.  The stage is read off the PDF's
    own running footer ("… Staff Report with Final Results"), which is more
    reliable than the filename.
  * **Documents are replaced in place.** An agency page swaps "Staff Report"
    for "Staff Report with Commission Decisions" at the same slot and often the
    same URL, and the intermediate version disappears.  Every discovered
    document is therefore pushed through the docstore on sight, which versions
    by content hash — capture-on-publication, not capture-on-demand.

No API, no JSON, no sitemap: Drupal HTML plus PDFs, crawled politely.
"""

from __future__ import annotations

import re
import sqlite3
from html import unescape
from urllib.parse import urljoin

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

BASE = "https://www.sunset.texas.gov"
# /review-cycles 301s to the canonical path; the fetcher follows redirects.
CYCLE_INDEX = BASE + "/review-cycles"
AGENCY_INDEX = BASE + "/reviews-and-reports/agencies"
FUTURE_INDEX = BASE + "/reviews-and-reports/future-reviews-year"
# Agencies under review right now (16 entities in the 2026-27 cycle).
CURRENT_REVIEWS = BASE + "/reviews-and-reports"

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# "2024-2025 Review Cycle, 89th Legislative Session" (en dashes appear on the
# future-reviews page, hyphens on the past-cycles page).
CYCLE_SPAN_RE = re.compile(r"(\d{4})\s*[-–—]\s*(\d{4})")
LEG_RE = re.compile(r"\b(\d{2,3})(?:st|nd|rd|th)\b")
AGENCY_HREF_RE = re.compile(r"/reviews-and-reports/agencies/([a-z0-9\-]+)/?$")

# Document labels seen live, mapped to the review stage they represent.  Order
# matters: the longest/most specific label must be tested first.
DOC_TYPES: tuple[tuple[str, str], ...] = (
    ("staff report with final results", "staff_report_final_results"),
    ("staff report with commission decisions", "staff_report_commission_decisions"),
    ("final report with legislative action", "staff_report_final_results"),
    ("analysis of legislative action", "final_results"),
    ("summary of recommendations", "final_results"),
    ("summary of results", "final_results"),
    ("final results", "final_results"),
    ("self-evaluation report", "self_evaluation"),
    ("self evaluation report", "self_evaluation"),
    ("report to the", "report_to_legislature"),
    ("report to legislature", "report_to_legislature"),
    ("staff report", "staff_report"),
    ("compliance report", "compliance"),
    ("implementation of", "compliance"),
    ("final report", "final_report"),
    ("review grid", "review_grid"),
)

# Documents that carry per-recommendation outcome labels are worth a PDF parse.
OUTCOME_BEARING = {"staff_report_final_results", "final_results", "staff_report_commission_decisions"}


def strip_html(html: str) -> str:
    return _WS.sub(" ", unescape(_TAG.sub(" ", html))).strip()


def doc_type_for(label: str) -> str:
    low = label.lower()
    for needle, kind in DOC_TYPES:
        if needle in low:
            return kind
    return "other"


def cycle_label(text: str) -> str | None:
    """'2024-2025 Review Cycle, 89th…' -> '2024-25' (the commission's own short
    form, and the key the agency pages and DB rows join on)."""
    m = CYCLE_SPAN_RE.search(text)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)[2:]}"


# --------------------------------------------------------------- index pages
def parse_cycle_index(content: bytes) -> list[dict]:
    """Cycle list from /reviews-and-reports/past-review-cycles.

    Cycles live at opaque Drupal ``/node/{id}`` URLs.  One row on the page
    covers two cycles ("1978-1979 and 1980-1981 Review Cycles, 66th and 67th
    Legislative Session"), so spans and legislatures are zipped rather than
    assumed 1:1.
    """
    html = content.decode("utf-8", errors="replace")
    out: list[dict] = []
    seen: set[str] = set()
    for m in re.finditer(r'<a[^>]+href="(/node/\d+)"[^>]*>(.*?)</a>', html, re.S):
        label = strip_html(m.group(2))
        spans = CYCLE_SPAN_RE.findall(label)
        if not spans:
            continue
        legs = [int(x) for x in LEG_RE.findall(label)]
        for i, (start, end) in enumerate(spans):
            cycle = f"{start}-{end[2:]}"
            if cycle in seen:
                continue
            seen.add(cycle)
            out.append(
                {
                    "cycle": cycle,
                    "legislature": legs[i] if i < len(legs) else (legs[0] if legs else None),
                    "label": label,
                    "url": urljoin(BASE, m.group(1)),
                }
            )
    return out


def parse_agency_index(content: bytes) -> list[dict]:
    """A–Z agency directory -> one row per slug.

    Names are filed library-style ("Accountancy, Texas State Board of Public");
    the inverted form is kept as ``name_raw`` and an un-inverted ``name`` is
    derived for display and matching.
    """
    html = content.decode("utf-8", errors="replace")
    out: list[dict] = []
    seen: set[str] = set()
    for m in re.finditer(r'<a[^>]+href="([^"]*/reviews-and-reports/agencies/[^"#?]+)"[^>]*>(.*?)</a>', html, re.S):
        href = m.group(1)
        slug_m = AGENCY_HREF_RE.search(href)
        if not slug_m:
            continue
        slug = slug_m.group(1)
        name_raw = strip_html(m.group(2))
        if not name_raw or slug in seen:
            continue
        seen.add(slug)
        out.append(
            {
                "slug": slug,
                "url": urljoin(BASE, href),
                "name_raw": name_raw,
                "name": uninvert(name_raw),
            }
        )
    return out


def uninvert(name: str) -> str:
    """'Criminal Justice, Texas Department of' -> 'Texas Department of Criminal Justice'."""
    if ", " not in name:
        return name
    head, _, tail = name.partition(", ")
    return f"{tail} {head}".strip()


def parse_future_reviews(content: bytes) -> list[dict]:
    """Forward schedule to 2036-37 — the audit's forecasting asset.

    The page is a flat sequence of ``<h2>{cycle} Review Cycle</h2>`` followed by
    an agency ``<ul>``, so each agency link is bound to the nearest preceding
    heading.
    """
    html = content.decode("utf-8", errors="replace")
    cut = html.find("<footer")
    if cut > 0:
        html = html[:cut]
    heads = [
        (m.start(), cycle_label(strip_html(m.group(1))))
        for m in re.finditer(r"<h2[^>]*>(.*?)</h2>", html, re.S)
    ]
    heads = [(p, c) for p, c in heads if c]
    out: list[dict] = []
    for m in re.finditer(r'<a[^>]+href="([^"]*/reviews-and-reports/agencies/[^"#?]+)"[^>]*>(.*?)</a>', html, re.S):
        slug_m = AGENCY_HREF_RE.search(m.group(1))
        if not slug_m:
            continue
        prior = [c for p, c in heads if p < m.start()]
        if not prior:
            continue
        name_raw = strip_html(m.group(2)).replace("​", "").strip()
        if not name_raw:
            continue
        out.append({"cycle": prior[-1], "slug": slug_m.group(1), "name_raw": name_raw})
    return out


# --------------------------------------------------------------- agency page
DOC_LINK_RE = re.compile(
    r'<a[^>]+href="(https?://[^"]*?/public/uploads/[^"]+)"[^>]*>(.*?)</a>\s*(?:</p>)?\s*(?:\((?P<pub>[A-Za-z]{3,9}\s+\d{4})\))?',
    re.S,
)
DOC_HEADING_RE = re.compile(
    r"(?:<h2[^>]*>\s*Sunset Documents for\s*(?P<h2>[^<]+?)\s*</h2>"
    r"|<h4[^>]*>\s*<span[^>]*>\s*(?P<h4>[^<]*?Review Cycle[^<]*?)\s*</span>\s*</h4>)",
    re.S,
)
NEXT_REVIEW_RE = re.compile(r"Next Review Date:\s*([^<]+?)\s*(?:</|$)")
LAST_REVIEW_RE = re.compile(r"Last Review Cycle:\s*([^<]+?)\s*(?:</|$)")
COMMENTS_RE = re.compile(r'href="(/reviews-and-reports/agencies/comments/(\d+))"')


def parse_agency_page(content: bytes, slug: str | None = None) -> dict:
    """One agency page -> its document rows, grouped by review cycle.

    Both document regions are handled by one pass: the main-column
    ``<h2>Sunset Documents for {cycle}</h2>`` block (current cycle) and the
    sidebar ``<h4>{cycle}</h4>`` blocks (previous cycles).  The page is cut at
    ``<footer`` first — the footer carries an unrelated "Annual Financial
    Report" PDF that would otherwise be inherited by the last cycle heading.
    """
    html = content.decode("utf-8", errors="replace")
    cut = html.find("<footer")
    body = html[:cut] if cut > 0 else html

    title_m = re.search(r"<h1[^>]*>\s*<span>(.*?)</span>\s*</h1>", body, re.S)
    agency = strip_html(title_m.group(1)) if title_m else None

    heads = []
    for m in DOC_HEADING_RE.finditer(body):
        label = m.group("h2") or m.group("h4") or ""
        cyc = cycle_label(strip_html(label))
        if cyc:
            heads.append((m.start(), cyc, strip_html(label)))

    docs: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for m in DOC_LINK_RE.finditer(body):
        url = unescape(m.group(1))
        label = strip_html(m.group(2))
        if not label:
            continue
        prior = [h for h in heads if h[0] < m.start()]
        if not prior:
            continue
        _, cyc, cyc_label_text = prior[-1]
        key = (cyc, url)
        if key in seen:
            continue
        seen.add(key)
        legs = LEG_RE.findall(cyc_label_text)
        docs.append(
            {
                "cycle": cyc,
                "legislature": int(legs[0]) if legs else None,
                "label": label,
                "doc_type": doc_type_for(label),
                "url": url,
                "published": m.group("pub"),
            }
        )

    next_m = NEXT_REVIEW_RE.search(body)
    last_m = LAST_REVIEW_RE.search(body)
    com = COMMENTS_RE.search(body)
    return {
        "slug": slug,
        "agency": agency,
        "next_review_cycle": cycle_label(next_m.group(1)) if next_m else None,
        "last_review_cycle": cycle_label(last_m.group(1)) if last_m else None,
        "comments_url": urljoin(BASE, com.group(1)) if com else None,
        "comment_index_id": com.group(2) if com else None,
        "documents": docs,
    }


# ---------------------------------------------------------- recommendations
MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
HEADER_RE = re.compile(rf"^(?:Sunset Advisory Commission\s+)?(?:{MONTHS})\s+\d{{4}}(?:\s+Sunset Advisory Commission)?$")
PAGENO_RE = re.compile(r"^[A-Za-z]?\d{1,4}$")
RUNNING_TITLE_RE = re.compile(r"^(?:[A-Za-z]?\d{1,4}\s+)?.{0,90}?Staff Report(?:\s+with\s+[A-Za-z ]+)?(?:\s+[A-Za-z]?\d{1,4})?$")
STAGE_FOOTER_RE = re.compile(r"Staff Report\s+with\s+(Commission Decisions|Final Results)", re.I)
ISSUE_FOOTER_RE = re.compile(r"^Issue\s+\d+$")

STAGE_NAMES = {
    "final results": "final_results",
    "sunset commission decisions": "commission_decisions",
    "commission decisions": "commission_decisions",
}

REC_OUTCOME_RE = re.compile(
    r"Recommendation\s+(\d+\.\d+)\s*,\s*"
    r"(Adopted as Modified|Adopted in Part|Not Adopted|Adopted)\s*[—–-]\s*"
)
OUTCOMES = {
    "adopted": "adopted",
    "adopted as modified": "adopted_modified",
    "adopted in part": "adopted_part",
    "not adopted": "not_adopted",
}
MGMT_MARKER_RE = re.compile(r"\(\s*Management action\s*[–—-]\s*nonstatutory\s*\)", re.I)
# An issue head is 'Issue N — Title', with the title wrapping over up to three
# lines and always terminated by the first 'Recommendation N.N' beneath it.
ISSUE_HEAD_RE = re.compile(
    r"^Issue\s+(\d+)\b[ \t]*[—–-]?[ \t]*"
    r"([^\n]*(?:\n(?!Recommendation |Issue \d|[ \t]*$)[^\n]*){0,3})",
    re.M,
)
TYPE_HEAD_RE = re.compile(r"^(Change in Statute|Management Action|Fiscal Implication|Budget Recommendation)$", re.M)
BODY_REC_RE = re.compile(r"^(\d+\.\d+)\s+([A-Z][^\n]*(?:\n(?![\d•]|\s*$)[^\n]*)*)", re.M)
BILL_LINE_RE = re.compile(r"^(House|Senate)\s+Bill\s+(\d+)\s+([A-Z][^\n]{0,80})$", re.M)
REC_TYPES = {"change in statute": "statute", "management action": "management",
             "budget recommendation": "funding"}


def pdf_pages(content: bytes) -> list[str]:
    """Per-page text. Kept separate from parsing so callers can cache it and so
    the parsers below stay pure over text."""
    import io

    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return [p.extract_text() or "" for p in pdf.pages]


def _page_stage(page: str) -> str | None:
    """Sunset prints the report stage in every page's running footer, e.g.
    'Texas Criminal Justice Entities Staff Report with Final Results'.  Reading
    the stage off the page itself survives the audit's in-place replacement and
    hand-typed filenames."""
    lines = [ln.strip() for ln in page.strip().split("\n") if ln.strip()]
    for ln in lines[-4:]:
        low = ln.lower()
        if low in STAGE_NAMES:
            return STAGE_NAMES[low]
        m = STAGE_FOOTER_RE.search(ln)
        if m:
            return STAGE_NAMES[m.group(1).lower()]
        if re.search(r"Staff Report(\s+\d{1,4})?$", ln) and "with" not in low:
            return "staff_report"
    return None


def _clean_page(page: str) -> str:
    """Drop the running header line and the running footer block, so a
    recommendation that straddles a page break reads as one sentence."""
    lines = [ln.rstrip() for ln in page.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and HEADER_RE.match(lines[0].strip()):
        lines.pop(0)
    while lines:
        tail = lines[-1].strip()
        if not tail:
            lines.pop()
            continue
        low = tail.lower()
        if (
            low in STAGE_NAMES
            or PAGENO_RE.match(tail)
            or ISSUE_FOOTER_RE.match(tail)
            or HEADER_RE.match(tail)
            or (RUNNING_TITLE_RE.match(tail) and "Staff Report" in tail)
        ):
            lines.pop()
            continue
        break
    return "\n".join(lines)


def normalize_text(text: str) -> str:
    """Undo the drop-cap mangling pdfplumber produces on Sunset's issue heads
    ('i ssue 1 —' / 'i 1\\nssue') so one Issue regex covers every report era."""
    text = re.sub(r"\bi\s+(\d+)\s*\n\s*ssue\b", r"Issue \1\n", text)
    text = re.sub(r"\bi\s?ssue\s+(\d+)\b", r"Issue \1", text, flags=re.I)
    return text


def _tidy(chunk: str) -> str:
    # Sunset's born-digital reports never soft-hyphenate: every hyphen before a
    # line break is part of the word ("paper-based", "faith-based"), so the
    # hyphen is kept and only the break is removed.
    chunk = re.sub(r"(\w)-\n(\w)", r"\1-\2", chunk)
    chunk = re.sub(r"\s*\n\s*", " ", chunk)
    return _WS.sub(" ", chunk).strip(" .;")


def parse_recommendations(content: bytes, pages: list[str] | None = None) -> dict:
    """Pure over PDF bytes: numbered recommendations with their outcomes.

    Returns ``{bill, issues, recommendations}`` where each recommendation is
    ``{number, outcome, text, stage, rec_type, issue_no}``.  Every occurrence
    is returned — the same number appears once per stage present in the file —
    and :func:`latest_recommendations` collapses them for the headline table.
    """
    pages = pdf_pages(content) if pages is None else pages
    stage = None
    blocks: list[tuple[int, int, str]] = []   # (start, end, stage)
    cleaned: list[str] = []
    pos = 0
    for page in pages:
        st = _page_stage(page) or stage
        stage = st
        body = normalize_text(_clean_page(page))
        cleaned.append(body)
        blocks.append((pos, pos + len(body) + 1, st or "unknown"))
        pos += len(body) + 1
    text = "\n".join(cleaned)

    def stage_at(idx: int) -> str:
        for start, end, st in blocks:
            if start <= idx < end:
                return st
        return "unknown"

    issues = [
        {"number": int(m.group(1)), "pos": m.start(), "title": _tidy(m.group(2))}
        for m in ISSUE_HEAD_RE.finditer(text)
    ]
    # Each issue head is reprinted once per stage, and "Issue N" also occurs as
    # a cross-reference inside body prose. The first occurrence is always the
    # real heading (front matter precedes the body), so first wins.
    titles: dict[int, str] = {}
    for i in issues:
        if i["title"] and i["number"] not in titles:
            titles[i["number"]] = i["title"]

    def issue_at(idx: int) -> int | None:
        prior = [i for i in issues if i["pos"] < idx]
        return prior[-1]["number"] if prior else None

    recs: list[dict] = []
    marks = list(REC_OUTCOME_RE.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        nxt = ISSUE_HEAD_RE.search(text, m.end(), end)
        if nxt:
            end = nxt.start()
        chunk = text[m.end():end]
        rec_type = "management" if MGMT_MARKER_RE.search(chunk) else None
        chunk = MGMT_MARKER_RE.sub("", chunk)
        recs.append(
            {
                "number": m.group(1),
                "outcome": OUTCOMES[m.group(2).lower()],
                "outcome_raw": m.group(2),
                "text": _tidy(chunk),
                "stage": stage_at(m.start()),
                "rec_type": rec_type,
                "issue_no": issue_at(m.start()),
            }
        )

    typed = parse_recommendation_types(text)
    for r in recs:
        if not r["rec_type"]:
            r["rec_type"] = typed.get(r["number"], {}).get("rec_type")
        if not r["text"]:
            r["text"] = typed.get(r["number"], {}).get("text", "")

    bill = None
    bm = BILL_LINE_RE.search(text)
    if bm:
        chamber = "HB" if bm.group(1) == "House" else "SB"
        bill = {
            "bill": f"{chamber}{bm.group(2)}",
            "authors_raw": _tidy(bm.group(3)),
            "line": _tidy(bm.group(0)),
        }
    return {
        "bill": bill,
        "issues": [{"number": n, "title": t} for n, t in sorted(titles.items())],
        "recommendations": recs,
        "staff_recommendations": typed,
    }


def parse_recommendation_types(text: str) -> dict[str, dict]:
    """The staff-report body types every recommendation under a
    ``Change in Statute`` / ``Management Action`` heading and restates it in
    full — the only place the *type* (and the untruncated staff wording) is
    stated."""
    out: dict[str, dict] = {}
    current: str | None = None
    events = sorted(
        [(m.start(), "type", m.group(1)) for m in TYPE_HEAD_RE.finditer(text)]
        + [(m.start(), "rec", m) for m in BODY_REC_RE.finditer(text)]
    )
    for _, kind, payload in events:
        if kind == "type":
            current = REC_TYPES.get(payload.lower())
            continue
        if current is None:
            continue
        number = payload.group(1)
        out.setdefault(number, {"rec_type": current, "text": _tidy(payload.group(2))})
    return out


def latest_recommendations(recs: list[dict]) -> dict[str, dict]:
    """Collapse per-stage occurrences to one row per number, preferring the
    latest stage present (legislature > commission > staff)."""
    rank = {"staff_report": 1, "commission_decisions": 2, "final_results": 3, "unknown": 0}
    best: dict[str, dict] = {}
    for r in recs:
        cur = best.get(r["number"])
        if cur is None or rank.get(r["stage"], 0) >= rank.get(cur["stage"], 0):
            if cur and not r.get("rec_type") and cur.get("rec_type"):
                r = {**r, "rec_type": cur["rec_type"]}
            best[r["number"]] = r
    return best


# ------------------------------------------------------------------ storage
def review_id(slug: str, cycle: str) -> str:
    return f"{slug}:{cycle}"


def doc_id_for(url: str) -> str:
    return "sunset:doc:" + url.split("/public/uploads/", 1)[-1]


def store_review(conn: sqlite3.Connection, slug: str, agency: str | None, cycle: str) -> str:
    rid = review_id(slug, cycle)
    dbx.upsert(conn, "sunset_review", {"id": rid, "agency_raw": agency or slug, "cycle": cycle}, ["id"])
    dbx.add_edge(conn, "organization_name", "Sunset Advisory Commission", "reviewed",
                 "agency_slug", slug, "explicit", None, span=cycle)
    return rid


def store_recommendations(
    conn: sqlite3.Connection,
    review_id_: str,
    parsed: dict,
    doc_id: str | None,
    legislature: int | None = None,
) -> int:
    bill = (parsed.get("bill") or {}).get("bill")
    if bill:
        dbx.add_edge(conn, "sunset_review", review_id_, "produced", "bill", bill, "explicit", doc_id)
    for r in parsed["recommendations"]:
        dbx.upsert(
            conn,
            "sunset_recommendation_stage",
            {
                "review_id": review_id_,
                "number": r["number"],
                "stage": r["stage"],
                "rec_type": r["rec_type"],
                "text": r["text"],
                "outcome": r["outcome"],
                "issue_no": r["issue_no"],
                "doc_id": doc_id,
            },
            ["review_id", "number", "stage"],
        )
    latest = latest_recommendations(parsed["recommendations"])
    for number, r in sorted(latest.items()):
        dbx.upsert(
            conn,
            "sunset_recommendation",
            {
                "review_id": review_id_,
                "number": number,
                "rec_type": r["rec_type"],
                "text": r["text"],
                "outcome": r["outcome"],
                "implementation": None,
                "bill_id": bill if r["outcome"] in ("adopted", "adopted_modified", "adopted_part") else None,
                "doc_id": doc_id,
            },
            ["review_id", "number"],
        )
        key = f"{review_id_}#{number}"
        dbx.upsert(conn, "sunset_recommendation_key",
                   {"rec_key": key, "review_id": review_id_, "number": number}, ["rec_key"])
        if legislature:
            predicate = {"adopted": "adopted_by", "adopted_modified": "modified_by",
                         "adopted_part": "modified_by", "not_adopted": "rejected_by"}[r["outcome"]]
            dbx.add_edge(conn, "sunset_recommendation", key, predicate, "legislature",
                         str(legislature), "explicit", doc_id)
        if bill and r["outcome"] != "not_adopted":
            dbx.add_edge(conn, "sunset_recommendation", key, "enacted_in", "bill", bill,
                         "explicit", doc_id)
    return len(latest)


@register
class SunsetConnector(Connector):
    """Sunset reviews, staged documents and recommendation-level outcomes."""

    name = "sunset"
    tier = 1
    cadence = "review_cycle"

    DDL = """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_sunset_rec_unique
        ON sunset_recommendation(review_id, number);

    -- One agency page row: a document at a stage, for a cycle. Kept per-cycle
    -- because Sunset reuses the same URL across stages.
    CREATE TABLE IF NOT EXISTS sunset_document (
        id          TEXT PRIMARY KEY,          -- '<slug>:<cycle>:<doc_type>'
        agency_slug TEXT NOT NULL,
        cycle       TEXT NOT NULL,
        legislature INTEGER,
        doc_type    TEXT,
        label       TEXT,
        url         TEXT,
        published   TEXT,
        doc_id      TEXT REFERENCES document(id)
    );
    CREATE INDEX IF NOT EXISTS idx_sunset_document_agency ON sunset_document(agency_slug);

    -- The staff -> commission -> legislature delta. The audit's
    -- lobbying-effectiveness proxy is computed off this table, not off
    -- sunset_recommendation (which holds only the latest stage).
    CREATE TABLE IF NOT EXISTS sunset_recommendation_stage (
        id        INTEGER PRIMARY KEY,
        review_id TEXT NOT NULL,
        number    TEXT NOT NULL,
        stage     TEXT NOT NULL,             -- staff_report|commission_decisions|final_results
        rec_type  TEXT,
        text      TEXT,
        outcome   TEXT,
        issue_no  INTEGER,
        doc_id    TEXT REFERENCES document(id)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_sunset_rec_stage_unique
        ON sunset_recommendation_stage(review_id, number, stage);

    -- sunset_recommendation has a surrogate INTEGER key; edges address the
    -- stable minted key instead, and this table is the join back.
    CREATE TABLE IF NOT EXISTS sunset_recommendation_key (
        rec_key   TEXT PRIMARY KEY,          -- '<review_id>#<number>'
        review_id TEXT NOT NULL,
        number    TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sunset_cycle (
        cycle       TEXT PRIMARY KEY,        -- '2024-25'
        legislature INTEGER,
        label       TEXT,
        url         TEXT
    );

    CREATE TABLE IF NOT EXISTS sunset_agency (
        slug      TEXT PRIMARY KEY,
        name_raw  TEXT,
        name      TEXT,
        url       TEXT,
        next_review_cycle TEXT,
        last_review_cycle TEXT,
        comments_url      TEXT
    );

    -- Reviews scheduled through 2036-37: literal future-agenda disclosure.
    CREATE TABLE IF NOT EXISTS sunset_future_review (
        cycle       TEXT NOT NULL,
        agency_slug TEXT NOT NULL,
        name_raw    TEXT,
        PRIMARY KEY (cycle, agency_slug)
    );
    """

    # ---------------------------------------------------------- discovery
    def cycles(self, conn: sqlite3.Connection) -> list[dict]:
        resp = fetcher().get(CYCLE_INDEX)
        resp.raise_for_status()
        store_document(conn, doc_id="sunset:index:cycles", source_family="sunset",
                       content=resp.content, url=str(resp.url), doc_type="cycle_index",
                       authority="A")
        rows = parse_cycle_index(resp.content)
        for r in rows:
            dbx.upsert(conn, "sunset_cycle",
                       {"cycle": r["cycle"], "legislature": r["legislature"],
                        "label": r["label"], "url": r["url"]}, ["cycle"])
        conn.commit()
        return rows

    def agencies(self, conn: sqlite3.Connection) -> list[dict]:
        resp = fetcher().get(AGENCY_INDEX)
        resp.raise_for_status()
        store_document(conn, doc_id="sunset:index:agencies", source_family="sunset",
                       content=resp.content, url=AGENCY_INDEX, doc_type="agency_index",
                       authority="A")
        rows = parse_agency_index(resp.content)
        for r in rows:
            dbx.upsert(conn, "sunset_agency",
                       {"slug": r["slug"], "name_raw": r["name_raw"], "name": r["name"],
                        "url": r["url"]}, ["slug"],
                       update_cols=["name_raw", "name", "url"])
        conn.commit()
        return rows

    def future_reviews(self, conn: sqlite3.Connection) -> list[dict]:
        resp = fetcher().get(FUTURE_INDEX)
        resp.raise_for_status()
        store_document(conn, doc_id="sunset:index:future", source_family="sunset",
                       content=resp.content, url=FUTURE_INDEX, doc_type="future_reviews",
                       authority="A")
        rows = parse_future_reviews(resp.content)
        for r in rows:
            dbx.upsert(conn, "sunset_future_review",
                       {"cycle": r["cycle"], "agency_slug": r["slug"], "name_raw": r["name_raw"]},
                       ["cycle", "agency_slug"])
            dbx.add_edge(conn, "agency_slug", r["slug"], "scheduled_for_review",
                         "sunset_cycle", r["cycle"], "explicit", "sunset:index:future")
        conn.commit()
        return rows

    # ------------------------------------------------------------ agency
    def ingest_agency(self, conn: sqlite3.Connection, slug: str) -> dict:
        url = f"{AGENCY_INDEX}/{slug}"
        resp = fetcher().get(url)
        resp.raise_for_status()
        store_document(conn, doc_id=f"sunset:agency:{slug}", source_family="sunset",
                       content=resp.content, url=url, doc_type="agency_page", authority="A")
        page = parse_agency_page(resp.content, slug)
        dbx.upsert(
            conn, "sunset_agency",
            {"slug": slug, "name_raw": page["agency"], "name": page["agency"], "url": url,
             "next_review_cycle": page["next_review_cycle"],
             "last_review_cycle": page["last_review_cycle"],
             "comments_url": page["comments_url"]},
            ["slug"],
            update_cols=["next_review_cycle", "last_review_cycle", "comments_url", "url"],
        )
        for d in page["documents"]:
            store_review(conn, slug, page["agency"], d["cycle"])
            dbx.upsert(
                conn, "sunset_document",
                {"id": f"{slug}:{d['cycle']}:{d['doc_type']}", "agency_slug": slug,
                 "cycle": d["cycle"], "legislature": d["legislature"],
                 "doc_type": d["doc_type"], "label": d["label"], "url": d["url"],
                 "published": d["published"], "doc_id": None},
                ["id"], update_cols=["label", "url", "published", "legislature"],
            )
            dbx.add_edge(conn, "sunset_review", review_id(slug, d["cycle"]), "produced",
                         "sunset_document", f"{slug}:{d['cycle']}:{d['doc_type']}",
                         "explicit", f"sunset:agency:{slug}")
        conn.commit()
        return page

    def ingest_document(
        self, conn: sqlite3.Connection, slug: str, doc: dict, agency: str | None = None
    ) -> dict:
        """Fetch one agency document, store its bytes (versioned — the audit's
        stage-capture rule), and parse recommendations when the stage carries
        outcome labels."""
        resp = fetcher().get(doc["url"])
        resp.raise_for_status()
        did = doc_id_for(doc["url"])
        _, changed = store_document(
            conn, doc_id=did, source_family="sunset", content=resp.content, url=doc["url"],
            doc_type=doc["doc_type"], published_at=doc.get("published"), authority="A",
        )
        conn.execute("UPDATE sunset_document SET doc_id=? WHERE id=?",
                     (did, f"{slug}:{doc['cycle']}:{doc['doc_type']}"))
        out = {"doc_id": did, "changed": changed, "recommendations": 0, "bill": None}
        if doc["doc_type"] in OUTCOME_BEARING and resp.content[:4] == b"%PDF":
            parsed = parse_recommendations(resp.content)
            rid = store_review(conn, slug, agency, doc["cycle"])
            out["recommendations"] = store_recommendations(
                conn, rid, parsed, did, doc.get("legislature")
            )
            out["bill"] = (parsed.get("bill") or {}).get("bill")
            out["outcomes"] = _outcome_counts(parsed["recommendations"])
        conn.commit()
        return out

    # ----------------------------------------------------------- entry points
    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """Refresh the indexes, then re-read the agency pages named in
        ``slugs`` (default: the agencies of the most recent cycle already in
        the DB) and pull any outcome-bearing document."""
        slugs = kwargs.get("slugs") or []
        max_docs = int(kwargs.get("max_docs", 0))
        cycles = self.cycles(conn)
        agencies = self.agencies(conn)
        pages, docs, recs = [], 0, 0
        for slug in slugs:
            page = self.ingest_agency(conn, slug)
            pages.append(page)
            docs += len(page["documents"])
            for d in page["documents"]:
                if max_docs <= 0:
                    break
                if d["doc_type"] in OUTCOME_BEARING:
                    recs += self.ingest_document(conn, slug, d, page["agency"])["recommendations"]
                    max_docs -= 1
        return {"cycles": len(cycles), "agencies": len(agencies), "agency_pages": len(pages),
                "documents": docs, "recommendations": recs}

    def backfill(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """Walk the whole A–Z directory. ``limit`` bounds the crawl; document
        bytes are pulled only for ``fetch_docs`` agencies."""
        limit = int(kwargs.get("limit", 5))
        agencies = self.agencies(conn)
        self.cycles(conn)
        self.future_reviews(conn)
        docs = 0
        for a in agencies[:limit]:
            docs += len(self.ingest_agency(conn, a["slug"])["documents"])
        return {"agencies": len(agencies), "crawled": min(limit, len(agencies)), "documents": docs}

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """Cycle index + one agency page + that agency's Final Results PDF.
        Four live requests, well inside the crawl budget."""
        cycles = self.cycles(conn)
        slug = "texas-department-criminal-justice"
        page = self.ingest_agency(conn, slug)
        stats = {"cycles": len(cycles), "documents": len(page["documents"]),
                 "agency": page["agency"], "recommendations": 0}
        ok = len(cycles) >= 20 and len(page["documents"]) >= 1
        # An agency page lists outcome-bearing documents for several cycles
        # (TDCJ carries every review since 1998); take the newest, which is the
        # one whose format the parser is verified against.
        final = next(
            (d for d in sorted(page["documents"], key=lambda d: d["cycle"], reverse=True)
             if d["doc_type"] in OUTCOME_BEARING),
            None,
        )
        if ok and final:
            res = self.ingest_document(conn, slug, final, page["agency"])
            stats["recommendations"] = res["recommendations"]
            stats["bill"] = res["bill"]
            stats["outcomes"] = res.get("outcomes")
            ok = res["recommendations"] >= 5
        return SmokeResult(
            ok=ok,
            detail=(f"{stats['cycles']} cycles; {stats['documents']} documents for "
                    f"{stats['agency']}; {stats['recommendations']} recommendations"),
            stats=stats,
        )


def _outcome_counts(recs: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in latest_recommendations(recs).values():
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    return counts
