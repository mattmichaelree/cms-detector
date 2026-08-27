"""TLO — Texas Legislature Online (capitol.texas.gov).

Reference connector: this module establishes the pattern every source module
follows (Connector subclass + register, parsers as pure functions over bytes,
document-store-first, edges with provenance). Spec: the audit deep dive
docs/texas-politics-audit/03-deep-dives/01-tlo.md.

Implemented here:
  * the ten public RSS feeds (verified live in the audit) → new-activity queue
  * BillLookup/History.aspx parser → bill, bill_action, bill_author,
    bill_subject, bill_companion rows + explicit edges
  * tlodocs document fetcher (per-version bill text)
Session codes are opaque TLO strings ('89R', '891'..'894') — never parsed
arithmetically (audit temporal trap #4).
"""

from __future__ import annotations

import re
import sqlite3
from html import unescape

import feedparser

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

BASE = "https://capitol.texas.gov"

RSS_FEEDS = {
    "todaysfiledhouse": "Today's filed House bills",
    "todaysfiledsenate": "Today's filed Senate bills",
    "todaysbilltext": "Today's bill text",
    "todaysfiscalnotes": "Today's fiscal notes",
    "todaysbillanalyses": "Today's bill analyses",
    "todaysbillspassed": "Today's passed bills",
    "upcomingmeetingshouse": "Upcoming House committee meetings",
    "upcomingmeetingssenate": "Upcoming Senate committee meetings",
    "upcomingcalendarshouse": "Upcoming House calendars",
    "upcomingcalendarssenate": "Upcoming Senate calendars",
}


def rss_url(feed: str) -> str:
    return f"{BASE}/MyTLO/RSS/RSS.aspx?Type={feed}"


def bill_id(session: str, bill: str) -> str:
    """'89R', 'HB 1' → '89R-HB1'."""
    return f"{session}-{bill.replace(' ', '').upper()}"


BILL_RE = re.compile(r"\b(HB|SB|HJR|SJR|HCR|SCR|HR|SR)\s*0*(\d+)\b", re.I)


def parse_rss(content: bytes) -> list[dict]:
    """Feed bytes → [{title, link, guid, published, bills:[('HB',1),...]}]."""
    parsed = feedparser.parse(content)
    out = []
    for e in parsed.entries:
        title = unescape(getattr(e, "title", "") or "")
        out.append(
            {
                "title": title,
                "link": getattr(e, "link", None),
                "guid": getattr(e, "id", None) or getattr(e, "link", None),
                "published": getattr(e, "published", None),
                "bills": [(m.group(1).upper(), int(m.group(2))) for m in BILL_RE.finditer(title)],
            }
        )
    return out


# --- History.aspx --------------------------------------------------------
_CAPTION_RE = re.compile(
    r"Caption(?:\s+Text)?:?\s*</[^>]+>\s*(?:<[^>]+>\s*)*([^<]{5,400})", re.I
)
_CELLSPLIT = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.I | re.S)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_FIELD_RE = re.compile(
    r"(?:<td[^>]*>|<span[^>]*>)\s*(Author|Coauthor|Sponsor|Cosponsor|Subjects|Companion)s?:?\s*"
    r"</[^>]+>\s*<td[^>]*>(.*?)</td>",
    re.I | re.S,
)
_DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")


def _strip(html: str) -> str:
    return unescape(_TAG_RE.sub(" ", html)).replace("\xa0", " ").strip()


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_history(content: bytes, session: str, bill: str) -> dict:
    """History.aspx HTML → {caption, authors, subjects, companions, actions}.

    TLO's HTML is semantically flat (audit: structure score 2/5); parsing keys
    on label text and table rows, not markup hierarchy, and tolerates absence.
    """
    html = content.decode("utf-8", errors="replace")
    result: dict = {"caption": None, "authors": [], "subjects": [], "companions": [], "actions": []}

    m = _CAPTION_RE.search(html)
    if m:
        result["caption"] = _norm_ws(_strip(m.group(1)))

    for label, value_html in _FIELD_RE.findall(html):
        value = _norm_ws(_strip(value_html))
        if not value:
            continue
        label = label.lower()
        if label in ("author", "coauthor", "sponsor", "cosponsor"):
            names = [n.strip() for n in re.split(r"\s*\|\s*|\s{2,}", value) if n.strip()]
            result["authors"] += [(label, n) for n in names]
        elif label == "subjects":
            for subj in re.findall(r"([^()]+?)\s*\((I\d{4})\)", value):
                result["subjects"].append((subj[1], _norm_ws(subj[0])))
            if not result["subjects"] and value:
                result["subjects"].append((None, value))
        elif label == "companion":
            for bm in BILL_RE.finditer(value):
                result["companions"].append(f"{bm.group(1).upper()}{bm.group(2)}")

    # Action rows: TLO renders the action table with Description/Comment/Date columns.
    seq = 0
    for row in _ROW_RE.findall(html):
        cells = [_norm_ws(_strip(c)) for c in _CELLSPLIT.findall(row)]
        if len(cells) < 2:
            continue
        dates = [c for c in cells if _DATE_RE.fullmatch(c or "")]
        desc = max(cells, key=len)
        if not dates or len(desc) < 4 or desc in dates:
            continue
        chamber = None
        first = cells[0].upper()
        if first in ("H", "S", "E", "G"):
            chamber = first
        seq += 1
        result["actions"].append(
            {"seq": seq, "date": dates[0], "chamber": chamber, "description": desc}
        )
    return result


