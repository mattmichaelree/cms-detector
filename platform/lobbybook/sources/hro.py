"""HRO — House Research Organization bill analyses (+ Senate Research Center).

Spec: docs/texas-politics-audit/03-deep-dives/02-hro-src.md.

The HRO per-bill analysis is the richest single pre-floor document in Texas: a
neutral digest, the named committee vote, the full witness roster, and both
sides' arguments pre-labeled by stance. This module turns the PDF into rows:

  * ``hro_analysis``       — one row per analyzed bill (date, committee, tally)
  * ``hro_section``        — the labeled prose blocks (the training labels)
  * ``hro_committee_vote`` — named aye/nay/absent members
  * ``witness_slip``       — For/Against/On witnesses, testified vs registered

Parsing keys on HRO's fixed left-margin labels. Two verified extraction
gotchas drive the design:

1. the label sits in a left margin column, so a two- or three-word label wraps
   across physical lines *with body text interleaved*::

       OTHER      While the juvenile justice system should focus on ...
       CRITICS    home, CSHB 16 may not have the consequences it intends...
       SAY:       youth intervention services and community based providers...

   so a label match may consume several lines and each of those lines still
   contributes body text (:func:`_match_label`);
2. HRO writes ``CRITICS SAY:`` where no organized opposition registered and
   ``OPPONENTS SAY:`` where it did. Both are the against-stance block, so both
   normalize to ``opponents_say``; the printed label survives in
   ``hro_section.label_raw`` so the distinction is not lost.

Digest-only analyses (uncontested bills) simply yield no argument sections.

Authority (audit §7): facts — disposition, tallies, witnesses, digest, NOTES
figures — are HRO-attributable fact; SUPPORTERS/OPPONENTS SAY are *reported*
arguments, never HRO's position. Temporal trap (§6): an analysis reflects the
bill as reported by committee and first considered by the House — not floor
amendments, not the engrossed or enrolled text.
"""

from __future__ import annotations

import io
import re
import sqlite3

import pdfplumber

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

HRO_BASE = "https://hro.house.texas.gov"
TLO_BASE = "https://capitol.texas.gov"

BILL_RE = re.compile(r"\b(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\s*0*(\d+)\b", re.I)


def bill_id(session: str, bill: str) -> str:
    """('88R', 'HB 16') → '88R-HB16' (the TLO join key)."""
    return f"{session.upper()}-{bill.replace(' ', '').upper()}"


def analysis_url(session: str, bill: str, ext: str = "pdf") -> str:
    """('88R', 'HB16') → .../pdf/ba88r/hb0016.pdf (lowercase dir, 4-digit bill)."""
    m = BILL_RE.search(bill)
    if not m:
        raise ValueError(f"unparseable bill designator: {bill!r}")
    stem = f"{m.group(1).lower()}{int(m.group(2)):04d}"
    return f"{HRO_BASE}/pdf/ba{session.lower()}/{stem}.{ext}"


def src_url(session: str, billcode: str, version: str) -> str:
    """('88R', 'SB01577', 'F') → .../tlodocs/88R/analysis/pdf/SB01577F.pdf."""
    return f"{TLO_BASE}/tlodocs/{session.upper()}/analysis/pdf/{billcode.upper()}{version.upper()}.pdf"


# ---------------------------------------------------------------- extraction

def extract_text(content: bytes) -> str:
    """PDF bytes → text. Born-digital 1995→present; no OCR path is needed."""
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


# Running headers/footers that interleave with the label column and would
# otherwise break a wrapped label across a page boundary.
_NOISE = [
    re.compile(r"^page\s+\d+$", re.I),
    re.compile(r"^house research organization$", re.I),
    re.compile(r"^(CS)?(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\s*\d+$", re.I),
    re.compile(r"^SRC-\S*\s+.*\bPage\s+\d+\s+of\s+\d+$", re.I),
    re.compile(r"^\s*$"),
]


def _clean_lines(text: str) -> list[str]:
    out = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if any(p.match(line.strip()) for p in _NOISE):
            continue
        out.append(line)
    return out


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# ------------------------------------------------------------ label matching

