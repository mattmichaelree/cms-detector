"""Committees & testimony — hearings, witness lists, minutes votes, captions.

Spec: docs/texas-politics-audit/03-deep-dives/04-committees-testimony.md.

Four capabilities, in the order the audit ranks them:

1. **House JSON API client** (undocumented, unauthenticated, verified live):
   ``/api/getCommitteeMeetings/{legislature}/{chamber}/{committeeId}`` returns
   notice/minutes/witness-list/handouts/comments URLs for every meeting of one
   committee in one JSON row, and
   ``/api/GetVideoEvents/{legislature}/{called}/published/{type}`` returns the
   archived video listing with an HLS ``videoUrl`` and a ``captions`` boolean.
   Preferring this API over crawling ``capitol.texas.gov`` is a *compliance*
   decision, not just an ergonomic one — see below.

2. **Witness-list parsers for both eras.** 1999-era documents are plain text in
   an HTML ``<PRE>`` block under ``FOR:``/``AGAINST:``/``ON:`` headers grouped
   under bill anchors; 2025-era documents are born-digital per-meeting,
   multi-bill PDFs with the same group vocabulary plus a
   "Registering, but not testifying:" section that is itself sub-split by
   For/Against/On. Both eras write the affiliation field as ``(Self)``,
   ``(Org)`` or — the entity-resolution wrinkle the audit calls out —
   ``(Self; Org)``, which sets *both* ``is_self`` and ``org_raw``.

3. **Minutes parser** for committee record votes ("Ayes: Representatives
   Anchia; Parker; ... (6). Nays: Representatives Capriglione; Rogers;
   Slawson (3)."). Only bills actually *reported* generate a vote; bills left
   pending never do. One meeting can vote twice on one bill (verified: a failed
   vote reconsidered and passed in the same meeting), so minted vote ids carry
   an occurrence suffix.

4. **Caption harvester** — the audit's headline discovery. A House HLS master
   playlist for a captioned hearing carries an ``EXT-X-MEDIA:TYPE=SUBTITLES``
   line; walking master → subtitle playlist → ``.vtt`` segments yields real
   timestamped ASR text. It is machine-generated and unofficial: caption text
   is stored as authority ``D`` and must always be attributed as ASR-derived,
   never as "the record says".

**Compliance.** ``capitol.texas.gov``'s robots.txt disallows ``/TLODOCS/`` — the
tree that hosts minutes, witness lists and notices — and the TLC's file-download
policy blocks data-mining vendors. This connector therefore:
  * gets every *listing* from house.texas.gov's JSON API and never enumerates
    the tlodocs tree;
  * fetches tlodocs documents only one at a time, for meetings the API already
    told us exist, under an explicit ``max_docs`` bound that every batch entry
    point requires;
  * relies on the shared fetcher's automatic 3s throttle for that host.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from urllib.parse import urljoin

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

HOUSE_API = "https://house.texas.gov/api"

# The tlodocs filename token 'C###YYYYMMDDHHMM<seq>' is the natural hearing key.
HEARING_TOKEN_RE = re.compile(r"\b(C\d{3}\d{8}\d{4}\d{1,2})\b")
COMMITTEE_CODE_RE = re.compile(r"^(C\d{3})")
SESSION_IN_URL_RE = re.compile(r"/tlodocs/(\d{2,3}[R1-4])/", re.I)

BILL_RE = re.compile(r"\b(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\s*0*(\d+)\b", re.I)
BILL_HEADER_RE = re.compile(r"^(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\s*0*(\d+)$", re.I)

POSITIONS = {"for": "for", "against": "against", "on": "on"}

# Verified meeting used by smoke(): House State Affairs, 8/22/2025 (HB 7, SB 8).
VERIFIED_WITNESS_TOKEN = "C4502025082208001"


# ---------------------------------------------------------------- utilities


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def _decode(content: bytes) -> str:
    for enc in ("utf-8", "windows-1252", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|tr|h\d)>", "\n", html)
    return unescape(_TAG_RE.sub("", html))


def iso_date(raw: str | None) -> str | None:
    """'3/5/2025' or '8/26/26' → '2025-03-05' / '2026-08-26'."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([AaPp])\.?\s*[Mm]\.?")


def iso_time(raw: str | None) -> str | None:
    """'8:00 A.M.' → '08:00'; '10:30AM' → '10:30'."""
    if not raw:
        return None
    m = _TIME_RE.search(raw)
    if not m:
        return None
    hour = int(m.group(1)) % 12
    if m.group(3).upper() == "P":
        hour += 12
    return f"{hour:02d}:{m.group(2)}"


def bill_id(session: str, designator: str) -> str:
    """('89R', 'HB 7') → '89R-HB7'."""
    return f"{session}-{designator.replace(' ', '').upper()}"


def committee_id(session: str, chamber: str, code: str) -> str:
    return f"{session}-{chamber}-{code}"


def hearing_token(url: str | None) -> str | None:
    """Pull the 'C###YYYYMMDDHHMM<seq>' token out of any linked doc URL."""
    if not url:
        return None
    m = HEARING_TOKEN_RE.search(url)
    return m.group(1) if m else None


