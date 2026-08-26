"""Interim charges and interim committee reports.

Spec: docs/texas-politics-audit/03-deep-dives/12-interim-reports.md.

The interim charge lists are the pre-announced agenda of the *next* session,
published 10–14 months early — the audit rates them the highest-signal forward
document in Texas politics. Three things drive this module's shape:

  * **Monitoring charges name enacted bills.** Every House committee's charge 1
    is a monitoring charge that enumerates specific 89th-session bills under
    oversight ("• HB 43, relating to …"); the Senate does the same inline
    ("Monitor rulemaking related to Senate Bill 6, 89th Legislature"). Those
    citations are the implementation-oversight signal, and they are lifted into
    explicit ``charge → monitors → bill`` edges.
  * **Reports are indexed by the legislature that ORDERED the study.** A report
    delivered in November 2024 sits under the 88th but exists to serve the 89th
    session. ``ordering_leg`` is stored verbatim and
    :func:`receiving_leg` (= ordering_leg + 1) is the derived join — never the
    other way round.
  * **Compliance.** lrl.texas.gov's robots.txt disallows ``/*.pdf`` and names
    AI crawlers, so the LRL aggregator is not used for documents at all here;
    every artifact comes from the chambers' own sites (house.texas.gov,
    ltgov.texas.gov), which the audit lists as the preferred mitigation. The
    shared fetcher will raise ``DeniedURL`` if anything ever points an LRL PDF
    path at it, and that is the intended behaviour.
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

HOUSE = "https://www.house.texas.gov"
HOUSE_CHARGES_89 = HOUSE + "/pdfs/speaker/F-Interim-Charges-3.25.pdf"
HOUSE_REPORT_INDEX = "https://house.texas.gov/committees/reports/interim"
LTGOV_CHARGES_PAGE = "https://www.ltgov.texas.gov/2026-interim-charges/"

# The 89th Legislature's interim: charges issued 2026, reports serve the 90th.
CURRENT_ORDERING_LEG = 89

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

CHAMBER_PREFIX = {"House": "HB", "Senate": "SB"}
BILL_REF_RE = re.compile(
    r"\b(?:(House|Senate)\s+(Bills?|Joint\s+Resolutions?)|(HB|SB|HJR|SJR|HCR|SCR|HR|SR))\s*"
    # A comma-run ("Bills 2 and 3", "HB 1, 2, and 3") must not swallow the
    # trailing legislature in "Senate Bill 6, 89th Legislature".
    r"(\d{1,4}(?!\d)(?:\s*(?:,|and|&)\s*\d{1,4}(?!\d)(?!(?:st|nd|rd|th)\s+Legislature))*)"
    r"(?:\s*[,(]?\s*(\d{2,3})(?:st|nd|rd|th)\s+Legislature\s*\)?)?",
    re.I,
)
# House: '1. Monitoring: Monitor the implementation ...' — numbered, titled.
HOUSE_CHARGE_RE = re.compile(r"^(\d{1,2})\.\s+(?=\S)", re.M)
# Senate: unnumbered bullets, titled the same way.
SENATE_CHARGE_RE = re.compile(r"^[•]\s*(?=\S)", re.M)
CHARGE_TITLE_RE = re.compile(r"^([A-Z][^:\n]{2,110}):\s*")
PAGE_NO_RE = re.compile(r"^\s*\d{1,3}\s*$")
SENATE_COMMITTEE_RE = re.compile(r"^(?:Select\s+Committee\s+on\s+.{3,70}|[A-Z][A-Za-z,&'’\- ]{3,70}\s+Committee)$")
MONITOR_RE = re.compile(r"\bmonitor(?:ing)?\b", re.I)


def strip_html(html: str) -> str:
    return _WS.sub(" ", unescape(_TAG.sub(" ", html))).strip()


def receiving_leg(ordering_leg: int) -> int:
    """The audit's join semantic: a study ordered by the Nth Legislature is
    delivered to, and serves, the (N+1)th."""
    return ordering_leg + 1


def _tidy(text: str) -> str:
    text = re.sub(r"(\w)-\n(\w)", r"\1-\2", text)
    return _WS.sub(" ", text.replace("\n", " ")).strip()


def pdf_pages(content: bytes) -> list[str]:
    import io

    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return [p.extract_text() or "" for p in pdf.pages]


def _drop_page_numbers(page: str) -> str:
    lines = [ln for ln in page.split("\n")]
    while lines and (not lines[-1].strip() or PAGE_NO_RE.match(lines[-1])):
        lines.pop()
    return "\n".join(lines)


# ------------------------------------------------------------------- bills
def parse_bill_refs(text: str) -> list[dict]:
    """Enacted bills cited inside charge text.

    Handles every form seen live: bare codes ("HB 43"), spelled-out with a
    parenthesised legislature ("Senate Bill 815 (89th Legislature)"), with a
    trailing one ("Senate Bill 6, 89th Legislature"), and the plural run
    ("Senate Bills 2 and 3, 87th Legislature") which expands to two refs.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for m in BILL_REF_RE.finditer(text):
        spelled, kind, code, numbers, leg = m.groups()
        if code:
            prefix = code.upper()
        else:
            prefix = CHAMBER_PREFIX[spelled.title()]
            if kind and "resolution" in kind.lower():
                prefix = prefix[0] + "JR"
        legislature = int(leg) if leg else None
        for num in re.findall(r"\d{1,4}", numbers):
            bill = f"{prefix}{int(num)}"
            key = f"{bill}@{legislature or ''}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"bill": bill, "chamber": prefix[0], "number": int(num),
                        "legislature": legislature})
    return out


