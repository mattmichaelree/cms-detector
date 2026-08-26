"""Texas House & Senate Journals — the only authoritative source of named
roll-call votes and amendment dispositions in context.

Spec: docs/texas-politics-audit/03-deep-dives/03-journals.md (Tier 0, class A).

Ingestion shape (verified live, Aug 2026):

  * ``/{h,s}jrnl/{session}/html/data/jrnlData.txt`` is an undocumented jqGrid
    JSON payload: one row per journal *file*, carrying the calendar date, the
    legislative-day ordinal ("6th", "6th Cont.", "61st Supplement"), the
    printed page range, and anchor markup for the PDF + HTML renderings.
    Format is stable 74R-89R apart from column order inside the anchor cell
    and the filename convention (``day01`` in 76R, ``89RDAY01FINAL`` today) —
    so the dedup key is the *filename stem parsed out of the href*, never the
    calendar date and never the grid's own ``id`` (which is "1stDay" in the
    old era).  PRELIM->FINAL regeneration keeps the stem and changes the
    bytes, so the docstore's content hash carries change detection.

  * A day's HTML is one flowing document with no anchors and no page markers
    (audit §2).  Structure is carried entirely by ALL-CAPS centred headers and
    the chamber's boilerplate disposition sentences, so the segmenter keys on
    text, not markup.

  * House record votes print a sequential record number and semicolon-delimited
    named lists::

        SB 269 was passed by (Record 3200): 104 Yeas, 37 Nays, 3 Present, not voting.
        Yeas - Alders; Ashby; Barry; Bell, C.; Bell, K.; ...
        Nays - Allen; Anchia; ...
        Present, not voting - Mr. Speaker; Morales Shaw; Vasut(C).
        Absent, Excused, Committee Meeting - Cook; Little; ...

    The Senate prints ``by the following vote: Yeas 27, Nays 4.`` with
    comma-delimited lists and *no* record number (vote ids are synthesized),
    and reuses a preceding list with "(Same as previous roll call)".

Names are stored exactly as printed — "Bell, C.", "Vasut(C)", "A. Hinojosa" —
because the journal's own disambiguation is the resolution key (audit §4); the
spine resolves them to ``person`` later.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from html import unescape

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

CHAMBERS = {
    "house": {
        "host": "https://journals.house.texas.gov",
        "path": "hjrnl",
        "code": "H",
        "cite": "H. Jour.",
    },
    "senate": {
        "host": "https://journals.senate.texas.gov",
        "path": "sjrnl",
        "code": "S",
        "cite": "S. Jour.",
    },
}


def _chamber(chamber: str) -> dict:
    key = chamber.lower()
    if key in ("h", "house"):
        return CHAMBERS["house"]
    if key in ("s", "senate"):
        return CHAMBERS["senate"]
    raise ValueError(f"unknown chamber: {chamber!r}")


def chamber_key(chamber: str) -> str:
    """Normalize any chamber spelling to 'house' / 'senate'."""
    return "house" if _chamber(chamber)["code"] == "H" else "senate"


def index_url(chamber: str, session: str) -> str:
    c = _chamber(chamber)
    return f"{c['host']}/{c['path']}/{session}/html/data/jrnlData.txt"


def day_url(chamber: str, session: str, file_id: str) -> str:
    """Modern-era HTML URL. Pre-80R files are reached through the href stored
    on the journal_day row instead (naming differs by era)."""
    c = _chamber(chamber)
    return f"{c['host']}/{c['path'].upper()}/{session}/HTML/{file_id}.HTM"


# --------------------------------------------------------------- text layer

_BR_RE = re.compile(r"<br[^>]*>", re.I)
_BLOCK_END_RE = re.compile(r"</(div|p|tr|h[1-6]|li)>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(content: bytes) -> str:
    """Journal HTML -> line-oriented plain text.

    ``<br class="hardReturn">`` carries real line breaks inside a centred
    header (``SB 269 - RULES SUSPENDED`` / ``ADDITIONAL SPONSOR AUTHORIZED``);
    dropping it silently welds header lines together, so it is converted
    before tags are stripped.
    """
    text = content.decode("utf-8", errors="replace")
    text = _BR_RE.sub("\n", text)
    text = _BLOCK_END_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = unescape(text).replace("\xa0", " ").replace("‑", "-")
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# -------------------------------------------------------------- day index

_ANCHOR_RE = re.compile(r'href="([^"]+)"[^>]*>\s*([A-Za-z]+)', re.I)
_ROW_RE = re.compile(r'\{"id":"(?P<id>[^"]*)","cell":\[(?P<cells>.*?)\]\}', re.S)


def _stem(href: str) -> str:
    tail = href.rsplit("/", 1)[-1]
    return tail.rsplit(".", 1)[0]


def parse_day_index(content: bytes) -> list[dict]:
    """jrnlData.txt -> [{file_id, calendar_date, date_label, leg_day,
    page_start, page_end, page_range, html_url, pdf_url}].

    Tolerates the two verified era formats and falls back to a regex row
    scan if the payload is ever served as non-strict JSON.
    """
    raw = content.decode("utf-8-sig", errors="replace")
    rows: list[tuple[str, list[str]]] = []
    try:
        payload = json.loads(raw)
        for row in payload.get("rows", []):
            rows.append((str(row.get("id", "")), [str(c) for c in row.get("cell", [])]))
    except (ValueError, AttributeError):
        for m in _ROW_RE.finditer(raw):
            cells = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group("cells"))
            rows.append((m.group("id"), [c.encode().decode("unicode_escape") for c in cells]))

    out: list[dict] = []
    for row_id, cells in rows:
        cells = cells + [""] * (6 - len(cells))
        links = cells[5]
        html_url = pdf_url = None
        for href, label in _ANCHOR_RE.findall(links):
            if label.upper().startswith("PDF"):
                pdf_url = href
            elif label.upper().startswith("HTM"):
                html_url = href
        file_id = _stem(html_url or pdf_url or row_id)
        page_range = cells[4].strip()
        pm = re.match(r"(\d+)\s*[-–]\s*(\d+)", page_range)
        out.append(
            {
                "file_id": file_id,
                "row_id": row_id,
                "date_label": cells[0].strip(),
                "calendar_date": cells[1].strip() or None,
                "leg_day": cells[3].strip() or None,
                "page_range": page_range or None,
                "page_start": int(pm.group(1)) if pm else None,
                "page_end": int(pm.group(2)) if pm else None,
                "html_url": html_url,
                "pdf_url": pdf_url,
            }
        )
    return out


# --------------------------------------------------------------- segmenter

BILL_RE = re.compile(r"\b(?:CS)?(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\s*0*(\d+)\b")
_SPELLED_BILL_RE = re.compile(
    r"\b(HOUSE|SENATE)\s+(BILL|JOINT RESOLUTION|CONCURRENT RESOLUTION|RESOLUTION)\s+0*(\d+)\b",
    re.I,
)
_SPELLED_MAP = {
    ("HOUSE", "BILL"): "HB",
    ("HOUSE", "JOINT RESOLUTION"): "HJR",
    ("HOUSE", "CONCURRENT RESOLUTION"): "HCR",
    ("HOUSE", "RESOLUTION"): "HR",
    ("SENATE", "BILL"): "SB",
    ("SENATE", "JOINT RESOLUTION"): "SJR",
    ("SENATE", "CONCURRENT RESOLUTION"): "SCR",
    ("SENATE", "RESOLUTION"): "SR",
}


def find_bill(text: str) -> str | None:
    """First bill/resolution designator in ``text``, normalized to 'SB269'.

    The 'CS' committee-substitute prefix is dropped: CSSB 379 is still SB 379
    (the substitute is a bill *version*, not a separate bill).
    """
    m = BILL_RE.search(text)
    if m:
        return f"{m.group(1).upper()}{int(m.group(2))}"
    m2 = _SPELLED_BILL_RE.search(text)
    if m2:
        key = (m2.group(1).upper(), m2.group(2).upper())
        prefix = _SPELLED_MAP.get(key)
        if prefix:
            return f"{prefix}{int(m2.group(3))}"
    return None


# ALL-CAPS section headers are the journal's only structural signal.
_HEADER_KINDS = (
    ("point_of_order", ("POINT OF ORDER",)),
    ("message", ("MESSAGE FROM THE SENATE", "MESSAGE FROM THE HOUSE", "MESSAGE FROM")),
    ("statement_of_vote", ("STATEMENT OF VOTE", "STATEMENTS OF VOTE", "REASON FOR VOTE")),
    ("vote_correction", ("RECORD OF VOTE", "RECORD OF VOTES", "VOTE RECORDED")),
    ("leave_of_absence", ("LEAVE OF ABSENCE", "LEAVES OF ABSENCE")),
    ("conference_committee", ("CONFERENCE COMMITTEE", "CONFEREES")),
    ("committee", ("COMMITTEE MEETING", "COMMITTEE REPORT", "COMMITTEES GRANTED")),
    ("signed", ("BILLS AND RESOLUTIONS SIGNED", "SIGNED BY THE SPEAKER")),
    ("adjournment", ("ADJOURN",)),
    ("guests", ("INTRODUCTION OF GUESTS", "GUESTS PRESENTED", "PHYSICIAN OF THE DAY")),
    ("rules_suspended", ("RULES SUSPENDED", "REGULAR ORDER OF BUSINESS SUSPENDED")),
)

_READING_RE = re.compile(r"\bON (FIRST|SECOND|THIRD) READING\b")
_READING_MAP = {"FIRST": "first", "SECOND": "second", "THIRD": "third"}


def is_header_line(line: str) -> bool:
    """True for the journal's centred ALL-CAPS section headers.

    Keyed on the uppercase ratio rather than a literal ``isupper()`` so
    accented names ("GAMEZ"), the ``(C)`` chair marker and trailing
    parentheticals survive, while prose paragraphs that merely open with a
    capitalized speaker name do not.
    """
    s = line.strip()
    if not (4 <= len(s) <= 120):
        return False
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 3:
        return False
    upper = sum(1 for c in letters if c.isupper())
    if upper / len(letters) < 0.9:
        return False
    return bool(re.match(r"^[A-Z0-9]", s))


def classify_header(header: str) -> str:
    up = header.upper()
    for kind, needles in _HEADER_KINDS:
        if any(n in up for n in needles):
            return kind
    if find_bill(header):
        return "bill_action"
    return "other"


# Headers that end the floor's business on the previous bill: after these, an
# un-attributed vote ("The motion to table prevailed by (Record N)") must not
# inherit a stale bill.
_BILL_CLEARING = (
    "RECESS",
    "ADJOURN",
    "MORNING SESSION",
    "AFTERNOON SESSION",
    "EVENING SESSION",
    "CALENDAR",
    "POSTPONED BUSINESS",
    "MESSAGE FROM",
)

# Interruptions (a point of order, a leave of absence, bill signing) routinely
# split one bill's floor consideration across several segments; the chamber
# resumes with a *lower-case* resumption line rather than a new ALL-CAPS
# header, so it is promoted to a header here or the bill link is lost for
# every vote after the interruption.
_RESUME_RE = re.compile(
    r"^(?:CS)?(?:HB|SB|HJR|SJR|HCR|SCR|HR|SR) ?\d+\s*[-\u2013\u2014]\s*\(consideration continued\)",
    re.I,
)


def _clears_bill(header: str) -> bool:
    up = header.upper()
    return any(n in up for n in _BILL_CLEARING)


@dataclass
class JournalSegment:
    kind: str
    header: str
    text: str
    line_start: int
    bill: str | None = None
    reading: str | None = None
    lines: list[str] = field(default_factory=list)


def segment_day(text: str) -> list[JournalSegment]:
    """Split a day's text into typed segments on ALL-CAPS headers.

    Consecutive header lines belong to one header ("SB 31 - RULES SUSPENDED" /
    "ADDITIONAL SPONSORS AUTHORIZED"). A segment inherits the last header that
    named a bill, so a vote printed under a bare "STATEMENTS OF VOTE" header
    still resolves to the bill under debate.
    """
    lines = text.split("\n")
    segments: list[JournalSegment] = []
    cur = JournalSegment(kind="preamble", header="", text="", line_start=0)
    pending_header: list[str] = []
    header_start = 0
    carried_bill: str | None = None
    carried_reading: str | None = None

    def flush(seg: JournalSegment) -> None:
        seg.text = "\n".join(seg.lines).strip()
        if seg.text or seg.header:
            segments.append(seg)

    for i, line in enumerate(lines):
        if is_header_line(line) or _RESUME_RE.match(line.strip()):
            if not pending_header:
                header_start = i
            pending_header.append(line.strip())
            continue
        if pending_header:
            flush(cur)
            header = " / ".join(pending_header)
            bill = find_bill(header)
            if bill and bill != carried_bill:
                # a new bill takes the floor: its reading is unknown until stated
                carried_reading = None
            if bill:
                carried_bill = bill
            elif _clears_bill(header):
                carried_bill = None
                carried_reading = None
            rm = _READING_RE.search(header.upper())
            if rm:
                carried_reading = _READING_MAP[rm.group(1)]
            cur = JournalSegment(
                kind=classify_header(header),
                header=header,
                text="",
                line_start=header_start,
                bill=bill or carried_bill,
                reading=carried_reading,
            )
            pending_header = []
        cur.lines.append(line)
    if pending_header:
        flush(cur)
        header = " / ".join(pending_header)
        cur = JournalSegment(
            kind=classify_header(header),
            header=header,
            text="",
            line_start=header_start,
            bill=find_bill(header) or carried_bill,
            reading=carried_reading,
        )
    flush(cur)
    return segments


# ------------------------------------------------------------ vote parsing

_DASH = "[—–-]"

# House: "SB 269 was passed by (Record 3200): 104 Yeas, 37 Nays, 3 Present, not voting."
_HOUSE_RECORD_RE = re.compile(r"\(Record\s*(?P<rec>\d+)\)(?P<rest>\s*:[^\n]*)?")
_TALLY_RE = re.compile(
    r"(\d+)\s+(Yeas|Nays|Present,\s*not\s*voting|Present|Absent,\s*Excused|Absent)",
    re.I,
)
_HOUSE_LIST_RE = re.compile(
    r"^(?P<label>Yeas|Nays|Present,\s*not\s*voting|Present|Absent,\s*Excused[^" + "—–" + r"]*|Absent)"
    r"\s*" + _DASH + r"\s*(?P<names>.+)$"
)

# Senate: "The motion prevailed by the following vote: Yeas 27, Nays 4."
_SENATE_TALLY_RE = re.compile(
    r"by the following vote:\s*(?P<tallies>Yeas[^\n.]*)", re.I
)
_SENATE_COUNT_RE = re.compile(
    r"(Yeas|Nays|Present-not voting|Present, not voting|Absent-excused|Absent)\s+(\d+)", re.I
)
_SENATE_LIST_RE = re.compile(
    r"^(?P<label>Yeas|Nays|Present-not voting|Present, not voting|Absent-excused|Absent)"
    r"\s*:\s*(?P<names>.+)$",
    re.I,
)
_SAME_ROLL_RE = re.compile(r"\(Same as previous roll call\)", re.I)


def _position(label: str) -> str:
    up = re.sub(r"\s+", " ", label).strip().upper().rstrip(":")
    if up.startswith("YEA"):
        return "yea"
    if up.startswith("NAY"):
        return "nay"
    if up.startswith("PRESENT, NOT VOTING") or up.startswith("PRESENT-NOT VOTING"):
        return "pnv"
    if up.startswith("PRESENT"):
        return "present"
    if up.startswith("ABSENT, EXCUSED") or up.startswith("ABSENT-EXCUSED"):
        return "absent_excused"
    if up.startswith("ABSENT"):
        return "absent"
    return up.lower()


def _split_names(names: str, sep: str) -> list[str]:
    body = names.strip().rstrip(".")
    return [n.strip() for n in body.split(sep) if n.strip()]


def _parse_tallies(text: str, pattern: re.Pattern, count_first: bool) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in pattern.finditer(text):
        num, label = (m.group(1), m.group(2)) if count_first else (m.group(2), m.group(1))
        out[_position(label)] = int(num)
    return out


@dataclass
class ParsedVote:
    record_no: str | None
    question: str
    tallies: dict[str, int]
    casts: list[tuple[str, str]]          # (name_raw, position)
    bill: str | None
    line: int
    same_as_previous: bool = False

    def tally_check(self) -> dict[str, tuple[int, int]]:
        """{position: (reported, named)} for every position the journal both
        tallied *and* listed by name.

        The Senate prints only the minority list when a vote is near-unanimous
        ("Yeas 30, Nays 1." + "Nays: Hall."), so an unlisted position is a
        formatting fact, not a parse failure, and is excluded here.
        """
        named = self.named_counts
        return {
            pos: (count, named[pos])
            for pos, count in self.tallies.items()
            if pos in named
        }

    @property
    def named_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _, pos in self.casts:
            counts[pos] = counts.get(pos, 0) + 1
        return counts


def _collect_lists(
    lines: list[str], start: int, list_re: re.Pattern, sep: str
) -> tuple[list[tuple[str, str]], int]:
    """Consume the named-vote lists that follow a tally sentence.

    A list can wrap onto the next physical line (it ends at the period), and
    blank lines separate lists, so the scan continues across blanks and stops
    at the first non-blank line that is not a list label.
    """
    casts: list[tuple[str, str]] = []
    i = start
    seen: set[str] = set()
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        m = list_re.match(line)
        if not m:
            break
        buf = m.group("names").strip()
        i += 1
        while not buf.endswith(".") and i < len(lines) and lines[i].strip():
            nxt = lines[i].strip()
            if list_re.match(nxt):
                break
            buf += " " + nxt
            i += 1
        pos = _position(m.group("label"))
        for name in _split_names(buf, sep):
            if name in seen:
                continue
            seen.add(name)
            casts.append((name, pos))
    return casts, i


def parse_votes_house(text: str) -> list[ParsedVote]:
    lines = text.split("\n")
    votes: list[ParsedVote] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _HOUSE_RECORD_RE.search(line)
        if not m:
            i += 1
            continue
        rest = m.group("rest") or ""
        tallies = _parse_tallies(rest, _TALLY_RE, count_first=True)
        casts, nxt = _collect_lists(lines, i + 1, _HOUSE_LIST_RE, ";")
        votes.append(
            ParsedVote(
                record_no=m.group("rec"),
                question=line.strip()[:400],
                tallies=tallies,
                casts=casts,
                bill=find_bill(line),
                line=i,
            )
        )
        i = max(nxt, i + 1)
    return votes


def parse_votes_senate(text: str) -> list[ParsedVote]:
    lines = text.split("\n")
    votes: list[ParsedVote] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _SENATE_TALLY_RE.search(line)
        if not m:
            i += 1
            continue
        tallies = _parse_tallies(m.group("tallies"), _SENATE_COUNT_RE, count_first=False)
        casts, nxt = _collect_lists(lines, i + 1, _SENATE_LIST_RE, ",")
        same = bool(_SAME_ROLL_RE.search(line))
        if same and not casts:
            for prev in reversed(votes):
                if prev.casts:
                    casts = list(prev.casts)
                    break
        votes.append(
            ParsedVote(
                record_no=None,
                question=line.strip()[:400],
                tallies=tallies,
                casts=casts,
                bill=find_bill(line),
                line=i,
                same_as_previous=same,
            )
        )
        i = max(nxt, i + 1)
    return votes


def parse_votes(text: str, chamber: str) -> list[ParsedVote]:
    """Record votes for a day's text, with each vote's bill resolved from its
    own sentence when named, else from the enclosing segment's header."""
    key = chamber_key(chamber)
    votes = parse_votes_house(text) if key == "house" else parse_votes_senate(text)
    segments = segment_day(text)
    for v in votes:
        if v.bill:
            continue
        owner = None
        for seg in segments:
            if seg.line_start <= v.line:
                owner = seg
            else:
                break
        if owner:
            v.bill = owner.bill
    return votes