# (token sequence, normalized section_type). CRITICS SAY: is HRO's label when
# no organized opposition registered; it is the same against-stance block.
_LABELS: list[tuple[tuple[str, ...], str]] = [
    (("SUBJECT:",), "subject"),
    (("COMMITTEE:",), "committee"),
    (("VOTE:",), "vote"),
    (("SENATE", "VOTE:"), "senate_vote"),
    (("WITNESSES:",), "witnesses"),
    (("BACKGROUND:",), "background"),
    (("DIGEST:",), "digest"),
    (("SUPPORTERS", "SAY:"), "supporters_say"),
    (("OPPONENTS", "SAY:"), "opponents_say"),
    (("CRITICS", "SAY:"), "opponents_say"),
    (("OTHER", "OPPONENTS", "SAY:"), "other_opponents_say"),
    (("OTHER", "CRITICS", "SAY:"), "other_opponents_say"),
    (("NOTES:",), "notes"),
]
_LABELS_SORTED = sorted(_LABELS, key=lambda t: -len(t[0]))

# Sections whose prose we keep verbatim; committee/vote/witnesses are shredded
# into their own tables instead.
PROSE_SECTIONS = (
    "subject",
    "background",
    "digest",
    "supporters_say",
    "opponents_say",
    "other_opponents_say",
    "notes",
    "senate_vote",
)


def _starts_with_token(rest: str, token: str) -> bool:
    if len(rest) < len(token) or rest[: len(token)].upper() != token:
        return False
    tail = rest[len(token) :]
    return token.endswith(":") or tail == "" or tail[0].isspace()


def _match_label(lines: list[str], i: int):
    """Try to match a (possibly line-wrapped) margin label starting at line i.

    Returns ``(section_type, label_raw, consumed, fragments)`` where fragments
    are the body-text remainders of every line the label spanned.
    """
    for tokens, stype in _LABELS_SORTED:
        frags: list[str] = []
        pos = 0
        j = i
        ok = True
        while pos < len(tokens):
            if j >= len(lines):
                ok = False
                break
            rest = lines[j].strip()
            matched_here = False
            while pos < len(tokens) and _starts_with_token(rest, tokens[pos]):
                rest = rest[len(tokens[pos]) :].lstrip()
                pos += 1
                matched_here = True
            if not matched_here:
                ok = False
                break
            frags.append(rest)
            j += 1
        if ok:
            return stype, " ".join(tokens), j - i, frags
    return None


def split_sections(text: str) -> tuple[list[str], list[dict]]:
    """Text → (preamble lines, [{type, label_raw, lines}]) in document order."""
    lines = _clean_lines(text)
    preamble: list[str] = []
    sections: list[dict] = []
    current: dict | None = None
    i = 0
    while i < len(lines):
        hit = _match_label(lines, i)
        if hit:
            stype, label_raw, consumed, frags = hit
            current = {"type": stype, "label_raw": label_raw, "lines": [f for f in frags if f]}
            sections.append(current)
            i += consumed
            continue
        if current is None:
            preamble.append(lines[i])
        else:
            current["lines"].append(lines[i].strip())
        i += 1
    return preamble, sections


# ------------------------------------------------------------ header / vote

_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
_SUBST_RE = re.compile(r"\((CS[A-Z]{2,4}\s*\d+)\s+by\s+([^)]+)\)")


def parse_header(preamble: list[str]) -> dict:
    """The three-line HRO masthead → date, bill label, author, substitute author."""
    blob = " ".join(preamble)
    head: dict = {
        "analysis_date": None,
        "bill_label": None,
        "author_raw": None,
        "substitute_of": None,
        "substitute_author_raw": None,
        "reading": None,
    }
    m = _DATE_RE.search(blob)
    if m:
        head["analysis_date"] = m.group(1)
    m = re.search(r"^HOUSE\s+((?:CS)?[A-Z]{2,4}\s*\d+)", " ".join(preamble[:1]), re.I)
    if m:
        head["bill_label"] = _ws(m.group(1))
    m = re.search(r"\((\d+(?:st|nd|rd|th)\s+reading[^)]*)\)", blob, re.I)
    if m:
        head["reading"] = m.group(1)
    for line in preamble:
        s = line.strip()
        if s.upper().startswith("RESEARCH "):
            candidate = _ws(s[len("RESEARCH ") :])
            # Guard against the masthead of non-analysis HRO publications
            # (Focus/State Finance reports reuse the same three-line header).
            if candidate and len(candidate) <= 60 and not any(c.isdigit() for c in candidate):
                head["author_raw"] = candidate
            break
    m = _SUBST_RE.search(blob)
    if m:
        head["substitute_of"] = _ws(m.group(1))
        head["substitute_author_raw"] = _ws(m.group(2))
    return head