def _charge_record(
    raw: str, committee: str, chamber: str, ordering_leg: int, issuer: str, charge_no: str
) -> dict:
    body = _tidy(raw)
    tm = CHARGE_TITLE_RE.match(body)
    title = tm.group(1).strip() if tm else None
    text = body[tm.end():].strip() if tm else body
    bills = parse_bill_refs(body)
    # House monitoring charges state the legislature once, in the stem ("all
    # legislation ... enacted by the 89th Legislature ... including: • HB 43"),
    # and never again per bill. Backfilling that stem legislature onto the
    # unqualified refs is what makes the bill cite resolvable to a session.
    stem = re.search(r"\b(\d{2,3})(?:st|nd|rd|th)\s+Legislature\b", body)
    for b in bills:
        b["legislature_derived"] = False
        if b["legislature"] is None and stem:
            b["legislature"] = int(stem.group(1))
            b["legislature_derived"] = True
    is_monitor = bool(
        (title and MONITOR_RE.search(title))
        or re.match(r"Monitor\b", text)
        or re.search(r"\bMonitor (?:the implementation|rulemaking|and oversee)\b", body)
    )
    return {
        "ordering_leg": ordering_leg,
        "receiving_leg": receiving_leg(ordering_leg),
        "chamber": chamber,
        "issuer": issuer,
        "committee_raw": committee,
        "charge_no": charge_no,
        "charge_type": "monitoring" if is_monitor else "study",
        "title": title,
        "text": text,
        "full_text": body,
        "bills": bills,
    }


# ------------------------------------------------------- House charges PDF
def parse_house_charges(
    content: bytes, ordering_leg: int = CURRENT_ORDERING_LEG, pages: list[str] | None = None
) -> list[dict]:
    """Speaker's interim charges -> one row per numbered charge.

    Committee names are the only all-caps lines in the document, which makes
    them a reliable section marker; a candidate only counts as a committee if a
    numbered charge follows it before the next candidate, which discards the
    cover block and the bare 'SELECT COMMITTEES' divider.
    """
    pages = pdf_pages(content) if pages is None else pages
    text = "\n".join(_drop_page_numbers(p) for p in pages)

    heads: list[tuple[int, int, str]] = []
    for m in re.finditer(r"^(?![•])([A-Z][A-Z0-9,&'’\.\-\(\) ]{3,90})$", text, re.M):
        name = m.group(1).strip()
        letters = [c for c in name if c.isalpha()]
        if len(letters) < 4 or not all(c.isupper() for c in letters):
            continue
        heads.append((m.start(), m.end(), name))

    charges: list[dict] = []
    for i, (_start, end, name) in enumerate(heads):
        section_end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        section = text[end:section_end]
        marks = list(HOUSE_CHARGE_RE.finditer(section))
        if not marks:
            continue  # cover block / 'SELECT COMMITTEES' divider
        for j, m in enumerate(marks):
            stop = marks[j + 1].start() if j + 1 < len(marks) else len(section)
            charges.append(
                _charge_record(section[m.end():stop], name, "house", ordering_leg,
                               "speaker", m.group(1))
            )
    return charges


