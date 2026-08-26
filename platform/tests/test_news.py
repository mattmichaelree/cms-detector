"""Offline assertions run against bytes captured live on 2026-08-26.

Everything asserted here is a real value from a real fetch: real Texas Tribune
headlines, bylines and RSS category tags; a real Texas Scorecard Yoast sitemap
index. The licensing and robots tests are the load-bearing ones — they prove
the audit's copyright and crawl-policy rules are enforced by code rather than
by good intentions.
"""

from __future__ import annotations

import pytest

from lobbybook.core.registry import get
from lobbybook.sources.news import (
    OUTLETS,
    LicenseError,
    NewsConnector,
    SitemapEntry,
    blocked_outlets,
    canonical_tribune_url,
    extract_entities,
    licensed_outlets,
    news_row,
    parse_sitemap,
    parse_tribune_feed,
    policy,
    select_article_sitemap,
    store_article_text,
    store_item,
)

FIRST_TITLE = (
    "Judge rejects Minnesota request to keep ICE officer jailed in extradition fight with Texas"
)


def _news(fixtures, name: str) -> bytes:
    return (fixtures / "news" / name).read_bytes()


def _feed(fixtures):
    return parse_tribune_feed(_news(fixtures, "tribune_main.xml"))


# ------------------------------------------------------------------ RSS feed
def test_tribune_feed_yields_titled_dated_bylined_items(fixtures):
    items = _feed(fixtures)
    assert len(items) == 20
    assert all(i["title"] and i["published"] for i in items)

    first = items[0]
    assert first["title"] == FIRST_TITLE
    # dc:creator — the Tribune writes a co-byline as one string.
    assert first["byline"] == "Alex Nguyen and Berenice Garcia"
    assert first["published"] == "2026-08-25T22:52:27Z"
    assert first["guid"] == "https://www.texastribune.org/?p=240861"
    assert first["post_id"] == "240861"


def test_rss_category_tags_survive_verbatim(fixtures):
    """The audit calls RSS categories free labels for issue classification, so
    they must arrive unmangled — including the person-name tags."""
    drag = next(i for i in _feed(fixtures) if "drag shows" in i["title"])
    assert drag["byline"] == "Ayden Runnels"
    assert drag["categories"] == [
        "Courts",
        "State Government",
        "Greg Abbott",
        "Ken Paxton",
        "Texas Legislature",
        "Well A Homepage",
    ]


def test_feed_link_is_resolved_to_the_canonical_permalink(fixtures):
    """<link> is a FeedPress click-tracking redirect; the dedup key the audit
    specifies is (outlet, canonical URL), so the permalink is derived locally
    rather than costing one redirect fetch per story."""
    first = _feed(fixtures)[0]
    assert first["feed_link"] == (
        "https://feeds.texastribune.org/link/16799/17428555/"
        "texas-minnesota-ice-officer-extradition-judge"
    )
    # Verified live: this redirect terminates at exactly this URL.
    assert first["url"] == (
        "https://www.texastribune.org/2026/08/25/"
        "texas-minnesota-ice-officer-extradition-judge/"
    )


def test_canonical_date_path_uses_central_not_utc(fixtures):
    """A story filed at 8pm Central is already the next UTC day; the permalink
    follows the site's Central timezone. NewsConnector.resolve_canonical is the
    live check that keeps this derivation honest (smoke runs it)."""
    link = _feed(fixtures)[0]["feed_link"]
    assert canonical_tribune_url(link, "2026-08-26T01:00:00Z").startswith(
        "https://www.texastribune.org/2026/08/25/"
    )
    # Nothing to derive from -> hand back the link untouched rather than guess.
    assert canonical_tribune_url(link, None) == link
    assert canonical_tribune_url("https://example.com/x", "2026-08-26T01:00:00Z") == (
        "https://example.com/x"
    )


# ------------------------------------------------------- licensing policy
def test_only_the_tribune_is_cleared_for_full_text():
    assert licensed_outlets() == ["texas_tribune"]
    assert policy("texas_tribune").full_text_licensed is True
    for key in ("texas_monthly", "quorum_report", "dallas_morning_news", "houston_chronicle"):
        assert policy(key).full_text_licensed is False, key