# ------------------------------------------------------- amendment parsing

_AMD_HEAD_RE = re.compile(
    r"^(?:Floor\s+)?Amendment No\.\s*(?P<num>\d+[A-Za-z]?)\s*(?P<tail>on (First|Second|Third) Reading)?$",
    re.I,
)
_AMD_OFFER_RE = re.compile(
    r"^(?:Senator|Representative)\s+(?P<who>.+?)\s+offered the following"
    r"(?:\s+(?:committee\s+)?amendment|\s+floor\s+amendment)?",
    re.I,
)
_AMD_ADOPTED_RE = re.compile(
    r"(?:Floor\s+)?Amendment No\.\s*(\d+[A-Za-z]?)\s+was adopted(?:\s+by\s+\(Record\s*(\d+)\))?",
    re.I,
)
_AMD_FAILED_RE = re.compile(
    r"(?:Floor\s+)?Amendment No\.\s*(\d+[A-Za-z]?)\s+failed of adoption"
    r"(?:\s+by\s+\(Record\s*(\d+)\))?",
    re.I,
)
_AMD_WITHDRAWN_RE = re.compile(
    r"(?:Floor\s+)?Amendment No\.\s*(\d+[A-Za-z]?)\s+was withdrawn", re.I
)
_AMD_OOO_RE = re.compile(
    r"(?:Floor\s+)?Amendment No\.\s*(\d+[A-Za-z]?)\s+was ruled out of order", re.I
)
_AMD_TABLE_MOVE_RE = re.compile(
    r"moved to table (?:Floor\s+)?Amendment No\.\s*(\d+[A-Za-z]?)", re.I
)
_TABLE_RESULT_RE = re.compile(
    r"The motion to table (prevailed|failed|was lost)", re.I
)
_DEEMED_YEA_RE = re.compile(
    r'All Members are deemed to have voted "Yea" on the adoption of '
    r"(?:Floor\s+)?Amendment No\.\s*(\d+[A-Za-z]?)",
    re.I,
)


