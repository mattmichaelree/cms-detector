"""Texas party platforms — RPT platform PDFs, plank compound keys, TDP's block.

Spec: docs/texas-politics-audit/03-deep-dives/15-party-platforms.md.

Three audit findings shape this module.

**1. A bare plank number is meaningless.**  Platform numbering is not unique
inside a cycle: the 2024 RPT PDF runs three independently numbered series in
one document (Principles 1–10, planks 1–252, Resolutions 1–7), so "RPT Plank
3" resolves to three different texts — a principle about sovereignty, a plank
about Article 4 Section 4, and the resolution condemning the 2023 Paxton
impeachment.  Subsection headings repeat across sections too ("Parents'
Rights" appears under both *Education* and *Health and Human Services*).  The
durable identity is therefore the compound key
``(party, cycle, section, subsection, number)`` — the natural key of
``platform_plank`` — and :func:`number_collisions` exists to keep proving it
on every new cycle.

*QA note, verified against the 2024 PDF in this repo's fixtures:* the audit
states plank numbers "RESTART at 1 within every subsection".  In the 2024
final they do **not** — the plank series runs continuously 1→252 across every
section and subsection.  The restarts are between series (Principles,
planks, Resolutions).  The conclusion is unchanged and if anything stronger:
number 3 exists three times in one document, so the compound key is load-
bearing whichever way a future cycle numbers itself.  Nothing here assumes
continuity; the parser keys every row on the heading stack it was found
under.

**2. The RPT's own URLs churn.**  ``/platform/`` 301-redirects to
``/official-documents-2/`` (QA-verified).  Discovery therefore parses the
index page for *links*, never for a hard-coded upload path, and it takes the
cycle year from the filename or the link text — never from the
``/wp-content/uploads/{year}/`` path, which is the year the file was
*uploaded* (the 2022 platform lives under ``uploads/2024/06/``).  Convention
drafts on ``convention.texasgop.org`` and any "TEMPORARY"/"DRAFT" filename
are flagged :attr:`PlatformLink.draft` so a draft is never indexed as the
adopted document.

**3. One party is off-limits and its canonical URL is dead.**  The TDP
platform page 404s (verified) while the party's own resources page still
links to it, and texasdemocrats.org's robots.txt disallows ClaudeBot, GPTBot
and ~25 other named AI crawlers.  :data:`PARTIES` carries that as
``blocked_by_robots=True, canonical_url_broken=True``; every ingest path
consults the policy and refuses to fetch.  Recovering TDP text means Wayback
or the Google Docs the 2022/2024 platforms actually lived on, plus a
permission conversation — not a crawl.

Authority class C throughout: a platform is what a party adopted on a date,
never neutral fact and never any officeholder's position.
"""

from __future__ import annotations

import io
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import pdfplumber

from lobbybook.core import db as dbx
from lobbybook.core.docstore import load_latest, store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

# The canonical entry point. It 301s to /official-documents-2/; the fetcher
# follows redirects, and discovery resolves every link against the *final*
# URL so relative hrefs survive the move.
RPT_PLATFORM_INDEX = "https://texasgop.org/platform/"
TDP_PLATFORM_URL = "https://www.texasdemocrats.org/platform"

_WS = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")
_ANCHOR = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
_HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_YEAR = re.compile(r"(19[89]\d|20[0-5]\d)")
_DOT_LEADER = re.compile(r"\.{4,}")
_NUMBERED = re.compile(r"^(\d{1,3})\.\s+(.*)$", re.S)
# "12. Protecting Constitutional Rights Regarding Age: There should be ..."
_TITLED = re.compile(r"^(.{3,120}?):\s")
_DRAFT_MARKERS = ("temporary", "draft", "-proposed", "preliminary")

# Font geometry of the RPT finals (Times New Roman, verified on the 2024 PDF):
# 16pt bold = section, 14pt = subsection, 12pt bold lead-in = plank, 12pt
# regular = body, 11pt = the keyword index, footer band at the page bottom.
SECTION_MIN_SIZE = 15.5
SUBSECTION_MIN_SIZE = 13.5
BODY_MIN_SIZE = 11.5
FOOTER_TOP = 730.0
LINE_TOLERANCE = 2.5

#: Headings that are front matter, not platform content.
FRONT_MATTER = {
    "table of contents",
    "platform committee members",
    "editorial committee",
    "index",
}