def test_unlicensed_outlet_body_text_is_never_stored(conn):
    """The audit's hard rule: for a paywalled outlet keep headline + url +
    published + byline and link out. Nothing else may be persisted."""
    body = b"<html><body><p>Paragraph one of a paywalled feature.</p></body></html>"
    with pytest.raises(LicenseError) as exc:
        store_article_text(conn, "texas_monthly", "https://www.texasmonthly.com/news/x/", body)
    assert "no republish license" in str(exc.value)
    # Nothing reached the docstore: no document row, no version, no blob.
    assert conn.execute("SELECT COUNT(*) c FROM document").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM document_version").fetchone()["c"] == 0

    item = {
        "url": "https://www.texasmonthly.com/news/x/",
        "title": "The Best and Worst Legislators of 2025",
        "published": "2025-07-01",
        "byline": "Texas Monthly Staff",
        "categories": ["Politics"],
        "summary": "Paragraph one of a paywalled feature.",
    }
    store_item(conn, item, "texas_monthly")
    row = dict(conn.execute("SELECT * FROM news_item").fetchone())
    assert row["full_text_licensed"] == 0
    assert row["title"] == "The Best and Worst Legislators of 2025"
    assert row["doc_id"] is None
    # The summary was offered and dropped; no column anywhere holds body text.
    assert not any(
        isinstance(v, str) and "Paragraph one" in v for v in row.values()
    ), row


def test_news_row_never_carries_body_text_even_when_licensed(fixtures):
    item = _feed(fixtures)[0]
    assert item["summary"]  # the Tribune feed does ship a description
    row = news_row(item, "texas_tribune")
    assert set(row) == {
        "url", "outlet", "title", "published", "byline", "categories",
        "full_text_licensed", "doc_id",
    }
    assert row["full_text_licensed"] == 1
    assert row["outlet"] == "The Texas Tribune"
    assert row["categories"] == "Immigration; Brownsville; Cameron County; Greg Abbott; " \
                                "U.S. Supreme Court; Well C Homepage"


def test_licensed_outlet_may_archive_the_artifact(conn):
    doc_id = store_article_text(
        conn, "texas_tribune", "https://www.texastribune.org/2026/08/25/x/", b"<html>body</html>"
    )
    stored = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
    assert stored["authority"] == "E" and stored["doc_type"] == "article"


def test_advocacy_linkage_is_disclosed_in_attribution():
    """Never assign class E by reputation: Scorecard is the news arm of the
    Empower Texans Foundation and the attribution string must say so."""
    p = policy("texas_scorecard")
    assert p.authority_class == "C-behind-E"
    assert p.attribution() == "Texas Scorecard, published by the Empower Texans Foundation"
    assert policy("texas_tribune").attribution() == "The Texas Tribune"


# ----------------------------------------------------------- robots policy
def test_the_texan_is_known_but_never_fetched(conn, monkeypatch):
    """thetexan.news robots.txt disallows ClaudeBot/GPTBot/CCBot/anthropic-ai
    by name. It stays in the policy table for attribution and a future
    licensing conversation, and every ingest path must skip it without
    issuing a request."""
    assert blocked_outlets() == ["the_texan"]
    assert OUTLETS["the_texan"].blocked_by_robots is True
    assert OUTLETS["the_texan"].sitemap is None

    def explode(*a, **k):
        raise AssertionError("the connector must not open a connection to a blocked outlet")

    monkeypatch.setattr("lobbybook.sources.news.fetcher", explode)
    c = NewsConnector()
    assert c.ingest_sitemap(conn, "the_texan")["skipped"] == "blocked_by_robots"
    assert c.ingest_feed(conn, "the_texan")["skipped"] == "blocked_by_robots"
    assert c.incremental(conn, outlets=["the_texan"])["skipped"] == ["the_texan"]
    assert conn.execute("SELECT COUNT(*) c FROM news_item").fetchone()["c"] == 0

    with pytest.raises(LicenseError, match="robots.txt"):
        store_article_text(conn, "the_texan", "https://thetexan.news/x/", b"body")


# --------------------------------------------------------- sitemap crawler
def test_sitemap_index_parses_to_loc_lastmod_pairs(fixtures):
    kind, entries = parse_sitemap(_news(fixtures, "scorecard_sitemap_index.xml"))
    assert kind == "index"
    assert len(entries) == 33
    assert entries[0] == SitemapEntry(
        "https://texasscorecard.com/post-sitemap.xml", "2026-08-26T00:05:46+00:00"
    )
    assert entries[-1].loc == "https://texasscorecard.com/news-sitemap.xml"