def pdf_witness_url(html_url: str) -> str:
    """The born-digital PDF twin of a witlistmtg HTML URL.

    Both formats publish in parallel for the modern era; the PDF extracts far
    more cleanly than the Word-generated HTML (162KB vs 301KB for the same
    meeting), so the live path prefers it and falls back on 404.
    """
    return html_url.replace("/witlistmtg/html/", "/witlistmtg/pdf/").replace(".htm", ".PDF")


# ------------------------------------------------------- House JSON API


def parse_committee_meetings(content: bytes, legislature: int | str | None = None) -> list[dict]:
    """getCommitteeMeetings JSON → normalized meeting rows.

    Session codes are taken from the linked tlodocs URLs when present — never
    computed from the meeting date. Session codes span the whole biennium
    including the interim (verified: 89R-labelled hearings in Aug 2026), so
    date→session inference is always wrong (audit temporal trap).
    """
    rows = json.loads(_decode(content))
    if isinstance(rows, dict):
        rows = rows.get("meetings") or rows.get("data") or []
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        links = {k: (r.get(k) or None) for k in ("notice", "minutes", "witnesses", "handouts", "comments")}
        session = None
        for url in links.values():
            if url:
                m = SESSION_IN_URL_RE.search(url)
                if m:
                    session = m.group(1).upper()
                    break
        if session is None and legislature is not None:
            session = f"{legislature}R"
        token = None
        for url in links.values():
            token = token or hearing_token(url)
        code = (r.get("id") or "").strip().upper()
        date = iso_date(r.get("date"))
        start = iso_time(r.get("start"))
        if not token and code and date and start:
            # Minted, and visibly so: the tlodocs token is the only real key.
            token = f"MINTED-{code}-{date.replace('-', '')}-{start.replace(':', '')}"
        out.append(
            {
                "committee_code": code,
                "committee_name": _norm_ws(r.get("name") or ""),
                "chamber": (r.get("chamber") or "").strip().upper() or None,
                "session": session,
                "date": date,
                "start": start,
                "scheduled_at": f"{date}T{start}" if date and start else date,
                "location": r.get("location") or None,
                "canceled": str(r.get("canceled") or "").strip().lower() == "yes",
                "hearing_id": token,
                "committee_link": r.get("committee_link") or None,
                **links,
            }
        )
    return out


def parse_video_events(content: bytes, session: str | None = None) -> list[dict]:
    """GetVideoEvents JSON → video_event rows (id, date, videoUrl, captions)."""
    rows = json.loads(_decode(content))
    if isinstance(rows, dict):
        rows = rows.get("events") or rows.get("data") or []
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict) or r.get("id") is None:
            continue
        out.append(
            {
                "id": int(r["id"]),
                "session": session,
                "kind": r.get("type") or None,
                "title": _norm_ws(r.get("name") or "") or None,
                "event_date": iso_date(r.get("date")),
                "video_url": r.get("videoUrl") or None,
                "has_captions": 1 if r.get("captions") else 0,
                "status": r.get("status") or None,
                "duration": r.get("duration") or None,
                "room": r.get("room") or None,
                "event_url": r.get("EventUrl") or r.get("eventUrl") or None,
            }
        )
    return out


# ------------------------------------------------------------ witness lists


@dataclass
class WitnessList:
    """Parsed witness list: meeting header plus one row per registration."""

    committee: str | None = None
    date_raw: str | None = None
    era: str = "modern"
    rows: list[dict] = field(default_factory=list)

    def bills(self) -> list[str]:
        seen: list[str] = []
        for r in self.rows:
            if r["bill"] not in seen:
                seen.append(r["bill"])
        return seen


_AFFIL_SELF_RE = re.compile(r"^self$", re.I)
_AFFIL_SELF_AND_RE = re.compile(r"^self\s*(?:&|and)\s+(.*)$", re.I)


def parse_affiliation(paren: str) -> tuple[int, str | None]:
    """'(Self; Texas Right to Life)' body → (is_self, org_raw).

    'Self' and an organization co-occur constantly; the audit flags treating
    them as mutually exclusive as a real entity-resolution error. Both are kept.
    """
    parts = [p.strip() for p in paren.split(";") if p.strip()]
    is_self = 0
    orgs: list[str] = []
    for part in parts:
        if _AFFIL_SELF_RE.match(part):
            is_self = 1
            continue
        m = _AFFIL_SELF_AND_RE.match(part)
        if m:
            is_self = 1
            if m.group(1).strip():
                orgs.append(m.group(1).strip())
            continue
        orgs.append(part)
    return is_self, "; ".join(orgs) or None


# Greedy name/paren split anchored at end-of-line, so nested parens inside the
# affiliation ("...(LGPOA))") stay with the affiliation.
_MODERN_ROW_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<paren>.*)\)$")
_ERA_ROW_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<paren>.*)\)\s*,\s*(?P<city>[^()]*)$")
_GROUP_RE = re.compile(r"^(For|Against|On)\s*:\s*(.*)$", re.I)
_REGISTERING_RE = re.compile(r"^registering,?\s*but\s*not\s*testifying\s*:?\s*$", re.I)
_WRITTEN_RE = re.compile(r"^written\s+materials\s+submitted\s*:?\s*$", re.I)
_MEETING_DATE_RE = re.compile(r"([A-Z][a-z]+ \d{1,2},\s*\d{4}.*)$")