def parse_committee(text: str) -> dict:
    """'Public Education — committee substitute recommended' → raw + disposition."""
    t = _ws(text)
    parts = re.split(r"\s*[—–]\s*", t, maxsplit=1)
    raw = parts[0].strip() or None
    disp = _ws(parts[1]) if len(parts) > 1 else None
    return {"committee_raw": raw, "committee_disposition": disp}


_TALLY_RE = re.compile(
    r"(\d+)\s+(ayes?|nays?|absent|present,?\s+not\s+voting|abstain\w*)\b", re.I
)
_POSITION = {"aye": "aye", "nay": "nay", "absent": "absent", "present": "present_not_voting"}


def parse_vote(text: str) -> dict:
    """'7 ayes — S. Thompson, Hull...; 0 nays; 2 absent — Dutton' → tally + members."""
    t = _ws(text)
    result: dict = {
        "ayes": None,
        "nays": None,
        "absent": None,
        "present_not_voting": None,
        "members": [],
    }
    hits = list(_TALLY_RE.finditer(t))
    for k, m in enumerate(hits):
        count = int(m.group(1))
        word = m.group(2).lower().split(",")[0].split()[0].rstrip("s")
        pos = _POSITION.get(word)
        if pos is None:
            continue
        key = {"aye": "ayes", "nay": "nays", "absent": "absent"}.get(pos, "present_not_voting")
        result[key] = count
        end = hits[k + 1].start() if k + 1 < len(hits) else len(t)
        names_blob = t[m.end() : end].strip()
        names_blob = names_blob.lstrip("—–-:").strip()
        for name in names_blob.split(","):
            name = _ws(name).strip(".;")
            if not name or name.lower() == "and":
                continue
            name = re.sub(r"^and\s+", "", name, flags=re.I)
            result["members"].append({"name_raw": name, "position": pos})
    return result


# --------------------------------------------------------------- witnesses

_GROUP_RE = re.compile(r"\b(For|Against|On)\s*[—–]\s*")
_REG_RE = re.compile(r"\(\s*Registered,?\s*but\s+did\s+not\s+testify:?\s*", re.I)
_ANON_RE = re.compile(r"^\(?\s*(?:and\s+)?(\d+)\s+individuals?\)?\.?$", re.I)
_SELF_RE = re.compile(r"\(\s*self\s*\)", re.I)

# Tokens that mark a comma-part as an organization rather than a person name.
_ORG_WORDS = {
    "action", "advocacy", "agency", "alliance", "america", "american", "americans",
    "assn", "associates", "association", "associations", "authority", "bank", "bar",
    "board", "bureau", "campaign", "capital", "caucus", "center", "centers", "central",
    "chamber", "chapter", "church", "citizens", "city", "coalition", "college",
    "commission", "committee", "company", "conference", "congress", "consultants",
    "consulting", "cooperative", "corp", "corporation", "council", "county", "dept",
    "department", "district", "division", "energy", "enterprises", "family", "federation",
    "firm", "force", "foundation", "fund", "government", "group", "health", "holdings",
    "hospital", "inc", "industries", "initiative", "inst", "institute", "insurance",
    "isd", "league", "legal", "llc", "llp", "lp", "ministries", "movement", "national",
    "network", "office", "org", "organization", "pac", "partners", "partnership", "party",
    "police", "policy", "project", "public", "resistance", "resources", "school",
    "schools", "service", "services", "society", "solutions", "state", "system",
    "systems", "taxpayers", "texans", "texas", "trust", "union", "united", "university",
    "usa", "watch", "works",
}
_CONNECTORS = {"of", "for", "the", "and", "in", "at", "on", "&"}