def parse_amendments(text: str, chamber: str) -> list[dict]:
    """'Amendment No. N' offerings and their dispositions.

    Dispositions are stated three ways: directly ("was adopted", "failed of
    adoption", "was withdrawn"), via a tabling motion ("moved to table
    Amendment No. 1" + "The motion to table prevailed"), and in the Senate by
    the unanimous-consent boilerplate ('All Members are deemed to have voted
    "Yea"'). All three are handled; an amendment offered and never disposed of
    in the same day file keeps disposition NULL rather than guessing.
    """
    code = _chamber(chamber)["code"]
    segments = segment_day(text)
    amendments: dict[tuple[str, str, str], dict] = {}
    order: list[dict] = []

    for seg in segments:
        if not seg.bill:
            continue
        lines = seg.lines
        current: dict | None = None
        pending_table: str | None = None
        pending_author: str | None = None
        reading = seg.reading or "unknown"

        def slot(num: str, reading: str = reading, seg: JournalSegment = seg) -> dict:
            key = (seg.bill, reading, num)
            if key not in amendments:
                rec = {
                    "bill": seg.bill,
                    "chamber": code,
                    "reading": reading,
                    "number": num,
                    "author_raw": None,
                    "disposition": None,
                    "record_no": None,
                }
                amendments[key] = rec
                order.append(rec)
            return amendments[key]

        for line in lines:
            s = line.strip()
            if not s:
                continue
            hm = _AMD_HEAD_RE.match(s)
            if hm:
                rd = reading
                if hm.group("tail"):
                    rd = _READING_MAP[hm.group(3).upper()]
                current = slot(hm.group("num"), rd)
                # The House prints the offer line after the "Amendment No. N"
                # head, the Senate before it; accept either order.
                if current["author_raw"] is None and pending_author:
                    current["author_raw"] = pending_author
                pending_author = None
                pending_table = None
                continue
            om = _AMD_OFFER_RE.match(s)
            if om:
                who = om.group("who").strip().rstrip(":")
                if current is not None and current["author_raw"] is None:
                    current["author_raw"] = who
                else:
                    pending_author = who
            for regex, disposition in (
                (_AMD_ADOPTED_RE, "adopted"),
                (_AMD_FAILED_RE, "failed"),
            ):
                dm = regex.search(s)
                if dm:
                    rec = slot(dm.group(1))
                    rec["disposition"] = disposition
                    if dm.lastindex and dm.lastindex >= 2 and dm.group(2):
                        rec["record_no"] = dm.group(2)
            for regex, disposition in (
                (_AMD_WITHDRAWN_RE, "withdrawn"),
                (_AMD_OOO_RE, "point_of_order"),
                (_DEEMED_YEA_RE, "adopted"),
            ):
                dm = regex.search(s)
                if dm:
                    slot(dm.group(1))["disposition"] = disposition
            tm = _AMD_TABLE_MOVE_RE.search(s)
            if tm:
                pending_table = tm.group(1)
                slot(pending_table)
                continue
            if pending_table:
                rm = _TABLE_RESULT_RE.search(s)
                if rm:
                    rec = slot(pending_table)
                    if rm.group(1).lower() == "prevailed":
                        rec["disposition"] = "tabled"
                    recm = _HOUSE_RECORD_RE.search(s)
                    if recm:
                        rec["record_no"] = recm.group("rec")
                    pending_table = None
    return order