def _parse_modern_lines(text: str) -> WitnessList:
    """Shared line machine for the born-digital (2025-era) layout.

    Page furniture ("WITNESS LIST", bare page numbers) is dropped; group
    headers repeat on continuation pages, and the
    "Registering, but not testifying" state is sticky until the next bill —
    a repeated 'Against:' header inside that section must not flip rows back
    to testified.
    """
    wl = WitnessList(era="modern")
    bill: str | None = None
    position: str | None = None
    channel = "testified"
    for raw in text.split("\n"):
        line = _norm_ws(raw)
        if not line or line.upper() == "WITNESS LIST" or line.isdigit():
            continue
        if bill is None:
            if line.lower().endswith("committee") and not wl.committee:
                wl.committee = line
                continue
            m = _MEETING_DATE_RE.match(line)
            if m and not wl.date_raw:
                wl.date_raw = m.group(1).strip()
                continue
        m = BILL_HEADER_RE.match(line)
        if m:
            bill = f"{m.group(1).upper()}{int(m.group(2))}"
            position = None
            channel = "testified"
            continue
        if _REGISTERING_RE.match(line):
            channel = "registered"
            position = None
            continue
        if _WRITTEN_RE.match(line):
            channel = "written"
            position = None
            continue
        m = _GROUP_RE.match(line)
        if m:
            position = POSITIONS[m.group(1).lower()]
            rest = m.group(2).strip()
            if not rest:
                continue
            line = rest
        if bill is None or position is None:
            continue
        rm = _MODERN_ROW_RE.match(line)
        if not rm:
            continue
        is_self, org = parse_affiliation(rm.group("paren"))
        wl.rows.append(
            {
                "bill": bill,
                "name_raw": _norm_ws(rm.group("name")),
                "org_raw": org,
                "is_self": is_self,
                "position": position,
                "channel": channel,
                "testified": 1 if channel == "testified" else 0,
                "city": None,
            }
        )
    return wl


def parse_witness_pdf(content: bytes) -> WitnessList:
    """Modern per-meeting, multi-bill witness-list PDF → WitnessList."""
    import io

    import pdfplumber  # local import: pdfplumber is slow to import

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    return _parse_modern_lines(text)


def parse_witness_html_1999(content: bytes) -> WitnessList:
    """1999-era witness list: fixed-width text inside <PRE>, bills as anchors.

    Rows wrap at a deep indent ('(Texas Department of Mental Health &\\n
    Mental Retardation), Austin'), so physical lines are re-joined before
    parsing. Uppercase FOR:/AGAINST:/ON: mark testifying witnesses; the
    mixed-case headers belong to the registering-only and written-materials
    sections that follow.
    """
    html = _decode(content)
    m = re.search(r"(?is)<pre>(.*?)</pre>", html)
    body = m.group(1) if m else html
    wl = WitnessList(era="1999")

    bill: str | None = None
    position: str | None = None
    channel = "testified"
    buffer: str | None = None

    def flush() -> None:
        nonlocal buffer, position, channel
        if buffer is None:
            return
        line, buffer = _norm_ws(buffer), None
        if not line:
            return
        if _REGISTERING_RE.match(line):
            channel, position = "registered", None
            return
        if _WRITTEN_RE.match(line):
            channel, position = "written", None
            return
        g = _GROUP_RE.match(line)
        if g:
            label = g.group(1)
            if label.isupper():          # FOR:/AGAINST:/ON: — the testifying block
                channel = "testified"
            position = POSITIONS[label.lower()]
            line = g.group(2).strip()
            if not line:
                return
        if bill is None or position is None:
            if line.lower().endswith("committee") and not wl.committee:
                wl.committee = line
            elif re.match(r"^[A-Z][a-z]+ \d{1,2},", line) and not wl.date_raw:
                wl.date_raw = line
            return
        rm = _ERA_ROW_RE.match(line) or _MODERN_ROW_RE.match(line)
        if not rm:
            return
        is_self, org = parse_affiliation(rm.group("paren"))
        city = rm.groupdict().get("city")
        wl.rows.append(
            {
                "bill": bill,
                "name_raw": _norm_ws(rm.group("name")),
                "org_raw": org,
                "is_self": is_self,
                "position": position,
                "channel": channel,
                "testified": 1 if channel == "testified" else 0,
                "city": _norm_ws(city) if city else None,
            }
        )

    for raw in body.split("\n"):
        raw = raw.replace("\r", "")
        if "<" in raw and re.search(r"(?i)<a\b", raw):
            flush()
            text = _norm_ws(_strip_tags(raw))
            bm = BILL_HEADER_RE.match(text) or BILL_RE.search(text)
            if bm:
                bill = f"{bm.group(1).upper()}{int(bm.group(2))}"
                position, channel = None, "testified"
            continue
        if "<" in raw:
            raw = _strip_tags(raw)
        if not raw.strip():
            flush()
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent >= 20 and buffer is not None:
            buffer += " " + raw.strip()
        else:
            flush()
            buffer = raw.strip()
    flush()
    return wl