def _looks_like_person(part: str) -> bool:
    tokens = part.split()
    if not (2 <= len(tokens) <= 5):
        return False
    if any(ch.isdigit() for ch in part) or "&" in part or "/" in part:
        return False
    low = [t.lower().strip(".,;") for t in tokens]
    if any(t in _ORG_WORDS for t in low) or any(t in _CONNECTORS for t in low):
        return False
    if any(t.isupper() and len(t) > 2 for t in tokens):
        return False
    return tokens[0][:1].isupper()


def _split_name_org(entry: str) -> list[dict]:
    """One witness entry → [{name_raw, org_raw, is_self}] (an org may be shared)."""
    is_self = False
    if _SELF_RE.search(entry):
        is_self = True
        entry = _SELF_RE.sub("", entry)
    entry = _ws(entry).strip(".;,")
    org_paren = None
    m = re.search(r"\(([^)]+)\)\s*$", entry)
    if m:
        org_paren = _ws(m.group(1))
        entry = entry[: m.start()].strip().rstrip(",")
    parts = [_ws(p) for p in entry.split(",") if _ws(p)]
    if not parts:
        return []
    if org_paren:
        names, org = parts, org_paren
    else:
        idx = 0
        while idx < len(parts) and _looks_like_person(parts[idx]):
            idx += 1
        if idx == 0:
            names, org = [parts[0]], (", ".join(parts[1:]) or None)
        elif idx == len(parts):
            # Every part reads as a person: the trailing one is the affiliation
            # ("Kevin Whitt, Mass Resistance"), unless there is only one part.
            names, org = (parts, None) if len(parts) == 1 else (parts[:-1], parts[-1])
        else:
            names, org = parts[:idx], ", ".join(parts[idx:])
    return [{"name_raw": n, "org_raw": org, "is_self": is_self or org is None} for n in names]


def _entries(blob: str) -> tuple[list[str], int]:
    """Split a witness run on ';' → (entries, anonymous 'N individuals' count)."""
    entries, anon = [], 0
    for chunk in blob.split(";"):
        chunk = _ws(chunk).strip(".").strip()
        chunk = re.sub(r"^and\s+", "", chunk, flags=re.I)
        if not chunk:
            continue
        m = _ANON_RE.match(chunk)
        if m:
            anon += int(m.group(1))
            continue
        # trailing "..., and 31 individuals" glued to the last entry
        m = re.search(r",?\s*and\s+(\d+)\s+individuals?\.?\)?$", chunk, re.I)
        if m:
            anon += int(m.group(1))
            chunk = chunk[: m.start()].strip()
        if chunk.strip("().,"):
            entries.append(chunk)
    return entries, anon


def parse_witnesses(text: str) -> list[dict]:
    """WITNESSES: block → witness dicts (position, testified, is_self, org)."""
    t = _ws(text)
    out: list[dict] = []
    marks = list(_GROUP_RE.finditer(t))
    for k, m in enumerate(marks):
        position = m.group(1).lower()
        end = marks[k + 1].start() if k + 1 < len(marks) else len(t)
        seg = t[m.end() : end]
        rm = _REG_RE.search(seg)
        if rm:
            testified_blob = seg[: rm.start()]
            registered_blob = seg[rm.end() :].rstrip().rstrip(")")
        else:
            testified_blob, registered_blob = seg, ""
        for blob, testified in ((testified_blob, 1), (registered_blob, 0)):
            entries, anon = _entries(blob)
            for entry in entries:
                for w in _split_name_org(entry):
                    out.append({**w, "position": position, "testified": testified})
            if anon:
                out.append(
                    {
                        "name_raw": f"({anon} individuals)",
                        "org_raw": None,
                        "is_self": True,
                        "position": position,
                        "testified": testified,
                        "anonymous_count": anon,
                    }
                )
    return out


# ----------------------------------------------------------------- analysis

