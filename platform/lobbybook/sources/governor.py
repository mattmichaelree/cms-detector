"""Texas Governor — appointments, executive orders, proclamations.

Spec: docs/texas-politics-audit/03-deep-dives/07-executive-orders.md.

Four verified facts shape this module:

  * **There is no EO index.** The news taxonomy is only Press Release /
    Appointment / Proclamation / Legislative Statement / Texanthropy; EOs post
    as press releases carrying an ad-hoc ``/uploads/files/press/EO-GA-##*.pdf``
    upload. Discovery is therefore *category polling*, not index reading, and
    RSS (a rolling 10-item window against a multi-post-per-day cadence) cannot
    carry it alone.
  * **No appointee roster exists anywhere.** The office announces ~1,500
    appointments per term as prose press releases and publishes no queryable
    list, so the roster is a build-it-yourself dataset: parse the announcement.
    Listing titles carry only a *surname* ("Appoints Nielsen To ..."); the full
    name lives in the post body, and a weekly "Latest Slate Of Appointments"
    post names a dozen people across a dozen boards in one page.
  * **The GA-number collision.** ``GA-####`` is an Abbott *AG opinion*
    (2002-14); ``GA-##`` is an Abbott *executive order* (2015+). Every id
    minted here is role-scoped, and :func:`eo_id` refuses AG-shaped numbers
    outright rather than silently minting a colliding key.
  * **The OCR lottery.** Governor-office PDFs are scanner output whose text
    layer is present, absent, or present-but-mangled with no chronological
    pattern. Extraction is always attempted and the *result* recorded
    (``governor_pdf_text.text_recovered``) instead of assumed.

Compliance: gov.texas.gov robots.txt blocks named AI crawlers (GPTBot,
ClaudeBot, ...) but not identified research tooling; every request goes
through the shared throttled fetcher under the platform UA, and this connector
samples bounded pages rather than crawling. LRL PDF paths are denylisted in
``core.fetch`` by LRL's own robots.txt and are never touched here.
"""

from __future__ import annotations

import io
import re
import sqlite3
from datetime import date, datetime
from html import unescape

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

BASE = "https://gov.texas.gov"
CATEGORY_URL = BASE + "/news/category/{category}"
# Listing pagination is offset-based: /news/category/appointment/P8 is items 8+.
CATEGORIES = ("appointment", "proclamation", "legislative", "press-release")

GOVERNOR = "abbott"

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# ----------------------------------------------------------------- listings

# One listing card. Note the date carries month + day but *no year* — the year
# has to be inferred against the poll date (see infer_year).
_CARD_SPLIT = '<div class="media-object m-b-4">'
_CARD_DATE = re.compile(
    r'date-month">\s*([A-Za-z]{3})\s*</span>\s*<span class="date-day">\s*(\d{1,2})\s*</span>'
)
_CARD_LINK = re.compile(r'<h3 class="h2"><a href="([^"]+)"\s*>(.*?)</a>', re.S)
_NEXT_PAGE = re.compile(r'href="([^"]+)" class="pagination-next')

# Post pages open with "<p class="meta">August 25, 2026 | Austin, Texas | ...".
_META = re.compile(r'<p class="meta">\s*([A-Z][a-z]+ \d{1,2}, \d{4})\s*\|(.*?)</p>', re.S)
_META_CAT = re.compile(r'/news/category/([a-z-]+)"[^>]*>([^<]+)</a>')
_CONTENT = re.compile(r'class="l-content columns[^"]*"\s*>(.*?)</section>', re.S)
_PARA = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S)
_STRONG_LINK = re.compile(r"<strong>\s*(?:<a[^>]*>)?(.*?)(?:</a>)?\s*</strong>", re.S)

_MONTHS = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), start=1)}


def strip_html(html: str) -> str:
    return _WS.sub(" ", unescape(_TAG.sub(" ", html))).strip()


def infer_year(month: str, day: int, ref: date) -> int:
    """Listing cards print 'Aug 26' with no year. A card can only be at or
    before the poll date, so a month ahead of the reference month belongs to
    the previous year."""
    mon = _MONTHS[month[:3].title()]
    if (mon, day) > (ref.month, ref.day):
        return ref.year - 1
    return ref.year