def parse_witness_list(content: bytes) -> WitnessList:
    """Era-dispatching entry point: PDF → modern, <PRE> HTML → 1999-era."""
    if content[:5] == b"%PDF-":
        return parse_witness_pdf(content)
    html = _decode(content)
    if re.search(r"(?i)<pre\b", html):
        return parse_witness_html_1999(content)
    return _parse_modern_lines(_strip_tags(html))


# ----------------------------------------------------------------- minutes

_NAME_PREFIX_RE = re.compile(r"^(Representatives?|Senators?|Members?)\b[:.]?\s*", re.I)

# Verified 87R layout: 'Ayes: Representatives Anchia; Parker; ... (6).'
_TALLY_A = (
    r"{label}\s*:\s*(?P<{key}>.*?)\s*\(\s*(?P<{key}_n>\d+)\s*\)"
)
_VOTE_RE_A = re.compile(
    _TALLY_A.format(label="Ayes", key="ayes")
    + r"\s*\.?\s*"
    + _TALLY_A.format(label="Nays", key="nays")
    + r"\s*\.?\s*"
    + r"(?:Present,?\s*Not\s*Voting\s*:\s*(?P<pnv>.*?)\s*\(\s*(?P<pnv_n>\d+)\s*\)\s*\.?\s*)?"
    + r"(?:Absent[^:]*:\s*(?P<absent>.*?)\s*\(\s*(?P<absent_n>\d+)\s*\)\s*\.?)?",
    re.I,
)
# Narrative layout quoted in the audit: 'Ayes 6 (Anchia, Parker, ...); Nays 3 (...)'.
_VOTE_RE_B = re.compile(
    r"Ayes\s+(?P<ayes_n>\d+)\s*\((?P<ayes>[^)]*)\)\s*[;,]?\s*"
    r"Nays\s+(?P<nays_n>\d+)\s*\((?P<nays>[^)]*)\)"
    r"(?:\s*[;,]?\s*Present,?\s*Not\s*Voting\s+(?P<pnv_n>\d+)\s*\((?P<pnv>[^)]*)\))?"
    r"(?:\s*[;,]?\s*Absent\s+(?P<absent_n>\d+)\s*\((?P<absent>[^)]*)\))?",
    re.I,
)
_MOTION_RE = re.compile(
    r"((?:The chair|Representative|Senator)(?:\s+\S+){0,4}?\s+moved that\s[^:]{0,500}?record vote)",
    re.I,
)


def _split_names(raw: str | None, sep: str) -> list[str]:
    if not raw:
        return []
    raw = _NAME_PREFIX_RE.sub("", _norm_ws(raw)).strip(" .;,")
    if not raw or raw.lower() in ("none", "n/a"):
        return []
    return [n.strip(" ;,") for n in raw.split(sep) if n.strip(" ;,")]


def parse_minutes(content: bytes) -> list[dict]:
    """Committee minutes (HTML or text) → per-bill record votes.

    Only reported bills produce a vote; 'left pending' bills never do. Votes
    are attached to the nearest preceding bill designator, and a repeated
    bill gets an incrementing occurrence number so a failed-then-reconsidered
    pair in one meeting stays two distinct votes.
    """
    text = _decode(content)
    if "<" in text and re.search(r"(?i)<(html|body|p|div|pre)\b", text):
        text = _strip_tags(text)
    flat = _norm_ws(text)

    bills = [(m.start(), f"{m.group(1).upper()}{int(m.group(2))}") for m in BILL_RE.finditer(flat)]

    votes: list[dict] = []
    seen: dict[str, int] = {}
    for rx, sep in ((_VOTE_RE_A, ";"), (_VOTE_RE_B, ",")):
        for m in rx.finditer(flat):
            g = m.groupdict()
            bill = None
            for pos, b in bills:
                if pos < m.start():
                    bill = b
                else:
                    break
            motion = _MOTION_RE.findall(flat[max(0, m.start() - 700) : m.start()])
            occurrence = seen[bill] = seen.get(bill, 0) + 1
            votes.append(
                {
                    "seq": len(votes) + 1,
                    "bill": bill,
                    "occurrence": occurrence,
                    "question": _norm_ws(motion[-1]) if motion else None,
                    "ayes": _split_names(g.get("ayes"), sep),
                    "nays": _split_names(g.get("nays"), sep),
                    "pnv": _split_names(g.get("pnv"), sep),
                    "absent": _split_names(g.get("absent"), sep),
                    "n_ayes": int(g["ayes_n"]),
                    "n_nays": int(g["nays_n"]),
                    "n_pnv": int(g["pnv_n"]) if g.get("pnv_n") else 0,
                    "n_absent": int(g["absent_n"]) if g.get("absent_n") else 0,
                }
            )
        if votes:
            break
    return votes


# ------------------------------------------------------------ HLS / WebVTT


def parse_hls_master(content: bytes | str) -> list[dict]:
    """Master .m3u8 → the EXT-X-MEDIA subtitle tracks (TYPE=SUBTITLES)."""
    text = content if isinstance(content, str) else _decode(content)
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.upper().startswith("#EXT-X-MEDIA:"):
            continue
        attrs = dict(
            (k.upper(), v.strip('"'))
            for k, v in re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', line.split(":", 1)[1])
        )
        if attrs.get("TYPE") != "SUBTITLES" or not attrs.get("URI"):
            continue
        out.append(
            {
                "uri": attrs["URI"],
                "name": attrs.get("NAME"),
                "language": attrs.get("LANGUAGE"),
                "group_id": attrs.get("GROUP-ID"),
                "default": attrs.get("DEFAULT") == "YES",
            }
        )
    return out