def parse_analysis(content: bytes) -> dict:
    """HRO analysis PDF bytes → header, prose sections, committee, vote, witnesses.

    Pure function over bytes; digest-only analyses simply come back with no
    argument sections.
    """
    text = extract_text(content)
    preamble, raw_sections = split_sections(text)
    parsed: dict = {
        "text": text,
        "header": parse_header(preamble),
        "sections": [],
        "committee_raw": None,
        "committee_disposition": None,
        "vote": {"ayes": None, "nays": None, "absent": None, "present_not_voting": None,
                 "members": []},
        "witnesses": [],
    }
    ordinal = 0
    for sec in raw_sections:
        body = "\n".join(sec["lines"]).strip()
        if sec["type"] == "committee":
            parsed.update(parse_committee(body))
        elif sec["type"] == "vote":
            parsed["vote"] = parse_vote(body)
        elif sec["type"] == "witnesses":
            parsed["witnesses"] = parse_witnesses(body)
        elif sec["type"] in PROSE_SECTIONS:
            if not body:
                continue
            ordinal += 1
            parsed["sections"].append(
                {
                    "section_type": sec["type"],
                    "label_raw": sec["label_raw"],
                    "ordinal": ordinal,
                    "text": body if sec["type"] != "subject" else _ws(body),
                }
            )
    return parsed


def section_text(parsed: dict, section_type: str) -> str | None:
    for sec in parsed["sections"]:
        if sec["section_type"] == section_type:
            return sec["text"]
    return None


# --------------------------------------------------------------------- SRC

_SRC_HEADERS = {
    "AUTHOR'S/SPONSOR'S STATEMENT OF INTENT": "src_statement_of_intent",
    "AUTHOR'S STATEMENT OF INTENT": "src_statement_of_intent",
    "SPONSOR'S STATEMENT OF INTENT": "src_statement_of_intent",
    "PURPOSE": "src_purpose",
    "RULEMAKING AUTHORITY": "src_rulemaking_authority",
    "SECTION BY SECTION ANALYSIS": "src_section_by_section",
    "SUMMARY OF COMMITTEE CHANGES": "src_summary_of_committee_changes",
    "COMMITTEE CHANGES": "src_summary_of_committee_changes",
}


def _norm_src_header(line: str) -> str:
    s = line.strip().replace("’", "'").upper()
    s = re.sub(r"\s*/\s*", "/", s)
    return re.sub(r"\s+", " ", s).strip(" .:")


def parse_src(content: bytes) -> dict:
    """SRC analysis PDF bytes → {'sections': [...], 'version': 'Enrolled', ...}.

    SRC carries no arguments, votes, or witnesses — neutral intent plus a
    section-by-section, re-issued and version-stamped per bill version.
    """
    text = extract_text(content)
    lines = [ln for ln in _clean_lines(text) if _norm_src_header(ln) != "BILL ANALYSIS"]
    sections: list[dict] = []
    preamble: list[str] = []
    current: dict | None = None
    for line in lines:
        stype = _SRC_HEADERS.get(_norm_src_header(line))
        if stype:
            current = {"section_type": stype, "label_raw": _ws(line), "lines": []}
            sections.append(current)
            continue
        (current["lines"] if current else preamble).append(line.strip())
    if preamble:
        sections.insert(
            0, {"section_type": "src_header", "label_raw": "HEADER", "lines": preamble}
        )
    out = []
    for i, sec in enumerate(sections, start=1):
        body = "\n".join(sec["lines"]).strip()
        if body:
            out.append(
                {
                    "section_type": sec["section_type"],
                    "label_raw": sec["label_raw"],
                    "ordinal": i,
                    "text": body,
                }
            )
    head = " ".join(preamble)
    version = None
    m = re.search(
        r"\b(Introduced|Committee Report|Engrossed|Enrolled|As Filed|Senate Committee Report)\b",
        head,
    )
    if m:
        version = m.group(1)
    author = None
    m = re.search(r"^By:\s*(.+)$", "\n".join(preamble), re.M)
    if m:
        author = _ws(m.group(1))
    date = None
    m = _DATE_RE.search(head)
    if m:
        date = m.group(1)
    return {"text": text, "sections": out, "version": version, "author_raw": author, "date": date}


# ------------------------------------------------------------------ storage

