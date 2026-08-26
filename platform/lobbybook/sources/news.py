"""Texas political news — feeds, sitemap diffing, and the licensing gate.

Spec: docs/texas-politics-audit/03-deep-dives/18-news.md.

Three audit findings shape this module.

**1. Copyright is a code-level constraint, not a policy document.**  The audit's
rule is blunt: store full text *only* where a republish license exists (the
Texas Tribune's CC-style grant), and for everyone else store
headline + URL + published date + byline and link out.  That rule lives in
:data:`OUTLETS` as a per-outlet :class:`OutletPolicy` with a
``full_text_licensed`` flag, and it is enforced, not merely documented:
:func:`news_row` cannot emit body text for any outlet, and
:func:`store_article_text` raises :class:`LicenseError` before any bytes reach
the docstore for an unlicensed outlet.  ``news_item.full_text_licensed``
mirrors the flag so a downstream consumer can tell licensed rows from
link-out stubs without re-deriving the policy.

**2. One outlet is off-limits by its own robots policy.**  thetexan.news
disallows essentially every named AI/LLM crawler (ClaudeBot, GPTBot, CCBot,
anthropic-ai, Google-Extended, Bytespider…) while allowing search crawlers.
It is present in :data:`OUTLETS` with ``blocked_by_robots=True`` so the
platform *knows about* the outlet — for attribution, for a future licensing
conversation — while every ingest path refuses to fetch it.  The audit's
instruction is to resolve that with the publisher, not to route around it.

**3. Outlet authority is scored per outlet, never per family.**  Texas
Scorecard is organizationally the news arm of the Empower Texans Foundation;
its policy row carries ``publisher`` and ``advocacy_linkage`` so the
attribution string can disclose that.  ``authority_class`` is an editorial
judgment and is marked as such.

Ingestion shape: an RSS listener for the Tribune (hourly, the one outlet with
a verified feed) plus a generic sitemap-diff crawler (:func:`sitemap_items`)
for outlets that publish sitemaps but no feed.  Entity tagging is a pure
NER-ish pass over headline+summary that emits ``news_item -> discusses ->
bill`` edges with provenance ``inferred`` — never ``explicit``: the story did
not declare the link, we guessed it.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from zoneinfo import ZoneInfo

import feedparser

from lobbybook.core import db as dbx
from lobbybook.core.docstore import load_latest, store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

# Story URLs are minted from a Central-time date path; pubDate is UTC.
CENTRAL = ZoneInfo("America/Chicago")


class LicenseError(RuntimeError):
    """Refused: the outlet has no republish license, so its body text must not
    be stored. Headline + URL + date + byline are the only permitted fields."""


# --------------------------------------------------------------- outlet policy
@dataclass(frozen=True)
class OutletPolicy:
    """What we are allowed to do with one outlet, and how to attribute it."""

    key: str
    name: str
    #: A/B/C/D/E per the audit. E = journalism. Editorial judgment, per outlet.
    authority_class: str
    #: True only where a republish grant is confirmed. Gates full-text storage.
    full_text_licensed: bool
    license_note: str
    #: True where the outlet's robots.txt names AI crawlers and disallows them.
    blocked_by_robots: bool = False
    rss: str | None = None
    sitemap: str | None = None
    #: Corporate parent, where disclosing it changes how a reader weighs the story.
    publisher: str | None = None
    advocacy_linkage: str | None = None

    def attribution(self) -> str:
        if self.publisher:
            return f"{self.name}, published by {self.publisher}"
        return self.name

    @property
    def ingestable(self) -> bool:
        return not self.blocked_by_robots


OUTLETS: dict[str, OutletPolicy] = {
    "texas_tribune": OutletPolicy(
        key="texas_tribune",
        name="The Texas Tribune",
        authority_class="E",
        full_text_licensed=True,
        license_note=(
            "CC-style republish grant: free republication with canonical URL and the "
            "Tribune's tracking pixel. The only outlet in this family cleared for "
            "full-text storage."
        ),
        rss="https://feeds.texastribune.org/feeds/main/",
        sitemap="https://www.texastribune.org/sitemap.xml",
    ),
    "texas_scorecard": OutletPolicy(
        key="texas_scorecard",
        name="Texas Scorecard",
        # Presents as news; organizationally an advocacy arm. Score per outlet,
        # never per family, and disclose the linkage in the attribution string.
        authority_class="C-behind-E",
        full_text_licensed=False,
        license_note="No republish grant; standard all-rights-reserved WordPress site.",
        sitemap="https://texasscorecard.com/sitemap_index.xml",
        publisher="the Empower Texans Foundation",
        advocacy_linkage="501(c)(3) foundation linked to an affiliated (c)(4) and PAC",
    ),
    "the_texan": OutletPolicy(
        key="the_texan",
        name="The Texan",
        authority_class="E",
        full_text_licensed=False,
        license_note=(
            "No republish grant, and irrelevant while the robots ban stands: "
            "resolve with the publisher, do not route around it."
        ),
        # thetexan.news/robots.txt names and disallows AI/LLM crawlers
        # (ClaudeBot, Claude-Web, GPTBot, CCBot, anthropic-ai, Google-Extended,
        # Bytespider, PerplexityBot, ...) while allowing search crawlers.
        # Year-sharded TownNews sitemaps exist; we deliberately do not wire them.
        blocked_by_robots=True,
        sitemap=None,
    ),
    "texas_monthly": OutletPolicy(
        key="texas_monthly",
        name="Texas Monthly",
        authority_class="E",
        full_text_licensed=False,
        license_note="Paywalled; every fetch in the audit returned 403. Metadata + link only.",
    ),
    "quorum_report": OutletPolicy(
        key="quorum_report",
        name="Quorum Report",
        authority_class="E",
        full_text_licensed=False,
        license_note="$325/yr subscription tipsheet. Subscriber access is not a republish right.",
    ),
    "capitol_inside": OutletPolicy(
        key="capitol_inside",
        name="Capitol Inside",
        authority_class="E",
        full_text_licensed=False,
        license_note="Subscription insider publication. Metadata + link only.",
    ),
    "texas_observer": OutletPolicy(
        key="texas_observer",
        name="The Texas Observer",
        authority_class="E",
        full_text_licensed=False,
        license_note="No republish grant. robots.txt sets crawl-delay 10 — throttle hard.",
        sitemap="https://www.texasobserver.org/sitemap_index.xml",
    ),
    "dallas_morning_news": OutletPolicy(
        key="dallas_morning_news",
        name="The Dallas Morning News",
        authority_class="E",
        full_text_licensed=False,
        license_note="Metro daily, paywalled. Headline + URL + date + byline only.",
    ),
    "houston_chronicle": OutletPolicy(
        key="houston_chronicle",
        name="Houston Chronicle",
        authority_class="E",
        full_text_licensed=False,
        license_note="Metro daily, paywalled. Headline + URL + date + byline only.",
    ),
    "austin_american_statesman": OutletPolicy(
        key="austin_american_statesman",
        name="Austin American-Statesman",
        authority_class="E",
        full_text_licensed=False,
        license_note="Metro daily, paywalled. Headline + URL + date + byline only.",
    ),
    "kut": OutletPolicy(
        key="kut",
        name="KUT News",
        authority_class="E",
        full_text_licensed=False,
        license_note="Public radio; no blanket republish grant confirmed. Metadata + link only.",
    ),
}


def policy(outlet_key: str) -> OutletPolicy:
    try:
        return OUTLETS[outlet_key]
    except KeyError:
        raise KeyError(
            f"unknown outlet {outlet_key!r}; add an OutletPolicy before ingesting it"
        ) from None


def licensed_outlets() -> list[str]:
    return sorted(k for k, p in OUTLETS.items() if p.full_text_licensed)


def blocked_outlets() -> list[str]:
    return sorted(k for k, p in OUTLETS.items() if p.blocked_by_robots)


# ------------------------------------------------------------------- parsing
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(html: str) -> str:
    return _WS.sub(" ", unescape(_TAG.sub(" ", html))).strip()


def _iso(struct) -> str | None:
    if not struct:
        return None
    return datetime(*struct[:6], tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# The feed's <link> is a FeedPress click-tracking redirect whose final path
# segment is the story slug; the story's own permalink is
# /<yyyy>/<mm>/<dd>/<slug>/ on Central-time dates. Resolving it locally keeps
# the natural dedup key (outlet, canonical URL) stable without a HEAD per item.
_FEEDPRESS = re.compile(r"^https?://feeds\.texastribune\.org/link/\d+/\d+/(?P<slug>[^/?#]+)/?$")


def canonical_tribune_url(link: str, published_iso: str | None) -> str:
    """Feed redirect link -> texastribune.org permalink. Derived, not fetched."""
    m = _FEEDPRESS.match(link or "")
    if not m or not published_iso:
        return link
    try:
        when = datetime.strptime(published_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return link
    local = when.astimezone(CENTRAL)
    return f"https://www.texastribune.org/{local:%Y/%m/%d}/{m.group('slug')}/"


def parse_tribune_feed(content: bytes) -> list[dict]:
    """RSS 2.0 bytes -> one dict per story. Pure; no network, no database.

    ``summary`` is carried because the Tribune is licensed; callers for other
    outlets never see it (there is no other RSS source in this family).
    """
    feed = feedparser.parse(content)
    items: list[dict] = []
    for e in feed.entries:
        published = _iso(e.get("published_parsed"))
        link = e.get("link") or ""
        items.append(
            {
                "outlet": "texas_tribune",
                "title": (e.get("title") or "").strip() or None,
                "feed_link": link,
                "url": canonical_tribune_url(link, published),
                "published": published,
                # dc:creator; the Tribune writes co-bylines as one string.
                "byline": (e.get("author") or "").strip() or None,
                "categories": [t.term for t in e.get("tags", []) if t.get("term")],
                "guid": e.get("id"),
                "post_id": e.get("post-id"),
                "summary": strip_html(e.get("summary") or "") or None,
            }
        )
    return items


@dataclass(frozen=True)
class SitemapEntry:
    loc: str
    lastmod: str | None


_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S | re.I)
_LASTMOD = re.compile(r"<lastmod>\s*(.*?)\s*</lastmod>", re.S | re.I)
_ENTRY = re.compile(r"<(?:url|sitemap)\b.*?</(?:url|sitemap)>", re.S | re.I)


def parse_sitemap(content: bytes) -> tuple[str, list[SitemapEntry]]:
    """Sitemap or sitemap index bytes -> (kind, entries).

    ``kind`` is ``'index'`` (entries are child sitemaps) or ``'urlset'``
    (entries are pages). Pure over bytes; regex rather than a DOM parse
    because these files run to hundreds of thousands of entries and only two
    child elements matter.
    """
    text = content.decode("utf-8", errors="replace")
    kind = "index" if re.search(r"<sitemapindex\b", text, re.I) else "urlset"
    entries: list[SitemapEntry] = []
    for block in _ENTRY.findall(text):
        loc = _LOC.search(block)
        if not loc:
            continue
        lm = _LASTMOD.search(block)
        entries.append(SitemapEntry(unescape(loc.group(1)), unescape(lm.group(1)) if lm else None))
    return kind, entries


# A WordPress/Yoast index mixes article shards with taxonomy and directory
# sitemaps, and the taxonomy ones are often the most recently touched — picking
# the newest child outright lands on category or cornerstone-directory pages
# rather than stories (verified against texasscorecard.com/sitemap_index.xml,
# where cornerstone-directory-sitemap.xml was the freshest entry).
_ARTICLE_SITEMAP = re.compile(r"/(?:post|article|news|story|stories)[-_]?sitemap(\d*)\.xml$", re.I)
_NOT_ARTICLES = re.compile(
    r"/(?:category|post_tag|tag|series|author|page|directory|cornerstone|"
    r"attachment|product|video)[-_a-z]*sitemap", re.I
)


def select_article_sitemap(entries: list[SitemapEntry]) -> SitemapEntry | None:
    """Pick the child sitemap most likely to hold the newest stories.

    Prefers a Google News sitemap where the CMS publishes one (it is the
    rolling recent-articles shard the audit names alongside the Tribune's RSS),
    then falls back to the freshest numbered post shard. Yoast stamps every
    shard with the same index-level lastmod, so ties break on the shard number
    — new posts land in the highest-numbered shard.
    """
    articles = [
        e for e in entries
        if _ARTICLE_SITEMAP.search(e.loc) and not _NOT_ARTICLES.search(e.loc)
    ]
    if not articles:
        return None
    google_news = [e for e in articles if "news-sitemap" in e.loc.lower()]
    pool = google_news or articles

    def rank(e: SitemapEntry) -> tuple[str, int]:
        m = _ARTICLE_SITEMAP.search(e.loc)
        shard = int(m.group(1)) if m and m.group(1) else 0
        return (e.lastmod or "", shard)

    return max(pool, key=rank)


def sitemap_items(url: str, *, conn: sqlite3.Connection | None = None,
                  outlet_key: str | None = None) -> list[SitemapEntry]:
    """Fetch one sitemap (or sitemap index) and return its (loc, lastmod) pairs.

    Generic across CMSs — verified against Yoast/WordPress output. When a
    connection is supplied the raw sitemap is archived first, so a later
    lastmod diff can be run against the bytes we actually saw.
    """
    resp = fetcher().get(url)
    resp.raise_for_status()
    if conn is not None:
        store_document(
            conn,
            doc_id=f"news:sitemap:{url}",
            source_family="news",
            content=resp.content,
            url=url,
            doc_type="sitemap",
            authority=OUTLETS[outlet_key].authority_class if outlet_key else None,
        )
        conn.commit()
    return parse_sitemap(resp.content)[1]


# ------------------------------------------------------------ entity tagging
# HB/SB/HJR/SJR (plus the concurrent/simple resolution forms, which show up in
# session coverage) either as an abbreviation or spelled out.
BILL_RE = re.compile(
    r"\b(H\.?B\.?|S\.?B\.?|H\.?J\.?R\.?|S\.?J\.?R\.?|H\.?C\.?R\.?|S\.?C\.?R\.?"
    r"|House Bill|Senate Bill|House Joint Resolution|Senate Joint Resolution)"
    r"\s*(?:No\.?\s*)?(\d{1,4})\b",
    re.I,
)
_BILL_TYPE = {
    "hb": "HB", "housebill": "HB",
    "sb": "SB", "senatebill": "SB",
    "hjr": "HJR", "housejointresolution": "HJR",
    "sjr": "SJR", "senatejointresolution": "SJR",
    "hcr": "HCR", "scr": "SCR",
}


def normalize_bill_ref(prefix: str, number: str) -> str | None:
    key = re.sub(r"[^a-z]", "", prefix.lower())
    kind = _BILL_TYPE.get(key)
    return f"{kind}{int(number)}" if kind else None


def legislator_surnames(conn: sqlite3.Connection) -> dict[str, str]:
    """surname -> person_id, from the spine's person table.

    Empty until the spine is loaded — tagging then degrades to bills only
    rather than guessing at names it cannot verify.
    """
    out: dict[str, str] = {}
    try:
        rows = conn.execute("SELECT id, canonical_name, sort_name FROM person").fetchall()
    except sqlite3.OperationalError:
        return out
    for r in rows:
        for candidate in (r["sort_name"], r["canonical_name"]):
            if not candidate:
                continue
            surname = candidate.split(",")[0].strip() if "," in candidate else candidate.split()[-1]
            # One-syllable common words ("King", "Bell") would over-fire at
            # length 3; require 4+ characters and alphabetic-only.
            if len(surname) >= 4 and surname.replace("-", "").replace("'", "").isalpha():
                out.setdefault(surname, r["id"])
            break
    return out


def extract_entities(text: str, surnames: dict[str, str] | None = None) -> dict:
    """Pure NER-ish pass over a headline + summary.

    Returns ``{"bills": [(ref, span)], "people": [(person_id, surname)]}``.
    Everything it finds is a guess about what a story is *about*: callers must
    record it with provenance ``inferred``.
    """
    bills: dict[str, str] = {}
    for m in BILL_RE.finditer(text or ""):
        ref = normalize_bill_ref(m.group(1), m.group(2))
        if ref:
            bills.setdefault(ref, m.group(0))
    people: dict[str, str] = {}
    for surname, pid in (surnames or {}).items():
        if re.search(rf"\b{re.escape(surname)}\b", text or ""):
            people.setdefault(pid, surname)
    return {
        "bills": sorted(bills.items()),
        "people": sorted(people.items()),
    }


# ------------------------------------------------------------------- storage
def news_row(item: dict, outlet_key: str, doc_id: str | None = None) -> dict:
    """The ONLY shape a news_item row may take.

    Headline, URL, published date, byline, categories. No body, no summary,
    no excerpt — for any outlet, licensed or not. The license flag decides
    whether the *artifact* may be archived (see :func:`store_article_text`),
    not whether the row grows extra columns.
    """
    p = policy(outlet_key)
    cats = item.get("categories") or []
    return {
        "url": item["url"],
        "outlet": p.name,
        "title": item.get("title"),
        "published": item.get("published"),
        "byline": item.get("byline"),
        "categories": "; ".join(cats) if cats else None,
        "full_text_licensed": 1 if p.full_text_licensed else 0,
        "doc_id": doc_id,
    }


def store_article_text(
    conn: sqlite3.Connection, outlet_key: str, url: str, content: bytes, **kw
) -> str:
    """Archive one article's bytes — permitted only for licensed outlets.

    This is the single door to the docstore for article bodies, so the
    copyright rule cannot be violated by a connector that forgets it.
    """
    p = policy(outlet_key)
    if p.blocked_by_robots:
        raise LicenseError(f"{p.name} disallows automated collection by robots.txt; do not fetch")
    if not p.full_text_licensed:
        raise LicenseError(
            f"{p.name} has no republish license ({p.license_note}); "
            "store headline + url + published + byline and link out"
        )
    doc_id = f"news:{outlet_key}:{hashlib.sha256(url.encode()).hexdigest()[:16]}"
    store_document(
        conn,
        doc_id=doc_id,
        source_family="news",
        content=content,
        url=url,
        doc_type="article",
        authority=p.authority_class,
        **kw,
    )
    return doc_id


def store_item(
    conn: sqlite3.Connection,
    item: dict,
    outlet_key: str,
    doc_id: str | None = None,
    surnames: dict[str, str] | None = None,
) -> dict:
    """Upsert one news_item plus its explicit and inferred edges."""
    row = news_row(item, outlet_key, doc_id)
    dbx.upsert(conn, "news_item", row, ["url"])
    p = policy(outlet_key)
    url = row["url"]
    dbx.add_edge(conn, "news_item", url, "published_by", "outlet", p.name, "explicit", doc_id)
    if row["byline"]:
        dbx.add_edge(
            conn, "news_item", url, "written_by", "reporter", row["byline"], "explicit", doc_id
        )
    for cat in (item.get("categories") or []):
        dbx.add_edge(conn, "news_item", url, "tagged", "category", cat, "explicit", doc_id)

    # Tagging reads the headline plus (where licensed) the summary. For an
    # unlicensed outlet only the headline exists, so tagging is thinner —
    # that is the correct trade, not a bug to work around.
    text = " ".join(filter(None, [row["title"], item.get("summary") if p.full_text_licensed else None]))
    tags = extract_entities(text, surnames)
    for ref, span in tags["bills"]:
        dbx.add_edge(
            conn, "news_item", url, "discusses", "bill", ref, "inferred", doc_id,
            confidence=0.6, span=span,
        )
    for pid, surname in tags["people"]:
        dbx.add_edge(
            conn, "news_item", url, "discusses", "person", pid, "inferred", doc_id,
            confidence=0.5, span=surname,
        )
    return {"url": url, "bills": len(tags["bills"]), "people": len(tags["people"])}


# ----------------------------------------------------------------- connector
@register
class NewsConnector(Connector):
    """Feed listener + sitemap-diff crawler, license-gated at every write."""

    name = "news"
    tier = 1
    cadence = "hourly"

    DDL = """
    -- Two watermarks, because they answer different questions.
    -- index_lastmod is the index's own stamp for this child sitemap: if it has
    -- not moved, the child need not be fetched at all.
    -- page_lastmod is the newest <lastmod> we have actually ingested a page
    -- for. Diffing against the index stamp instead would permanently skip
    -- every page whose lastmod sits just behind the index's.
    CREATE TABLE IF NOT EXISTS news_sitemap_state (
        outlet        TEXT NOT NULL,
        sitemap       TEXT NOT NULL,
        index_lastmod TEXT,
        page_lastmod  TEXT,
        seen_at       TEXT,
        PRIMARY KEY (outlet, sitemap)
    );
    CREATE INDEX IF NOT EXISTS idx_news_outlet ON news_item(outlet);
    """

    # ---------------------------------------------------------- RSS listener
    def ingest_feed(
        self, conn: sqlite3.Connection, outlet_key: str = "texas_tribune", limit: int | None = None
    ) -> dict:
        p = policy(outlet_key)
        if not p.ingestable:
            return {"outlet": outlet_key, "skipped": "blocked_by_robots", "items": 0}
        if not p.rss:
            return {"outlet": outlet_key, "skipped": "no_rss", "items": 0}
        resp = fetcher().get(p.rss)
        resp.raise_for_status()
        # Artifact first, parse second: the feed is a 20-item rolling window,
        # so an unarchived poll is a permanently lost hour of coverage.
        doc_id = f"news:{outlet_key}:feed"
        _, changed = store_document(
            conn,
            doc_id=doc_id,
            source_family="news",
            content=resp.content,
            url=p.rss,
            doc_type="rss",
            authority=p.authority_class,
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )
        items = parse_tribune_feed(resp.content)
        if limit:
            items = items[:limit]
        surnames = legislator_surnames(conn)
        stats = [store_item(conn, it, outlet_key, doc_id, surnames) for it in items]
        conn.commit()
        return {
            "outlet": outlet_key,
            "items": len(items),
            "feed_changed": changed,
            "bill_tags": sum(s["bills"] for s in stats),
            "person_tags": sum(s["people"] for s in stats),
        }

    # -------------------------------------------------- sitemap-diff crawler
    def ingest_sitemap(
        self, conn: sqlite3.Connection, outlet_key: str, limit: int = 25
    ) -> dict:
        """Poll an outlet's sitemap index, follow the most recently changed
        child sitemap, and record the newest URLs as metadata-only rows.

        No article is fetched: for every sitemap-only outlet in this family
        the license flag is False, so the URL, the lastmod date and the link
        are all we are entitled to keep.
        """
        p = policy(outlet_key)
        if not p.ingestable:
            # The Texan lands here. Skipping is the feature.
            return {"outlet": outlet_key, "skipped": "blocked_by_robots", "items": 0}
        if not p.sitemap:
            return {"outlet": outlet_key, "skipped": "no_sitemap", "items": 0}

        entries = sitemap_items(p.sitemap, conn=conn, outlet_key=outlet_key)
        newest = select_article_sitemap(entries)
        if newest is None:
            return {"outlet": outlet_key, "items": 0, "child_sitemaps": len(entries)}
        seen = conn.execute(
            "SELECT index_lastmod, page_lastmod FROM news_sitemap_state "
            "WHERE outlet=? AND sitemap=?",
            (outlet_key, newest.loc),
        ).fetchone()
        watermark = seen["page_lastmod"] if seen else None
        if seen and newest.lastmod and seen["index_lastmod"] == newest.lastmod:
            # The index says this shard has not changed since the last poll —
            # one request saved, and the politeness budget spent elsewhere.
            return {"outlet": outlet_key, "child_sitemaps": len(entries),
                    "sitemap": newest.loc, "items": 0, "unchanged": True,
                    "previous_lastmod": watermark}

        pages = sitemap_items(newest.loc, conn=conn, outlet_key=outlet_key)
        fresh = self.diff_sitemap(pages, watermark)
        backlog = max(0, len(fresh) - limit)
        # Catch up oldest-first. Taking the *newest* `limit` would push the
        # watermark past everything older in the same batch, and those pages
        # would never be collected — a silent hole exactly where a cold start
        # or an outage put one. Oldest-first walks the backlog forward and
        # converges; in steady state (a handful of new stories per poll) the
        # two orders are identical.
        batch = fresh[-limit:] if fresh else []
        for e in batch:
            store_item(
                conn,
                {"url": e.loc, "title": None, "published": e.lastmod, "categories": []},
                outlet_key,
            )
        if batch:
            watermark = max(filter(None, [watermark, batch[0].lastmod]))
        dbx.upsert(
            conn,
            "news_sitemap_state",
            {
                "outlet": outlet_key,
                "sitemap": newest.loc,
                # Hold the index stamp back while a backlog remains, so the
                # next poll does not short-circuit on "unchanged".
                "index_lastmod": None if backlog else newest.lastmod,
                "page_lastmod": watermark,
                "seen_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            ["outlet", "sitemap"],
        )
        conn.commit()
        return {
            "outlet": outlet_key,
            "child_sitemaps": len(entries),
            "sitemap": newest.loc,
            "pages": len(pages),
            "items": len(batch),
            "backlog": backlog,
            "unchanged": False,
            "previous_lastmod": seen["page_lastmod"] if seen else None,
        }

    @staticmethod
    def diff_sitemap(pages: list[SitemapEntry], since: str | None) -> list[SitemapEntry]:
        """Newest-first pages strictly newer than the last poll's watermark."""
        rows = [e for e in pages if e.lastmod]
        if since:
            rows = [e for e in rows if e.lastmod > since]
        return sorted(rows, key=lambda e: e.lastmod, reverse=True)

    @staticmethod
    def resolve_canonical(feed_link: str) -> str:
        """Follow one FeedPress redirect to the story's real permalink.

        :func:`canonical_tribune_url` derives that permalink locally (from the
        slug plus the Central-time publication date) so ingest costs one
        request per poll rather than one per story. This is the audit check
        that keeps the derivation honest — smoke runs it on a single item and
        reports whether derived and resolved agree.
        """
        return str(fetcher().get(feed_link).url)

    def headline_only(self, outlet_key: str, url: str) -> str | None:
        """Fetch an unlicensed outlet's page and keep the headline, nothing else.

        The response body is never handed to the docstore; it goes out of
        scope with this call. That is the difference between citing a story
        and republishing it.
        """
        p = policy(outlet_key)
        if not p.ingestable:
            raise LicenseError(f"{p.name} disallows automated collection by robots.txt")
        resp = fetcher().get(url)
        if resp.status_code != 200:
            return None
        return extract_headline(resp.text)

    # ------------------------------------------------------------- lifecycle
    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        outlets = kwargs.get("outlets") or ["texas_tribune", "texas_scorecard", "the_texan"]
        results = []
        for key in outlets:
            p = policy(key)
            if not p.ingestable:
                results.append({"outlet": key, "skipped": "blocked_by_robots", "items": 0})
            elif p.rss:
                results.append(self.ingest_feed(conn, key, limit=kwargs.get("limit")))
            else:
                results.append(self.ingest_sitemap(conn, key, limit=int(kwargs.get("limit") or 25)))
        return {
            "outlets": results,
            "news_items": conn.execute("SELECT COUNT(*) c FROM news_item").fetchone()["c"],
            "skipped": [r["outlet"] for r in results if r.get("skipped")],
        }

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """Two live requests: the Tribune feed, plus one redirect resolution
        that checks the locally derived canonical URL against the real one."""
        stats = self.ingest_feed(conn, "texas_tribune")
        rows = conn.execute(
            "SELECT COUNT(*) c FROM news_item WHERE title IS NOT NULL AND published IS NOT NULL"
        ).fetchone()["c"]
        counts = {
            r["outlet"]: r["c"]
            for r in conn.execute("SELECT outlet, COUNT(*) c FROM news_item GROUP BY outlet")
        }
        licensed = conn.execute(
            "SELECT COUNT(*) c FROM news_item WHERE full_text_licensed=1"
        ).fetchone()["c"]
        stats.update(outlet_counts=counts, dated_titled=rows, licensed_rows=licensed,
                     blocked=blocked_outlets())

        sample = conn.execute(
            "SELECT url FROM news_item WHERE outlet='The Texas Tribune' "
            "ORDER BY published DESC LIMIT 1"
        ).fetchone()
        if sample:
            archived = load_latest(conn, "news:texas_tribune:feed") or b""
            feed_link = next(
                (i["feed_link"] for i in parse_tribune_feed(archived)
                 if i["url"] == sample["url"]),
                None,
            )
            if feed_link:
                resolved = self.resolve_canonical(feed_link)
                stats["canonical_derived"] = sample["url"]
                stats["canonical_resolved"] = resolved
                stats["canonical_verified"] = resolved.rstrip("/") == sample["url"].rstrip("/")

        ok = rows >= 5
        return SmokeResult(
            ok=ok,
            detail=f"{rows} dated+titled items; outlets={counts}; "
                   f"{stats['bill_tags']} inferred bill tags; "
                   f"canonical_verified={stats.get('canonical_verified')}; "
                   f"blocked={blocked_outlets()}",
            stats=stats,
        )


_OG_TITLE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', re.I | re.S)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def extract_headline(html: str) -> str | None:
    """Headline only, from og:title or <title>. Deliberately cannot return body text."""
    for pat in (_OG_TITLE, _TITLE):
        m = pat.search(html or "")
        if m:
            title = unescape(_WS.sub(" ", m.group(1))).strip()
            if title:
                return title
    return None


__all__ = [
    "OUTLETS",
    "LicenseError",
    "NewsConnector",
    "OutletPolicy",
    "SitemapEntry",
    "blocked_outlets",
    "canonical_tribune_url",
    "extract_entities",
    "extract_headline",
    "licensed_outlets",
    "news_row",
    "parse_sitemap",
    "parse_tribune_feed",
    "select_article_sitemap",
    "policy",
    "sitemap_items",
    "store_article_text",
    "store_item",
]
