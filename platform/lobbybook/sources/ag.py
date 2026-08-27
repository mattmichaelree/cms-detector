"""Texas Attorney General — opinions, opinion requests, supersession status.

Spec: docs/texas-politics-audit/03-deep-dives/06-ag-opinions.md.

Five verified facts shape this module:

  * **The index is a numbering ledger, not a list.** /opinions publishes one
    row per administration — AG name, years, and the *number range* that
    administration issued (``O-0001 - O-5740`` Gerald Mann 1939-43 through
    ``KP-0001 - KP-05xx`` Paxton) — so coverage back to 1939 is enumerable
    arithmetic rather than a crawl. The ledger is parsed into its own table
    because the range endpoints are the backfill plan *and* the collision
    guard (``GA-####`` here is an Abbott AG opinion; ``GA-##`` on gov.texas.gov
    is an Abbott executive order — same person, two roles).
  * **Pending requests are the highest-value live path.** An RQ letter
    publishes the requestor, the question, and the date *before any answer
    exists* — a damaging opinion is visible months ahead. The index sidebar
    dates only the three newest, and the requestor lives one page deeper, so
    the poller pages down from the ledger's high-water number and opens the
    request pages the index does not date.
  * **The request→opinion edge is printed inside the opinion.** A modern
    opinion's ``Re:`` line ends with its own request number — "... outside the
    county (RQ-0518-KP)" — which is the one explicit join between the two
    corpora. It is extracted from the PDF text, not guessed by date proximity.
  * **Supersession is a signal, never a guarantee.** The overruled/modified/
    affirmed/withdrawn list says of itself that it "is not entirely complete";
    absence from it is *not* evidence an opinion is good law. Every entry is
    therefore stored with its source in :data:`ag_supersession`, and an
    opinion with no entry stays ``status='active'`` — meaning "no supersession
    signal recorded", not "verified current".
  * **Bot mitigation fingerprints tooling, not access.** Generic fetchers get
    HTTP 402 from texasattorneygeneral.gov while browser-UA requests to the
    same public URLs succeed. ``core.fetch`` already carries that host in
    ``BROWSER_PROFILE_HOSTS``; this module just uses the shared fetcher, still
    throttled, and never crawls.

Everything below the fetch boundary is a pure function over bytes/text so the
parsers are testable against captured fixtures with no network.
"""

from __future__ import annotations

import io
import re
import sqlite3
from datetime import UTC, datetime
from html import unescape

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

BASE = "https://www.texasattorneygeneral.gov"
OPINIONS_URL = BASE + "/opinions"
REQUESTS_URL = BASE + "/requests"
# The supersession tracker never migrated off the legacy host; the modern site
# links out to it. Kept as an absolute URL because the www2 copy is canonical.
SUPERSESSION_URL = (
    "https://www2.texasattorneygeneral.gov/opinion/opinions-overruled-modified-affirmed-withdrawn"
)

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_MONTHS = {m: i for i, m in enumerate(
    "January February March April May June July August September October "
    "November December".split(), start=1)}


def strip_html(html: str) -> str:
    return _WS.sub(" ", unescape(_TAG.sub(" ", html))).strip()


def iso_date(raw: str | None) -> str | None:
    """'August 26, 2026' / 'Aug 4, 2026' / '2026-08-12T12:00:00Z' -> ISO date."""
    if not raw:
        return None
    raw = raw.strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return m.group(0)
    m = re.search(r"([A-Z][a-z]+)\.?\s+(\d{1,2}),\s*(\d{4})", raw)
    if not m:
        return None
    for name, num in _MONTHS.items():
        if name.lower().startswith(m.group(1).lower()[:3]):
            return f"{int(m.group(3)):04d}-{num:02d}-{int(m.group(2)):02d}"
    return None


# --------------------------------------------------------------- the ledger

# One administration row on /opinions or /requests: name, years, and the
# number range that administration owns, linking to its own numbered page.
_LEDGER_ROW = re.compile(
    r'attorney-general--name">(?P<name>[^<]+)</div>\s*'
    r'<div class="attorney-general--years">(?P<years>[^<]*)</div>.*?'
    r'<a href="(?P<href>[^"]+)">(?P<range>[^<]+)</a>',
    re.S,
)
# 'O-0001 - O-5740', 'RQ-0001-KP - RQ-0653-KP'
_RANGE = re.compile(
    r"([A-Z]{1,2})-(\d{3,4})(?:-([A-Z]{2}))?\s*[-–]\s*([A-Z]{1,2})-(\d{3,4})(?:-([A-Z]{2}))?"
)


def parse_administrations(content: bytes, ledger: str) -> list[dict]:
    """Index HTML -> the per-administration numbering ledger.

    `ledger` is 'opinion' or 'request'; the same markup carries both on their
    respective index pages. The range endpoints are kept verbatim *and* split
    into prefix/first/last so a backfill can enumerate a series without
    re-reading the page.
    """
    html = content.decode("utf-8", errors="replace")
    out: list[dict] = []
    for m in _LEDGER_ROW.finditer(html):
        years = unescape(m.group("years")).strip()
        rng = unescape(m.group("range")).strip()
        rm = _RANGE.search(rng)
        if not rm:
            continue
        y = re.findall(r"(1[89]\d{2}|20\d{2})", years)
        first = f"{rm.group(1)}-{rm.group(2)}" + (f"-{rm.group(3)}" if rm.group(3) else "")
        last = f"{rm.group(4)}-{rm.group(5)}" + (f"-{rm.group(6)}" if rm.group(6) else "")
        href = m.group("href")
        out.append({
            "ledger": ledger,
            "slug": href.rstrip("/").rsplit("/", 1)[-1],
            "ag_name": unescape(m.group("name")).strip(),
            "years_raw": years,
            "year_start": int(y[0]) if y else None,
            # 'Present' leaves the end open — a sitting AG's range still grows.
            "year_end": int(y[1]) if len(y) > 1 else None,
            "provisional": int("provisional" in years.lower()),
            "prefix": rm.group(3) or rm.group(1),
            "first_number": first,
            "last_number": last,
            "count_est": int(rm.group(5)) - int(rm.group(2)) + 1,
            "range_raw": rng,
            "url": href if href.startswith("http") else BASE + href,
        })
    return out


