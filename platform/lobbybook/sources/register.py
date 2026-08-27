"""Texas Register — weekly rulemaking notices (Secretary of State).

Spec: docs/texas-politics-audit/03-deep-dives/05-texas-register-tac.md.

Two facts from the audit shape this module:
  * The SOS keeps only a rolling ~1-year archive on its own site, so every
    issue must be captured as it publishes — a missed week is gone.
  * Notices are concatenated many-per-file (one file per Register section per
    TAC title), each terminated by a TRD number, which is the natural unique
    key and the splitter's boundary marker.
"""

from __future__ import annotations

import re
import sqlite3
from html import unescape
from urllib.parse import quote, unquote, urljoin

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

BASE = "https://www.sos.state.tx.us/texreg/"
CURRENT_TOC = BASE + "sos/index.html"
ARCHIVE_INDEX = BASE + "archive/index.shtml"

# Register section -> canonical action_type stored on rule_action.
SECTION_ACTIONS = {
    "proposed rules": "proposed",
    "adopted rules": "adopted",
    "withdrawn rules": "withdrawn",
    "emergency rules": "emergency",
    "review of agency rules": "review",
    "transferred rules": "transferred",
    "in addition": "in_addition",
    "the governor": "governor",
    "attorney general": "attorney_general",
    "tables and graphics": "tables",
}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
TRD_RE = re.compile(r"TRD-(\d{9,})")
TAC_RE = re.compile(r"\b(\d{1,2})\s+TAC\s+(?:§+|&#167;|Sec(?:tion)?\.?)\s*([\d.]+(?:\s*-\s*[\d.]+)?)", re.I)
TEXREG_CITE_RE = re.compile(r"\((\d{2,3})\s+TexReg\s+(\d+)\)")
# Two filing forms observed live: the terse "Filed:" and the full
# "Filed with the Office of the Secretary of State on <date>".
FILED_RE = re.compile(
    r"(?:Filed with the Office of the Secretary of State on|Filed:)\s*([A-Z][a-z]+ \d{1,2}, \d{4})"
)
PROPOSAL_PUB_RE = re.compile(r"Proposal publication date:\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
# Agency headings appear as "PART 15. TEXAS HEALTH AND HUMAN SERVICES COMMISSION"
# and again in the signature block that follows the TRD.
PART_AGENCY_RE = re.compile(r"PART\s+[IVXLC\d]+\.\s+([A-Z][A-Z &',.\-]{5,80}?)\s+(?:CHAPTER|SUBCHAPTER)\b")
SIG_AGENCY_RE = re.compile(r"TRD-\d{9,}\s+(.{0,120}?)\s*(?:Effective date:|Earliest possible date|For further information)")
EARLIEST_RE = re.compile(r"Earliest possible date of adoption:\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
EFFECTIVE_RE = re.compile(r"Effective date:\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
COMMENT_END_RE = re.compile(r"comment period[^.]{0,200}?ends?\s+([A-Z][a-z]+ \d{1,2}, \d{4})", re.I)
# Agencies state comment deadlines two ways (both verified live): an absolute
# date, or a period relative to the issue date. A lobbyist needs the real
# date, so the relative form is resolved against the issue date and marked
# derived rather than left unparsed.
COMMENT_RELATIVE_RE = re.compile(
    r"no later than\s+(\d{1,3})\s+days after the date of (?:this|the) issue", re.I
)
AUTHORITY_RE = re.compile(r"STATUTORY AUTHORITY(.{0,1200}?)(?:The (?:new|amendment|repeal|rule)s? .{0,80}?(?:affects?|implements?)|TRD-|$)", re.S)
STATUTE_CITE_RE = re.compile(
    r"\b(Texas\s+)?((?:[A-Z][a-z]+\s+){0,3}(?:Government|Health and Safety|Occupations|Insurance|"
    r"Education|Water|Natural Resources|Human Resources|Transportation|Labor|Tax|Agriculture|"
    r"Finance|Utilities|Property|Local Government|Family|Alcoholic Beverage|Business)\s+Code)"
    r"\s*(?:§+|&#167;)\s*([\d.]+[\w().]*)"
)
BILL_RE = re.compile(r"\b((?:House|Senate) Bill|HB|SB)\s*(\d+),?\s*(?:(\d{2,3})(?:st|nd|rd|th)\s+Legislature)?", re.I)



def strip_html(html: str) -> str:
    return _WS.sub(" ", unescape(_TAG.sub(" ", html))).strip()


def split_notices(content: bytes) -> list[dict]:
    """One section file -> one dict per notice.

    Notices are concatenated; each ends with its TRD block, so the TRD is used
    as the terminator. Both the raw HTML slice (for diff markup) and the
    stripped text (for field extraction) are returned.
    """
    html = content.decode("utf-8", errors="replace")
    out: list[dict] = []
    start = 0
    for m in TRD_RE.finditer(html):
        # Include a little past the TRD so the trailing Filed:/effective lines
        # that follow it stay with their own notice.
        end = html.find("TRD-", m.end())
        chunk_end = m.end() + 400 if end == -1 else min(m.end() + 400, end)
        raw = html[start:chunk_end]
        out.append({"trd": f"TRD-{m.group(1)}", "html": raw, "text": strip_html(raw)})
        start = chunk_end
    return out


def _add_days(date_str: str, days: int) -> str | None:
    from datetime import datetime, timedelta

    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return (datetime.strptime(date_str, fmt) + timedelta(days=days)).strftime("%B %d, %Y")
        except ValueError:
            continue
    return None


def parse_notice(notice: dict, action_type: str, issue_date: str | None = None) -> dict:
    """Extract the canonical fields from one notice."""
    text, html = notice["text"], notice["html"]
    rec: dict = {"trd": notice["trd"], "action_type": action_type}

    tac = [f"{t} TAC §{s}" for t, s in TAC_RE.findall(text)]
    rec["tac_cites"] = list(dict.fromkeys(tac))
    rec["tac_cite"] = rec["tac_cites"][0] if rec["tac_cites"] else None

    for key, pat in (
        ("filed_date", FILED_RE),
        ("earliest_adoption", EARLIEST_RE),
        ("effective", EFFECTIVE_RE),
        ("comment_end", COMMENT_END_RE),
    ):
        m = pat.search(text)
        rec[key] = m.group(1) if m else None

    # An adoption names the proposal it adopts by its TexReg citation.
    cites = TEXREG_CITE_RE.findall(text)
    rec["register_cite"] = f"{cites[0][0]} TexReg {cites[0][1]}" if cites else None
    rec["adopts_cite"] = rec["register_cite"] if action_type in ("adopted", "withdrawn") else None

    # Resolve a relative comment deadline against the issue date.
    rec["comment_end_derived"] = False
    if not rec["comment_end"]:
        rel = COMMENT_RELATIVE_RE.search(text)
        if rel and issue_date:
            computed = _add_days(issue_date, int(rel.group(1)))
            if computed:
                rec["comment_end"] = computed
                rec["comment_end_derived"] = True

    auth = AUTHORITY_RE.search(text)
    authority_text = auth.group(1) if auth else ""
    rec["authority"] = list(
        dict.fromkeys(f"{c[1]} §{c[2]}" for c in STATUTE_CITE_RE.findall(authority_text or text))
    )
    rec["bills"] = list(
        dict.fromkeys(
            f"{'HB' if b[0].lower().startswith(('house', 'hb')) else 'SB'}{b[1]}"
            + (f"@{b[2]}" if b[2] else "")
            for b in BILL_RE.findall(authority_text or "")
        )
    )

    rec["proposal_pub_date"] = (
        PROPOSAL_PUB_RE.search(text).group(1) if PROPOSAL_PUB_RE.search(text) else None
    )
    rec["agency"] = _agency(text)

    # Amendment markup: additions <u>, deletions [<s>...</s>] (verified live).
    rec["additions"] = html.count("<u>")
    rec["deletions"] = html.count("<s>")

    rec["commenters"] = parse_commenters(text) if action_type == "adopted" else []
    return rec


COMMENT_BLOCK_RE = re.compile(
    r"(?:COMMENTS?|comments? were received from|The (?:department|agency|commission) received comments? from)"
    r"(.{0,900})", re.S | re.I,
)
_ORG_TOKEN = re.compile(r"\b((?:[A-Z][\w&.'-]*\s+){1,7}(?:Association|Coalition|Company|Center|Institute|Society|Council|Alliance|Foundation|Inc|LLC|Corporation|Board|University|Hospital|Group|Texas|Partners|Energy|Health))\b")


def parse_commenters(text: str) -> list[str]:
    """Named commenters from an adoption preamble (best-effort; the audit
    notes many adoptions receive none, and naming style varies by agency)."""
    m = COMMENT_BLOCK_RE.search(text)
    if not m:
        return []
    block = m.group(1)
    if re.search(r"did not receive any comments|no comments were received", block, re.I):
        return []
    names = [n.strip() for n in _ORG_TOKEN.findall(block)]
    return list(dict.fromkeys(n for n in names if 3 < len(n) < 90))[:25]


def _agency(text: str) -> str | None:
    """Agency name from the PART heading, falling back to the signature block
    that follows the TRD (name / title / agency / effective date)."""
    m = PART_AGENCY_RE.search(text)
    if m:
        return m.group(1).strip().title()
    m = SIG_AGENCY_RE.search(text)
    if m:
        # Last title-cased run in "Karen Ray Chief Counsel Texas Health and ..."
        tail = m.group(1).strip()
        parts = re.findall(r"((?:Texas|Department|Commission|Board|Office|State)[\w &',.\-]{3,70})", tail)
        if parts:
            return parts[-1].strip()
        return tail[:80] or None
    return None


def store_notice(conn: sqlite3.Connection, rec: dict, doc_id: str | None, issue_date: str | None) -> None:
    dbx.upsert(
        conn,
        "rule_action",
        {
            "trd": rec["trd"],
            "agency_raw": rec.get("agency"),
            "agency_org_id": None,
            "action_type": rec["action_type"],
            "tac_cite": rec.get("tac_cite"),
            "register_cite": rec.get("register_cite"),
            "issue_date": issue_date,
            "filed_date": rec.get("filed_date"),
            "comment_end": rec.get("comment_end"),
            "effective": rec.get("effective"),
            "adopts_trd": None,
            "proposal_pub_date": rec.get("proposal_pub_date"),
            "doc_id": doc_id,
        },
        ["trd"],
    )
    for cite in rec.get("authority", []):
        dbx.upsert(conn, "rule_authority", {"trd": rec["trd"], "statute_cite": cite},
                   ["trd", "statute_cite"], update_cols=[])
        dbx.add_edge(conn, "rule_action", rec["trd"], "authorized_by", "statute", cite,
                     "explicit", doc_id)
    for bill in rec.get("bills", []):
        dbx.add_edge(conn, "rule_action", rec["trd"], "implements", "bill", bill,
                     "explicit", doc_id)
    for name in rec.get("commenters", []):
        exists = conn.execute(
            "SELECT id FROM rule_commenter WHERE trd=? AND name_raw=?", (rec["trd"], name)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO rule_commenter (trd, name_raw, org_id, response) VALUES (?,?,?,?)",
                (rec["trd"], name, None, None),
            )
        dbx.add_edge(conn, "organization_name", name, "commented_on", "rule_action",
                     rec["trd"], "explicit", doc_id)


def section_action(path: str) -> str:
    # URLs arrive percent-encoded ("Adopted%20Rules"); match on the decoded form.
    low = unquote(path).lower()
    for key, action in SECTION_ACTIONS.items():
        if key in low:
            return action
    return "other"


@register
class RegisterConnector(Connector):
    name = "register"
    tier = 0
    cadence = "weekly_friday"

    def section_urls(self, toc_url: str = CURRENT_TOC) -> tuple[str, list[str]]:
        resp = fetcher().get(toc_url)
        resp.raise_for_status()
        html = resp.text
        m = re.search(r"<title>\s*Texas Register\s*(.*?)\s*</title>", html, re.S | re.I)
        issue_date = _WS.sub(" ", m.group(1)).strip() if m else None
        hrefs = re.findall(r'href\s*=\s*"([^"]*)"', html)
        files = sorted({h.split("#")[0] for h in hrefs if ".html" in h.lower()})
        # Paths contain literal spaces; encode without mangling separators.
        return issue_date, [urljoin(toc_url, quote(f, safe=":/")) for f in files]

    def ingest_section(self, conn: sqlite3.Connection, url: str, issue_date: str | None) -> dict:
        resp = fetcher().get(url)
        if resp.status_code != 200:
            return {"url": url, "status": resp.status_code, "notices": 0}
        action = section_action(url)
        doc_id = f"register:section:{url.rsplit('/archive/', 1)[-1]}"
        store_document(conn, doc_id=doc_id, source_family="register", content=resp.content,
                       url=url, doc_type=f"register_{action}", published_at=issue_date,
                       authority="A" if action == "adopted" else "B")
        notices = split_notices(resp.content)
        for n in notices:
            store_notice(conn, parse_notice(n, action, issue_date), doc_id, issue_date)
        conn.commit()
        return {"url": url, "status": 200, "notices": len(notices)}

    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        limit = int(kwargs.get("limit", 6))
        issue_date, urls = self.section_urls()
        rules = [u for u in urls if section_action(u) in ("proposed", "adopted", "withdrawn", "emergency")]
        results = [self.ingest_section(conn, u, issue_date) for u in rules[:limit]]
        return {
            "issue": issue_date,
            "sections": len(results),
            "notices": sum(r["notices"] for r in results),
            "rule_actions": conn.execute("SELECT COUNT(*) c FROM rule_action").fetchone()["c"],
        }

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        stats = self.incremental(conn, limit=2)
        auth = conn.execute("SELECT COUNT(*) c FROM rule_authority").fetchone()["c"]
        stats["authority_cites"] = auth
        ok = stats["notices"] >= 2 and auth >= 1
        return SmokeResult(ok=ok, detail=f"{stats['issue']}: {stats['notices']} notices, {auth} authority cites", stats=stats)