def parse_hls_playlist(content: bytes | str) -> list[str]:
    """Media .m3u8 → ordered segment URIs (comment lines dropped)."""
    text = content if isinstance(content, str) else _decode(content)
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


_CUE_RE = re.compile(
    r"^(?P<start>(?:\d{1,3}:)?\d{2}:\d{2}\.\d{3})\s*-->\s*(?P<end>(?:\d{1,3}:)?\d{2}:\d{2}\.\d{3})"
    r"(?P<settings>.*)$"
)


def parse_vtt(content: bytes | str) -> list[dict]:
    """WebVTT bytes → [{start_ts, end_ts, text}].

    Pure and tolerant: HLS subtitle segments carry an ``X-TIMESTAMP-MAP``
    header, cue settings ('line:-3') trail the timing line, speaker turns are
    marked '>>', and a segment can legitimately contain zero cues (verified —
    the first segment of a captioned hearing was empty).
    """
    text = content if isinstance(content, str) else _decode(content)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cues: list[dict] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = _CUE_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        i += 1
        body: list[str] = []
        while i < len(lines) and lines[i].strip():
            body.append(lines[i].strip())
            i += 1
        payload = _norm_ws(" ".join(body))
        payload = re.sub(r"<[^>]+>", "", payload)
        if payload:
            cues.append({"start_ts": m.group("start"), "end_ts": m.group("end"), "text": payload})
    return cues


# ------------------------------------------------------------------ storage


def store_meeting(conn: sqlite3.Connection, meeting: dict, docs: dict | None = None) -> str | None:
    """Upsert committee + hearing rows for one API meeting row."""
    session = meeting.get("session")
    hid = meeting.get("hearing_id")
    if not session or not hid:
        return None
    dbx.ensure_session(conn, session)
    code = meeting["committee_code"] or (COMMITTEE_CODE_RE.match(hid) or [None, None])[1]
    chamber = meeting.get("chamber") or "H"
    cid = committee_id(session, chamber, code) if code else None
    if cid:
        dbx.upsert(
            conn,
            "committee",
            {
                "id": cid,
                "session_id": session,
                "chamber": chamber,
                "native_code": code,
                "name": meeting["committee_name"] or code,
            },
            ["id"],
        )
    row = {
        "id": hid,
        "committee_id": cid,
        "scheduled_at": meeting.get("scheduled_at"),
        "location": meeting.get("location"),
        "kind": "canceled" if meeting.get("canceled") else "meeting",
    }
    for key in ("notice_doc", "minutes_doc", "witness_doc", "comments_doc"):
        if docs and docs.get(key):
            row[key] = docs[key]
    dbx.upsert(conn, "hearing", row, ["id"])
    if cid:
        dbx.add_edge(conn, "committee", cid, "held", "hearing", hid, "explicit")
    return hid


def _ensure_bill(conn: sqlite3.Connection, session: str, designator: str) -> str:
    bid = bill_id(session, designator)
    m = BILL_RE.search(designator)
    if m:
        dbx.upsert(
            conn,
            "bill",
            {
                "id": bid,
                "session_id": session,
                "bill_type": m.group(1).upper(),
                "number": int(m.group(2)),
            },
            ["id"],
            update_cols=[],
        )
    return bid


def store_witness_list(
    conn: sqlite3.Connection,
    hearing_id: str,
    session: str,
    wl: WitnessList,
    doc_id: str | None = None,
) -> dict:
    """Persist witness slips + hearing_bill + position edges (idempotent)."""
    conn.execute(
        "DELETE FROM witness_slip_city WHERE witness_slip_id IN "
        "(SELECT id FROM witness_slip WHERE hearing_id=?)",
        (hearing_id,),
    )
    conn.execute("DELETE FROM witness_slip WHERE hearing_id=?", (hearing_id,))
    dbx.ensure_session(conn, session)
    org_positions: set[tuple[str, str, str]] = set()
    for designator in wl.bills():
        bid = _ensure_bill(conn, session, designator)
        dbx.upsert(
            conn,
            "hearing_bill",
            {"hearing_id": hearing_id, "bill_id": bid},
            ["hearing_id", "bill_id"],
            update_cols=[],
        )
        dbx.add_edge(conn, "hearing", hearing_id, "considered", "bill", bid, "explicit", doc_id)
    for r in wl.rows:
        bid = bill_id(session, r["bill"])
        cur = conn.execute(
            """INSERT INTO witness_slip
               (hearing_id, bill_id, name_raw, org_raw, is_self, position, testified)
               VALUES (?,?,?,?,?,?,?)""",
            (hearing_id, bid, r["name_raw"], r["org_raw"], r["is_self"], r["position"], r["testified"]),
        )
        if r.get("city"):
            conn.execute(
                "INSERT OR REPLACE INTO witness_slip_city (witness_slip_id, city) VALUES (?,?)",
                (cur.lastrowid, r["city"]),
            )
        predicate = ("testified_" if r["testified"] else "registered_only_") + r["position"]
        dbx.add_edge(
            conn, "person_name", r["name_raw"], predicate, "bill", bid, "explicit", doc_id, span=hearing_id
        )
        if r["org_raw"]:
            org_positions.add((r["org_raw"], r["position"], bid))
    # DERIVED: the source records positions per person, never per org — the
    # org-level stance is a rollup of the person rows sharing an org string.
    for org, position, bid in sorted(org_positions):
        dbx.add_edge(
            conn,
            "org_name",
            org,
            f"registered_position_on_{position}",
            "bill",
            bid,
            "derived",
            doc_id,
            confidence=0.8,
            span=hearing_id,
        )
    return {
        "slips": len(wl.rows),
        "bills": len(wl.bills()),
        "testified": sum(1 for r in wl.rows if r["testified"]),
        "registered_only": sum(1 for r in wl.rows if not r["testified"]),
        "orgs": len({o for o, _, _ in org_positions}),
    }