# ------------------------------------------------------- index sidebar feeds

# Both indexes publish their newest items in an identically-classed sidebar
# block; only the date markup differs (requests carry a <time datetime>).
_SIDEBAR_BLOCK = '<div class="sidebar-ag-opinion-content">'
_SB_LINK = re.compile(r'casenum">\s*<h4><a href="([^"]+)">\s*<span>([^<]+)</span>', re.S)
_SB_DATE = re.compile(r'casedate">\s*(?:<time datetime="([^"]+)">)?\s*([^<]*)', re.S)
_SB_TEXT = re.compile(r'sidebar-ag-opinion-text">(.*?)</div>', re.S)
_SB_PDF = re.compile(r'href="([^"]+\.pdf)"', re.I)


def _sidebar_items(content: bytes) -> list[dict]:
    html = content.decode("utf-8", errors="replace")
    items: list[dict] = []
    for block in html.split(_SIDEBAR_BLOCK)[1:]:
        link = _SB_LINK.search(block)
        if not link:
            continue
        dm = _SB_DATE.search(block)
        raw_date = (dm.group(1) or dm.group(2)) if dm else None
        text = _SB_TEXT.search(block)
        pdf = _SB_PDF.search(block)
        items.append({
            "number": unescape(link.group(2)).strip(),
            "url": link.group(1) if link.group(1).startswith("http") else BASE + link.group(1),
            "date": iso_date(raw_date),
            "date_raw": (raw_date or "").strip() or None,
            "summary": strip_html(text.group(1)) if text else None,
            "pdf_url": (pdf.group(1) if pdf.group(1).startswith("http") else BASE + pdf.group(1))
            if pdf else None,
        })
    return items


def parse_recent_opinions(content: bytes) -> list[dict]:
    """/opinions -> the 'Most Recent Opinions' feed (number, date, summary, PDF)."""
    return [i for i in _sidebar_items(content) if not i["number"].startswith("RQ-")]


def parse_recent_requests(content: bytes) -> list[dict]:
    """/requests -> the 'Most Recent Requests' feed (number, date, subject)."""
    return [i for i in _sidebar_items(content) if i["number"].startswith("RQ-")]


# ------------------------------------------------- per-administration browse

# The browse page renders every request of an administration as <option>s in
# per-year <select>s — the "empty without JS" index the audit warns about. The
# options themselves are plain HTML and enumerate the full numbered series.
_OPTION = re.compile(r'<option value="(/node/\d+)">((?:RQ|[A-Z]{1,2})-[\w-]+)</option>')
_YEAR_GROUP = re.compile(r'form-item-request-select(\d{4})|form-item-opinion-select(\d{4})')


def parse_browse_options(content: bytes) -> list[dict]:
    """Per-administration browse page -> [{number, node}] for the whole series.

    Node paths are the only stable handle the page offers; a detail fetch
    resolves each to its canonical /requests/<ag>/<slug> URL.
    """
    html = content.decode("utf-8", errors="replace")
    return [{"number": num, "node": node} for node, num in _OPTION.findall(html)]


# ------------------------------------------------------ request detail pages

_RQ_NUM = re.compile(r"\b(RQ-\d{3,4}-[A-Z]{2})\b")
_RQ_H1 = re.compile(r'RQ-<span class="numbers">(\d{3,4})</span>-([A-Z]{2})')
_OPINION_LINK = re.compile(r'href="/opinions/[^"]+/([a-z]{1,2}-\d{3,4})"')
_BR = re.compile(r"<br\s*/?>", re.I)


def _labelled(html: str, label: str) -> str | None:
    """Text of the block introduced by ``<h3>label</h3>`` on a detail page."""
    m = re.search(rf"<h3>\s*{re.escape(label)}\s*</h3>(.*?)(?=<h3|</div>\s*<div class=\"m-t-2\"|$)",
                  html, re.S | re.I)
    if not m:
        return None
    body = _BR.sub("\n", m.group(1))
    text = _WS.sub(" ", unescape(_TAG.sub(" ", body))).strip()
    return text or None


def parse_request_page(content: bytes) -> dict:
    """One /requests/<ag>/<rq> page -> the full request record.

    This page — not the index — is where the requestor lives, which is the
    whole point of the pending-request feed: *who* asked, published before any
    answer exists.
    """
    html = content.decode("utf-8", errors="replace")
    m = _RQ_H1.search(html)
    number = f"RQ-{m.group(1)}-{m.group(2)}" if m else None
    if not number:
        cm = _RQ_NUM.search(html)
        number = cm.group(1) if cm else None

    raw_req = None
    rm = re.search(r"<h3>\s*Requestor\s*</h3>(.*?)(?=<h3|</div>\s*</div>|$)", html, re.S | re.I)
    if rm:
        lines = [strip_html(x) for x in _BR.split(rm.group(1))]
        raw_req = [x for x in lines if x]

    date_m = re.search(r'<h3>\s*Request Date\s*</h3>.*?<time datetime="([^"]+)"', html, re.S | re.I)
    pdf_m = re.search(r'<h3>\s*Request File\s*</h3>.*?href="([^"]+\.pdf)"', html, re.S | re.I)

    # The sidebar states the join explicitly in both directions: a link to the
    # answering opinion, or the sentence that none exists yet.
    side = html.split("Associated Opinion", 1)
    answered = None
    if len(side) > 1 and "No opinion currently associated" not in side[1][:1200]:
        om = _OPINION_LINK.search(side[1][:1200])
        answered = om.group(1).upper() if om else None

    return {
        "number": number,
        "date": iso_date(date_m.group(1)) if date_m else iso_date(_labelled(html, "Request Date")),
        "status": _labelled(html, "Request Status"),
        "summary": _labelled(html, "Re"),
        "requestor": raw_req[0] if raw_req else None,
        "requestor_location": ", ".join(raw_req[1:]) if raw_req and len(raw_req) > 1 else None,
        "requestor_raw": ", ".join(raw_req) if raw_req else None,
        "pdf_url": (pdf_m.group(1) if pdf_m.group(1).startswith("http") else BASE + pdf_m.group(1))
        if pdf_m else None,
        "answered_by": answered,
    }