# ------------------------------------------------------------- whole-day

def parse_day(content: bytes, chamber: str) -> dict:
    text = html_to_text(content)
    segments = segment_day(text)
    return {
        "text": text,
        "segments": segments,
        "votes": parse_votes(text, chamber),
        "amendments": parse_amendments(text, chamber),
    }


def journal_cite(chamber: str, session: str, day: dict | None) -> str | None:
    """'89 H. Jour. 5579-5708 (2025)'.

    HTML carries no page markers (audit §2), so the citation is day-scoped:
    the printed page *range* from the index, not a per-vote page. Per-vote
    page anchors require the PDF and are left for a later pass.
    """
    if not day or not day.get("page_start"):
        return None
    m = re.match(r"^(\d{2,3})", session)
    if not m:
        return None
    year = (day.get("calendar_date") or "")[:4]
    cite = _chamber(chamber)["cite"]
    pages = f"{day['page_start']}-{day['page_end']}" if day.get("page_end") else str(day["page_start"])
    return f"{m.group(1)} {cite} {pages} ({year})" if year else f"{m.group(1)} {cite} {pages}"


def vote_id(session: str, chamber: str, record_no: str | None, file_id: str, seq: int) -> str:
    """'89R-H-R3200' when the chamber prints a record number; the Senate
    reports tallies without one, so the id is synthesized from the file stem
    plus the vote's ordinal within the day (stable across refetches because
    the ordinal comes from document order)."""
    code = _chamber(chamber)["code"]
    if record_no:
        return f"{session}-{code}-R{record_no}"
    return f"{session}-{code}-{file_id}-{seq:03d}"