def store_history(conn: sqlite3.Connection, session: str, bill: str, parsed: dict, doc_id: str) -> None:
    m = BILL_RE.search(bill)
    if not m:
        raise ValueError(f"unparseable bill designator: {bill!r}")
    bid = bill_id(session, bill)
    dbx.ensure_session(conn, session)
    dbx.upsert(
        conn,
        "bill",
        {
            "id": bid,
            "session_id": session,
            "bill_type": m.group(1).upper(),
            "number": int(m.group(2)),
            "caption": parsed.get("caption"),
        },
        ["id"],
    )
    for role, name in parsed["authors"]:
        dbx.upsert(
            conn,
            "bill_author",
            {"bill_id": bid, "name_raw": name, "role": role, "person_id": None},
            ["bill_id", "name_raw", "role"],
            update_cols=[],
        )
        dbx.add_edge(conn, "person_name", name, f"{role}_of", "bill", bid, "explicit", doc_id)
    for code, text in parsed["subjects"]:
        dbx.upsert(
            conn,
            "bill_subject",
            {"bill_id": bid, "subject_code": code, "subject_text": text},
            ["bill_id", "subject_text"],
            update_cols=[],
        )
    for comp in parsed["companions"]:
        dbx.upsert(
            conn,
            "bill_companion",
            {"bill_id": bid, "companion_id": comp},
            ["bill_id", "companion_id"],
            update_cols=[],
        )
    for a in parsed["actions"]:
        dbx.upsert(
            conn,
            "bill_action",
            {
                "bill_id": bid,
                "seq": a["seq"],
                "date": a["date"],
                "chamber": a["chamber"],
                "description": a["description"],
                "action_code": None,
                "journal_cite": None,
            },
            ["bill_id", "seq"],
        )


@register
class TLOConnector(Connector):
    name = "tlo"
    tier = 0
    cadence = "hourly_in_session"

    def history_url(self, session: str, bill: str) -> str:
        return f"{BASE}/BillLookup/History.aspx?LegSess={session}&Bill={bill.replace(' ', '')}"

    def ingest_bill(self, conn: sqlite3.Connection, session: str, bill: str) -> dict:
        url = self.history_url(session, bill)
        resp = fetcher().get(url)
        resp.raise_for_status()
        doc_id = f"tlo:history:{bill_id(session, bill)}"
        _, changed = store_document(
            conn,
            doc_id=doc_id,
            source_family="tlo",
            content=resp.content,
            url=url,
            doc_type="bill_history",
            session_id=session,
            authority="A",
        )
        parsed = parse_history(resp.content, session, bill)
        store_history(conn, session, bill, parsed, doc_id)
        conn.commit()
        return {"bill": bill_id(session, bill), "changed": changed, "actions": len(parsed["actions"])}

    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """Poll every RSS feed; store items; return the mentioned-bill set."""
        seen: set[str] = set()
        items = 0
        for feed in RSS_FEEDS:
            resp = fetcher().get(rss_url(feed))
            if resp.status_code != 200:
                continue
            store_document(
                conn,
                doc_id=f"tlo:rss:{feed}",
                source_family="tlo",
                content=resp.content,
                url=rss_url(feed),
                doc_type="rss",
                authority="A",
            )
            for entry in parse_rss(resp.content):
                items += 1
                for btype, num in entry["bills"]:
                    seen.add(f"{btype}{num}")
        conn.commit()
        return {"feeds": len(RSS_FEEDS), "items": items, "bills_mentioned": sorted(seen)[:50]}

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        r = self.ingest_bill(conn, "89R", "HB1")
        ok = r["actions"] > 0
        return SmokeResult(ok=ok, detail=f"89R HB1 history: {r['actions']} actions", stats=r)