def test_urlset_sitemap_parses_and_ignores_image_children(fixtures):
    kind, entries = parse_sitemap(_news(fixtures, "scorecard_post_sitemap.xml"))
    assert kind == "urlset"
    assert len(entries) == 12
    # The first <url> block also contains an <image:loc>; only <loc> counts.
    assert entries[0] == SitemapEntry(
        "https://texasscorecard.com/state/suddenly-responsible/", "2006-12-01T10:54:02+00:00"
    )
    assert all(e.loc.startswith("https://texasscorecard.com/") for e in entries)


def test_sitemap_diff_returns_only_pages_newer_than_the_watermark(fixtures):
    _, entries = parse_sitemap(_news(fixtures, "scorecard_post_sitemap.xml"))
    fresh = NewsConnector.diff_sitemap(entries, "2006-12-06T14:37:45+00:00")
    assert [e.lastmod for e in fresh] == sorted(
        [e.lastmod for e in fresh], reverse=True
    )
    assert all(e.lastmod > "2006-12-06T14:37:45+00:00" for e in fresh)
    assert len(NewsConnector.diff_sitemap(entries, None)) == 12


def test_article_shard_is_chosen_over_fresher_taxonomy_sitemaps(fixtures):
    """The freshest child of Scorecard's real index is
    cornerstone-directory-sitemap.xml — taking the newest child outright lands
    on directory pages, not stories."""
    _, entries = parse_sitemap(_news(fixtures, "scorecard_sitemap_index.xml"))
    freshest = max(entries, key=lambda e: e.lastmod or "")
    assert freshest.loc.endswith("cornerstone-directory-sitemap.xml")

    chosen = select_article_sitemap(entries)
    # A Google News sitemap is the rolling recent-articles shard; prefer it.
    assert chosen.loc == "https://texasscorecard.com/news-sitemap.xml"

    # Without one, fall back to the highest-numbered post shard — Yoast stamps
    # every shard with the same index lastmod, so the number breaks the tie.
    no_news = [e for e in entries if "news-sitemap" not in e.loc]
    assert select_article_sitemap(no_news).loc == "https://texasscorecard.com/post-sitemap24.xml"
    assert select_article_sitemap([]) is None


def test_sitemap_crawl_walks_a_backlog_oldest_first_without_losing_pages(conn, fixtures):
    """A limited poll must not push the watermark past pages it did not take.
    Four polls at limit 5 drain a 12-page shard and then go quiet."""
    idx = _news(fixtures, "scorecard_sitemap_index.xml")
    shard = _news(fixtures, "scorecard_post_sitemap.xml")

    class _Resp:
        status_code = 200
        headers: dict = {}

        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

    def _get(_self, url, **kw):
        return _Resp(idx if url.endswith("sitemap_index.xml") else shard)

    import lobbybook.sources.news as news_mod

    original = news_mod.fetcher
    news_mod.fetcher = lambda: type("F", (), {"get": _get})()
    try:
        c = NewsConnector()
        seen = [c.ingest_sitemap(conn, "texas_scorecard", limit=5) for _ in range(4)]
    finally:
        news_mod.fetcher = original

    assert [r["items"] for r in seen] == [5, 5, 2, 0]
    assert [r.get("backlog") for r in seen] == [7, 2, 0, None]
    assert seen[-1]["unchanged"] is True  # index stamp unmoved -> shard not refetched

    urls = {r["url"] for r in conn.execute("SELECT url FROM news_item")}
    _, pages = parse_sitemap(shard)
    assert urls == {e.loc for e in pages}
    # Metadata only: an unlicensed outlet's rows carry no title from a sitemap
    # and no archived artifact.
    rows = conn.execute("SELECT * FROM news_item").fetchall()
    assert all(r["full_text_licensed"] == 0 and r["outlet"] == "Texas Scorecard" for r in rows)
    assert conn.execute(
        "SELECT COUNT(*) c FROM document WHERE doc_type='article'"
    ).fetchone()["c"] == 0


# ------------------------------------------------------------ entity tagging
def test_bill_references_are_extracted_in_every_written_form():
    # Real Texas headline forms, from the senate.texas.gov press-room fixture.
    tags = extract_entities(
        "First Use of Senate Bill 3 Flood Sirens Sound Across Kerr County; "
        "Senator Bettencourt Passes SB 762 and SJR 2, plus HB1 and House Joint Resolution 34"
    )
    assert dict(tags["bills"]) .keys() >= {"SB3", "SB762", "SJR2", "HB1", "HJR34"}
    assert dict(tags["bills"])["SB3"] == "Senate Bill 3"
    assert tags["people"] == []