def _ensure_bill(conn: sqlite3.Connection, session: str, bill: str) -> str:
    m = BILL_RE.search(bill)
    if not m:
        raise ValueError(f"unparseable bill designator: {bill!r}")
    bid = bill_id(session, f"{m.group(1)}{int(m.group(2))}")
    dbx.ensure_session(conn, session)
    dbx.upsert(
        conn,
        "bill",
        {
            "id": bid,
            "session_id": session.upper(),
            "bill_type": m.group(1).upper(),
            "number": int(m.group(2)),
        },
        ["id"],
        update_cols=[],
    )
    return bid


def _store_sections(conn: sqlite3.Connection, bid: str, sections: list[dict], *, src: bool) -> None:
    if src:
        conn.execute(
            "DELETE FROM hro_section WHERE bill_id=? AND section_type LIKE 'src_%'", (bid,)
        )
    else:
        conn.execute(
            "DELETE FROM hro_section WHERE bill_id=? AND section_type NOT LIKE 'src_%'", (bid,)
        )
    for sec in sections:
        conn.execute(
            "INSERT INTO hro_section (bill_id, section_type, label_raw, ordinal, text)"
            " VALUES (?,?,?,?,?)",
            (bid, sec["section_type"], sec.get("label_raw"), sec["ordinal"], sec["text"]),
        )


def _store_witness(conn: sqlite3.Connection, bid: str, w: dict) -> bool:
    exists = conn.execute(
        "SELECT 1 FROM witness_slip WHERE bill_id=? AND name_raw=? AND position=?"
        " AND COALESCE(org_raw,'')=? AND hearing_id IS NULL",
        (bid, w["name_raw"], w["position"], w.get("org_raw") or ""),
    ).fetchone()
    if exists:
        return False
    conn.execute(
        "INSERT INTO witness_slip (hearing_id, bill_id, name_raw, org_raw, is_self, position,"
        " testified) VALUES (NULL,?,?,?,?,?,?)",
        (
            bid,
            w["name_raw"],
            w.get("org_raw"),
            1 if w.get("is_self") else 0,
            w["position"],
            w.get("testified", 1),
        ),
    )
    return True


def store_analysis(
    conn: sqlite3.Connection, session: str, bill: str, parsed: dict, doc_id: str
) -> dict:
    """Persist a parsed analysis + its explicit edges. Idempotent per bill."""
    bid = _ensure_bill(conn, session, bill)
    vote = parsed["vote"]
    dbx.upsert(
        conn,
        "hro_analysis",
        {
            "bill_id": bid,
            "session_id": session.upper(),
            "analysis_date": parsed["header"].get("analysis_date"),
            "committee_raw": parsed.get("committee_raw"),
            "committee_disposition": parsed.get("committee_disposition"),
            "vote_ayes": vote.get("ayes"),
            "vote_nays": vote.get("nays"),
            "vote_absent": vote.get("absent"),
            "doc_id": doc_id,
        },
        ["bill_id"],
    )
    dbx.add_edge(conn, "bill", bid, "has_analysis", "document", doc_id, "explicit", doc_id)

    _store_sections(conn, bid, parsed["sections"], src=False)
    for sec in parsed["sections"]:
        if sec["section_type"] == "supporters_say":
            dbx.add_edge(conn, "argument", f"{bid}:supporters", "supports", "bill", bid,
                         "explicit", doc_id, span=sec["label_raw"])
        elif sec["section_type"] in ("opponents_say", "other_opponents_say"):
            dbx.add_edge(conn, "argument", f"{bid}:{sec['section_type']}", "opposes", "bill", bid,
                         "explicit", doc_id, span=sec["label_raw"])

    if parsed.get("committee_raw"):
        dbx.add_edge(conn, "bill", bid, "reported_by", "committee_name",
                     parsed["committee_raw"], "explicit", doc_id)

    conn.execute("DELETE FROM hro_committee_vote WHERE bill_id=?", (bid,))
    for member in vote["members"]:
        dbx.upsert(
            conn,
            "hro_committee_vote",
            {"bill_id": bid, "name_raw": member["name_raw"], "position": member["position"]},
            ["bill_id", "name_raw"],
        )
        dbx.add_edge(conn, "person_name", member["name_raw"], f"voted_{member['position']}",
                     "bill", bid, "explicit", doc_id)

    witnesses = 0
    for w in parsed["witnesses"]:
        if _store_witness(conn, bid, w):
            witnesses += 1
        mode = "testified" if w.get("testified", 1) else "registered"
        dbx.add_edge(conn, "person_name", w["name_raw"], f"{mode}_{w['position']}", "bill", bid,
                     "explicit", doc_id)
        if w.get("org_raw"):
            dbx.add_edge(conn, "person_name", w["name_raw"], "represents", "org_name",
                         w["org_raw"], "explicit", doc_id)
            dbx.add_edge(conn, "org_name", w["org_raw"], f"witness_{w['position']}", "bill", bid,
                         "explicit", doc_id)

    head = parsed["header"]
    if head.get("author_raw"):
        author = re.sub(r"\s+et al\.?$", "", head["author_raw"], flags=re.I)
        dbx.add_edge(conn, "person_name", author, "authored", "bill", bid, "explicit", doc_id)
    if head.get("substitute_author_raw"):
        dbx.add_edge(conn, "person_name", head["substitute_author_raw"], "substitute_authored",
                     "bill", bid, "explicit", doc_id)

    return {
        "bill_id": bid,
        "sections": len(parsed["sections"]),
        "votes": len(vote["members"]),
        "witnesses": len(parsed["witnesses"]),
        "witnesses_new": witnesses,
    }