def request_url(number: str, admin_slug: str = "ken-paxton") -> str:
    """'RQ-0650-KP' -> its canonical detail URL.

    Detail URLs are a pure function of the number, which is what lets the
    poller walk down from the ledger's high-water mark without first loading
    the JS-gated browse index.
    """
    return f"{BASE}/requests/{admin_slug}/{number.lower()}"


def numbers_below(last_number: str, count: int, skip: set[str] | None = None) -> list[str]:
    """The `count` request numbers at or below `last_number`, newest first."""
    m = re.match(r"RQ-(\d{3,4})-([A-Z]{2})$", last_number)
    if not m:
        return []
    width, suffix = len(m.group(1)), m.group(2)
    n = int(m.group(1))
    skip = skip or set()
    out: list[str] = []
    while n > 0 and len(out) < count:
        num = f"RQ-{n:0{width}d}-{suffix}"
        if num not in skip:
            out.append(num)
        n -= 1
    return out


# ------------------------------------------------------------ opinion PDFs

_OPINION_NO = re.compile(r"Opinion No\.\s*([A-Z]{1,2}-\d{3,4})")
_RE_LINE = re.compile(r"\bRe:\s*(.+?)(?=\n\s*Dear\b|\Z)", re.S)
_RQ_XREF = re.compile(r"\(\s*(RQ-\d{3,4}-[A-Z]{2})\s*\)")
# The summary heading is letter-spaced in the source PDFs ("S U M M A R Y").
_SUMMARY = re.compile(
    r"S\s*U\s*M\s*M\s*A\s*R\s*Y\s*(.*?)(?=V\s*ery truly yours|Very truly yours|\Z)", re.S
)
_PAGE_FOOTER = re.compile(r"^.{0,70}?\s-\sPage\s\d+\s*$", re.M)
_LETTER_DATE = re.compile(r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b")


def _deline(text: str) -> str:
    """Undo the PDF's line wrapping, including hyphen-split words."""
    return _WS.sub(" ", text.replace("-\n", "-").replace("­", "")).strip()


# Small-caps citations as opinions print them: "TEX. LOC. GOV'T CODE § 86.021(d)",
# "TEX. GOV'T CODE §§ 418.017(a)", "Texas Government Code section 552.201(b)".
# Canonical output matches the register/courts connectors ("Government Code
# §2001.038") so all three feeds land on the same statute node.
CODE_ALIASES = {
    "government": "Government", "gov't": "Government", "govt": "Government",
    "local government": "Local Government", "loc gov't": "Local Government",
    "loc govt": "Local Government",
    "health & safety": "Health & Safety", "health and safety": "Health & Safety",
    "occupations": "Occupations", "occ": "Occupations",
    "education": "Education", "educ": "Education",
    "election": "Election", "elec": "Election",
    "tax": "Tax", "transportation": "Transportation", "transp": "Transportation",
    "water": "Water", "labor": "Labor", "lab": "Labor",
    "natural resources": "Natural Resources", "nat res": "Natural Resources",
    "human resources": "Human Resources", "hum res": "Human Resources",
    "insurance": "Insurance", "ins": "Insurance",
    "finance": "Finance", "fin": "Finance",
    "family": "Family", "fam": "Family",
    "property": "Property", "prop": "Property",
    "penal": "Penal", "agriculture": "Agriculture", "agric": "Agriculture",
    "utilities": "Utilities", "util": "Utilities",
    "business & commerce": "Business & Commerce", "bus & com": "Business & Commerce",
    "business organizations": "Business Organizations", "bus orgs": "Business Organizations",
    "civil practice & remedies": "Civil Practice & Remedies",
    "civ prac & rem": "Civil Practice & Remedies",
    "alcoholic beverage": "Alcoholic Beverage", "alco bev": "Alcoholic Beverage",
    "parks & wildlife": "Parks & Wildlife",
    "special districts local laws": "Special District Local Laws",
    "special district local laws": "Special District Local Laws",
    "estates": "Estates", "est": "Estates",
}
_STATUTE_RE = re.compile(
    r"\b((?:[A-Za-z&][\w'’&.]*\s+){1,4})CODE\b\s*(?:ANN\.\s*)?"
    r"(?:§{1,2}|Sec(?:tion|s?\.))\s*(\d[\w.\-]*(?:\([^)\s]{1,8}\))*)",
    re.I,
)


def _canon_code(raw: str) -> str | None:
    phrase = raw.lower().replace("’", "'").replace(".", " ")
    phrase = phrase.replace(" and ", " & ")
    phrase = _WS.sub(" ", phrase).strip()
    phrase = re.sub(r"^(see|also|e\s*g|cf|the|under|in|of|generally)\s+", "", phrase).strip()
    phrase = re.sub(r"^(tex|texas)\s+", "", phrase).strip()
    while phrase and phrase not in CODE_ALIASES:
        parts = phrase.split(" ", 1)
        if len(parts) == 1:
            return None
        phrase = parts[1]
    return CODE_ALIASES.get(phrase)


def extract_statute_cites(text: str) -> list[str]:
    """Section-level Texas code citations in opinion text (pure over text).

    Edges point at the *section*, not the pincite: "§86.021(d)" and "§86.021"
    are the same statute node, which is what makes "who else touches this
    section" answerable across connectors.
    """
    flat = _deline(text)
    out: dict[str, None] = {}
    for m in _STATUTE_RE.finditer(flat):
        code = _canon_code(m.group(1))
        if not code:
            continue
        section = m.group(2).rstrip(".,;").split("(")[0]
        out.setdefault(f"{code} Code §{section}", None)
    return list(out)


def parse_opinion_text(text: str) -> dict:
    """Opinion text -> number, date, question presented, request cross-ref,
    conclusion, statute citations. Pure over text.

    The ``Re:`` line is the opinion's own statement of the question presented
    and ends with the request number that produced it — the explicit
    request→opinion join. The ``S U M M A R Y`` block is the conclusion.
    """
    number = _OPINION_NO.search(text)
    re_m = _RE_LINE.search(text)
    re_line = _deline(re_m.group(1)) if re_m else None
    xref = _RQ_XREF.search(re_line or text)
    question = re_line
    if question and xref:
        question = _WS.sub(" ", question.replace(f"({xref.group(1)})", "")).strip()

    summary = _SUMMARY.search(text)
    conclusion = None
    if summary:
        conclusion = _deline(_PAGE_FOOTER.sub("", summary.group(1)))

    dates = _LETTER_DATE.findall(text[:600])
    return {
        "number": number.group(1) if number else None,
        "date": iso_date(dates[0]) if dates else None,
        "re_line": re_line,
        "question": question,
        "request_number": xref.group(1) if xref else None,
        "conclusion": conclusion,
        "statutes": extract_statute_cites(text),
    }


def extract_opinion_pdf(content: bytes) -> dict:
    """Opinion PDF bytes -> parsed record. Pure over bytes.

    Modern opinions are born-digital with a clean text layer; 1939-era ones
    are scans with 1998-vintage OCR. Extraction is always attempted and the
    *outcome* recorded, so a garbled scan is a measured fact rather than a
    silent empty parse.
    """
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = len(pdf.pages)
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as exc:  # a scan pdfplumber cannot open is still a fact
        return {"pages": 0, "chars": 0, "text": "", "text_recovered": False,
                "error": str(exc), "number": None, "date": None, "re_line": None,
                "question": None, "request_number": None, "conclusion": None,
                "statutes": []}
    rec = parse_opinion_text(text)
    chars = len(text.strip())
    rec.update({"pages": pages, "chars": chars, "text": text,
                "text_recovered": chars >= 500, "error": None})
    return rec


# ---------------------------------------------------------- the overruled list

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
# Affected-opinion cell: modern zero-padded numbers ("KP-0326 (2020)"), the
# unpadded older style ("DM-56 (1991)"), amended-opinion suffixes ("DM-45A")
# and the 1990s letter-opinion series ("LO-98-125").
_AFFECTED = re.compile(r"^([A-Z]{1,2}-\d{1,4}[A-Z]?(?:-\d{2,4})?)\s*(?:\((\d{4})\))?$", re.I)
_DISCLAIMER = re.compile(r"<p>(This list of overruled[^<]*)</p>", re.S | re.I)

# Free-text status phrasing, 40+ distinct forms live. Order is precedence:
# a withdrawal outranks an overruling outranks a supersession, and an
# affirmation is checked before "clarified/modified" so "Affirmed/clarified
# by" reads as the affirmation it is.
_STATUS_RULES = (
    ("withdrawn", ("withdrawn",)),
    ("overruled", ("overrul",)),
    ("superseded", ("supersed", "superced", "repealed")),
    ("affirmed", ("affirm", "sustained", "cited and approved")),
    ("modified", ("modif", "clarif", "correct", "reconsider")),
)
# Which of those actually displace the opinion as law. ag_opinion.status keeps
# the schema's documented vocabulary (active|overruled|modified|withdrawn);
# the fine-grained normalized status lives on ag_supersession.
_STATUS_TO_OPINION = {
    "withdrawn": "withdrawn",
    "overruled": "overruled",
    "superseded": "overruled",
    "modified": "modified",
    "affirmed": "active",   # an affirmation strengthens; it never invalidates
    "listed": "active",
}
_SEVERITY = {"active": 0, "modified": 1, "overruled": 2, "withdrawn": 3}


def normalize_status(raw: str) -> str:
    low = (raw or "").lower()
    for status, needles in _STATUS_RULES:
        if any(n in low for n in needles):
            return status
    return "listed"


# A displacing AG document: an opinion (KP-0445), an amended one (DM-45A), a
# letter opinion (LO-98-019), an open-records decision (ORD-624), and the
# occasional un-hyphenated typo in the source ("JC0249").
_BY_OPINION = re.compile(r"^(?:see\s+)?(?:ORD|[A-Z]{1,2})-?\d{1,4}[A-Z]?(?:-\d{2,4})?\b", re.I)
_BY_BILL = re.compile(r"\b(?:h|s)\.?\s?[bjc]\.?\s?r?\.?\s?\d|\b\d{2,3}(?:st|nd|rd|th)\s+leg", re.I)
_BY_CASE = re.compile(
    r"\bv\.\s|\d+\s+s\.?w\.?\s?\d|\bf\.\s?\d|\bu\.s\.\s\d|(?:court|ct\.)\s+decision", re.I)


def classify_by_what(raw: str, raw_html: str = "") -> str:
    """What did the displacing: opinion, bill, case, statute, letter.

    Order matters — a session law cites the code section it amended ("HB 1118
    ... (amending Government Code section 2054.5191)"), and the *bill* is what
    overruled the opinion, so the bill test runs before the statute test.
    """
    raw = raw or ""
    low = raw.lower()
    if _BY_OPINION.match(raw) or "att'y gen" in low or "attorney general op" in low:
        return "opinion"
    if _BY_BILL.search(raw):
        return "bill"
    if "<em>" in raw_html or _BY_CASE.search(raw):
        return "case"
    if "code" in low or "const" in low or "§" in raw or "sect" in low or "stat" in low:
        return "statute"
    if "letter" in low or re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", raw.strip()):
        return "letter"
    return "unknown"


def parse_supersession(content: bytes) -> list[dict]:
    """Overruled/modified/affirmed/withdrawn table -> one dict per entry.

    Rows are grouped under bold AG-name headers; the three columns are the
    affected opinion (with its year), the free-text status, and what did it.
    """
    html = content.decode("utf-8", errors="replace")
    out: list[dict] = []
    ag_name = None
    for row in _ROW.findall(html):
        cells_html = _CELL.findall(row)
        cells = [strip_html(c) for c in cells_html]
        if len(cells) < 2 or not cells[0]:
            continue
        if "<b>" in cells_html[0] and not _AFFECTED.match(cells[0]):
            ag_name = cells[0]
            continue
        m = _AFFECTED.match(cells[0])
        if not m:
            continue
        status_raw = cells[1]
        by_what = cells[2] if len(cells) > 2 else ""
        by_html = cells_html[2] if len(cells_html) > 2 else ""
        out.append({
            "number": m.group(1).upper(),
            "year": m.group(2),
            "status_raw": status_raw,
            "status": normalize_status(status_raw),
            "by_what": by_what or None,
            # An entry can name no displacing document at all ("Statute on
            # which opinion was based was repealed"); the status text is then
            # the only evidence of what kind of change it was.
            "by_kind": classify_by_what(by_what or status_raw, by_html),
            "ag_name": ag_name,
        })
    return out


def parse_supersession_disclaimer(content: bytes) -> str | None:
    """The publisher's own completeness disclaimer, kept verbatim.

    The list "is not entirely complete" by its own admission — the single most
    important sentence on the page, and the reason absence is not evidence.
    """
    m = _DISCLAIMER.search(content.decode("utf-8", errors="replace"))
    return strip_html(m.group(1)) if m else None


# ------------------------------------------------------------------ storage


def store_administration(conn: sqlite3.Connection, rec: dict, doc_id: str | None) -> None:
    row = {k: rec[k] for k in (
        "ledger", "slug", "ag_name", "years_raw", "year_start", "year_end", "provisional",
        "prefix", "first_number", "last_number", "count_est", "range_raw", "url")}
    row["doc_id"] = doc_id
    dbx.upsert(conn, "ag_administration", row, ["ledger", "slug"])


def store_opinion(conn: sqlite3.Connection, rec: dict, doc_id: str | None = None) -> None:
    """Upsert an opinion without ever touching its status.

    Status is owned by the supersession differ; an index re-read must not
    silently reset an overruled opinion back to 'active'.
    """
    row = {
        "number": rec["number"],
        "ag_code": rec.get("ag_code") or rec["number"].split("-")[0],
        "date": rec.get("date"),
        "request_number": rec.get("request_number"),
        "summary": rec.get("summary"),
        "doc_id": doc_id,
    }
    cols = [c for c, v in row.items() if v is not None or c == "number"]
    dbx.upsert(conn, "ag_opinion", {c: row[c] for c in cols}, ["number"],
               update_cols=[c for c in cols if c != "number"])


def store_request(conn: sqlite3.Connection, rec: dict, doc_id: str | None = None) -> None:
    row = {"number": rec["number"], "date": rec.get("date"),
           "requestor_raw": rec.get("requestor_raw"), "doc_id": doc_id}
    cols = [c for c, v in row.items() if v is not None or c == "number"]
    dbx.upsert(conn, "ag_request", {c: row[c] for c in cols}, ["number"],
               update_cols=[c for c in cols if c != "number"])
    dbx.upsert(
        conn, "ag_request_detail",
        {"number": rec["number"], "status": rec.get("status"), "summary": rec.get("summary"),
         "requestor_office": rec.get("requestor"), "requestor_location": rec.get("requestor_location"),
         "url": rec.get("url"), "pdf_url": rec.get("pdf_url"), "doc_id": doc_id},
        ["number"],
    )
    if rec.get("requestor"):
        # No stable requestor ID exists (free-text office/title) — the audit's
        # entity-resolution gap. The name is still a citable assertion.
        dbx.add_edge(conn, "organization_name", rec["requestor"], "requested",
                     "ag_request", rec["number"], "explicit", doc_id)
    if rec.get("answered_by"):
        link_request_to_opinion(conn, rec["answered_by"], rec["number"], doc_id)


def link_request_to_opinion(
    conn: sqlite3.Connection, opinion: str, request: str, doc_id: str | None
) -> None:
    """RQ →answered_by→ opinion, explicit: the number is printed in the source."""
    conn.execute("INSERT OR IGNORE INTO ag_request (number) VALUES (?)", (request,))
    conn.execute(
        "INSERT INTO ag_opinion (number, ag_code, request_number) VALUES (?,?,?) "
        "ON CONFLICT(number) DO UPDATE SET request_number=COALESCE(excluded.request_number, "
        "ag_opinion.request_number)",
        (opinion, opinion.split("-")[0], request),
    )
    dbx.add_edge(conn, "ag_request", request, "answered_by", "ag_opinion", opinion,
                 "explicit", doc_id)


def store_opinion_pdf(conn: sqlite3.Connection, rec: dict, doc_id: str, url: str) -> None:
    """Persist a parsed opinion PDF: text outcome, Q→conclusion, and edges."""
    number = rec["number"]
    dbx.upsert(
        conn, "ag_opinion_text",
        {"number": number, "doc_id": doc_id, "url": url, "pages": rec.get("pages"),
         "chars": rec.get("chars"), "text_recovered": int(bool(rec.get("text_recovered"))),
         "question": rec.get("question"), "conclusion": rec.get("conclusion"),
         "error": rec.get("error")},
        ["number"],
    )
    store_opinion(conn, {"number": number, "date": rec.get("date"),
                         "request_number": rec.get("request_number"),
                         "summary": rec.get("question")}, doc_id)
    if rec.get("request_number"):
        link_request_to_opinion(conn, number, rec["request_number"], doc_id)
    for cite in rec.get("statutes", []):
        # Derived, not explicit: an opinion has no structured citation field —
        # these are mined out of prose and can over- or under-count.
        dbx.add_edge(conn, "ag_opinion", number, "interprets", "statute", cite,
                     "derived", doc_id)


def apply_supersession(
    conn: sqlite3.Connection, rows: list[dict], source_url: str, doc_id: str | None = None
) -> dict:
    """Diff the overruled list into ag_supersession and ag_opinion.status.

    Change detection is a diff of *this list*, not of the opinion numbering:
    an opinion goes stale years after it publishes, with no new number
    anywhere. Both directions matter — a new entry means an opinion just
    became bad law, and an entry that disappeared means the office withdrew a
    status claim LobbyBook is still repeating. Vanished entries are reported,
    never deleted; the last state they were seen in stays on the record.
    """
    retrieved = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    stored = {
        (r["number"], r["status_raw"], r["by_what_key"])
        for r in conn.execute(
            "SELECT number, status_raw, by_what_key FROM ag_supersession WHERE source_url=?",
            (source_url,),
        )
    }
    seen: set[tuple[str, str, str]] = set()
    for r in rows:
        key = (r["number"], r["status_raw"], r["by_what"] or "")
        seen.add(key)
        dbx.upsert(
            conn, "ag_supersession",
            {"number": r["number"], "status_raw": r["status_raw"], "by_what_key": key[2],
             "status": r["status"], "by_what": r["by_what"], "by_kind": r["by_kind"],
             "year": r["year"], "ag_name": r["ag_name"], "source_url": source_url,
             "first_seen": retrieved, "retrieved_at": retrieved, "doc_id": doc_id},
            ["number", "status_raw", "by_what_key"],
            # first_seen is set once: when the office started saying this.
            update_cols=["status", "by_what", "by_kind", "year", "ag_name",
                         "retrieved_at", "doc_id"],
        )
        note = f"{r['status_raw']} {r['by_what'] or ''}".strip()
        note = f"{note} — source: {source_url} (list is incomplete by its publisher's own statement)"
        opinion_status = _STATUS_TO_OPINION.get(r["status"], "active")
        cur = conn.execute(
            "SELECT status, status_note FROM ag_opinion WHERE number=?", (r["number"],)
        ).fetchone()
        if cur is None:
            conn.execute(
                "INSERT INTO ag_opinion (number, ag_code, status, status_note) VALUES (?,?,?,?)",
                (r["number"], r["number"].split("-")[0], opinion_status,
                 note if opinion_status != "active" else None),
            )
        elif _SEVERITY.get(opinion_status, 0) > _SEVERITY.get(cur["status"], 0):
            # An opinion can carry several entries; the strongest signal wins,
            # and a weaker one never downgrades a recorded invalidation.
            conn.execute("UPDATE ag_opinion SET status=?, status_note=? WHERE number=?",
                         (opinion_status, note, r["number"]))
        elif opinion_status != "active" and cur["status"] == opinion_status and not cur["status_note"]:
            conn.execute("UPDATE ag_opinion SET status_note=? WHERE number=?",
                         (note, r["number"]))
        if r["by_kind"] in ("statute", "bill", "case", "opinion") and r["by_what"]:
            dbx.add_edge(conn, "ag_opinion", r["number"], "superseded_by", r["by_kind"],
                         r["by_what"], "explicit", doc_id)
    gone = sorted(stored - seen)
    return {"entries": len(rows), "new": len(seen - stored), "gone": len(gone),
            "gone_keys": [f"{n} {s}" for n, s, _ in gone[:20]]}


# ---------------------------------------------------------------- connector


@register
class AGConnector(Connector):
    name = "ag"
    tier = 2
    cadence = "daily"

    DDL = """
    -- The numbering ledger: one row per administration per corpus. Holds the
    -- range endpoints that make a 1939-to-now backfill enumerable, and the
    -- date span that disambiguates 'GA-0997' (Abbott AG opinion) from 'GA-40'
    -- (Abbott executive order).
    CREATE TABLE IF NOT EXISTS ag_administration (
        ledger       TEXT NOT NULL,           -- opinion|request
        slug         TEXT NOT NULL,           -- 'gerald-mann'
        ag_name      TEXT NOT NULL,
        years_raw    TEXT,
        year_start   INTEGER,
        year_end     INTEGER,                 -- NULL while the AG is sitting
        provisional  INTEGER NOT NULL DEFAULT 0,
        prefix       TEXT,                    -- 'O','KP','GA'
        first_number TEXT,
        last_number  TEXT,
        count_est    INTEGER,
        range_raw    TEXT,
        url          TEXT,
        doc_id       TEXT REFERENCES document(id),
        PRIMARY KEY (ledger, slug)
    );

    -- Request fields the shared ag_request table has no column for; the
    -- requestor office is split out because it is the opposition-research
    -- handle and has no stable ID.
    CREATE TABLE IF NOT EXISTS ag_request_detail (
        number             TEXT PRIMARY KEY,
        status             TEXT,              -- 'Pending' | 'Withdrawn' | ...
        summary            TEXT,
        requestor_office   TEXT,
        requestor_location TEXT,
        url                TEXT,
        pdf_url            TEXT,
        doc_id             TEXT REFERENCES document(id)
    );

    -- The opinion's own Question Presented -> Conclusion structure, plus the
    -- measured outcome of text extraction (born-digital vs 1939 scan).
    CREATE TABLE IF NOT EXISTS ag_opinion_text (
        number         TEXT PRIMARY KEY,
        doc_id         TEXT REFERENCES document(id),
        url            TEXT,
        pages          INTEGER,
        chars          INTEGER,
        text_recovered INTEGER NOT NULL DEFAULT 0,
        question       TEXT,
        conclusion     TEXT,
        error          TEXT
    );

    -- Every supersession signal, with the source that asserted it. Kept as a
    -- log rather than collapsed into ag_opinion.status because the list is
    -- incomplete by its publisher's own statement: absence proves nothing,
    -- and a later entry must be diffable against what was seen before.
    CREATE TABLE IF NOT EXISTS ag_supersession (
        number       TEXT NOT NULL,
        status_raw   TEXT NOT NULL,           -- verbatim ('Overruled by')
        by_what_key  TEXT NOT NULL,           -- by_what, '' when absent (PK part)
        status       TEXT NOT NULL,           -- overruled|superseded|modified|withdrawn|affirmed
        by_what      TEXT,
        by_kind      TEXT,                    -- statute|bill|case|opinion|letter|unknown
        year         TEXT,
        ag_name      TEXT,
        source_url   TEXT NOT NULL,
        first_seen   TEXT,                    -- when the office started saying it
        retrieved_at TEXT,                    -- when it was last seen on the list
        doc_id       TEXT REFERENCES document(id),
        PRIMARY KEY (number, status_raw, by_what_key)
    );
    """

    # ------------------------------------------------------------ opinions

    def ingest_opinions(self, conn: sqlite3.Connection) -> dict:
        """One GET of /opinions: the ledger plus the newest opinions."""
        resp = fetcher().get(OPINIONS_URL)
        resp.raise_for_status()
        doc_id = "ag:index:opinions"
        store_document(
            conn, doc_id=doc_id, source_family="ag", content=resp.content, url=OPINIONS_URL,
            doc_type="ag_opinion_index", authority="B",
            etag=resp.headers.get("ETag"), last_modified=resp.headers.get("Last-Modified"),
        )
        admins = parse_administrations(resp.content, "opinion")
        for a in admins:
            store_administration(conn, a, doc_id)
        recent = parse_recent_opinions(resp.content)
        for op in recent:
            store_opinion(conn, op, doc_id)
        conn.commit()
        return {"administrations": len(admins), "opinions": len(recent),
                "oldest_series": admins[-1]["first_number"] if admins else None,
                "recent": [o["number"] for o in recent],
                "pdf_urls": [{"number": o["number"], "pdf_url": o["pdf_url"]}
                             for o in recent if o["pdf_url"]]}

    def sample_opinion_pdf(self, conn: sqlite3.Connection, url: str) -> dict:
        """Fetch one opinion PDF, store the bytes, then parse them.

        Bytes land in the docstore before any parsing, so a 1939 scan whose
        OCR is unusable today is still captured for a later OCR pass.
        """
        resp = fetcher().get(url)
        resp.raise_for_status()
        rec = extract_opinion_pdf(resp.content)
        number = rec["number"] or url.rsplit("/", 1)[-1].removesuffix(".pdf").upper()
        rec["number"] = number
        doc_id = f"ag:opinion:{number}"
        store_document(
            conn, doc_id=doc_id, source_family="ag", content=resp.content, url=url,
            native_id=number, doc_type="ag_opinion_pdf", published_at=rec.get("date"),
            authority="B",
        )
        store_opinion_pdf(conn, rec, doc_id, url)
        conn.commit()
        rec["doc_id"] = doc_id
        return rec

    # ------------------------------------------------------------ requests

    def ingest_requests(self, conn: sqlite3.Connection, *, details: int = 3) -> dict:
        """Poll pending opinion requests. 1 + `details` live GETs, always.

        The index dates only its three newest requests and names no requestor,
        so the poller pages down from the ledger's high-water number into the
        detail pages the index does not cover — which is where the requestor,
        the status, and the request letter live.
        """
        resp = fetcher().get(REQUESTS_URL)
        resp.raise_for_status()
        doc_id = "ag:index:requests"
        store_document(
            conn, doc_id=doc_id, source_family="ag", content=resp.content, url=REQUESTS_URL,
            doc_type="ag_request_index", authority="C",
            etag=resp.headers.get("ETag"), last_modified=resp.headers.get("Last-Modified"),
        )
        admins = parse_administrations(resp.content, "request")
        for a in admins:
            store_administration(conn, a, doc_id)
        recent = parse_recent_requests(resp.content)
        for rq in recent:
            store_request(conn, {"number": rq["number"], "date": rq["date"],
                                 "summary": rq["summary"], "url": rq["url"]}, doc_id)
        conn.commit()

        current = admins[0] if admins else None
        seen = {r["number"] for r in recent}
        queue = numbers_below(current["last_number"], details, skip=seen) if current else []
        opened, failed = [], []
        for number in queue:
            rec = self.fetch_request(conn, number, current["slug"])
            (opened if rec else failed).append(number)
        conn.commit()
        pending = conn.execute(
            "SELECT COUNT(*) c FROM ag_request_detail WHERE status='Pending'"
        ).fetchone()["c"]
        dated = conn.execute(
            "SELECT COUNT(*) c FROM ag_request WHERE date IS NOT NULL"
        ).fetchone()["c"]
        return {"administrations": len(admins), "index_requests": len(recent),
                "details_opened": len(opened), "details_missing": len(failed),
                "dated": dated, "pending": pending,
                "high_water": current["last_number"] if current else None}

    def fetch_request(
        self, conn: sqlite3.Connection, number: str, admin_slug: str = "ken-paxton"
    ) -> dict | None:
        """One request detail page -> stored record (None when it 404s).

        A gap in the numbering is real (numbers get withdrawn before
        publication); it costs one request and is recorded as a miss rather
        than retried.
        """
        url = request_url(number, admin_slug)
        resp = fetcher().get(url)
        if resp.status_code != 200:
            return None
        doc_id = f"ag:request:{number}"
        store_document(
            conn, doc_id=doc_id, source_family="ag", content=resp.content, url=url,
            native_id=number, doc_type="ag_request_page", authority="C",
        )
        rec = parse_request_page(resp.content)
        rec["number"] = rec["number"] or number
        rec["url"] = url
        store_request(conn, rec, doc_id)
        return rec

    # -------------------------------------------------------- supersession

    def ingest_supersession(self, conn: sqlite3.Connection) -> dict:
        """Fetch and diff the overruled/modified/affirmed/withdrawn list."""
        resp = fetcher().get(SUPERSESSION_URL)
        resp.raise_for_status()
        doc_id = "ag:index:supersession"
        store_document(
            conn, doc_id=doc_id, source_family="ag", content=resp.content,
            url=SUPERSESSION_URL, doc_type="ag_supersession_list", authority="B",
            etag=resp.headers.get("ETag"), last_modified=resp.headers.get("Last-Modified"),
        )
        rows = parse_supersession(resp.content)
        stats = apply_supersession(conn, rows, SUPERSESSION_URL, doc_id)
        stats["disclaimer"] = parse_supersession_disclaimer(resp.content)
        conn.commit()
        return stats

    # ------------------------------------------------------------ backfill

    def backfill(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """Walk one administration's request series from its browse page.

        Bounded by `limit`; 1 + limit live GETs. The browse page is the audit's
        "renders empty without JS" index — its <option> list is plain HTML and
        enumerates every number in the series.
        """
        slug = kwargs.get("admin", "ken-paxton")
        limit = int(kwargs.get("limit", 5))
        url = f"{BASE}/requests/{slug}"
        resp = fetcher().get(url)
        resp.raise_for_status()
        doc_id = f"ag:requests:{slug}"
        store_document(conn, doc_id=doc_id, source_family="ag", content=resp.content,
                       url=url, doc_type="ag_request_browse", authority="C")
        options = parse_browse_options(resp.content)
        done = 0
        for opt in options[:limit]:
            if self.fetch_request(conn, opt["number"], slug):
                done += 1
        conn.commit()
        return {"admin": slug, "enumerated": len(options), "fetched": done}

    # --------------------------------------------------------- incremental

    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """Daily poll: both indexes, N request details, the supersession diff,
        and the PDFs of opinions seen for the first time.

        Live GETs = 2 + details + 1 + (PDFs of newly-published opinions,
        capped by `pdfs`) — knowable in advance, which is what keeps a daily
        cadence polite against a bot-mitigated host.
        """
        details = int(kwargs.get("details", 3))
        pdfs = int(kwargs.get("pdfs", 3))
        ops = self.ingest_opinions(conn)
        # An opinion whose PDF has not been fetched yet is the work queue; the
        # index gives the number and the summary, the PDF gives the request
        # cross-reference and the conclusion. The queue is keyed on the URL
        # actually fetched, not on the index's number, so a PDF that disagrees
        # with the index about its own number cannot make the queue immortal.
        fresh = [
            o for o in ops["pdf_urls"]
            if not conn.execute(
                "SELECT 1 FROM document WHERE url=? AND doc_type='ag_opinion_pdf'",
                (o["pdf_url"],)).fetchone()
        ][:pdfs]
        sampled = [self.sample_opinion_pdf(conn, o["pdf_url"])["number"] for o in fresh]
        rqs = self.ingest_requests(conn, details=details)
        sup = self.ingest_supersession(conn)
        return {"opinions": ops, "requests": rqs, "supersession": sup,
                "pdfs_parsed": sampled}

    # -------------------------------------------------------------- smoke

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """2 index GETs + 3 request detail GETs — 5 live requests, ceiling 6."""
        ops = self.ingest_opinions(conn)
        rqs = self.ingest_requests(conn, details=3)
        admins = conn.execute(
            "SELECT COUNT(*) c FROM ag_administration WHERE ledger='opinion'"
        ).fetchone()["c"]
        mann = conn.execute(
            "SELECT * FROM ag_administration WHERE ledger='opinion' AND year_start=1939"
        ).fetchone()
        dated = conn.execute(
            "SELECT COUNT(*) c FROM ag_request WHERE date IS NOT NULL"
        ).fetchone()["c"]
        requestors = conn.execute(
            "SELECT COUNT(*) c FROM ag_request_detail WHERE requestor_office IS NOT NULL"
        ).fetchone()["c"]
        stats = {
            "administrations": admins,
            "opinions": ops["opinions"],
            "recent_opinions": ops["recent"],
            "requests_dated": dated,
            "requests_pending": rqs["pending"],
            "requestors_named": requestors,
            "oldest_series": mann["first_number"] if mann else None,
            "high_water": rqs["high_water"],
        }
        ok = (
            admins >= 10
            and mann is not None
            and str(mann["prefix"]) == "O"
            and dated >= 5
        )
        return SmokeResult(
            ok=ok,
            detail=(
                f"ledger: {admins} administrations back to "
                f"{mann['ag_name'] if mann else '?'} "
                f"{mann['range_raw'] if mann else '?'}; "
                f"{ops['opinions']} recent opinions; {dated} dated requests "
                f"({requestors} with a named requestor), high water {rqs['high_water']}"
            ),
            stats=stats,
        )