# ----------------------------------------------------------------- party policy
@dataclass(frozen=True)
class PartyPolicy:
    """What we are allowed to fetch for one party, and why."""

    key: str
    name: str
    abbr: str
    #: Page that lists the platform editions. None where there is nothing to crawl.
    index_url: str | None
    #: True where the party's robots.txt names AI crawlers and disallows them.
    blocked_by_robots: bool = False
    #: True where the party's own canonical platform URL is a verified 404.
    canonical_url_broken: bool = False
    canonical_url: str | None = None
    #: Where the platform of record actually lives when it is not self-hosted.
    off_domain_note: str = ""
    note: str = ""

    @property
    def ingestable(self) -> bool:
        """False disables every fetch path for this party. Both flags block."""
        return not (self.blocked_by_robots or self.canonical_url_broken)

    @property
    def skip_reason(self) -> str | None:
        if self.blocked_by_robots and self.canonical_url_broken:
            return "blocked_by_robots+canonical_url_broken"
        if self.blocked_by_robots:
            return "blocked_by_robots"
        if self.canonical_url_broken:
            return "canonical_url_broken"
        return None


PARTIES: dict[str, PartyPolicy] = {
    "rpt": PartyPolicy(
        key="rpt",
        name="Republican Party of Texas",
        abbr="RPT",
        index_url=RPT_PLATFORM_INDEX,
        canonical_url=RPT_PLATFORM_INDEX,
        note=(
            "robots fully open; finals are text-layer PDFs under "
            "/wp-content/uploads/{year}/{month}/. /platform/ 301s to "
            "/official-documents-2/. Convention drafts live on "
            "convention.texasgop.org and must not be indexed as adopted."
        ),
    ),
    "tdp": PartyPolicy(
        key="tdp",
        name="Texas Democratic Party",
        abbr="TDP",
        index_url=None,
        blocked_by_robots=True,
        canonical_url_broken=True,
        canonical_url=TDP_PLATFORM_URL,
        off_domain_note=(
            "The 2022 and 2024 platforms were published as Google Docs linked "
            "from convention recap posts — the platform of record has lived "
            "off the party's own domain, with no fixed hash, so change "
            "detection must be a content diff rather than a checksum."
        ),
        note=(
            "texasdemocrats.org/platform is a verified live 404 (CDX shows it "
            "live 2022-09 -> 2025-01) while the party's own resources page "
            "still links to it; robots.txt disallows ClaudeBot, GPTBot and "
            "~25 other named AI crawlers while allowing search indexing. "
            "Recover via Wayback or with the party's permission — never by "
            "crawling texasdemocrats.org."
        ),
    ),
}


def policy(key: str) -> PartyPolicy:
    return PARTIES[key]


def blocked_parties() -> list[str]:
    return sorted(k for k, p in PARTIES.items() if not p.ingestable)


# -------------------------------------------------------------------- index
@dataclass(frozen=True)
class PlatformLink:
    """One platform edition advertised on a party's index page."""

    url: str
    cycle: int
    kind: str  # 'pdf' | 'drive'
    label: str
    draft: bool = False

    @property
    def native_pdf(self) -> bool:
        return self.kind == "pdf" and not self.draft