def _ensure_bill(conn: sqlite3.Connection, session: str, designator: str) -> str | None:
    m = re.match(r"^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)(\d+)$", designator)
    if not m:
        return None
    bid = f"{session}-{designator}"
    dbx.upsert(
        conn,
        "bill",
        {
            "id": bid,
            "session_id": session,
            "bill_type": m.group(1),
            "number": int(m.group(2)),
        },
        ["id"],
        update_cols=[],
    )
    return bid


def store_day(
    conn: sqlite3.Connection,
    chamber: str,
    session: str,
    file_id: str,
    parsed: dict,
    doc_id: str,
    day: dict | None = None,
) -> dict:
    """Write votes / casts / amendments + explicit edges for one day file."""
    dbx.ensure_session(conn, session)
    code = _chamber(chamber)["code"]
    cite = journal_cite(chamber, session, day)
    date = (day or {}).get("calendar_date")

    n_votes = n_casts = 0
    for seq, v in enumerate(parsed["votes"], start=1):
        vid = vote_id(session, chamber, v.record_no, file_id, seq)
        bid = _ensure_bill(conn, session, v.bill) if v.bill else None
        # The tally sentence often omits absences; the named lists always carry
        # them, so an unreported count falls back to the list length.
        named = v.named_counts
        dbx.upsert(
            conn,
            "vote",
            {
                "id": vid,
                "session_id": session,
                "chamber": code,
                "bill_id": bid,
                "record_no": v.record_no,
                "date": date,
                "question": v.question,
                "yeas": v.tallies.get("yea", named.get("yea")),
                "nays": v.tallies.get("nay", named.get("nay")),
                "pnv": v.tallies.get("pnv", named.get("pnv")),
                "absent": v.tallies.get(
                    "absent", (named.get("absent", 0) + named.get("absent_excused", 0)) or None
                ),
                "journal_cite": cite,
                "doc_id": doc_id,
            },
            ["id"],
        )
        n_votes += 1
        if bid:
            dbx.add_edge(conn, "vote", vid, "concerns", "bill", bid, "explicit", doc_id)
        for name_raw, position in v.casts:
            dbx.upsert(
                conn,
                "vote_cast",
                {"vote_id": vid, "name_raw": name_raw, "position": position, "person_id": None},
                ["vote_id", "name_raw"],
                update_cols=["position"],
            )
            dbx.add_edge(
                conn, "person_name", name_raw, "cast_vote", "vote", vid, "explicit", doc_id
            )
            n_casts += 1

    n_amend = 0
    for a in parsed["amendments"]:
        bid = _ensure_bill(conn, session, a["bill"])
        if not bid:
            continue
        dbx.upsert(
            conn,
            "amendment",
            {
                "bill_id": bid,
                "chamber": a["chamber"],
                "reading": a["reading"],
                "number": a["number"],
                "author_raw": a["author_raw"],
                "disposition": a["disposition"],
                "action_date": date,
                "journal_cite": cite,
                "doc_id": doc_id,
            },
            ["bill_id", "chamber", "reading", "number"],
            update_cols=["author_raw", "disposition", "action_date", "journal_cite", "doc_id"],
        )
        n_amend += 1
        if a["author_raw"]:
            dbx.add_edge(
                conn,
                "person_name",
                a["author_raw"],
                "offered_amendment_to",
                "bill",
                bid,
                "explicit",
                doc_id,
            )
    return {"votes": n_votes, "casts": n_casts, "amendments": n_amend}