# ------------------------------------------------------ Senate charges PDF
def parse_senate_charges(
    content: bytes, ordering_leg: int = CURRENT_ORDERING_LEG, pages: list[str] | None = None
) -> list[dict]:
    """Lt. Governor's interim charges -> one row per bulleted charge.

    The Senate does not number its charges, so they are numbered positionally
    within each committee. Committee headings always open a page (the cover
    page's committee list is skipped because it is never the page's first
    line), and a page whose first line is a bullet is a continuation.
    """
    pages = pdf_pages(content) if pages is None else pages
    charges: list[dict] = []
    current: str | None = None
    counters: dict[str, int] = {}
    for page in pages:
        body = _drop_page_numbers(page)
        lines = [ln for ln in body.split("\n")]
        first = next((ln.strip() for ln in lines if ln.strip()), "")
        if SENATE_COMMITTEE_RE.match(first):
            current = first
            body = body[body.find(first) + len(first):]
        if current is None:
            continue
        marks = list(SENATE_CHARGE_RE.finditer(body))
        for j, m in enumerate(marks):
            stop = marks[j + 1].start() if j + 1 < len(marks) else len(body)
            counters[current] = counters.get(current, 0) + 1
            charges.append(
                _charge_record(body[m.end():stop], current, "senate", ordering_leg,
                               "lt_governor", str(counters[current]))
            )
    return charges


def senate_charges_url(content: bytes, base: str = LTGOV_CHARGES_PAGE) -> str | None:
    """The ltgov page links one cumulative PDF that is replaced in place as new
    rounds of charges are released — so it must be re-hashed, not skipped."""
    html = content.decode("utf-8", errors="replace")
    m = re.search(r"""href=['"]([^'"]*Interim-Charges[^'"]*\.pdf)['"]""", html, re.I)
    if not m:
        m = re.search(r"""href=['"]([^'"]+\.pdf)['"]""", html, re.I)
    return urljoin(base, unescape(m.group(1))) if m else None


# -------------------------------------------------------- report index page
REPORT_LEG_RE = re.compile(r"Legislative Session\s+(\d{2,3})(?:st|nd|rd|th)", re.I)
REPORT_URL_LEG_RE = re.compile(r"/interim/(\d{2,3})interim/", re.I)
SIZE_SUFFIX_RE = re.compile(r"\s*\[PDF[^\]]*\]|\s*\(PDF[^)]*\)", re.I)