def strip_html(html: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", html)).replace("&#8217;", "'").strip()


def _cycle_from(url: str, label: str) -> int | None:
    """Cycle year from the *filename* or the link text — never the upload path.

    ``.../uploads/2024/06/2022-RPT-Platform.pdf`` is the 2022 platform: the
    path year is when the file was uploaded, which is a different fact.
    """
    basename = urlparse(url).path.rsplit("/", 1)[-1]
    for source in (basename, label):
        m = _YEAR.search(source)
        if m:
            return int(m.group(1))
    return None


def parse_platform_index(html: bytes, base_url: str = RPT_PLATFORM_INDEX) -> list[PlatformLink]:
    """Platform editions advertised on the RPT index page, newest cycle first.

    Pure over bytes. Accepts native PDFs and Google Drive/Docs links (the 2020
    platform is Drive-hosted), requires a cycle year recoverable from the
    filename or the link text, and de-duplicates the same file linked twice
    (the page links each PDF from a button *and* an embedded viewer).
    """
    text = html.decode("utf-8", errors="replace")
    found: dict[str, PlatformLink] = {}
    for m in _ANCHOR.finditer(text):
        href_m = _HREF.search(m.group(1))
        if not href_m:
            continue
        href = href_m.group(1).strip()
        label = strip_html(m.group(2))
        low_href, low_label = href.lower(), label.lower()
        if "platform" not in low_href and "platform" not in low_label:
            continue
        if low_href.endswith(".pdf"):
            kind = "pdf"
        elif "drive.google.com" in low_href or "docs.google.com" in low_href:
            kind = "drive"
        else:
            continue
        url = urljoin(base_url, href)
        cycle = _cycle_from(url, label)
        if cycle is None:
            # e.g. PERM-PLATFORM-as-Amended-by-Gen-Body-5.13.16.pdf — an
            # undated party-structure handout, not a cycle platform.
            continue
        host = urlparse(url).netloc.lower()
        draft = host.startswith("convention.") or any(
            marker in url.lower() for marker in _DRAFT_MARKERS
        )
        link = PlatformLink(url=url, cycle=cycle, kind=kind, label=label, draft=draft)
        found.setdefault(url, link)
    return sorted(found.values(), key=lambda link: (-link.cycle, link.url))


# --------------------------------------------------------------- PDF parsing
@dataclass(frozen=True)
class TocEntry:
    title: str
    level: int  # 0 = section, 1 = subsection
    page: int


@dataclass(frozen=True)
class Plank:
    """One numbered item, carrying the heading stack it was found under."""

    party: str
    cycle: int
    section: str
    subsection: str
    number: str
    title: str | None
    text: str
    page: int

    @property
    def key(self) -> tuple[str, int, str, str, str]:
        """The only durable identity. A bare number is not one."""
        return (self.party, self.cycle, self.section, self.subsection, self.number)

    @property
    def plank_id(self) -> str:
        return "|".join(str(part) for part in self.key)

    @property
    def citation(self) -> str:
        return (
            f"{self.party} {self.cycle} platform, {self.section} › "
            f"{self.subsection}, item {self.number}"
        )


@dataclass(frozen=True)
class Line:
    text: str
    size: float
    bold: bool
    x0: float
    top: float
    page: int


def _lines(pdf_bytes: bytes) -> list[Line]:
    """Every text line with the font facts the heading rules need."""
    out: list[Line] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(extra_attrs=["size", "fontname"])
            buckets: list[list[dict]] = []
            for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
                if buckets and abs(word["top"] - buckets[-1][0]["top"]) <= LINE_TOLERANCE:
                    buckets[-1].append(word)
                else:
                    buckets.append([word])
            for bucket in buckets:
                ordered = sorted(bucket, key=lambda w: w["x0"])
                head = ordered[0]
                out.append(
                    Line(
                        text=_WS.sub(" ", " ".join(w["text"] for w in ordered)).strip(),
                        size=round(float(head["size"]), 1),
                        bold="Bold" in head["fontname"],
                        x0=round(float(head["x0"]), 1),
                        top=round(float(head["top"]), 1),
                        page=page_no,
                    )
                )
    return out


def parse_toc(pdf_bytes: bytes) -> list[TocEntry]:
    """The table of contents, with hierarchy read from the dot-leader indent.

    Two entries can share a title at different indents and under different
    parents — ``Parents' Rights`` is a subsection of both *Education* and
    *Health and Human Services* in 2024 — which is the second reason the
    plank key needs its section.
    """
    return toc_from_lines(_lines(pdf_bytes))


def toc_from_lines(lines: list[Line]) -> list[TocEntry]:
    raw: list[tuple[str, float, int]] = []
    for line in lines:
        # 11pt is the keyword index at the back of the book: it uses the same
        # dot leaders as the TOC and would otherwise flood the heading
        # vocabulary with page-index phrases.
        if line.top > FOOTER_TOP or line.size < BODY_MIN_SIZE:
            continue
        if not _DOT_LEADER.search(line.text):
            continue
        m = re.match(r"^(.*?)\s*\.{4,}\s*(\d{1,3})$", line.text)
        if not m:
            continue
        title = m.group(1).strip()
        if not title or title.lower() in FRONT_MATTER:
            continue
        raw.append((title, line.x0, int(m.group(2))))
    if not raw:
        return []
    left = min(x0 for _, x0, _ in raw)
    return [
        TocEntry(title=title, level=0 if abs(x0 - left) < 3 else 1, page=page)
        for title, x0, page in raw
    ]


def detect_cycle(pdf_bytes: bytes | None = None, *, lines: list[Line] | None = None) -> int | None:
    """Cycle year from the document's own words ("We, the 2024 Republican...")."""
    src = lines if lines is not None else _lines(pdf_bytes or b"")
    for line in src[:80]:
        m = _YEAR.search(line.text)
        if m and "platform" in line.text.lower():
            return int(m.group(1))
    for line in src:
        m = re.search(r"We,?\s+the\s+(19[89]\d|20[0-5]\d)\s+", line.text)
        if m:
            return int(m.group(1))
    return None


def _split_title(body: str) -> tuple[str | None, str]:
    m = _TITLED.match(body)
    if m and "." not in m.group(1):
        return m.group(1).strip(), body
    return None, body


def parse_planks(pdf_bytes: bytes, *, party: str = "RPT", cycle: int | None = None) -> list[Plank]:
    """Numbered platform items, each keyed on the heading stack above it.

    Pure over PDF bytes. Walks the document in reading order keeping a
    (section, subsection) stack; a 12pt **bold** line opening with ``N.``
    starts a new item and every following body line accretes onto it until
    the next item or heading.

    ``subsection`` is never NULL: where a section has no subsection headings
    (Principles, Resolutions) it repeats the section name. That is deliberate
    — ``platform_plank``'s natural key is UNIQUE over five columns, and both
    SQLite and Postgres treat NULLs in a unique key as distinct, so a NULL
    subsection would silently duplicate every row on re-ingest instead of
    upserting it.
    """
    lines = _lines(pdf_bytes)
    if cycle is None:
        cycle = detect_cycle(lines=lines)
    if cycle is None:
        raise ValueError("cycle not given and not derivable from the document")

    toc = toc_from_lines(lines)
    sections = {e.title.lower() for e in toc if e.level == 0}
    subsections = {e.title.lower() for e in toc if e.level == 1}

    planks: list[Plank] = []
    section = subsection = None
    number = title = None
    page = 0
    buf: list[str] = []

    def flush() -> None:
        nonlocal number, title, buf
        if number is None:
            return
        text = _WS.sub(" ", " ".join(buf)).strip()
        if text:
            planks.append(
                Plank(
                    party=party,
                    cycle=cycle,
                    section=section or "",
                    subsection=subsection or section or "",
                    number=number,
                    title=title,
                    text=text,
                    page=page,
                )
            )
        number, title, buf = None, None, []

    for line in lines:
        if line.top > FOOTER_TOP or line.size < BODY_MIN_SIZE or not line.text:
            continue  # page footer, keyword index, or blank
        low = line.text.lower()
        is_section = (line.size >= SECTION_MIN_SIZE and line.bold) or (
            low in sections and not _NUMBERED.match(line.text)
        )
        is_subsection = (SUBSECTION_MIN_SIZE <= line.size < SECTION_MIN_SIZE) or (
            low in subsections and not _NUMBERED.match(line.text)
        )
        if is_section:
            flush()
            section = None if low in FRONT_MATTER else line.text
            subsection = None
            continue
        if is_subsection:
            flush()
            subsection = line.text
            continue
        if section is None or _DOT_LEADER.search(line.text):
            continue  # front matter / table of contents
        m = _NUMBERED.match(line.text)
        if m and line.bold:
            flush()
            number = m.group(1)
            title, body = _split_title(m.group(2))
            buf = [body]
            page = line.page
            continue
        if number is not None:
            buf.append(line.text)
    flush()
    return planks


def number_collisions(planks: list[Plank]) -> dict[str, list[tuple[str, str]]]:
    """Numbers used by more than one (section, subsection) — the ambiguity map.

    Any non-empty result is proof that citing "Plank N" without its heading
    stack is a misinformation risk, which is exactly what the audit warns about.
    """
    seen: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for plank in planks:
        seen[plank.number].add((plank.section, plank.subsection))
    return {n: sorted(v) for n, v in sorted(seen.items(), key=lambda kv: int(kv[0])) if len(v) > 1}


def subsection_spread(planks: list[Plank]) -> int:
    return len({(p.section, p.subsection) for p in planks})


# ------------------------------------------------------------------- storage
def store_planks(conn: sqlite3.Connection, planks: list[Plank], doc_id: str | None) -> int:
    """Upsert planks on the compound key and link each to its document."""
    for plank in planks:
        dbx.upsert(
            conn,
            "platform_plank",
            {
                "party": plank.party,
                "cycle": plank.cycle,
                "section": plank.section,
                "subsection": plank.subsection,
                "number": plank.number,
                "text": plank.text,
                "doc_id": doc_id,
            },
            ["party", "cycle", "section", "subsection", "number"],
        )
        if doc_id:
            dbx.add_edge(
                conn, "document", doc_id, "contains", "platform_plank", plank.plank_id,
                "explicit", doc_id,
            )
    return len(planks)


# ----------------------------------------------------------------- connector
@register
class PlatformsConnector(Connector):
    """RPT platform discovery + plank extraction; TDP refused by policy."""

    name = "platforms"
    tier = 2
    cadence = "convention_cycle"

    DDL = """
    -- What discovery found, including editions we deliberately do not fetch
    -- (Drive-hosted 2020, convention drafts). Keeping the row is how the
    -- platform knows an edition exists without pretending it is ingested.
    CREATE TABLE IF NOT EXISTS platform_edition (
        party        TEXT NOT NULL,
        cycle        INTEGER NOT NULL,
        url          TEXT NOT NULL,
        kind         TEXT,               -- 'pdf' | 'drive'
        draft        INTEGER NOT NULL DEFAULT 0,
        label        TEXT,
        doc_id       TEXT REFERENCES document(id),
        planks       INTEGER,
        discovered_at TEXT,
        PRIMARY KEY (party, cycle, url)
    );
    CREATE INDEX IF NOT EXISTS idx_platform_plank_party_cycle
        ON platform_plank(party, cycle);
    """

    # ------------------------------------------------------------ discovery
    def discover(self, party_key: str = "rpt") -> tuple[list[PlatformLink], dict]:
        """Fetch and parse a party's platform index. One live request."""
        p = policy(party_key)
        if not p.ingestable:
            return [], {"party": party_key, "skipped": p.skip_reason, "note": p.note}
        if not p.index_url:
            return [], {"party": party_key, "skipped": "no_index_url"}
        resp = fetcher().get(p.index_url)
        resp.raise_for_status()
        links = parse_platform_index(resp.content, str(resp.url))
        return links, {
            "party": party_key,
            "index_url": p.index_url,
            "resolved_url": str(resp.url),
            "redirected": str(resp.url).rstrip("/") != p.index_url.rstrip("/"),
            "editions": len(links),
            "content": resp.content,
        }

    def record_editions(
        self, conn: sqlite3.Connection, party_key: str, links: list[PlatformLink]
    ) -> None:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        for link in links:
            dbx.upsert(
                conn,
                "platform_edition",
                {
                    "party": policy(party_key).abbr,
                    "cycle": link.cycle,
                    "url": link.url,
                    "kind": link.kind,
                    "draft": int(link.draft),
                    "label": link.label,
                    "discovered_at": now,
                },
                ["party", "cycle", "url"],
                update_cols=["kind", "draft", "label", "discovered_at"],
            )

    # -------------------------------------------------------------- ingest
    def ingest_platform(
        self, conn: sqlite3.Connection, link: PlatformLink, party_key: str = "rpt"
    ) -> dict:
        """Fetch one platform PDF, archive it, then parse planks from the bytes."""
        p = policy(party_key)
        if not p.ingestable:
            return {"party": party_key, "skipped": p.skip_reason, "planks": 0}
        if link.draft:
            return {"url": link.url, "skipped": "draft", "planks": 0}
        if link.kind != "pdf":
            # Drive-hosted editions need an export path and a change-detection
            # strategy that is a content diff, not a checksum. Not a crawl.
            return {"url": link.url, "skipped": f"not_native_pdf:{link.kind}", "planks": 0}

        resp = fetcher().get(link.url)
        resp.raise_for_status()
        doc_id = f"platforms:{p.abbr}:{link.cycle}:platform"
        # Artifact first, parse second.
        store_document(
            conn,
            doc_id=doc_id,
            source_family="platforms",
            content=resp.content,
            url=link.url,
            native_id=f"{p.abbr}-{link.cycle}-platform",
            doc_type="party_platform",
            published_at=str(link.cycle),
            authority="C",
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )
        planks = parse_planks(resp.content, party=p.abbr, cycle=link.cycle)
        store_planks(conn, planks, doc_id)
        dbx.add_edge(
            conn, "organization", p.abbr, "adopted", "document", doc_id, "explicit", doc_id,
        )
        dbx.upsert(
            conn,
            "platform_edition",
            {
                "party": p.abbr,
                "cycle": link.cycle,
                "url": link.url,
                "kind": link.kind,
                "draft": int(link.draft),
                "label": link.label,
                "doc_id": doc_id,
                "planks": len(planks),
                "discovered_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            ["party", "cycle", "url"],
        )
        conn.commit()
        return {
            "url": link.url,
            "cycle": link.cycle,
            "doc_id": doc_id,
            "planks": len(planks),
            "subsections": subsection_spread(planks),
            "collisions": len(number_collisions(planks)),
        }

    # ----------------------------------------------------------- lifecycle
    def backfill(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """Every native PDF edition the index advertises (bounded by `limit`)."""
        limit = int(kwargs.get("limit", 3))
        parties = kwargs.get("parties") or list(PARTIES)
        results: list[dict] = []
        skipped: list[dict] = []
        for key in parties:
            p = policy(key)
            if not p.ingestable:
                skipped.append({"party": key, "reason": p.skip_reason, "note": p.note})
                continue
            links, meta = self.discover(key)
            self.record_editions(conn, key, links)
            conn.commit()
            for link in [link for link in links if link.native_pdf][:limit]:
                results.append(self.ingest_platform(conn, link, key))
            results.append({"party": key, "editions": meta.get("editions", 0)})
        return {
            "ingested": [r for r in results if r.get("planks")],
            "skipped_parties": skipped,
            "planks": conn.execute("SELECT COUNT(*) c FROM platform_plank").fetchone()["c"],
        }

    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """Newest edition only — platforms are adopted once per convention."""
        return self.backfill(conn, limit=1, parties=kwargs.get("parties"))

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """Two live requests: the index, then the newest native platform PDF."""
        links, meta = self.discover("rpt")
        self.record_editions(conn, "rpt", links)
        conn.commit()
        pdfs = [link for link in links if link.native_pdf]
        stats = {
            "editions": len(links),
            "pdf_editions": len(pdfs),
            "cycles": [link.cycle for link in links],
            "redirected_to": meta.get("resolved_url"),
            "drive_only": [link.cycle for link in links if link.kind == "drive"],
            "blocked_parties": blocked_parties(),
        }
        if len(pdfs) < 2:
            return SmokeResult(
                ok=False, detail=f"expected >=2 platform PDFs, found {len(pdfs)}", stats=stats
            )
        got = self.ingest_platform(conn, pdfs[0], "rpt")
        planks = conn.execute(
            "SELECT * FROM platform_plank WHERE party='RPT' AND cycle=?", (pdfs[0].cycle,)
        ).fetchall()
        spread = len({(r["section"], r["subsection"]) for r in planks})
        # Re-parse from the archived bytes, not the response: this proves the
        # stored artifact is what the plank rows were derived from.
        archived = load_latest(conn, got["doc_id"]) or b""
        collisions = number_collisions(parse_planks(archived, party="RPT", cycle=pdfs[0].cycle))
        stats.update(
            ingested_cycle=pdfs[0].cycle,
            planks=len(planks),
            subsection_spread=spread,
            colliding_numbers=len(collisions),
            example_collision=next(iter(collisions.items()), None),
        )
        ok = len(planks) >= 50 and spread >= 3
        return SmokeResult(
            ok=ok,
            detail=(
                f"RPT {pdfs[0].cycle}: {len(planks)} planks across {spread} subsections "
                f"from {len(pdfs)} PDF editions {stats['cycles']}; "
                f"{len(collisions)} numbers reused across subsections; "
                f"skipped parties={blocked_parties()}"
            ),
            stats=stats,
        )


__all__ = [
    "PARTIES",
    "Plank",
    "PlatformLink",
    "PlatformsConnector",
    "PartyPolicy",
    "TocEntry",
    "blocked_parties",
    "detect_cycle",
    "number_collisions",
    "parse_planks",
    "parse_platform_index",
    "parse_toc",
    "policy",
    "store_planks",
    "subsection_spread",
]