@register
class JournalsConnector(Connector):
    """House & Senate Journals — day index poller + day segmenter/vote parser."""

    name = "journals"
    tier = 0
    cadence = "daily_in_session"

    DDL = """
    CREATE TABLE IF NOT EXISTS journal_day (
        chamber       TEXT NOT NULL,          -- 'H' | 'S'
        session_id    TEXT NOT NULL,
        file_id       TEXT NOT NULL,          -- filename stem: '89RDAY81FINAL', 'day01'
        calendar_date TEXT,
        leg_day       TEXT,                   -- '81st', '6th Cont.', '61st Supplement'
        page_start    INTEGER,
        page_end      INTEGER,
        html_url      TEXT,
        pdf_url       TEXT,
        doc_id        TEXT,
        PRIMARY KEY (chamber, session_id, file_id)
    );
    CREATE INDEX IF NOT EXISTS idx_journal_day_date ON journal_day(calendar_date);
    """

    # ---------------------------------------------------------- day index

    def ingest_day_index(self, conn: sqlite3.Connection, chamber: str, session: str) -> dict:
        key = chamber_key(chamber)
        code = CHAMBERS[key]["code"]
        url = index_url(key, session)
        resp = fetcher().get(url)
        resp.raise_for_status()
        doc_id = f"journals:{code}:{session}:index"
        _, changed = store_document(
            conn,
            doc_id=doc_id,
            source_family="journals",
            content=resp.content,
            url=url,
            native_id=f"{code}:{session}:jrnlData",
            doc_type="journal_day_index",
            session_id=session,
            authority="A",
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )
        rows = parse_day_index(resp.content)
        dbx.ensure_session(conn, session)
        host = CHAMBERS[key]["host"]
        for row in rows:
            dbx.upsert(
                conn,
                "journal_day",
                {
                    "chamber": code,
                    "session_id": session,
                    "file_id": row["file_id"],
                    "calendar_date": row["calendar_date"],
                    "leg_day": row["leg_day"],
                    "page_start": row["page_start"],
                    "page_end": row["page_end"],
                    "html_url": _abs(host, row["html_url"]),
                    "pdf_url": _abs(host, row["pdf_url"]),
                },
                ["chamber", "session_id", "file_id"],
                update_cols=[
                    "calendar_date",
                    "leg_day",
                    "page_start",
                    "page_end",
                    "html_url",
                    "pdf_url",
                ],
            )
        conn.commit()
        return {"chamber": code, "session": session, "days": len(rows), "changed": changed}

    def day_row(self, conn: sqlite3.Connection, chamber: str, session: str, file_id: str) -> dict | None:
        code = _chamber(chamber)["code"]
        row = conn.execute(
            "SELECT * FROM journal_day WHERE chamber=? AND session_id=? AND file_id=?",
            (code, session, file_id),
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------ day doc

    def ingest_day(
        self, conn: sqlite3.Connection, chamber: str, session: str, file_id: str
    ) -> dict:
        key = chamber_key(chamber)
        code = CHAMBERS[key]["code"]
        day = self.day_row(conn, key, session, file_id)
        url = (day or {}).get("html_url") or day_url(key, session, file_id)
        resp = fetcher().get(url)
        resp.raise_for_status()
        doc_id = f"journals:{code}:{session}:{file_id}"
        _, changed = store_document(
            conn,
            doc_id=doc_id,
            source_family="journals",
            content=resp.content,
            url=url,
            native_id=file_id,
            doc_type="journal_day_html",
            session_id=session,
            published_at=(day or {}).get("calendar_date"),
            authority="A",
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )
        parsed = parse_day(resp.content, key)
        stats = store_day(conn, key, session, file_id, parsed, doc_id, day)
        conn.execute(
            "UPDATE journal_day SET doc_id=? WHERE chamber=? AND session_id=? AND file_id=?",
            (doc_id, code, session, file_id),
        )
        conn.commit()
        return {
            "file_id": file_id,
            "changed": changed,
            "segments": len(parsed["segments"]),
            **stats,
        }

    def incremental(self, conn: sqlite3.Connection, session: str = "89R", limit: int = 3, **kw) -> dict:
        """Poll both day indexes; ingest the newest ``limit`` unfetched days."""
        out: dict = {"indexes": {}, "days": []}
        for key in ("house", "senate"):
            out["indexes"][key] = self.ingest_day_index(conn, key, session)
            code = CHAMBERS[key]["code"]
            pending = conn.execute(
                """SELECT file_id FROM journal_day
                   WHERE chamber=? AND session_id=? AND doc_id IS NULL
                   ORDER BY calendar_date DESC, file_id DESC LIMIT ?""",
                (code, session, limit),
            ).fetchall()
            for row in pending:
                out["days"].append(self.ingest_day(conn, key, session, row["file_id"]))
        return out

    # --------------------------------------------------------------- smoke

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """89R House day index + one real floor-vote day (<=6 live requests)."""
        idx = self.ingest_day_index(conn, "house", "89R")
        code = "H"
        rows = conn.execute(
            """SELECT file_id, calendar_date FROM journal_day
               WHERE chamber=? AND session_id='89R' AND calendar_date >= '2025-05-20'
               ORDER BY calendar_date, file_id""",
            (code,),
        ).fetchall()
        candidates = [r["file_id"] for r in rows if "SUPPLEMENT" not in r["file_id"].upper()]
        if not candidates:
            return SmokeResult(ok=False, detail="no late-May 89R House days in index", stats=idx)

        best: dict | None = None
        for file_id in candidates[:5]:
            day = self.ingest_day(conn, "house", "89R", file_id)
            if best is None or day["casts"] > best["casts"]:
                best = day
            if day["votes"] >= 1 and day["casts"] >= 50:
                break
        assert best is not None

        top = conn.execute(
            """SELECT v.id, v.record_no, v.yeas,
                      (SELECT COUNT(*) FROM vote_cast c
                        WHERE c.vote_id=v.id AND c.position='yea') AS yea_names
                 FROM vote v WHERE v.doc_id LIKE 'journals:H:89R:%'
                 ORDER BY yea_names DESC LIMIT 1"""
        ).fetchone()
        stats = {
            "days_indexed": idx["days"],
            "day": best["file_id"],
            "votes": best["votes"],
            "casts": best["casts"],
            "amendments": best["amendments"],
            "top_vote": top["id"] if top else None,
            "top_yeas_reported": top["yeas"] if top else None,
            "top_yeas_named": top["yea_names"] if top else None,
        }
        ok = (
            idx["days"] > 0
            and best["votes"] >= 1
            and best["casts"] >= 50
            and top is not None
            and top["yeas"] == top["yea_names"]
        )
        detail = (
            f"89R House: {idx['days']} days indexed; {best['file_id']} -> "
            f"{best['votes']} record votes, {best['casts']} casts; tally check "
            f"{stats['top_vote']} {stats['top_yeas_reported']} reported == "
            f"{stats['top_yeas_named']} named"
        )
        return SmokeResult(ok=ok, detail=detail, stats=stats)


def _abs(host: str, href: str | None) -> str | None:
    if not href:
        return None
    if href.startswith("http"):
        return href
    return host.rstrip("/") + "/" + href.lstrip("/")
