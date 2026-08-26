"""Legislator press releases and official statements — and the turnover archive.

Spec: docs/texas-politics-audit/03-deep-dives/16-legislator-communications.md.

Authority class **C**: these are official self-advocacy. A statement may be
quoted verbatim with its date and URL; it must never be presented as an
objective account of a bill or as a prediction of how its author will vote.

**The source destroys its own history, so capture timing is the product.**
house.texas.gov member pages are keyed by district number
(``/members/87``) and that URL is an *alias to whoever currently holds the
seat*. When District 87 changed hands in Jan 2025, the page stopped serving
Rep. Four Price's newsletters and media and started serving Rep. Caroline
Fairly's; Price's content was not moved, redirected, or archived — it is
recoverable only from the Wayback Machine. The same URL silently became a
different person's content, which is a misinformation mechanism as much as a
data-loss one.

:func:`StatementsConnector.archive_member_pages` is the countermeasure and the
single highest-value scheduled job in this family. **It is meant to run on
election results** — the night a seat is called, before the House rebuilds the
page — and again on the eve of each swearing-in. Every district's page is
stored under one stable ``document`` id, so the docstore's content-addressed
versioning turns the overwrite into an explicit two-version history instead of
silent loss: version 1 is the outgoing member's page, version 2 the
successor's. ``schedule.yaml`` lists ``turnover_archival`` under ``per_event``
for exactly this reason.

Coverage here follows the audit's finding that the **Senate is materially
deeper and more crawlable than the House**: a general newsroom with a year
dropdown back to 1997, per-senator press rooms with compound native IDs
(``7-20250530a`` = district + date + intraday letter — a real primary key,
which the House lacks entirely), plus the Lt. Governor's WordPress newsroom.
No RSS exists anywhere in this family except the Comptroller, so every path
here is a listing parse.

Every row carries both ``published`` (the source's date) and ``captured`` (when
we saw it), because on these sites those two facts diverge and the divergence
is the story.
"""

from __future__ import annotations

import hashlib
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

SENATE = "https://senate.texas.gov/"
SENATE_NEWSROOM = SENATE + "newsroom.php"
SENATE_PRESSROOM = SENATE + "pressroom.php?d={district}"
LTGOV_NEWS = "https://www.ltgov.texas.gov/news/"
HOUSE_MEMBER = "https://house.texas.gov/members/{district}"

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(html: str) -> str:
    return _WS.sub(" ", unescape(_TAG.sub(" ", html))).strip()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ parsing
# Both Senate listings render one release as:
#   <p class="pr"><span class="sm">08/19/2026</span> <img ...><br>
#     <a aria-label="TITLE, 08/19/2026" href="press.php?id=7-20260819a&ref=1">TITLE</a></p>
# HTML releases link to press.php/news.php; older ones link straight to a PDF
# under members/d07/press/en/p20150409a.pdf.
_PR_BLOCK = re.compile(r'<p class="pr">(.*?)</p>', re.S | re.I)
_PR_DATE = re.compile(r'<span class="sm">\s*(\d{2}/\d{2}/\d{4})\s*</span>', re.I)
_PR_LINK = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_PGTITLE = re.compile(r'<h1 class="pgtitle">(.*?)</h1>', re.S | re.I)
# press.php?id=7-20260819a  /  news.php?id=20250904a
_ID_PARAM = re.compile(r"[?&]id=([^&\"']+)", re.I)
# members/d07/press/en/p20150409a.pdf -> district 7, 20150409a
_PDF_ID = re.compile(r"members/d(\d{2})/press/\w+/p(\d{8}[a-z]?)\.", re.I)


@dataclass(frozen=True)
class Statement:
    native_id: str | None
    title: str
    published: str | None
    url: str
    office: str
    actor_raw: str | None
    kind: str  # 'html' | 'pdf'