def parse_report_index(content: bytes, base: str = HOUSE_REPORT_INDEX) -> list[dict]:
    """house.texas.gov's interim-report archive (76th → current).

    The ordering legislature is taken from the URL's ``{NN}interim/`` segment
    when present — the audit warns the path's legislature number is the
    trustworthy one for Senate reports and it is equally so here — and falls
    back to the nearest ``<h2>Legislative Session NNth</h2>`` heading. Group
    headings ("Select Committees", "Joint Committees") are carried along.
    """
    html = content.decode("utf-8", errors="replace")
    cut = html.find("<footer")
    if cut > 0:
        html = html[:cut]
    heads = [
        (m.start(), int(m.group(1)))
        for m in re.finditer(r"<h2[^>]*>(?:(?!</h2>).)*?Legislative Session\s+(\d{2,3})(?:st|nd|rd|th)", html, re.S | re.I)
    ]
    groups = [
        (m.start(), strip_html(m.group(1)))
        for m in re.finditer(r"<h3[^>]*>(.*?)</h3>", html, re.S)
    ]

    def group_at(idx: int) -> str | None:
        # A group heading belongs to its own session block only; without this
        # reset a "Joint Committees" h3 in the 78th leaks onto the 76th.
        head_pos = max((p for p, _ in heads if p < idx), default=-1)
        prior = [g for p, g in groups if head_pos < p < idx]
        return prior[-1] if prior else None
    out: list[dict] = []
    seen: set[str] = set()
    for m in re.finditer(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', html, re.S | re.I):
        url = urljoin(base, unescape(m.group(1)))
        title = SIZE_SUFFIX_RE.sub("", strip_html(m.group(2))).strip()
        if not title or url in seen:
            continue
        seen.add(url)
        url_leg = REPORT_URL_LEG_RE.search(url)
        prior = [leg for pos, leg in heads if pos < m.start()]
        leg = int(url_leg.group(1)) if url_leg else (prior[-1] if prior else None)

        is_charges = "interim charge" in title.lower() or "interim-charges" in url.lower()
        out.append(
            {
                "ordering_leg": leg,
                "receiving_leg": receiving_leg(leg) if leg else None,
                "committee_raw": None if is_charges else title,
                "title": title,
                "url": url,
                "group": group_at(m.start()),
                "kind": "charges" if is_charges else "report",
            }
        )
    return out


def report_id(row: dict) -> str:
    """Minted, stable, and readable: LRL call numbers are the canonical ids but
    LRL is off-limits for bulk crawling, so the chamber URL's basename stands
    in until a call number is available."""
    basename = row["url"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return f"house:{row['ordering_leg']}:{basename}"


def charge_key(c: dict) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", c["committee_raw"].lower()).strip("-")
    return f"{c['ordering_leg']}:{c['chamber']}:{slug}:{c['charge_no']}"


# ------------------------------------------------------------------ storage
def store_charges(conn: sqlite3.Connection, charges: list[dict], doc_id: str | None) -> dict:
    bills = 0
    for c in charges:
        dbx.upsert(
            conn,
            "interim_charge",
            {
                "ordering_leg": c["ordering_leg"],
                "issuer": c["issuer"],
                "committee_raw": c["committee_raw"],
                "charge_no": c["charge_no"],
                "charge_type": c["charge_type"],
                "text": c["full_text"],
                "doc_id": doc_id,
            },
            ["ordering_leg", "issuer", "committee_raw", "charge_no"],
        )
        key = charge_key(c)
        dbx.upsert(
            conn,
            "interim_charge_key",
            {"charge_key": key, "ordering_leg": c["ordering_leg"], "issuer": c["issuer"],
             "chamber": c["chamber"], "committee_raw": c["committee_raw"],
             "charge_no": c["charge_no"], "title": c["title"],
             "charge_type": c["charge_type"]},
            ["charge_key"],
        )
        dbx.add_edge(conn, "office", c["issuer"], "issued", "interim_charge", key,
                     "explicit", doc_id)
        dbx.add_edge(conn, "interim_charge", key, "assigned_to", "committee_name",
                     c["committee_raw"], "explicit", doc_id)
        for b in c["bills"]:
            bills += 1
            dbx.upsert(
                conn,
                "interim_charge_bill",
                {"charge_key": key, "bill": b["bill"], "legislature": b["legislature"]},
                ["charge_key", "bill"],
            )
            dbx.add_edge(conn, "interim_charge", key, "monitors", "bill", b["bill"],
                         "explicit", doc_id,
                         span=f"{b['legislature']}R" if b["legislature"] else None)
    return {"charges": len(charges), "bill_refs": bills,
            "committees": len({c["committee_raw"] for c in charges})}


def store_reports(conn: sqlite3.Connection, rows: list[dict], doc_id: str | None) -> int:
    stored = 0
    for r in rows:
        if r["kind"] != "report" or r["ordering_leg"] is None:
            continue
        rid = report_id(r)
        dbx.upsert(
            conn, "interim_report",
            {"id": rid, "ordering_leg": r["ordering_leg"], "committee_raw": r["committee_raw"],
             "title": r["title"], "doc_id": None}, ["id"],
        )
        dbx.upsert(
            conn, "interim_report_meta",
            {"report_id": rid, "url": r["url"], "chamber": "house",
             "receiving_leg": r["receiving_leg"], "group_label": r["group"]},
            ["report_id"],
        )
        dbx.add_edge(conn, "committee_name", r["committee_raw"] or r["title"], "filed",
                     "interim_report", rid, "explicit", doc_id)
        dbx.add_edge(conn, "interim_report", rid, "serves", "legislature",
                     str(r["receiving_leg"]), "derived", doc_id,
                     span="ordering_leg + 1")
        stored += 1
    return stored


@register
class InterimConnector(Connector):
    """Interim charges (House + Senate) and the House interim-report archive."""

    name = "interim"
    tier = 1
    cadence = "interim_season"

    DDL = """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_interim_charge_unique
        ON interim_charge(ordering_leg, issuer, committee_raw, charge_no);

    -- interim_charge has a surrogate INTEGER key; edges address this stable
    -- minted key instead, and this table is the join back plus the fields the
    -- canonical table has no column for.
    CREATE TABLE IF NOT EXISTS interim_charge_key (
        charge_key    TEXT PRIMARY KEY,   -- '<leg>:<chamber>:<committee-slug>:<no>'
        ordering_leg  INTEGER NOT NULL,
        issuer        TEXT,
        chamber       TEXT,
        committee_raw TEXT,
        charge_no     TEXT,
        title         TEXT,
        charge_type   TEXT
    );

    -- The implementation-oversight signal: enacted bills named inside a
    -- monitoring charge, with the legislature that passed them when stated.
    CREATE TABLE IF NOT EXISTS interim_charge_bill (
        charge_key  TEXT NOT NULL,
        bill        TEXT NOT NULL,
        legislature INTEGER,
        PRIMARY KEY (charge_key, bill)
    );

    CREATE TABLE IF NOT EXISTS interim_report_meta (
        report_id     TEXT PRIMARY KEY,
        url           TEXT,
        chamber       TEXT,
        receiving_leg INTEGER,            -- derived: ordering_leg + 1
        group_label   TEXT
    );
    """

    # -------------------------------------------------------------- charges
    def ingest_house_charges(
        self, conn: sqlite3.Connection, url: str = HOUSE_CHARGES_89,
        ordering_leg: int = CURRENT_ORDERING_LEG,
    ) -> dict:
        resp = fetcher().get(url)
        resp.raise_for_status()
        doc_id = f"interim:charges:house:{ordering_leg}"
        _, changed = store_document(
            conn, doc_id=doc_id, source_family="interim", content=resp.content, url=url,
            doc_type="interim_charges", authority="A",
        )
        charges = parse_house_charges(resp.content, ordering_leg)
        stats = store_charges(conn, charges, doc_id)
        conn.commit()
        return {**stats, "changed": changed, "doc_id": doc_id, "url": url}

    def ingest_senate_charges(
        self, conn: sqlite3.Connection, page_url: str = LTGOV_CHARGES_PAGE,
        ordering_leg: int = CURRENT_ORDERING_LEG,
    ) -> dict:
        resp = fetcher().get(page_url)
        resp.raise_for_status()
        store_document(conn, doc_id="interim:charges:senate:index", source_family="interim",
                       content=resp.content, url=page_url, doc_type="charge_release_page",
                       authority="A")
        pdf_url = senate_charges_url(resp.content, page_url)
        if not pdf_url:
            return {"charges": 0, "bill_refs": 0, "committees": 0, "url": None}
        pdf = fetcher().get(pdf_url)
        pdf.raise_for_status()
        doc_id = f"interim:charges:senate:{ordering_leg}"
        # Rolling rounds accrete into the same file at the same URL; the
        # docstore versions by hash so each round survives as its own version.
        _, changed = store_document(
            conn, doc_id=doc_id, source_family="interim", content=pdf.content, url=pdf_url,
            doc_type="interim_charges", authority="A",
        )
        charges = parse_senate_charges(pdf.content, ordering_leg)
        stats = store_charges(conn, charges, doc_id)
        conn.commit()
        return {**stats, "changed": changed, "doc_id": doc_id, "url": pdf_url}

    # -------------------------------------------------------------- reports
    def ingest_report_index(self, conn: sqlite3.Connection, url: str = HOUSE_REPORT_INDEX) -> dict:
        resp = fetcher().get(url)
        resp.raise_for_status()
        doc_id = "interim:reports:house:index"
        store_document(conn, doc_id=doc_id, source_family="interim", content=resp.content,
                       url=url, doc_type="report_index", authority="A")
        rows = parse_report_index(resp.content, url)
        stored = store_reports(conn, rows, doc_id)
        conn.commit()
        legs = sorted({r["ordering_leg"] for r in rows if r["ordering_leg"]})
        return {"links": len(rows), "reports": stored,
                "ordering_legs": legs, "oldest_leg": legs[0] if legs else None}

    # ---------------------------------------------------------- entry points
    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        house = self.ingest_house_charges(conn)
        senate = self.ingest_senate_charges(conn) if kwargs.get("senate", True) else {}
        reports = self.ingest_report_index(conn) if kwargs.get("reports", True) else {}
        return {"house_charges": house, "senate_charges": senate, "reports": reports}

    def backfill(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """The chamber archive is the backfillable half; the LRL aggregator that
        reaches back to 1846 is deliberately not crawled (robots)."""
        return self.ingest_report_index(conn)

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """Parse the live House charges PDF end to end. One live request."""
        stats = self.ingest_house_charges(conn)
        monitoring = conn.execute(
            """SELECT COUNT(DISTINCT k.charge_key) c
                 FROM interim_charge_key k JOIN interim_charge_bill b USING (charge_key)
                WHERE k.charge_type='monitoring'"""
        ).fetchone()["c"]
        bills = conn.execute("SELECT COUNT(DISTINCT bill) c FROM interim_charge_bill").fetchone()["c"]
        stats["monitoring_charges_naming_bills"] = monitoring
        stats["distinct_bills"] = bills
        ok = stats["charges"] >= 20 and stats["committees"] >= 10 and monitoring >= 1
        return SmokeResult(
            ok=ok,
            detail=(f"{stats['charges']} charges across {stats['committees']} committees; "
                    f"{monitoring} monitoring charges naming {bills} bills"),
            stats=stats,
        )