def parse_listing(content: bytes, category: str, ref: date | None = None) -> list[dict]:
    """Category listing HTML -> dated items. Pure over bytes."""
    ref = ref or date.today()
    html = content.decode("utf-8", errors="replace")
    items: list[dict] = []
    for card in html.split(_CARD_SPLIT)[1:]:
        link = _CARD_LINK.search(card)
        if not link:
            continue
        dm = _CARD_DATE.search(card)
        published = None
        if dm:
            mon, day = dm.group(1), int(dm.group(2))
            published = f"{infer_year(mon, day, ref):04d}-{_MONTHS[mon.title()]:02d}-{day:02d}"
        items.append({
            "url": link.group(1).split("#")[0],
            "title": strip_html(link.group(2)),
            "date": published,
            "category": category,
        })
    return items


def next_page_url(content: bytes) -> str | None:
    m = _NEXT_PAGE.search(content.decode("utf-8", errors="replace"))
    return m.group(1) if m else None


def parse_post(content: bytes) -> dict:
    """Post page -> {date, categories, paragraphs(html), text}."""
    html = content.decode("utf-8", errors="replace")
    body = _CONTENT.search(html)
    inner = body.group(1) if body else ""
    meta = _META.search(inner)
    published, categories = None, []
    if meta:
        published = datetime.strptime(meta.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
        categories = [c[0] for c in _META_CAT.findall(meta.group(2))]
    paras = [p for p in _PARA.findall(inner) if 'class="meta"' not in p]
    return {
        "date": published,
        "categories": categories,
        "paragraphs": paras,
        "text": strip_html(inner),
        "pdf_links": pdf_links(html),
    }


_PDF_HREF = re.compile(r'href="([^"]+\.pdf)"', re.I)


def pdf_links(html: str) -> list[str]:
    out = []
    for href in _PDF_HREF.findall(html):
        out.append(href if href.startswith("http") else BASE + href)
    return list(dict.fromkeys(out))


# ------------------------------------------------------------- appointments

# Counted/collective stand-ins that appear where names would ("Reappoints Three
# To ...", "Announces Latest Slate Of Appointments") — the title is generic and
# the body must be parsed instead.
_COUNT_WORDS = {
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty", "multiple", "several",
}
_HONORIFICS = re.compile(
    r"^(?:Col\.|Lt\. Col\.|Maj\. Gen\.|Brig\. Gen\.|Gen\.|Capt\.|Sgt\.|Dr\.|Mr\.|Mrs\.|Ms\.|"
    r"Judge|Justice|Hon\.|Rev\.|Sen\.|Rep\.|Prof\.)\s+"
)
_SUFFIX = re.compile(r"^(?:Jr\.?|Sr\.?|I{1,3}|IV|V|M\.?D\.?|Ph\.?D\.?|D\.?O\.?|Esq\.?|CPA)$", re.I)

_TITLE_APPT = re.compile(
    r"Governor\s+Abbott\s+(Re-?appoints|Appoints|Names)\s+(.+?)\s+(To|As)\s+(.+)$", re.I
)
# A single title can carry two verbs and a role word:
# "Names Williams Chair, Appoints Lewis, Cardenas To ..." — so each comma-
# separated fragment is cleaned of stray verbs and trailing role nouns before
# it is accepted as a surname.
_TITLE_VERB_TOKEN = re.compile(r"^(?:And\s+)?(?:Re-?appoints|Appoints|Names)\s+", re.I)
_TITLE_ROLE_TAIL = re.compile(
    r"\s+(?:Chair(?:man|woman|person)?|Presiding\s+Officer|Vice\s+Chair|Commissioner|Director)$",
    re.I,
)

# Names may legitimately contain periods ("Col. Omar A. Perea", "Lemuel
# Williams, Jr."), so the name run cannot simply stop at the first '.'. It ends
# at an explicit terminator instead: the term clause, the board clause, a role
# clause, or the next appointment verb in the same sentence ("appointed Darryl
# Heath and Colt McCoy and reappointed Ashlie Thomas ...").
_BODY_VERB = re.compile(
    r"\b(re-?appointed|appointed|named|selected)\s+"
    r"(?P<names>[A-Z][^;]{0,160}?)"
    r"(?=\s+for\s+(?:a\s+)?terms?\b"
    r"|\s+to\s+(?:the|serve)\b"
    r"|\s+as\s+(?:chair|the|presiding|commissioner|director)\b"
    r"|[,]?\s*(?:and\s+)?(?:re-?appointed|appointed|named)\b"
    r"|\s*$)",
    re.I,
)
_BODY_BOARD = re.compile(r"\bto\s+the\s+(?P<board>[A-Z][A-Za-z0-9'’&.\- ]{4,90}?)"
                         r"(?=\s+for\s+(?:a\s+)?terms?|\s+for\s+a\s+term|,|\.|$)")
_POSITION_WORDS = re.compile(
    r"\b(Commissioner|Director|Secretary|Judge|Justice|Chair|Chancellor|Chief|Administrator|Presiding)\b",
    re.I,
)
_ORG_WORDS = re.compile(
    r"\b(Board|Committee|Commission|Council|Authority|Task Force|District|Corporation|"
    r"Department|Agency|Center|Institute|System|Fund|Court|University|Foundation)\b",
    re.I,
)


def normalize_name(raw: str) -> str:
    """Strip honorifics and collapse whitespace; keep generational suffixes."""
    n = _WS.sub(" ", unescape(raw)).strip(" ,;")
    prev = None
    while prev != n:
        prev = n
        n = _HONORIFICS.sub("", n).strip()
    return n


def split_names(blob: str) -> list[str]:
    """'Nelda Barrera, Colby McClendon, and Scott Frazier' -> three names.

    The comma is overloaded: it separates people *and* attaches generational
    suffixes ('Lemuel Williams, Jr.'), so suffix fragments are folded back onto
    the preceding name rather than emitted as a person.
    """
    blob = _WS.sub(" ", unescape(blob)).strip(" ,;")
    parts = [p.strip() for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", blob) if p.strip()]
    out: list[str] = []
    for p in parts:
        if out and _SUFFIX.match(p):
            out[-1] = f"{out[-1]}, {p}"
            continue
        out.append(p)
    names = []
    for n in out:
        n = normalize_name(n)
        # A real name is 2-5 capitalised tokens; anything else is prose that
        # leaked past the terminator.
        toks = [t for t in n.split(" ") if t]
        if 2 <= len(toks) <= 6 and all(t[:1].isupper() or t[:1] in "'’" for t in toks):
            names.append(n)
    return list(dict.fromkeys(names))


def classify_target(target: str) -> tuple[str | None, str | None]:
    """Return (board, position) for an appointment target string."""
    t = _WS.sub(" ", unescape(target)).strip(" .,")
    if not t:
        return None, None
    if _ORG_WORDS.search(t):
        return t, None
    if _POSITION_WORDS.search(t):
        return None, t
    return t, None


def parse_appointment_title(title: str) -> dict | None:
    """Listing title -> {surnames, board, position, action, generic}.

    Titles carry surnames only ('Appoints Nielsen To ...'), and go generic when
    a post covers many people ('Reappoints Three To ...'). `generic` tells the
    caller the body must be fetched to recover the actual names.
    """
    t = _WS.sub(" ", unescape(title)).strip()
    if re.search(r"Slate Of Appointments", t, re.I):
        return {"surnames": [], "board": None, "position": None,
                "action": "appointed", "generic": True}
    m = _TITLE_APPT.search(t)
    if not m:
        return None
    verb, who, connector, target = m.group(1), m.group(2), m.group(3), m.group(4)
    surnames = []
    for frag in re.split(r",\s*|\s+And\s+", who, flags=re.I):
        frag = _TITLE_ROLE_TAIL.sub("", _TITLE_VERB_TOKEN.sub("", frag.strip())).strip()
        if frag:
            surnames.append(frag)
    generic = any(s.lower() in _COUNT_WORDS for s in surnames) or not surnames
    board, position = classify_target(target)
    if connector.lower() == "as":
        board, position = None, _WS.sub(" ", unescape(target)).strip(" .,")
    return {
        "surnames": [] if generic else surnames,
        "board": board,
        "position": position,
        "action": "reappointed" if verb.lower().startswith(("reappoint", "re-appoint")) else
                  ("named" if verb.lower() == "names" else "appointed"),
        "generic": generic,
    }


def parse_appointment_post(post: dict, fallback_board: str | None = None) -> list[dict]:
    """Post body -> one record per appointee.

    Single-appointee posts state the board inline ('appointed Misti Nielsen to
    the Texas State Board of ...'). Slate posts put the board in a bolded link
    heading the paragraph and then name several people against it, sometimes
    with different verbs in one sentence ('named X as chair, appointed Y and
    reappointed Z').
    """
    records: list[dict] = []
    for para_html in post["paragraphs"]:
        text = strip_html(para_html)
        if not text or not re.search(r"\b(appointed|reappointed|named|selected)\b", text, re.I):
            continue
        head = _STRONG_LINK.search(para_html)
        para_board = strip_html(head.group(1)) if head else None
        for m in _BODY_VERB.finditer(text):
            verb = m.group(1).lower().replace("-", "")
            names = split_names(m.group("names"))
            if not names:
                continue
            tail = text[m.end():]
            inline = _BODY_BOARD.search(tail[:200])
            target = None
            if inline and inline.group("board").lower() not in ("board", "authority", "committee"):
                target = inline.group("board")
            elif para_board:
                target = para_board
            elif fallback_board:
                target = fallback_board
            board, position = classify_target(target or "")
            if not board and not position:
                board = fallback_board
            action = "reappointed" if verb.startswith("reappoint") else (
                "named" if verb == "named" else "appointed")
            for name in names:
                records.append({
                    "appointee": name,
                    "board": board,
                    "position": position,
                    "action": action,
                    "announced": post["date"],
                })
    # A slate post repeats a person only if genuinely re-listed; dedup on the key.
    seen, out = set(), []
    for r in records:
        key = (r["appointee"], r["board"], r["position"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# ----------------------------------------- executive actions & id collisions

EO_NUM_RE = re.compile(r"\bEO[-_ ]?GA[-_ ]?(\d{1,3})\b", re.I)
EO_TEXT_RE = re.compile(r"\bExecutive Order\s+(?:No\.\s*)?GA[-\s]?(\d{1,3})\b", re.I)
SPECIAL_SESSION_RE = re.compile(
    r"\b(?:call(?:s|ing)?|convene[sd]?|convening|proclamation)\b.{0,60}\bspecial session\b"
    r"|\bspecial session\b.{0,60}\b(?:call|agenda|proclamation)\b",
    re.I | re.S,
)
VETO_RE = re.compile(r"\bveto(?:e[sd])?\b", re.I)
DISASTER_RE = re.compile(r"\b(disaster|drought|flooding|wildfire|storm|hurricane)\b", re.I)


class GANumberCollision(ValueError):
    """A GA-#### (AG-opinion shaped) number was offered as an executive order.

    Abbott issued AG opinions GA-0001..GA-1099 (2002-14) and executive orders
    GA-1..GA-57 (2015+). A bare 'GA-41' is ambiguous across those roles, so
    every id this module mints is role-scoped and four-digit forms are refused.
    """


def normalize_eo_number(number: str) -> str:
    """'GA41' | 'ga-41' | '41' -> 'GA-41'. Refuses AG-opinion shapes."""
    raw = str(number).strip().upper().replace("_", "-")
    m = re.fullmatch(r"(?:GA[-\s]?)?(\d{1,4})", raw)
    if not m:
        raise GANumberCollision(f"not a GA executive-order number: {number!r}")
    digits = m.group(1)
    # GA-0041 / GA-1099: zero-padded or >3 digits is the AG-opinion series.
    if len(digits) == 4 or (len(digits) > 1 and digits.startswith("0")):
        raise GANumberCollision(
            f"GA-{digits} is an Attorney General opinion number (2002-14), not an "
            f"executive order; ids must be role-scoped"
        )
    return f"GA-{int(digits)}"


def eo_id(governor: str, number: str) -> str:
    """Role-scoped executive-order id, e.g. 'EO:abbott:GA-41'."""
    return f"EO:{governor.lower()}:{normalize_eo_number(number)}"


def ag_opinion_id(governor: str, number: str) -> str:
    """The other side of the collision, for tests and cross-source joins."""
    raw = str(number).strip().upper().replace("GA-", "").replace("GA", "")
    return f"AG:{governor.lower()}:GA-{int(raw):04d}"


def _slug(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1][:120]


def action_id(kind: str, governor: str, item: dict) -> str:
    """Role-scoped id for every executive action.

    Proclamations have no native identifier at all and renewals reuse identical
    titles, so the key is minted from (kind, governor, date, URL slug) — never a
    bare number, which would collide across Abbott's two 'GA' roles.
    """
    if kind == "eo":
        return eo_id(governor, item["number"])
    prefix = {"proclamation": "PROC", "special_session_call": "SSC", "veto": "VETO"}[kind]
    return f"{prefix}:{governor.lower()}:{item.get('date') or 'undated'}:{_slug(item['url'])}"


def classify_action(item: dict, pdf_hrefs: tuple[str, ...] = ()) -> dict | None:
    """Listing item (+ any PDF hrefs on its post) -> executive_action fields.

    EO detection is deliberately two-sided: the *title* may say "Executive
    Order GA-##", or it may say nothing while the attached upload is named
    EO-GA-##.pdf. Either alone misses items.
    """
    title = item.get("title") or ""
    number = None
    for m in (EO_TEXT_RE.search(title), EO_NUM_RE.search(title)):
        if m:
            number = m.group(1)
            break
    if number is None:
        for href in pdf_hrefs:
            m = EO_NUM_RE.search(href)
            if m:
                number = m.group(1)
                break
    if number is not None:
        return {"kind": "eo", "number": normalize_eo_number(number),
                "governor": GOVERNOR, "date": item.get("date"), "title": title,
                "url": item["url"]}
    if SPECIAL_SESSION_RE.search(title):
        kind = "special_session_call"
    elif VETO_RE.search(title):
        kind = "veto"
    elif item.get("category") == "proclamation" or DISASTER_RE.search(title):
        kind = "proclamation"
    else:
        return None
    return {"kind": kind, "number": None, "governor": GOVERNOR,
            "date": item.get("date"), "title": title, "url": item["url"]}


# --------------------------------------------------------------- OCR lottery

# Glued-word artifacts left by the office scanner's OCR ("Secretary ofState",
# "ofSit"). Their presence proves the text layer is machine-read, not
# born-digital — the distinction the audit found is non-chronological.
_OCR_ARTIFACT = re.compile(r"\bof(?:the|State|Texas|Sit|Justice|America)\b")


def extract_pdf_text(content: bytes) -> dict:
    """Attempt text extraction. Always attempt; record the outcome.

    Governor-office PDFs are an OCR lottery — some scans carry an imperfect
    text layer, some carry none, and it does not track with date. Callers get
    `text_recovered` as measured fact rather than an assumption.
    """
    import pdfplumber

    pages, chars, text = 0, 0, ""
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = len(pdf.pages)
            parts = [(p.extract_text() or "") for p in pdf.pages]
        text = "\n".join(parts)
        chars = len(text.strip())
    except Exception as exc:  # a scan that pdfplumber cannot open is still a fact
        return {"pages": 0, "chars": 0, "text": "", "text_recovered": False,
                "ocr_artifacts": 0, "error": str(exc)}
    return {
        "pages": pages,
        "chars": chars,
        "text": text,
        # A pure-image scan yields a handful of stray glyphs at most.
        "text_recovered": chars >= 200,
        "ocr_artifacts": len(_OCR_ARTIFACT.findall(text)),
        "error": None,
    }


# The audit found three dates on one EO that need not agree: the transmittal
# letter date, the Secretary of State's filing stamp, and any effective clause.
# All three are extracted separately rather than collapsed into one "date".
_EO_SUBJECT_RE = re.compile(
    r"Executive Order\s+(?:No\.\s*)?GA[-\s]?(\d{1,3})\s+relating to\s+(.+?)\.",
    re.I | re.S,
)
_LETTER_DATE_RE = re.compile(r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b")
# The SOS stamp is rubber-stamped and OCRs badly ("JUL 0 7 2022", and the
# surrounding "SECRETARY OF STATE" comes back as "SECRETPRYOF STATE"). A bare
# month-day-year search finds body prose first ("issued a disaster
# proclamation on May 31 2021"), so the stamp is anchored to the O'CLOCK line
# that always precedes it — the one token of the stamp OCR keeps legible.
_SOS_ANCHOR_RE = re.compile(r"O.{0,2}CLOCK", re.I)
_SOS_STAMP_RE = re.compile(
    r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s*(\d\s*\d?)\s*(\d)\s*(\d{4})", re.I
)


def parse_eo_pdf_text(text: str) -> dict:
    """Pull EO identity out of a (possibly OCR-mangled) governor PDF.

    Returns Nones rather than guesses when the text layer is absent — the
    OCR lottery means callers must handle an empty result as normal.
    """
    out: dict = {"number": None, "subject": None, "letter_date": None, "sos_filed": None}
    m = _EO_SUBJECT_RE.search(text)
    if m:
        out["number"] = normalize_eo_number(m.group(1))
        out["subject"] = _WS.sub(" ", m.group(2)).strip()
    if out["number"] is None:
        m2 = EO_NUM_RE.search(text) or EO_TEXT_RE.search(text) or re.search(r"\bGA[-\s]?(\d{1,3})\b", text)
        if m2:
            try:
                out["number"] = normalize_eo_number(m2.group(1))
            except GANumberCollision:
                out["number"] = None
    d = _LETTER_DATE_RE.search(text)
    if d:
        out["letter_date"] = datetime.strptime(d.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
    st = None
    for anchor in _SOS_ANCHOR_RE.finditer(text):
        st = _SOS_STAMP_RE.search(text, anchor.end(), anchor.end() + 80)
        if st:
            break
    if st:
        mon = _MONTHS[st.group(1).title()]
        day = int((st.group(2) + st.group(3)).replace(" ", ""))
        out["sos_filed"] = f"{st.group(4)}-{mon:02d}-{day:02d}"
    return out


# ------------------------------------------------------------------ storage


def store_appointment(conn: sqlite3.Connection, rec: dict, url: str, doc_id: str | None) -> None:
    """Upsert one appointee-to-body assertion plus its two explicit edges.

    ``appointment``'s natural key is (appointee_raw, board, announced). Both
    SQLite and Postgres treat NULL as distinct inside a UNIQUE constraint, so a
    NULL board — every "appointed X as Commissioner of Insurance", where the
    target is an office rather than a body — would defeat dedup and grow a new
    row on every poll. The key columns are therefore written empty-string-
    normalised, with the office kept in `position`.
    """
    board = rec.get("board")
    position = rec.get("position")
    dbx.upsert(
        conn,
        "appointment",
        {
            "governor": GOVERNOR,
            "appointee_raw": rec["appointee"],
            "position": position,
            "board": board if board is not None else "",
            "announced": rec.get("announced") or "",
            "url": url,
            "person_id": None,
        },
        ["appointee_raw", "board", "announced"],
        update_cols=["governor", "position", "url"],
    )
    dbx.add_edge(conn, "person", GOVERNOR, "appointed", "person_name",
                 rec["appointee"], "explicit", doc_id)
    target = rec.get("board") or rec.get("position")
    if target:
        dbx.add_edge(conn, "person_name", rec["appointee"], "serves_on",
                     "organization_name", target, "explicit", doc_id)


def store_action(conn: sqlite3.Connection, act: dict, doc_id: str | None) -> str:
    aid = action_id(act["kind"], act["governor"], act)
    dbx.upsert(
        conn,
        "executive_action",
        {
            "id": aid,
            "kind": act["kind"],
            "governor": act["governor"],
            "number": act.get("number"),
            "date": act.get("date"),
            "title": act.get("title"),
            "doc_id": doc_id,
        },
        ["id"],
    )
    predicate = {"eo": "issued", "special_session_call": "called",
                 "proclamation": "issued", "veto": "vetoed"}[act["kind"]]
    dbx.add_edge(conn, "person", act["governor"], predicate, "executive_action",
                 aid, "explicit", doc_id)
    return aid


@register
class GovernorConnector(Connector):
    name = "governor"
    tier = 1
    cadence = "daily"

    DDL = """
    -- Listing-level discovery log: the category pages are the only index that
    -- exists, so what they showed and when is itself provenance.
    CREATE TABLE IF NOT EXISTS governor_news_item (
        url      TEXT PRIMARY KEY,
        category TEXT NOT NULL,
        title    TEXT,
        date     TEXT,
        doc_id   TEXT REFERENCES document(id)
    );

    -- The OCR lottery, made measurable: every governor-office PDF records
    -- whether text extraction actually recovered anything, plus a count of the
    -- scanner's glued-word artifacts ("Secretary ofState") that mark an
    -- imperfect OCR layer as opposed to born-digital text.
    CREATE TABLE IF NOT EXISTS governor_pdf_text (
        doc_id         TEXT PRIMARY KEY REFERENCES document(id),
        url            TEXT,
        pages          INTEGER,
        chars          INTEGER,
        text_recovered INTEGER NOT NULL,
        ocr_artifacts  INTEGER,
        error          TEXT
    );
    """

    # ---------------------------------------------------------- category poll

    def poll_category(
        self,
        conn: sqlite3.Connection,
        category: str,
        ref: date | None = None,
    ) -> list[dict]:
        """Fetch one category listing, store it, return its dated items."""
        url = CATEGORY_URL.format(category=category)
        resp = fetcher().get(url)
        resp.raise_for_status()
        doc_id = f"governor:listing:{category}"
        store_document(
            conn, doc_id=doc_id, source_family="governor", content=resp.content,
            url=url, doc_type=f"governor_listing_{category}", authority="E",
            etag=resp.headers.get("ETag"), last_modified=resp.headers.get("Last-Modified"),
        )
        items = parse_listing(resp.content, category, ref)
        for it in items:
            dbx.upsert(conn, "governor_news_item",
                       {"url": it["url"], "category": category, "title": it["title"],
                        "date": it["date"], "doc_id": doc_id},
                       ["url"], update_cols=["category", "title", "date", "doc_id"])
        conn.commit()
        return items

    def fetch_post(self, conn: sqlite3.Connection, url: str) -> dict:
        resp = fetcher().get(url)
        resp.raise_for_status()
        doc_id = f"governor:post:{_slug(url)}"
        post = parse_post(resp.content)
        store_document(
            conn, doc_id=doc_id, source_family="governor", content=resp.content,
            url=url, doc_type="governor_post", published_at=post["date"], authority="E",
        )
        post["doc_id"] = doc_id
        return post

    # ------------------------------------------------------------ ingestion

    def ingest_appointments(
        self,
        conn: sqlite3.Connection,
        *,
        details: int = 0,
        open_generic: bool = True,
        max_posts: int = 12,
        ref: date | None = None,
    ) -> dict:
        """Poll the appointment category and record every appointee found.

        Listing titles carry a surname and a board — enough to count and route,
        not enough for a roster. Two request tiers follow from that:

        * a *generic* item ("Announces Latest Slate Of Appointments",
          "Reappoints Three To ...") names nobody in its title, so its post is
          always opened when `open_generic` — it is the only way to learn any
          name at all, and one slate post can carry twenty appointees;
        * a named item already yields surname + board from the listing, so its
          post is opened only while the `details` budget lasts, to upgrade the
          surname to a full name.

        `max_posts` is a hard ceiling on post fetches so the live-request count
        of any run is knowable in advance: 1 + min(max_posts, matching items).
        """
        items = self.poll_category(conn, "appointment", ref)
        parsed, rows, opened = 0, 0, 0
        budget = details
        for it in items:
            title = parse_appointment_title(it["title"])
            if not title:
                continue
            parsed += 1
            generic = title["generic"]
            open_it = (generic and open_generic) or (not generic and budget > 0)
            if open_it and opened >= max_posts:
                open_it = False
            if open_it:
                if not generic:
                    budget -= 1
                opened += 1
                post = self.fetch_post(conn, it["url"])
                recs = parse_appointment_post(post, title["board"] or title["position"])
                for r in recs:
                    r["announced"] = r["announced"] or it["date"]
                    store_appointment(conn, r, it["url"], post["doc_id"])
                rows += len(recs)
            elif not generic:
                # Surname-only fallback: a real, citable assertion, and one the
                # audit's roster reconstruction can upgrade on a later pass.
                for sn in title["surnames"]:
                    store_appointment(
                        conn,
                        {"appointee": sn, "board": title["board"],
                         "position": title["position"], "announced": it["date"]},
                        it["url"], "governor:listing:appointment",
                    )
                rows += len(title["surnames"])
        conn.commit()
        return {"items": len(items), "titles_parsed": parsed,
                "posts_opened": opened, "appointments": rows}

    def ingest_actions(
        self,
        conn: sqlite3.Connection,
        *,
        categories: tuple[str, ...] = ("proclamation", "press-release"),
        ref: date | None = None,
    ) -> dict:
        """Poll proclamation/press listings and record executive actions."""
        counts: dict[str, int] = {}
        for cat in categories:
            items = self.poll_category(conn, cat, ref)
            for it in items:
                act = classify_action(it)
                if not act:
                    continue
                store_action(conn, act, f"governor:listing:{cat}")
                counts[act["kind"]] = counts.get(act["kind"], 0) + 1
        conn.commit()
        return counts

    def sample_pdf(self, conn: sqlite3.Connection, url: str, act: dict | None = None) -> dict:
        """Fetch one governor-office PDF, store it, then *measure* whether text
        extraction recovered anything (the OCR lottery) and, if it did, mine
        the EO's own identity out of it.

        Bytes land in the docstore before any parsing, so an image-only scan is
        still captured and re-parseable when OCR arrives later.
        """
        resp = fetcher().get(url)
        resp.raise_for_status()
        doc_id = f"governor:pdf:{_slug(url)}"
        store_document(conn, doc_id=doc_id, source_family="governor",
                       content=resp.content, url=url, doc_type="governor_pdf",
                       published_at=(act or {}).get("date"), authority="B")
        info = record_pdf_text(conn, doc_id, url, resp.content)
        ident = parse_eo_pdf_text(info["text"]) if info["text_recovered"] else {}
        info["identity"] = ident
        number = ident.get("number") or (
            EO_NUM_RE.search(url).group(1) if EO_NUM_RE.search(url) else None
        )
        if act is None and number:
            act = {"kind": "eo", "number": normalize_eo_number(number), "governor": GOVERNOR,
                   "date": ident.get("letter_date"), "url": url,
                   "title": ident.get("subject") or f"Executive Order {number}"}
        if act:
            act.setdefault("date", ident.get("letter_date"))
            info["action_id"] = store_action(conn, act, doc_id)
        conn.commit()
        return info

    # ---------------------------------------------------------------- runner

    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        details = int(kwargs.get("details", 2))
        appts = self.ingest_appointments(conn, details=details)
        actions = self.ingest_actions(conn)
        return {"appointments": appts, "actions": actions}

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """1 listing GET + at most 3 post GETs — 4 live requests, ceiling 8."""
        stats = self.ingest_appointments(conn, details=1, max_posts=3)
        rows = conn.execute(
            "SELECT COUNT(*) c FROM appointment "
            "WHERE COALESCE(NULLIF(board, ''), position) IS NOT NULL"
        ).fetchone()["c"]
        total = conn.execute("SELECT COUNT(*) c FROM appointment").fetchone()["c"]
        edges = conn.execute(
            "SELECT COUNT(*) c FROM edge WHERE predicate='appointed'"
        ).fetchone()["c"]
        stats["appointments_total"] = total
        stats["with_target"] = rows
        stats["appointed_edges"] = edges
        ok = stats["titles_parsed"] >= 5 and total >= 5 and rows >= 5
        return SmokeResult(
            ok=ok,
            detail=(f"appointment feed: {stats['items']} items, {stats['titles_parsed']} titles "
                    f"parsed, {total} appointments ({rows} with a board/position), {edges} edges"),
            stats=stats,
        )


def record_pdf_text(conn: sqlite3.Connection, doc_id: str, url: str, content: bytes) -> dict:
    info = extract_pdf_text(content)
    dbx.upsert(
        conn,
        "governor_pdf_text",
        {"doc_id": doc_id, "url": url, "pages": info["pages"], "chars": info["chars"],
         "text_recovered": int(info["text_recovered"]),
         "ocr_artifacts": info["ocr_artifacts"], "error": info["error"]},
        ["doc_id"],
    )
    return info