def _iso_mdy(value: str) -> str | None:
    try:
        return datetime.strptime(value, "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def senate_actor(content: bytes) -> str | None:
    """'Press Room: Senator Paul   Bettencourt — District 7' -> the senator's name."""
    m = _PGTITLE.search(content.decode("utf-8", errors="replace"))
    if not m:
        return None
    text = strip_html(m.group(1))
    text = re.sub(r"^(Press Room|News Archives?|Newsroom)\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"\s*[—-]\s*District\s*\d+\s*$", "", text)
    return _WS.sub(" ", text).strip() or None


def parse_senate_listing(content: bytes, *, district: int | None = None) -> list[Statement]:
    """Senate newsroom or per-senator press room HTML -> statements. Pure.

    One parser serves both because senate.texas.gov renders them with the same
    ``<p class="pr">`` markup; only the link target and the presence of a
    district prefix in the native ID differ.
    """
    html = content.decode("utf-8", errors="replace")
    if district:
        office, actor = f"senate_d{district}", senate_actor(content)
    else:
        # The general newsroom's <h1> is "Texas Senate News Archives" — a page
        # label, not an actor. The institution is the actor for these items.
        office, actor = "senate", "The Texas Senate"
    out: list[Statement] = []
    seen: set[str] = set()
    for block in _PR_BLOCK.findall(html):
        date_m = _PR_DATE.search(block)
        link_m = _PR_LINK.search(block)
        if not link_m:
            continue
        href = unescape(link_m.group(1))
        title = strip_html(link_m.group(2))
        if not title:
            continue
        url = urljoin(SENATE, href)
        pdf = _PDF_ID.search(href)
        if pdf:
            # No id parameter on the PDF form; the compound ID is still fully
            # determined by the path (district + date + intraday letter).
            native = f"{int(pdf.group(1))}-{pdf.group(2)}"
            kind = "pdf"
        else:
            idm = _ID_PARAM.search(href)
            native = idm.group(1) if idm else None
            kind = "html"
        if url in seen:
            continue
        seen.add(url)
        out.append(
            Statement(
                native_id=native,
                title=title,
                published=_iso_mdy(date_m.group(1)) if date_m else None,
                url=url,
                office=office,
                actor_raw=actor,
                kind=kind,
            )
        )
    return out


# The Lt. Governor's newsroom is WordPress with date-path permalinks:
#   <article id="post-8262" ...>
#     <h3 class="h2 entry-title"><a href="https://www.ltgov.texas.gov/2026/07/27/slug/">TITLE</a>
#     <time class="updated entry-time" datetime="2026-07-27">
_ARTICLE = re.compile(r'<article\b[^>]*id="post-(\d+)"[^>]*>(.*?)</article>', re.S | re.I)
_ENTRY_TITLE = re.compile(r'<[^>]*class="[^"]*entry-title[^"]*"[^>]*>\s*<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_ENTRY_TIME = re.compile(r'<time\b[^>]*datetime="([^"]+)"', re.I)
_LTGOV_PERMALINK = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")


def parse_ltgov_listing(content: bytes) -> list[Statement]:
    """ltgov.texas.gov/news/ HTML -> statements. Pure."""
    html = content.decode("utf-8", errors="replace")
    out: list[Statement] = []
    for post_id, body in _ARTICLE.findall(html):
        t = _ENTRY_TITLE.search(body)
        if not t:
            continue
        url = unescape(t.group(1))
        title = strip_html(t.group(2))
        time_m = _ENTRY_TIME.search(body)
        published = time_m.group(1)[:10] if time_m else None
        if not published:
            # The permalink itself carries the publication date.
            pm = _LTGOV_PERMALINK.search(url)
            published = "-".join(pm.groups()) if pm else None
        out.append(
            Statement(
                native_id=f"post-{post_id}",
                title=title,
                published=published,
                url=url,
                office="lt_governor",
                actor_raw="Lt. Gov. Dan Patrick",
                kind="html",
            )
        )
    return out


_HOUSE_TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)


def house_member_name(content: bytes) -> str | None:
    """'... Website for Rep. Fairly, Caroline.' -> 'Fairly, Caroline'.

    The name is what makes an archived snapshot legible later: it is the only
    thing that says *whose* District 87 page this version was.
    """
    m = _HOUSE_TITLE.search(content.decode("utf-8", errors="replace"))
    if not m:
        return None
    text = strip_html(m.group(1))
    nm = re.search(r"for\s+(?:Rep\.|Representative|Speaker)\s+(.+?)\s*\.?\s*$", text, re.I)
    return nm.group(1).strip() if nm else None


# ------------------------------------------------------------------ storage
def statement_id(office: str, native_id: str | None, url: str, kind: str = "html") -> str:
    """Native compound ID where the source gives one ('senate_d7:7-20250530a');
    a URL hash otherwise, because the House publishes no stable release ID and
    a tested one was already dead.

    The compound ID is *not* unique across formats — verified: District 7
    publishes both ``press.php?id=7-20220302a`` (a release) and
    ``members/d07/press/en/p20220302a.pdf`` (a letter to the Lt. Governor the
    same day). They are different documents sharing an intraday letter, so the
    PDF namespace is suffixed rather than allowed to overwrite the HTML row.
    """
    key = native_id or hashlib.sha256(url.encode()).hexdigest()[:16]
    if native_id and kind == "pdf":
        key = f"{key}.pdf"
    return f"{office}:{key}"