def store_src(
    conn: sqlite3.Connection, session: str, bill: str, parsed: dict, doc_id: str
) -> dict:
    bid = _ensure_bill(conn, session, bill)
    _store_sections(conn, bid, parsed["sections"], src=True)
    dbx.add_edge(conn, "bill", bid, "has_src_analysis", "document", doc_id, "explicit", doc_id)
    if parsed.get("author_raw"):
        for name in re.split(r"\s*;\s*", parsed["author_raw"]):
            if name.strip():
                dbx.add_edge(conn, "person_name", name.strip(), "authored", "bill", bid,
                             "explicit", doc_id)
    return {"bill_id": bid, "sections": len(parsed["sections"]), "version": parsed.get("version")}


# ------------------------------------------------------------------ connector

@register
class HROConnector(Connector):
    name = "hro"
    tier = 0
    cadence = "daily_in_session"

    DDL = """
    -- One row per HRO-analyzed bill. Coverage is calendar-driven: a missing
    -- row means the bill never reached a House daily calendar (404 = normal).
    CREATE TABLE IF NOT EXISTS hro_analysis (
        bill_id               TEXT PRIMARY KEY,      -- '88R-HB16'
        session_id            TEXT,
        analysis_date         TEXT,                  -- floor-calendar day
        committee_raw         TEXT,
        committee_disposition TEXT,                  -- 'committee substitute recommended'
        vote_ayes             INTEGER,
        vote_nays             INTEGER,
        vote_absent           INTEGER,
        doc_id                TEXT
    );

    -- Labeled prose blocks. section_type:
    --   subject|background|digest|supporters_say|opponents_say|other_opponents_say|
    --   notes|senate_vote|src_*
    -- label_raw keeps the printed label, so CRITICS SAY vs OPPONENTS SAY (both
    -- normalized to opponents_say) survives for downstream labeling.
    CREATE TABLE IF NOT EXISTS hro_section (
        id           INTEGER PRIMARY KEY,
        bill_id      TEXT,
        section_type TEXT,
        ordinal      INTEGER,
        text         TEXT,
        label_raw    TEXT
    );

    -- Named committee vote (the committee vote, never the floor vote).
    CREATE TABLE IF NOT EXISTS hro_committee_vote (
        bill_id  TEXT,
        name_raw TEXT,
        position TEXT,                                -- aye|nay|absent|present_not_voting
        PRIMARY KEY (bill_id, name_raw)
    );

    CREATE INDEX IF NOT EXISTS idx_hro_section_bill ON hro_section(bill_id, section_type);
    """

    # ---------------------------------------------------------- fetching

    def fetch_analysis(self, session: str, bill: str) -> tuple[bytes, str] | None:
        """Fetch the per-bill analysis PDF, trying .pdf then .PDF.

        Returns None on 404 — a bill that never reached a calendar simply has
        no HRO analysis, which is the normal case, not an error.
        """
        for ext in ("pdf", "PDF"):
            url = analysis_url(session, bill, ext)
            resp = fetcher().get(url)
            if resp.status_code == 200 and resp.content[:5] == b"%PDF-":
                return resp.content, url
            if resp.status_code not in (403, 404):
                resp.raise_for_status()
        return None

    def ingest_analysis(self, conn: sqlite3.Connection, session: str, bill: str) -> dict | None:
        got = self.fetch_analysis(session, bill)
        if got is None:
            return None
        content, url = got
        bid = bill_id(session, bill)
        doc_id = f"hro:analysis:{bid}"
        _, changed = store_document(
            conn,
            doc_id=doc_id,
            source_family="hro",
            content=content,
            url=url,
            native_id=bid,
            doc_type="bill_analysis",
            session_id=session.upper(),
            authority="A",
        )
        parsed = parse_analysis(content)
        stats = store_analysis(conn, session, bill, parsed, doc_id)
        conn.commit()
        stats.update({"changed": changed, "url": url, "doc_id": doc_id})
        return stats

    def ingest_src(
        self, conn: sqlite3.Connection, session: str, billcode: str, version: str
    ) -> dict | None:
        """SRC analysis for one bill *version* ('SB01577', 'F' = Enrolled)."""
        url = src_url(session, billcode, version)
        resp = fetcher().get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        if resp.content[:5] != b"%PDF-":
            return None
        m = BILL_RE.search(billcode)
        if not m:
            raise ValueError(f"unparseable bill code: {billcode!r}")
        bill = f"{m.group(1).upper()}{int(m.group(2))}"
        bid = bill_id(session, bill)
        doc_id = f"src:analysis:{bid}:{version.upper()}"
        _, changed = store_document(
            conn,
            doc_id=doc_id,
            source_family="src",
            content=resp.content,
            url=url,
            native_id=f"{billcode.upper()}{version.upper()}",
            doc_type="src_bill_analysis",
            session_id=session.upper(),
            authority="A",
        )
        parsed = parse_src(resp.content)
        stats = store_src(conn, session, bill, parsed, doc_id)
        conn.commit()
        stats.update({"changed": changed, "url": url, "doc_id": doc_id})
        return stats

    def backfill(self, conn: sqlite3.Connection, session: str = "88R", bills=(), **kwargs) -> dict:
        """Walk an explicit bill list; 404s (not analyzed) are counted, not raised."""
        found = missing = 0
        for bill in bills:
            if self.ingest_analysis(conn, session, bill) is None:
                missing += 1
            else:
                found += 1
        return {"session": session, "analyzed": found, "not_analyzed": missing}

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        stats = self.ingest_analysis(conn, "88R", "HB16")
        if stats is None:
            return SmokeResult(ok=False, detail="88R HB16 analysis not reachable", stats={})
        bid = stats["bill_id"]
        rows = {
            r["section_type"]: len(r["text"])
            for r in conn.execute(
                "SELECT section_type, text FROM hro_section WHERE bill_id=?", (bid,)
            )
        }
        witnesses = conn.execute(
            "SELECT COUNT(*) AS n FROM witness_slip WHERE bill_id=?", (bid,)
        ).fetchone()["n"]
        votes = conn.execute(
            "SELECT COUNT(*) AS n FROM hro_committee_vote WHERE bill_id=?", (bid,)
        ).fetchone()["n"]
        src = self.ingest_src(conn, "88R", "SB01577", "F")
        ok = (
            rows.get("supporters_say", 0) > 0
            and rows.get("opponents_say", 0) > 0
            and witnesses >= 1
        )
        return SmokeResult(
            ok=ok,
            detail=(
                f"88R HB16: {len(rows)} sections "
                f"(supporters {rows.get('supporters_say', 0)}c / "
                f"opponents {rows.get('opponents_say', 0)}c), "
                f"{witnesses} witnesses, {votes} committee votes; "
                f"SRC 88R SB1577{'' if not src else ' ' + str(src['sections']) + ' sections'}"
            ),
            stats={"analysis": stats, "sections": rows, "witnesses": witnesses,
                   "votes": votes, "src": src},
        )