def test_tagging_does_not_fire_on_bare_numbers_or_years():
    assert extract_entities("Texas added 3 seats in 2026 under Proposition 4")["bills"] == []


def test_legislator_surnames_match_only_when_the_spine_is_populated(conn):
    text = "Bettencourt filed the bill after Huffman objected."
    assert extract_entities(text, {})["people"] == []
    conn.execute(
        "INSERT INTO person (id, canonical_name, sort_name) VALUES (?,?,?)",
        ("ocd-person/1", "Paul Bettencourt", "Bettencourt, Paul"),
    )
    from lobbybook.sources.news import legislator_surnames

    names = legislator_surnames(conn)
    assert names == {"Bettencourt": "ocd-person/1"}
    assert extract_entities(text, names)["people"] == [("ocd-person/1", "Bettencourt")]


def test_bill_tags_are_stored_as_inferred_edges(conn):
    """A story mentioning a bill did not *declare* that link — NER did. The
    edge must therefore be 'inferred', never 'explicit', and carry the exact
    matched span so a reader can check the guess."""
    item = {
        "url": "https://senate.texas.gov/press.php?id=7-20260716a&ref=1",
        "title": "First Use of Senate Bill 3 Flood Sirens Sound Across Kerr County "
                 "as Hill Country Flooding Returns",
        "published": "2026-07-16",
        "byline": None,
        "categories": ["Texas Legislature"],
    }
    stats = store_item(conn, item, "texas_tribune")
    assert stats["bills"] == 1
    edge = conn.execute(
        "SELECT * FROM edge WHERE predicate='discusses' AND dst_type='bill'"
    ).fetchone()
    assert edge["dst_id"] == "SB3"
    assert edge["provenance"] == "inferred"
    assert edge["span"] == "Senate Bill 3"
    assert edge["src_id"] == item["url"]
    # The outlet and category links, by contrast, are stated by the source.
    provs = {
        r["predicate"]: r["provenance"]
        for r in conn.execute("SELECT predicate, provenance FROM edge")
    }
    assert provs["published_by"] == "explicit"
    assert provs["tagged"] == "explicit"


def test_full_feed_ingest_is_idempotent(conn, fixtures):
    from lobbybook.core.docstore import store_document
    from lobbybook.sources.news import legislator_surnames

    # Artifact before rows, exactly as the connector does it.
    doc_id, changed = store_document(
        conn, doc_id="news:texas_tribune:feed", source_family="news",
        content=_news(fixtures, "tribune_main.xml"),
        url="https://feeds.texastribune.org/feeds/main/", doc_type="rss", authority="E",
    )
    assert changed is True

    items = _feed(fixtures)
    names = legislator_surnames(conn)
    for _ in range(2):
        for it in items:
            store_item(conn, it, "texas_tribune", doc_id, names)
    assert conn.execute("SELECT COUNT(*) c FROM news_item").fetchone()["c"] == 20
    assert conn.execute(
        "SELECT COUNT(*) c FROM news_item WHERE full_text_licensed=1"
    ).fetchone()["c"] == 20
    bylines = conn.execute(
        "SELECT COUNT(DISTINCT byline) c FROM news_item WHERE byline IS NOT NULL"
    ).fetchone()["c"]
    assert bylines >= 10
    # Every category tag became an explicit story->tagged->category edge.
    assert conn.execute(
        "SELECT COUNT(*) c FROM edge WHERE predicate='tagged' AND provenance='explicit'"
    ).fetchone()["c"] == sum(len(i["categories"]) for i in items)


def test_connector_is_registered_at_tier_one_hourly():
    c = get("news")
    assert (c.name, c.tier, c.cadence) == ("news", 1, "hourly")


# ------------------------------------------------------------------- live
@pytest.mark.live
def test_news_live_smoke(conn):
    r = get("news").smoke(conn)
    assert r.ok, r.detail
    assert r.stats["items"] >= 5
    assert r.stats["outlet_counts"]["The Texas Tribune"] >= 5
    # The derived permalink must match the one the redirect actually lands on.
    assert r.stats.get("canonical_verified") is True, r.stats