def store_statement(
    conn: sqlite3.Connection,
    st: Statement,
    doc_id: str | None = None,
    captured: str | None = None,
) -> str:
    sid = statement_id(st.office, st.native_id, st.url, st.kind)
    dbx.upsert(
        conn,
        "statement",
        {
            "id": sid,
            "office": st.office,
            "actor_raw": st.actor_raw,
            "person_id": None,  # resolved later by the spine; never guessed here
            "title": st.title,
            "published": st.published,
            "captured": captured or _now(),
            "url": st.url,
            "doc_id": doc_id,
        },
        ["id"],
        # captured is the first-seen timestamp; re-crawling must not rewrite it.
        update_cols=["office", "actor_raw", "title", "published", "url", "doc_id"],
    )
    if st.actor_raw:
        dbx.add_edge(conn, "office", st.office, "issued", "statement", sid, "explicit", doc_id)
    return sid


# ---------------------------------------------------------------- connector
@register
class StatementsConnector(Connector):
    """Senate + Lt. Gov. listings, plus the House turnover archive."""

    name = "statements"
    tier = 1
    cadence = "daily"

    DDL = """
    -- One row per *version* of a district's member page, not per poll: the
    -- unit that matters is "which occupant did this URL serve, and when did we
    -- first see that". captured/changed record the first sighting of the
    -- version; last_seen advances on every poll.
    CREATE TABLE IF NOT EXISTS member_page_snapshot (
        district    TEXT NOT NULL,
        chamber     TEXT NOT NULL,
        member_raw  TEXT,
        doc_id      TEXT NOT NULL,
        version_no  INTEGER NOT NULL,
        captured    TEXT NOT NULL,
        last_seen   TEXT NOT NULL,
        changed     INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (chamber, district, version_no)
    );
    CREATE INDEX IF NOT EXISTS idx_statement_office ON statement(office, published);
    """

    # ------------------------------------------------------------- listings
    def ingest_senate_pressroom(self, conn: sqlite3.Connection, district: int) -> dict:
        url = SENATE_PRESSROOM.format(district=district)
        resp = fetcher().get(url)
        resp.raise_for_status()
        doc_id = f"statements:senate:pressroom:{district}"
        store_document(
            conn, doc_id=doc_id, source_family="statements", content=resp.content,
            url=url, doc_type="pressroom_listing", authority="C",
        )
        captured = _now()
        items = parse_senate_listing(resp.content, district=district)
        for st in items:
            store_statement(conn, st, doc_id, captured)
        conn.commit()
        actor = items[0].actor_raw if items else None
        return {"office": f"senate_d{district}", "actor": actor, "statements": len(items),
                "with_dates": sum(1 for s in items if s.published)}

    def ingest_senate_newsroom(self, conn: sqlite3.Connection, year: int | None = None) -> dict:
        url = SENATE_NEWSROOM if year is None else f"{SENATE_NEWSROOM}?yr={year}&lang=en"
        resp = fetcher().get(url)
        resp.raise_for_status()
        doc_id = f"statements:senate:newsroom:{year or 'current'}"
        store_document(
            conn, doc_id=doc_id, source_family="statements", content=resp.content,
            url=url, doc_type="newsroom_listing", authority="C",
        )
        captured = _now()
        items = parse_senate_listing(resp.content)
        for st in items:
            store_statement(conn, st, doc_id, captured)
        conn.commit()
        return {"office": "senate", "year": year, "statements": len(items),
                "with_dates": sum(1 for s in items if s.published)}

    def ingest_ltgov(self, conn: sqlite3.Connection) -> dict:
        resp = fetcher().get(LTGOV_NEWS)
        resp.raise_for_status()
        doc_id = "statements:ltgov:news"
        store_document(
            conn, doc_id=doc_id, source_family="statements", content=resp.content,
            url=LTGOV_NEWS, doc_type="newsroom_listing", authority="C",
        )
        captured = _now()
        items = parse_ltgov_listing(resp.content)
        for st in items:
            store_statement(conn, st, doc_id, captured)
        conn.commit()
        return {"office": "lt_governor", "statements": len(items),
                "with_dates": sum(1 for s in items if s.published)}

    # ----------------------------------------------- the turnover-archival job
    def archive_member_pages(
        self, conn: sqlite3.Connection, districts, chamber: str = "house"
    ) -> dict:
        """Snapshot House member pages before the seat's URL is reassigned.

        Run this **on election results** (and again just before a swearing-in):
        house.texas.gov/members/{district} is an alias to the current
        officeholder, and the outgoing member's newsletters and media vanish
        the moment the site rebuilds. One stable ``document`` id per district
        means the docstore appends a new version instead of overwriting, so the
        turnover is preserved as history rather than lost.

        The district's occupancy is also written as an explicit
        ``district -> currently_held_by -> person_name`` edge per snapshot;
        because edges are additive, a changed name leaves both edges in place
        and the turnover becomes queryable.
        """
        results = []
        for d in districts:
            url = HOUSE_MEMBER.format(district=d)
            resp = fetcher().get(url)
            if resp.status_code != 200:
                results.append({"district": str(d), "status": resp.status_code, "changed": False})
                continue
            doc_id = f"statements:{chamber}:district:{d}"
            _, changed = store_document(
                conn, doc_id=doc_id, source_family="statements", content=resp.content,
                url=url, doc_type="member_page", authority="C",
                etag=resp.headers.get("ETag"), last_modified=resp.headers.get("Last-Modified"),
            )
            results.append(self._record_snapshot(conn, chamber, str(d), resp.content, doc_id, changed))
        conn.commit()
        return {
            "chamber": chamber,
            "districts": len(results),
            "captured": len([r for r in results if r.get("doc_id")]),
            "changed": sum(1 for r in results if r.get("changed")),
            "snapshots": results,
        }

    @staticmethod
    def _record_snapshot(
        conn: sqlite3.Connection, chamber: str, district: str, content: bytes,
        doc_id: str, changed: bool,
    ) -> dict:
        member = house_member_name(content)
        version = conn.execute(
            "SELECT COALESCE(MAX(version_no),0) n FROM document_version WHERE document_id=?",
            (doc_id,),
        ).fetchone()["n"]
        captured = _now()
        dbx.upsert(
            conn,
            "member_page_snapshot",
            {
                "district": district, "chamber": chamber, "member_raw": member,
                "doc_id": doc_id, "version_no": version, "captured": captured,
                "last_seen": captured, "changed": 1 if changed else 0,
            },
            ["chamber", "district", "version_no"],
            update_cols=["member_raw", "doc_id", "last_seen"],
        )
        if member:
            dbx.add_edge(
                conn, "district", f"TX-{chamber}-{district}", "currently_held_by",
                "person_name", member, "explicit", doc_id,
            )
        return {"district": district, "member": member, "doc_id": doc_id,
                "version_no": version, "changed": changed, "captured": captured}

    # ------------------------------------------------------------ lifecycle
    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        districts = kwargs.get("districts") or [7]
        results = [self.ingest_senate_pressroom(conn, d) for d in districts]
        results.append(self.ingest_senate_newsroom(conn))
        results.append(self.ingest_ltgov(conn))
        return {
            "sources": results,
            "statements": conn.execute("SELECT COUNT(*) c FROM statement").fetchone()["c"],
        }

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """One live request: a single senator's press room."""
        stats = self.ingest_senate_pressroom(conn, 7)
        dated = conn.execute(
            "SELECT COUNT(*) c FROM statement WHERE published IS NOT NULL AND captured IS NOT NULL"
        ).fetchone()["c"]
        native = conn.execute(
            "SELECT COUNT(*) c FROM statement WHERE id LIKE 'senate_d7:7-%'"
        ).fetchone()["c"]
        stats.update(dated=dated, native_ids=native)
        ok = stats["statements"] >= 5 and dated >= 5
        return SmokeResult(
            ok=ok,
            detail=f"{stats['actor']}: {stats['statements']} statements, {dated} dated, "
                   f"{native} with native compound IDs",
            stats=stats,
        )


__all__ = [
    "LTGOV_NEWS",
    "SENATE_NEWSROOM",
    "SENATE_PRESSROOM",
    "Statement",
    "StatementsConnector",
    "house_member_name",
    "parse_ltgov_listing",
    "parse_senate_listing",
    "senate_actor",
    "statement_id",
    "store_statement",
]