def store_minutes_votes(
    conn: sqlite3.Connection,
    hearing_id: str,
    session: str,
    chamber: str,
    date: str | None,
    votes: list[dict],
    doc_id: str | None = None,
) -> dict:
    """Persist committee record votes as vote + vote_cast rows."""
    dbx.ensure_session(conn, session)
    stored = 0
    casts = 0
    for v in votes:
        if not v["bill"]:
            continue
        bid = _ensure_bill(conn, session, v["bill"])
        vid = f"CMTE-{hearing_id}-{v['bill']}"
        if v["occurrence"] > 1:
            vid = f"{vid}-{v['occurrence']}"
        dbx.upsert(
            conn,
            "vote",
            {
                "id": vid,
                "session_id": session,
                "chamber": chamber,
                "bill_id": bid,
                "record_no": None,
                "date": date,
                "question": v["question"],
                "yeas": v["n_ayes"],
                "nays": v["n_nays"],
                "pnv": v["n_pnv"],
                "absent": v["n_absent"],
                "doc_id": doc_id,
            },
            ["id"],
        )
        conn.execute("DELETE FROM vote_cast WHERE vote_id=?", (vid,))
        for key, position in (("ayes", "yea"), ("nays", "nay"), ("pnv", "pnv"), ("absent", "absent")):
            for name in v[key]:
                dbx.upsert(
                    conn,
                    "vote_cast",
                    {"vote_id": vid, "name_raw": name, "position": position, "person_id": None},
                    ["vote_id", "name_raw"],
                )
                casts += 1
                if position in ("yea", "nay"):
                    dbx.add_edge(
                        conn, "person_name", name, f"voted_{position}_in_committee",
                        "bill", bid, "explicit", doc_id, span=vid,
                    )
        stored += 1
    return {"votes": stored, "casts": casts}


def store_video_events(conn: sqlite3.Connection, events: list[dict]) -> dict:
    for e in events:
        dbx.upsert(
            conn,
            "video_event",
            {
                "id": e["id"],
                "session": e.get("session"),
                "kind": e.get("kind"),
                "title": e.get("title"),
                "event_date": e.get("event_date"),
                "video_url": e.get("video_url"),
                "has_captions": e.get("has_captions", 0),
            },
            ["id"],
        )
    return {"events": len(events), "captioned": sum(1 for e in events if e.get("has_captions"))}


def store_caption_segments(conn: sqlite3.Connection, video_id: int, cues: list[dict]) -> int:
    for c in cues:
        dbx.upsert(
            conn,
            "caption_segment",
            {
                "video_id": video_id,
                "start_ts": c["start_ts"],
                "end_ts": c["end_ts"],
                "text": c["text"],
            },
            ["video_id", "start_ts", "text"],
            update_cols=["end_ts"],
        )
    return len(cues)


# ---------------------------------------------------------------- connector


