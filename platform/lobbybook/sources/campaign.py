"""Campaign content — site decay, endorsement rolls, and two honest stubs.

Spec: docs/texas-politics-audit/03-deep-dives/17-campaign-content.md.

The audit's central empirical finding is that **campaign websites decay on a
predictable curve** and that no systematic public archive of Texas
legislative campaign sites exists.  Three real domains, verified through the
Wayback CDX API:

* ``jamestalarico.com`` — continuing candidate, full captures every year
  2017→2026: **active**.
* ``averieforall.com`` — HD112 2024 loser, full captures continued about five
  months past the loss and then 404: **orphaned → dead**.
* ``beverlypowell.com`` — SD10, last full capture is the exact day she ended
  her campaign (2022-04-06); every later capture is a redirect and the live
  domain now resolves to HugeDomains: **parked** (resold).

So the product here is the *archive and the lifecycle verdict*, not the live
fetch.  A stored campaign URL is an actively misleading artifact — two of the
audit's three test domains now resolve to a reseller and a dead server, and
the Legislative Reference Library's own link to Powell points at the parked
domain.  :func:`classify_decay` is the intelligence: a pure function over CDX
rows that returns ``active`` / ``orphaned`` / ``dead`` / ``parked`` plus the
transition dates, so a citation can carry "as captured on <date>" instead of
a link that lies.

**Endorsements.** Texas Right to Life PAC's endorsement tool is live and
segmented by office level, and it publishes **only the current cycle** — last
cycle's endorsements simply vanish from the page.  Prior cycles therefore
have to come from Wayback (or Ballotpedia's per-org roll-ups); ingesting the
live page every cycle is how the history gets built in the first place, and
every row is stamped with the cycle it was scraped for.

**Ad libraries are not scraped and are not faked.**  Meta's Ad Library 403s
every non-browser fetch and its API needs ID-verified developer access;
Google's political ads are a public BigQuery dataset with no REST surface.
:func:`meta_ad_library` and :func:`google_political_ads` raise
:class:`NotImplementedError` naming exactly the credential that unblocks
them.  A stub that says what is missing is worth more than a scraper that
silently returns nothing.

Authority class C throughout: campaign claims and endorsement lists are
self-interested by design — attribute every one to its issuer by name.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

# The audit verified this API works from a plain client even though
# web.archive.org's *page* rendering does not.
CDX_ENDPOINT = "http://web.archive.org/cdx/search/cdx"
TRTL_ENDORSEMENTS = "https://texasrighttolifepac.com/endorsements/"
TRTL_ORG = "Texas Right to Life PAC"

#: Domain resellers / parking services. A redirect into one of these is the
#: end of a campaign site's life: the domain has been sold.
RESELLER_HOSTS = (
    "hugedomains.com",
    "sedo.com",
    "sedoparking.com",
    "afternic.com",
    "dan.com",
    "buydomains.com",
    "domainmarket.com",
    "undeveloped.com",
    "parkingcrew.net",
    "bodis.com",
    "above.com",
    "godaddy.com/domainsearch",
)

_WS = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")
_CDX_TS = re.compile(r"^\d{14}$")


class WaybackUnavailable(RuntimeError):
    """The CDX API could not be reached. Carries the observed reason verbatim."""


# --------------------------------------------------------------- CDX client
@dataclass(frozen=True)
class CdxRow:
    """One Wayback capture, as the CDX server reports it."""

    timestamp: str
    original: str
    statuscode: str
    digest: str
    mimetype: str = ""
    redirect: str = ""

    @property
    def status(self) -> int | None:
        """None for revisit records, which report '-' rather than a code."""
        return int(self.statuscode) if self.statuscode.isdigit() else None

    @property
    def date(self) -> str:
        t = self.timestamp
        return f"{t[0:4]}-{t[4:6]}-{t[6:8]}" if len(t) >= 8 else t

    @property
    def when(self) -> datetime:
        return datetime.strptime(self.timestamp[:14], "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def cdx_url(
    domain: str, *, limit: int = 500, collapse: str = "timestamp:6", match_type: str = "domain"
) -> str:
    """The exact query shape the audit verified.

    ``collapse=timestamp:6`` keeps one capture per month, which is the right
    resolution for a lifecycle verdict and keeps unbounded queries — which
    were observed to reset the connection — off the table.
    """
    return (
        f"{CDX_ENDPOINT}?url={domain}&matchType={match_type}"
        f"&output=json&limit={limit}&collapse={collapse}"
    )


def parse_cdx(payload: bytes) -> list[CdxRow]:
    """CDX JSON -> rows. Pure over bytes.

    The first row is a header naming the fields, so the column order is read
    from the payload rather than assumed.
    """
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    data = json.loads(text)
    if not data:
        return []
    header = [str(col) for col in data[0]]
    index = {name: i for i, name in enumerate(header)}
    if "timestamp" not in index:  # headerless variant
        header = ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"]
        index = {name: i for i, name in enumerate(header)}
        body = data
    else:
        body = data[1:]
    def field_at(raw: list, name: str) -> str:
        pos = index.get(name)
        return str(raw[pos]) if pos is not None and pos < len(raw) else ""

    rows: list[CdxRow] = []
    for raw in body:
        ts = field_at(raw, "timestamp")
        if not _CDX_TS.match(ts):
            continue
        rows.append(
            CdxRow(
                timestamp=ts,
                original=field_at(raw, "original"),
                statuscode=field_at(raw, "statuscode"),
                digest=field_at(raw, "digest"),
                mimetype=field_at(raw, "mimetype"),
                redirect=field_at(raw, "redirect"),
            )
        )
    return sorted(rows, key=lambda r: r.timestamp)


def cdx_history(domain: str, limit: int = 500, **kwargs) -> tuple[list[CdxRow], bytes]:
    """Live CDX lookup. Returns (rows, raw payload) so the payload can be archived.

    Raises :class:`WaybackUnavailable` with the observed reason rather than
    returning an empty history — "no captures" and "could not ask" are
    different facts and must never be confused.
    """
    url = cdx_url(domain, limit=limit, **kwargs)
    try:
        resp = fetcher().get(url)
    except httpx.HTTPError as exc:
        raise WaybackUnavailable(f"{domain}: transport error contacting CDX: {exc}") from exc
    if resp.status_code != 200:
        reason = resp.headers.get("x-block-reason") or resp.text.strip()[:120]
        raise WaybackUnavailable(
            f"{domain}: CDX returned HTTP {resp.status_code}"
            f"{f' ({reason})' if reason else ''}"
        )
    return parse_cdx(resp.content), resp.content


def cdx_reachable(domain: str = "example.com") -> tuple[bool, str]:
    """One cheap probe. Used by smoke() to choose a path honestly."""
    try:
        rows, _ = cdx_history(domain, limit=1)
    except WaybackUnavailable as exc:
        return False, str(exc)
    return True, f"{len(rows)} rows"


# ---------------------------------------------------------- decay classifier
ACTIVE = "active"
ORPHANED = "orphaned"
DEAD = "dead"
PARKED = "parked"


@dataclass(frozen=True)
class DecayVerdict:
    """A campaign domain's lifecycle, derived from capture history alone."""

    domain: str
    status: str
    captures: int
    first_capture: str | None = None
    last_capture: str | None = None
    #: Last capture that actually served content — the "as of" date for any
    #: quote taken from this site.
    last_full_capture: str | None = None
    #: First non-200 capture after the last full one: the went-dark date.
    went_dark: str | None = None
    first_error: str | None = None
    first_redirect: str | None = None
    parked_target: str | None = None
    note: str = ""
    evidence: dict = field(default_factory=dict)


def _reseller(value: str) -> str | None:
    low = (value or "").lower()
    for host in RESELLER_HOSTS:
        if host in low:
            return host
    return None


def _tail(rows: list[CdxRow], window_days: int, min_rows: int) -> list[CdxRow]:
    """The recent end of the history: what the domain is doing *now*.

    A single newest row is too fragile (one stale asset 404ing under a live
    site would flip the verdict), so the verdict reads a trailing window and
    takes its dominant behaviour.
    """
    if not rows:
        return []
    newest = rows[-1].when
    window = [r for r in rows if (newest - r.when).days <= window_days]
    return window if len(window) >= min_rows else rows[-min_rows:]


def classify_decay(
    rows: list[CdxRow],
    *,
    domain: str = "",
    today: datetime | str | None = None,
    active_window_days: int = 365,
    tail_window_days: int = 180,
    redirect_target: str | None = None,
) -> DecayVerdict:
    """Lifecycle verdict for one domain. Pure over CDX rows.

    ``active``   — served content within ``active_window_days`` of ``today``.
    ``orphaned`` — still serving 200s, but the newest capture is stale: the
                   site is up and nobody is tending it.
    ``dead``     — the recent captures are errors (the 404 phase).
    ``parked``   — the recent captures redirect, and the target is a domain
                   reseller. Confirming the reseller needs a redirect target,
                   from CDX's ``redirect`` field or a resolved ``Location``;
                   without one this returns ``dead`` and says so, because
                   "redirects somewhere" is not evidence of a sale.
    """
    if not rows:
        return DecayVerdict(domain=domain, status=DEAD, captures=0, note="no captures")
    if today is None:
        now = datetime.now(UTC)
    elif isinstance(today, str):
        now = datetime.strptime(today[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    else:
        now = today

    ok = [r for r in rows if r.status == 200]
    last_full = ok[-1] if ok else None
    after = [r for r in rows if last_full is None or r.timestamp > last_full.timestamp]
    errors = [r for r in rows if r.status is not None and r.status >= 400]
    redirects = [r for r in rows if r.status is not None and 300 <= r.status < 400]
    went_dark = after[0] if after else None

    target = redirect_target or next(
        (r.redirect for r in rows if _reseller(r.redirect)),
        None,
    ) or next((r.original for r in rows if _reseller(r.original)), None)
    reseller = _reseller(target or "")

    tail = _tail(rows, tail_window_days, min_rows=3)
    classes = [
        "ok" if r.status == 200 else
        "redirect" if r.status is not None and 300 <= r.status < 400 else
        "error" if r.status is not None and r.status >= 400 else
        "unknown"
        for r in tail
    ]
    ranked = sorted(
        {c for c in classes if c != "unknown"},
        key=lambda c: (-classes.count(c), c),
    )
    dominant = ranked[0] if ranked else "unknown"

    note = ""
    if dominant == "redirect":
        if reseller:
            status = PARKED
            note = f"redirect tail resolving to {reseller} — domain resold"
        else:
            status = DEAD
            note = "redirect tail; no reseller target supplied, parking unconfirmed"
    elif dominant == "error":
        status = DEAD
        note = "recent captures are errors"
    elif dominant == "ok":
        stale_days = (now - rows[-1].when).days
        if stale_days <= active_window_days:
            status = ACTIVE
            note = f"serving content, newest capture {stale_days}d old"
        else:
            status = ORPHANED
            note = f"still serving 200s but newest capture is {stale_days}d old"
    else:
        status = ORPHANED if ok else DEAD
        note = "capture statuses unknown (revisit records only)"

    return DecayVerdict(
        domain=domain or (urlparse("//" + rows[-1].original).netloc or rows[-1].original),
        status=status,
        captures=len(rows),
        first_capture=rows[0].date,
        last_capture=rows[-1].date,
        last_full_capture=last_full.date if last_full else None,
        went_dark=went_dark.date if went_dark else None,
        first_error=errors[0].date if errors else None,
        first_redirect=redirects[0].date if redirects else None,
        parked_target=target if reseller else None,
        note=note,
        evidence={
            "tail_classes": classes,
            "dominant": dominant,
            "ok_captures": len(ok),
            "error_captures": len(errors),
            "redirect_captures": len(redirects),
        },
    )


# ------------------------------------------------------------- endorsements
@dataclass(frozen=True)
class Endorsement:
    org_raw: str
    candidate_raw: str
    cycle: int | None
    office_level: str
    position: str
    counties: tuple[str, ...] = ()
    starred: bool = False
    url: str = TRTL_ENDORSEMENTS

    @property
    def office(self) -> str:
        """Normalized office. DERIVED from the position label, not stated."""
        pos = self.position.lower()
        if re.match(r"^hd\s*\d", pos):
            return "state_house"
        if re.match(r"^sd\s*\d", pos):
            return "state_senate"
        if "congressional district" in pos:
            return "us_house"
        if "u.s. senate" in pos or "us senate" in pos:
            return "us_senate"
        if "court" in pos or "justice" in pos:
            return "judicial"
        if self.office_level == "statewide":
            return "statewide_executive"
        return "local"


_DATA_BLOB = re.compile(r"const\s+data\s*=\s*(\{.*?\})\s*;", re.S)
_CYCLE_HEADING = re.compile(r"<h2[^>]*>\s*(20\d\d)\s+Endorsements?\s*</h2>", re.I)


def endorsement_cycle(html: bytes) -> int | None:
    """The cycle the live page is showing. It only ever shows one."""
    m = _CYCLE_HEADING.search(html.decode("utf-8", errors="replace"))
    return int(m.group(1)) if m else None


def parse_endorsements(html: bytes, org_raw: str = TRTL_ORG) -> list[Endorsement]:
    """TRTL PAC endorsement page -> one row per (candidate, position).

    Pure over bytes. The page renders from a county-keyed JSON blob embedded
    in a <script>, so the same candidate appears under every county whose
    voters can vote for them; counties are folded back onto the endorsement
    rather than duplicated.
    """
    text = html.decode("utf-8", errors="replace")
    m = _DATA_BLOB.search(text)
    if not m:
        return []
    data = json.loads(m.group(1))
    cycle = endorsement_cycle(html)

    merged: dict[tuple[str, str, str], dict] = {}
    for county, levels in data.items():
        if not isinstance(levels, dict):
            continue
        for level, items in levels.items():
            for item in items or []:
                name = _WS.sub(" ", str(item.get("candidate", ""))).strip()
                position = _WS.sub(" ", str(item.get("position", ""))).strip()
                if not name:
                    continue
                starred = name.endswith("*")
                name = name.rstrip("*").strip()
                key = (name, position, level)
                entry = merged.setdefault(
                    key, {"counties": set(), "starred": starred}
                )
                entry["counties"].add(str(county))
                entry["starred"] = entry["starred"] or starred
    return sorted(
        (
            Endorsement(
                org_raw=org_raw,
                candidate_raw=name,
                cycle=cycle,
                office_level=level,
                position=position,
                counties=tuple(sorted(entry["counties"])),
                starred=entry["starred"],
            )
            for (name, position, level), entry in merged.items()
        ),
        key=lambda e: (e.office_level, e.position, e.candidate_raw),
    )


def store_endorsements(
    conn: sqlite3.Connection, rows: list[Endorsement], doc_id: str | None
) -> int:
    """Endorsement rows + explicit org→endorsed→candidate edges."""
    for row in rows:
        dbx.upsert(
            conn,
            "endorsement",
            {
                "org_raw": row.org_raw,
                "candidate_raw": row.candidate_raw,
                "cycle": row.cycle,
                "url": row.url,
            },
            ["org_raw", "candidate_raw", "cycle"],
            update_cols=["url"],
        )
        dbx.upsert(
            conn,
            "endorsement_race",
            {
                "org_raw": row.org_raw,
                "candidate_raw": row.candidate_raw,
                "cycle": row.cycle,
                "position": row.position,
                "office_level": row.office_level,
                "office": row.office,
                "counties": len(row.counties),
                "starred": int(row.starred),
            },
            ["org_raw", "candidate_raw", "cycle", "position"],
        )
        dbx.add_edge(
            conn, "organization_name", row.org_raw, "endorsed", "person_name",
            row.candidate_raw, "explicit", doc_id, span=row.position,
        )
    return len(rows)


# --------------------------------------------------------------- ad libraries
def meta_ad_library(*_args, **_kwargs):
    """Not implemented, deliberately. See the message for what unblocks it."""
    raise NotImplementedError(
        "Meta Ad Library: the public page 403s every non-browser fetch, so the "
        "only lawful path is the Ad Library API, which requires a Meta "
        "developer app whose owner has completed Meta ID verification for "
        "issues/elections/politics ads and an access token with the "
        "'ads_archive' permission. Supply that credential to enable this path; "
        "do not scrape the page."
    )


def google_political_ads(*_args, **_kwargs):
    """Not implemented, deliberately. See the message for what unblocks it."""
    raise NotImplementedError(
        "Google political ads: the data is the public BigQuery dataset "
        "bigquery-public-data.google_political_ads (creative_stats, 2018+, "
        "7-year retention) and there is no REST surface to fetch. Unblocking "
        "requires Google Cloud credentials — a service account with the "
        "BigQuery Job User role on a billing-enabled project — queried via the "
        "BigQuery client. There is nothing to scrape."
    )


def fcc_opif(*_args, **_kwargs):
    """Not implemented, deliberately: no automatable surface exists today."""
    raise NotImplementedError(
        "FCC OPIF political files: publicfiles.fcc.gov serves per-station "
        "scanned PDFs inside a JavaScript SPA with no cross-station search and "
        "no coverage of cable-only, streaming, or digital buys. Unblocking "
        "requires either a headless-browser harvester per facility_id or a "
        "commercial feed (AdImpact) — a budget line, not a credential."
    )


# ----------------------------------------------------------------- connector
@register
class CampaignConnector(Connector):
    """Wayback-first campaign archaeology plus live endorsement rolls."""

    name = "campaign"
    tier = 2
    cadence = "cycle"

    DDL = """
    -- One row per campaign domain: the lifecycle verdict and the dates that
    -- justify it, so a stored campaign URL is never resolved live without a
    -- staleness check.
    CREATE TABLE IF NOT EXISTS campaign_site (
        domain            TEXT PRIMARY KEY,
        candidate_raw     TEXT,
        cycle             INTEGER,
        status            TEXT,        -- active | orphaned | dead | parked
        captures          INTEGER,
        first_capture     TEXT,
        last_capture      TEXT,
        last_full_capture TEXT,
        went_dark         TEXT,
        parked_target     TEXT,
        note              TEXT,
        checked_at        TEXT,
        doc_id            TEXT REFERENCES document(id)
    );
    -- Endorsements are keyed (org, candidate, cycle) in the canonical table;
    -- the race a candidate was endorsed for lives here.
    CREATE TABLE IF NOT EXISTS endorsement_race (
        org_raw       TEXT NOT NULL,
        candidate_raw TEXT NOT NULL,
        cycle         INTEGER,
        position      TEXT NOT NULL,
        office_level  TEXT,
        office        TEXT,            -- DERIVED from the position label
        counties      INTEGER,
        starred       INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (org_raw, candidate_raw, cycle, position)
    );
    CREATE INDEX IF NOT EXISTS idx_endorsement_cycle ON endorsement(cycle);
    """

    # --------------------------------------------------------- decay tracking
    def track_domain(
        self,
        conn: sqlite3.Connection,
        domain: str,
        *,
        candidate_raw: str | None = None,
        cycle: int | None = None,
        limit: int = 500,
        today: str | None = None,
    ) -> dict:
        """Fetch a domain's capture history, archive it, classify the decay.

        Raises :class:`WaybackUnavailable` if CDX cannot be reached — callers
        decide what to do about it; this never invents a verdict.
        """
        rows, payload = cdx_history(domain, limit=limit)
        doc_id = f"campaign:cdx:{domain}"
        store_document(
            conn,
            doc_id=doc_id,
            source_family="campaign",
            content=payload,
            url=cdx_url(domain, limit=limit),
            native_id=domain,
            doc_type="wayback_cdx",
            authority="C",
        )
        verdict = classify_decay(rows, domain=domain, today=today)
        self.record_verdict(conn, verdict, candidate_raw=candidate_raw, cycle=cycle, doc_id=doc_id)
        conn.commit()
        return {"domain": domain, "captures": len(rows), "status": verdict.status,
                "went_dark": verdict.went_dark, "doc_id": doc_id}

    def record_verdict(
        self,
        conn: sqlite3.Connection,
        verdict: DecayVerdict,
        *,
        candidate_raw: str | None = None,
        cycle: int | None = None,
        doc_id: str | None = None,
    ) -> None:
        dbx.upsert(
            conn,
            "campaign_site",
            {
                "domain": verdict.domain,
                "candidate_raw": candidate_raw,
                "cycle": cycle,
                "status": verdict.status,
                "captures": verdict.captures,
                "first_capture": verdict.first_capture,
                "last_capture": verdict.last_capture,
                "last_full_capture": verdict.last_full_capture,
                "went_dark": verdict.went_dark,
                "parked_target": verdict.parked_target,
                "note": verdict.note,
                "checked_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "doc_id": doc_id,
            },
            ["domain"],
        )
        if verdict.went_dark:
            # DERIVED, per the audit: the 200 -> 404/30x transition is inferred
            # from capture statuses, not stated by anyone.
            dbx.add_edge(
                conn, "campaign_site", verdict.domain, "went_dark", "date",
                verdict.went_dark, "derived", doc_id, confidence=0.8,
                span=verdict.note or None,
            )
        if verdict.parked_target:
            dbx.add_edge(
                conn, "campaign_site", verdict.domain, "resold_to", "domain",
                verdict.parked_target, "derived", doc_id, confidence=0.9,
            )

    # ----------------------------------------------------------- endorsements
    def ingest_endorsements(
        self, conn: sqlite3.Connection, url: str = TRTL_ENDORSEMENTS, org_raw: str = TRTL_ORG
    ) -> dict:
        """One live request. The page shows the current cycle only — which is
        precisely why it has to be captured every cycle."""
        resp = fetcher().get(url)
        resp.raise_for_status()
        cycle = endorsement_cycle(resp.content)
        doc_id = f"campaign:endorsements:{urlparse(url).netloc}:{cycle or 'unknown'}"
        store_document(
            conn,
            doc_id=doc_id,
            source_family="campaign",
            content=resp.content,
            url=url,
            native_id=org_raw,
            doc_type="endorsement_roll",
            published_at=str(cycle) if cycle else None,
            authority="C",
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )
        rows = parse_endorsements(resp.content, org_raw=org_raw)
        store_endorsements(conn, rows, doc_id)
        conn.commit()
        return {
            "org": org_raw,
            "cycle": cycle,
            "endorsements": len(rows),
            "candidates": len({r.candidate_raw for r in rows}),
            "office_levels": sorted({r.office_level for r in rows}),
            "doc_id": doc_id,
        }

    # ------------------------------------------------------------- lifecycle
    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """Endorsement roll every run; decay checks for whatever domains the
        caller is tracking, skipped honestly when Wayback is unreachable."""
        out: dict = {"endorsements": self.ingest_endorsements(conn)}
        domains = kwargs.get("domains") or []
        checked, skipped = [], []
        for domain in domains:
            try:
                checked.append(self.track_domain(conn, domain, today=kwargs.get("today")))
            except WaybackUnavailable as exc:
                skipped.append({"domain": domain, "reason": str(exc)})
        out["domains"] = checked
        out["wayback_skipped"] = skipped
        return out

    def backfill(self, conn: sqlite3.Connection, **kwargs) -> dict:
        return self.incremental(conn, **kwargs)

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """Prefer the decay path (the real intelligence); fall back to the
        endorsement roll when Wayback is unreachable, and say which ran."""
        domain = "jamestalarico.com"
        try:
            got = self.track_domain(conn, domain, candidate_raw="James Talarico", limit=200)
        except WaybackUnavailable as exc:
            wayback_error = str(exc)
        else:
            row = conn.execute(
                "SELECT * FROM campaign_site WHERE domain=?", (domain,)
            ).fetchone()
            stats = {
                "path": "wayback_cdx",
                "wayback_reachable": True,
                "domain": domain,
                "captures": got["captures"],
                "status": row["status"],
                "first_capture": row["first_capture"],
                "last_full_capture": row["last_full_capture"],
            }
            return SmokeResult(
                ok=got["captures"] >= 5 and bool(row["status"]),
                detail=(
                    f"wayback path: {domain} {got['captures']} captures "
                    f"{row['first_capture']}..{row['last_capture']} -> {row['status']}"
                ),
                stats=stats,
            )

        got = self.ingest_endorsements(conn)
        rows = conn.execute("SELECT COUNT(*) c FROM endorsement").fetchone()["c"]
        edges = conn.execute(
            "SELECT COUNT(*) c FROM edge WHERE predicate='endorsed' AND provenance='explicit'"
        ).fetchone()["c"]
        stats = {
            "path": "endorsements",
            "wayback_reachable": False,
            "wayback_error": wayback_error,
            "cycle": got["cycle"],
            "endorsements": rows,
            "candidates": got["candidates"],
            "office_levels": got["office_levels"],
            "endorsed_edges": edges,
        }
        return SmokeResult(
            ok=rows >= 20 and edges >= 20,
            detail=(
                f"endorsement path ({TRTL_ORG} {got['cycle']}): {rows} rows, "
                f"{got['candidates']} candidates, {edges} explicit edges. "
                f"Wayback unavailable: {wayback_error}"
            ),
            stats=stats,
        )


__all__ = [
    "ACTIVE",
    "DEAD",
    "ORPHANED",
    "PARKED",
    "RESELLER_HOSTS",
    "CampaignConnector",
    "CdxRow",
    "DecayVerdict",
    "Endorsement",
    "WaybackUnavailable",
    "cdx_history",
    "cdx_reachable",
    "cdx_url",
    "classify_decay",
    "endorsement_cycle",
    "fcc_opif",
    "google_political_ads",
    "meta_ad_library",
    "parse_cdx",
    "parse_endorsements",
    "store_endorsements",
]