@register
class CommitteesConnector(Connector):
    """Hearings, witness lists, committee votes and harvested captions."""

    name = "committees"
    tier = 0
    cadence = "hourly_in_session"

    DDL = """
    CREATE TABLE IF NOT EXISTS video_event (
        id           INTEGER PRIMARY KEY,   -- house.texas.gov numeric event id
        session      TEXT,
        kind         TEXT,                  -- committee|floor|...
        title        TEXT,
        event_date   TEXT,
        video_url    TEXT,                  -- HLS master .m3u8
        has_captions INTEGER NOT NULL DEFAULT 0
    );

    -- ASR-derived, unofficial (authority D). Never cite as "the record says".
    CREATE TABLE IF NOT EXISTS caption_segment (
        id       INTEGER PRIMARY KEY,
        video_id INTEGER REFERENCES video_event(id),
        start_ts TEXT,
        end_ts   TEXT,
        text     TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_caption_unique
        ON caption_segment(video_id, start_ts, text);
    CREATE INDEX IF NOT EXISTS idx_caption_video ON caption_segment(video_id);

    -- 1999-era witness lists carry a city per witness; witness_slip has no
    -- column for it and it is the single best disambiguator for an entity with
    -- no native id, so it is kept side-car rather than dropped.
    CREATE TABLE IF NOT EXISTS witness_slip_city (
        witness_slip_id INTEGER PRIMARY KEY REFERENCES witness_slip(id),
        city            TEXT
    );
    """

    # ------------------------------------------------------------- API calls

    def meetings_url(self, legislature: int | str, chamber: str, committee: int | str) -> str:
        return f"{HOUSE_API}/getCommitteeMeetings/{legislature}/{chamber}/{committee}"

    def video_events_url(self, legislature: int | str, called: str = "R", kind: str = "committee") -> str:
        return f"{HOUSE_API}/GetVideoEvents/{legislature}/{called}/published/{kind}"

    def fetch_committee_meetings(
        self, conn: sqlite3.Connection, legislature: int | str, chamber: str, committee: int | str
    ) -> list[dict]:
        """One JSON call → stored document + committee/hearing rows."""
        url = self.meetings_url(legislature, chamber, committee)
        resp = fetcher().get(url)
        resp.raise_for_status()
        store_document(
            conn,
            doc_id=f"committees:meetings:{legislature}:{chamber}:{committee}",
            source_family="committees",
            content=resp.content,
            url=url,
            doc_type="committee_meetings_json",
            authority="A",
        )
        meetings = parse_committee_meetings(resp.content, legislature)
        for m in meetings:
            store_meeting(conn, m)
        conn.commit()
        return meetings

    def fetch_video_events(
        self, conn: sqlite3.Connection, legislature: int | str, called: str = "R", kind: str = "committee"
    ) -> list[dict]:
        url = self.video_events_url(legislature, called, kind)
        resp = fetcher().get(url)
        resp.raise_for_status()
        store_document(
            conn,
            doc_id=f"committees:videos:{legislature}:{called}:{kind}",
            source_family="committees",
            content=resp.content,
            url=url,
            doc_type="video_events_json",
            authority="A",
        )
        events = parse_video_events(resp.content, session=f"{legislature}{called}")
        store_video_events(conn, events)
        conn.commit()
        return events

    # -------------------------------------------------------- document paths

    def ingest_witness_list(
        self, conn: sqlite3.Connection, meeting: dict, prefer_pdf: bool = True
    ) -> dict:
        """Fetch + parse one meeting's witness list (1–2 throttled requests)."""
        url = meeting.get("witnesses")
        hid = meeting.get("hearing_id")
        session = meeting.get("session")
        if not url or not hid or not session:
            return {"slips": 0, "skipped": "no witness list"}
        candidates = [url]
        if prefer_pdf and "/witlistmtg/html/" in url:
            candidates.insert(0, pdf_witness_url(url))
        resp = None
        for candidate in candidates:
            r = fetcher().get(candidate)
            if r.status_code == 200 and r.content:
                resp, url = r, candidate
                break
        if resp is None:
            return {"slips": 0, "skipped": "witness list unavailable"}
        doc_id = f"committees:witlist:{hid}"
        _, changed = store_document(
            conn,
            doc_id=doc_id,
            source_family="committees",
            content=resp.content,
            url=url,
            doc_type="witness_list",
            session_id=session,
            native_id=hid,
            authority="A",
        )
        wl = parse_witness_list(resp.content)
        store_meeting(conn, meeting, docs={"witness_doc": doc_id})
        stats = store_witness_list(conn, hid, session, wl, doc_id)
        conn.commit()
        return {**stats, "hearing": hid, "url": url, "changed": changed, "era": wl.era}

    def ingest_minutes(self, conn: sqlite3.Connection, meeting: dict) -> dict:
        url = meeting.get("minutes")
        hid = meeting.get("hearing_id")
        session = meeting.get("session")
        if not url or not hid or not session:
            return {"votes": 0, "skipped": "no minutes"}
        resp = fetcher().get(url)
        if resp.status_code != 200 or not resp.content:
            return {"votes": 0, "skipped": f"http {resp.status_code}"}
        doc_id = f"committees:minutes:{hid}"
        store_document(
            conn,
            doc_id=doc_id,
            source_family="committees",
            content=resp.content,
            url=url,
            doc_type="minutes",
            session_id=session,
            native_id=hid,
            authority="A",
        )
        votes = parse_minutes(resp.content)
        store_meeting(conn, meeting, docs={"minutes_doc": doc_id})
        stats = store_minutes_votes(
            conn, hid, session, meeting.get("chamber") or "H", meeting.get("date"), votes, doc_id
        )
        conn.commit()
        return {**stats, "hearing": hid}

    # ------------------------------------------------------ caption harvest

    def harvest_captions(
        self, conn: sqlite3.Connection, event: dict, max_segments: int = 2
    ) -> dict:
        """videoUrl → master .m3u8 → subtitle .m3u8 → first N .vtt segments.

        Undocumented and unsupported: every step degrades to a clean
        'captions absent' result rather than raising, because most videos have
        no subtitle track at all (~8% of 89R published committee videos).
        """
        video_url = event.get("video_url")
        vid = event.get("id")
        if not video_url:
            return {"captions": False, "reason": "no videoUrl", "segments": 0, "cues": 0}
        if not event.get("has_captions"):
            return {"captions": False, "reason": "captions flag false", "segments": 0, "cues": 0}
        resp = fetcher().get(video_url)
        if resp.status_code != 200:
            return {"captions": False, "reason": f"master http {resp.status_code}", "segments": 0, "cues": 0}
        tracks = parse_hls_master(resp.content)
        if not tracks:
            return {"captions": False, "reason": "no SUBTITLES track", "segments": 0, "cues": 0}
        track = next((t for t in tracks if (t.get("language") or "").lower().startswith("en")), tracks[0])
        sub_url = urljoin(video_url, track["uri"])
        resp = fetcher().get(sub_url)
        if resp.status_code != 200:
            return {"captions": False, "reason": f"subtitle http {resp.status_code}", "segments": 0, "cues": 0}
        segments = parse_hls_playlist(resp.content)[: max(0, max_segments)]
        cues: list[dict] = []
        fetched = 0
        for seg in segments:
            r = fetcher().get(urljoin(sub_url, seg))
            if r.status_code != 200:
                continue
            fetched += 1
            cues.extend(parse_vtt(r.content))
        if vid is not None:
            store_caption_segments(conn, int(vid), cues)
            conn.commit()
        return {
            "captions": True,
            "video_id": vid,
            "track": track.get("name"),
            "segments": fetched,
            "cues": len(cues),
            "sample": cues[0]["text"] if cues else None,
        }

    # --------------------------------------------------------- entry points

    def backfill(
        self,
        conn: sqlite3.Connection,
        legislature: int | str = 89,
        chamber: str = "H",
        committee_ids: tuple[int, ...] = (450,),
        max_docs: int = 0,
        with_minutes: bool = False,
        **kwargs,
    ) -> dict:
        """Meetings for the named committees; documents only up to max_docs.

        ``max_docs`` defaults to 0: listing the tlodocs tree is free via the
        JSON API, but *fetching* from it is the robots-disallowed part, so a
        caller must opt in with an explicit bound.
        """
        totals = {"meetings": 0, "witness_lists": 0, "slips": 0, "votes": 0}
        budget = max_docs
        for committee in committee_ids:
            meetings = self.fetch_committee_meetings(conn, legislature, chamber, committee)
            totals["meetings"] += len(meetings)
            for meeting in reversed(meetings):
                if budget <= 0:
                    break
                if meeting.get("witnesses"):
                    r = self.ingest_witness_list(conn, meeting)
                    budget -= 1
                    if r.get("slips"):
                        totals["witness_lists"] += 1
                        totals["slips"] += r["slips"]
                if with_minutes and budget > 0 and meeting.get("minutes"):
                    r = self.ingest_minutes(conn, meeting)
                    budget -= 1
                    totals["votes"] += r.get("votes", 0)
        return totals

    def incremental(
        self,
        conn: sqlite3.Connection,
        legislature: int | str = 89,
        chamber: str = "H",
        committee_ids: tuple[int, ...] = (450,),
        called: str = "R",
        max_docs: int = 2,
        **kwargs,
    ) -> dict:
        """Refresh listings, then chase documents for the newest meetings."""
        stats = self.backfill(
            conn,
            legislature=legislature,
            chamber=chamber,
            committee_ids=committee_ids,
            max_docs=max_docs,
            with_minutes=True,
        )
        events = self.fetch_video_events(conn, legislature, called)
        stats["video_events"] = len(events)
        stats["captioned_videos"] = sum(1 for e in events if e["has_captions"])
        return stats

    # ---------------------------------------------------------------- smoke

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """≤8 live requests: meetings JSON, one witness list, video events,
        and the caption walk for one captioned event."""
        meetings = self.fetch_committee_meetings(conn, 89, "H", 450)
        target = next((m for m in meetings if m["hearing_id"] == VERIFIED_WITNESS_TOKEN), None)
        if target is None:
            target = next(
                (m for m in sorted(meetings, key=lambda m: m["date"] or "", reverse=True)
                 if m.get("witnesses")),
                None,
            )
        if target is None:
            return SmokeResult(ok=False, detail="no meeting with a witness list", stats={"meetings": len(meetings)})
        wit = self.ingest_witness_list(conn, target)

        events = self.fetch_video_events(conn, 89, "R", "committee")
        captioned = [e for e in events if e["has_captions"] and e["video_url"]]
        cap = (
            self.harvest_captions(conn, captioned[0], max_segments=2)
            if captioned
            else {"captions": False, "reason": "no captioned events", "cues": 0, "segments": 0}
        )

        positions = {
            r["position"]
            for r in conn.execute(
                "SELECT DISTINCT position FROM witness_slip WHERE hearing_id=?", (target["hearing_id"],)
            )
        }
        ok = wit.get("slips", 0) >= 5 and bool(positions)
        stats = {
            "meetings": len(meetings),
            "hearing": target["hearing_id"],
            "witness_slips": wit.get("slips", 0),
            "witness_bills": wit.get("bills", 0),
            "positions": sorted(positions),
            "video_events": len(events),
            "captioned_videos": len(captioned),
            "caption_cues": cap.get("cues", 0),
            "caption_segments": cap.get("segments", 0),
        }
        detail = (
            f"89/H/450: {len(meetings)} meetings; {target['hearing_id']} → "
            f"{wit.get('slips', 0)} slips across {wit.get('bills', 0)} bills "
            f"{sorted(positions)}; {len(captioned)}/{len(events)} videos captioned, "
            f"harvested {cap.get('cues', 0)} cues from {cap.get('segments', 0)} segments"
        )
        return SmokeResult(ok=ok, detail=detail, stats=stats)
