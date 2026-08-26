"""Texas court opinions — CourtListener sync + the courts nobody else indexes.

Spec: docs/texas-politics-audit/03-deep-dives/13-courts.md.

Three facts from the audit shape this module:

  * **CourtListener is the cheap layer, not the fresh layer.** Its v4 search API
    covers SCOTX (`tex`, back to 1840) and the CCA (`texcrimapp`) for free, but
    the audit measured the CCA feed ~11 months stale at fetch. So every sync
    records the maximum ``dateFiled`` it actually saw as a *freshness metric*
    (``court_source_freshness``) rather than assuming the feed is current.
  * **The Business Court and the 15th COA are absent from CourtListener** —
    the first-mover gap and the reason this connector exists. The Business
    Court publishes its whole corpus on one chronological listing page with its
    own citation style ("2026 Tex. Bus. 60"), so it is polled directly.
  * **Statute edges are derived, never given.** Nothing in either source flags
    "this opinion construes Gov't Code §2001.038"; that edge comes out of
    citation parsing over opinion text and is stored with provenance
    ``derived`` (audit §5). §2001.038 — the APA rule-challenge hook — is
    flagged specially, because "did a court just strike the rule my client
    relies on?" is the question this corpus exists to answer.

Compliance (enforced in lobbybook.core.fetch, not here): TAMES
(search.txcourts.gov) is robots ``Disallow: /`` and re:SearchTX is bot-walled —
both are on the fetcher denylist and raise ``DeniedURL``. www.txcourts.gov
declares a 720-second crawl-delay, so this connector polls **listing pages
only** and fetches individual ``/media/{id}/`` PDFs on demand; it never crawls.
"""

from __future__ import annotations

import io
import json
import re
import sqlite3
from datetime import UTC, date, datetime
from html import unescape
from urllib.parse import urljoin

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

CL_SEARCH = "https://www.courtlistener.com/api/rest/v4/search/"
BIZCOURT_OPINIONS = "https://www.txcourts.gov/businesscourt/opinions/"

# The 15th COA is the other half of the first-mover gap, and it stays
# unimplemented on purpose: it has no dedicated opinions page (404) and its only
# listing is the shared TAMES case search, which is robots-disallowed and on the
# fetcher denylist. Covering it needs an OCA data arrangement, not a scraper.
COA15_BLOCKED_NOTE = "15th COA: no compliant listing endpoint; TAMES is denylisted"

# CourtListener court ids that resolve for Texas appellate courts. `texctapp15`
# (15th COA) 404s and the Business Court has no id at all — verified gaps.
CL_COURTS = {
    "tex": "Supreme Court of Texas",
    "texcrimapp": "Texas Court of Criminal Appeals",
}

# Authority classes per audit §7. Business Court opinions are first-instance
# persuasive signal, not binding precedent, so they are not A/B.
AUTHORITY = {"tex": "A", "texcrimapp": "A", "texbusct": "C"}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


# --------------------------------------------------------------- CourtListener

def _norm_kind(op_type: str | None, per_curiam: bool) -> str:
    """CourtListener opinion `type` -> the schema's kind vocabulary."""
    t = (op_type or "").lower()
    if per_curiam:
        return "per_curiam"
    if "dissent" in t:
        return "dissent"
    if "concurrence" in t or "in-part" in t:
        return "concurrence"
    if "remittitur" in t or "addendum" in t:
        return "order"
    return "majority"


def parse_courtlistener(content: bytes) -> list[dict]:
    """One v4 search response -> one dict per *opinion* (not per cluster).

    A cluster with a lead opinion plus a dissent surfaces as separate search
    results in the live API, and the schema's `kind` is per-opinion, so the
    opinion id is the natural key. `citations` holds the cluster's own reporter
    cites (frequently empty on recent hand-downs — Texas has no vendor-neutral
    cite, so a fresh opinion simply has none yet); `cites` holds the outbound
    citation graph as CourtListener opinion ids.
    """
    payload = json.loads(content.decode("utf-8", errors="replace"))
    out: list[dict] = []
    for res in payload.get("results", []):
        reporter = [c for c in (res.get("citation") or []) if c]
        if res.get("lexisCite"):
            reporter.append(res["lexisCite"])
        base = {
            "cluster_id": str(res.get("cluster_id") or ""),
            "docket_id": str(res.get("docket_id") or ""),
            "court_id": res.get("court_id"),
            "court_name": res.get("court"),
            "docket": res.get("docketNumber"),
            "style": res.get("caseName"),
            "date_filed": res.get("dateFiled"),
            "citations": reporter,
            "cite_count": res.get("citeCount"),
            "status": res.get("status"),
            "absolute_url": res.get("absolute_url"),
        }
        opinions = res.get("opinions") or [{}]
        for op in opinions:
            op_id = op.get("id")
            rec = dict(base)
            rec.update(
                {
                    "id": f"cl:{op_id}" if op_id else f"cl:cluster:{base['cluster_id']}",
                    "opinion_id": str(op_id or ""),
                    "kind": _norm_kind(op.get("type"), bool(op.get("per_curiam"))),
                    "per_curiam": bool(op.get("per_curiam")),
                    "sha1": op.get("sha1"),
                    "download_url": op.get("download_url"),
                    "author_id": op.get("author_id"),
                    "cites": [f"cl:{c}" for c in (op.get("cites") or [])],
                    "snippet": op.get("snippet") or "",
                }
            )
            out.append(rec)
    return out


def freshness(rows: list[dict]) -> str | None:
    """Max dateFiled actually observed — the audit's CCA-lag guard."""
    dates = [r["date_filed"] for r in rows if r.get("date_filed")]
    return max(dates) if dates else None


def _lag_days(max_date: str | None) -> int | None:
    if not max_date:
        return None
    try:
        return (date.today() - date.fromisoformat(max_date[:10])).days
    except ValueError:
        return None


# ------------------------------------------------------------- Business Court

BIZ_CITE_RE = re.compile(r"(\d{4})\s+Tex\.\s*Bus\.\s*(\d+)")
BIZ_DIV_RE = re.compile(r"\((\d+)(?:st|nd|rd|d|th)\.?\s*Div\.?\)", re.I)  # "3d Div." is live
# Cause numbers on the listing carry live typos ("25.BC01B-0049", "25-BC04B0017",
# "24-BC01B--0010", "25-BC-BC03A-0001"), so the separators are loose and the
# result is re-emitted in the canonical YY-BCddX-NNNN shape.
BIZ_DOCKET_RE = re.compile(r"\b(\d{2})\D{0,4}(BC\d{2}[A-Z]?)\D{0,2}(\d{4})\b", re.I)
# "Adrogué, J. | August 12, 2026" — accented names are live, and one entry
# carries a "Stagner, J," typo, so the punctuation after J is loose.
BIZ_JUDGE_RE = re.compile(
    r"([^\W\d_][\w.'’\- ]{1,40}?)\s*,\s*J[.,]\s*\|\s*"
    r"([A-Z][a-z]+ \d{1,2}[,.] \d{4})"
)
_P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
_PDF_HREF_RE = re.compile(r'href="([^"]+?\.pdf)"', re.I)
_TITLE_RE = re.compile(r'title="([^"]*)"')
_LI_RE = re.compile(r"<li>(.*?)</li>", re.S)


def strip_html(html: str) -> str:
    return _WS.sub(" ", unescape(_TAG.sub(" ", html))).strip()


def _iso_date(human: str | None) -> str | None:
    if not human:
        return None
    # "January 26. 2026" — a period for the comma, twice on the live page.
    human = human.strip().replace(". ", ", ")
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(human, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_bizcourt_listing(content: bytes, base_url: str = BIZCOURT_OPINIONS) -> list[dict]:
    """The Business Court opinions page -> one dict per opinion.

    Verified shape (Aug 2026): an ``<h2>`` per opinion carrying
    "Style, YYYY Tex. Bus. N (Nth Div.) (mem. op.)", then a ``/media/...pdf``
    link whose ``title`` carries the cause number, then "Judge, J. | Date", then
    a staff summary the page itself disclaims as non-authoritative — so the
    summary is stored flagged, never as holding text.
    """
    html = content.decode("utf-8", errors="replace")
    # One <h2> per opinion. The final block runs on into the page's own
    # chrome, so each block is cut at the first closing </div>.
    blocks = re.split(r"(?=<h2>)", html)[1:]
    out: list[dict] = []
    for block in blocks:
        block = re.split(r"</div>", block, maxsplit=1)[0]
        head_m = re.search(r"<h2>(.*?)</h2>", block, re.S)
        cite_m = BIZ_CITE_RE.search(block)
        if not head_m or not cite_m:
            continue
        heading = strip_html(head_m.group(1))
        cite = f"{cite_m.group(1)} Tex. Bus. {cite_m.group(2)}"
        style = re.split(r",?\s*\d{4}\s+Tex\.\s*Bus\.", heading)[0].strip().rstrip(",")

        href_m = _PDF_HREF_RE.search(block)
        pdf_url = urljoin(base_url, unescape(href_m.group(1))) if href_m else None
        title_m = _TITLE_RE.search(block)
        # The title attribute is authoritative for the cause number, but the
        # PDF filename slug is cleaner when the title is typo'd.
        docket_m = BIZ_DOCKET_RE.search(title_m.group(1) if title_m else "")
        if not docket_m and pdf_url:
            docket_m = BIZ_DOCKET_RE.search(pdf_url.rsplit("/", 1)[-1])
        # The byline is its own <p>; scanning paragraphs (rather than the flat
        # block, or <em> elements — one live byline is split across two of
        # them) keeps the link text and the summary's case names out of it.
        judge_m = None
        for para in _P_RE.finditer(block):
            judge_m = BIZ_JUDGE_RE.search(strip_html(para.group(1)))
            if judge_m:
                break
        div_m = BIZ_DIV_RE.search(heading)
        summaries = [strip_html(s) for s in _LI_RE.findall(block)]

        out.append(
            {
                "id": "txcourts:" + cite.lower().replace(" ", "-").replace(".", ""),
                "court": "texbusct",
                "cite": cite,
                "style": style,
                "docket": "-".join(g.upper() for g in docket_m.groups()) if docket_m else None,
                "division": div_m.group(1) if div_m else None,
                "judge": judge_m.group(1).strip() if judge_m else None,
                "date_filed": _iso_date(judge_m.group(2)) if judge_m else None,
                # "(mem. op.)" is on the listing line. Business Court output is
                # persuasive either way (audit §7), but the caption is the
                # court's own designation, so it is preserved rather than
                # flattened into a single "opinion" kind.
                "kind": "memorandum" if "mem. op." in heading.lower() else "opinion",
                "pdf_url": pdf_url,
                # Court staff wrote these and the page disclaims them; keep the
                # text but never treat it as the court's words.
                "summary": " ".join(summaries) or None,
                "summary_authoritative": False,
            }
        )
    return out


# ----------------------------------------------------- statute-citation parser
#
# The audit calls this "the single most valuable and most labor-intensive edge"
# and is explicit that it comes from parsing text, not from any structured
# field — hence provenance 'derived' on every edge minted here.

# Normalized code phrase -> canonical name. Unknown phrases are rejected, which
# is what keeps "Trust Code"/"Bogert's ... Code" short forms out of the graph.
CODE_ALIASES = {
    "government": "Government", "gov't": "Government", "govt": "Government",
    "property": "Property", "prop": "Property",
    "business & commerce": "Business & Commerce", "bus & com": "Business & Commerce",
    "business organizations": "Business Organizations", "bus orgs": "Business Organizations",
    "civil practice & remedies": "Civil Practice & Remedies",
    "civ prac & rem": "Civil Practice & Remedies",
    "tax": "Tax",
    "health & safety": "Health & Safety", "health and safety": "Health & Safety",
    "occupations": "Occupations", "occ": "Occupations",
    "insurance": "Insurance", "ins": "Insurance",
    "education": "Education", "educ": "Education",
    "water": "Water",
    "natural resources": "Natural Resources", "nat res": "Natural Resources",
    "human resources": "Human Resources", "hum res": "Human Resources",
    "transportation": "Transportation", "transp": "Transportation",
    "labor": "Labor", "lab": "Labor",
    "agriculture": "Agriculture", "agric": "Agriculture",
    "finance": "Finance", "fin": "Finance",
    "utilities": "Utilities", "util": "Utilities",
    "local government": "Local Government", "loc gov't": "Local Government",
    "family": "Family", "fam": "Family",
    "alcoholic beverage": "Alcoholic Beverage", "alco bev": "Alcoholic Beverage",
    "election": "Election", "elec": "Election",
    "estates": "Estates", "est": "Estates",
    "penal": "Penal",
    "parks & wildlife": "Parks & Wildlife",
    "special district local laws": "Special District Local Laws",
}

# "TEX. GOV'T CODE § 311.021(2)" / "Texas Government Code Section 551.001" /
# "TEX. PROP. CODE (Trust Code) § 51.0001(8)". The optional parenthetical
# between the code name and the section is a real live form (verified in a
# Business Court opinion).
STATUTE_RE = re.compile(
    r"\b((?:[A-Za-z&][\w'’&.]*\s+){1,4})CODE\b\s*(?:\([^)]{0,40}\)\s*)?"
    r"(?:§{1,2}|&#167;|Sec(?:tion|s?\.))\s*"
    r"(\d[\w.\-]*(?:\([^)\s]{1,8}\))*)",
    re.I,
)
# "22 TAC §501.52" / "22 Tex. Admin. Code § 501.52" — the register connector's
# canonical TAC form, reused verbatim so both feeds land on the same node.
TAC_RE = re.compile(
    r"\b(\d{1,2})\s+(?:TAC|Tex\.\s*Admin\.\s*Code)\s*(?:§{1,2}|&#167;|Sec(?:tion|\.)?)\s*"
    r"([\d.]+)",
    re.I,
)

# Gov't Code §2001.038: the APA declaratory-judgment action challenging an
# agency rule's validity — the reason a lobbyist watches this corpus at all.
RULE_CHALLENGE_SECTION = "2001.038"
RULE_CHALLENGE_CITE = "Government Code §2001.038"


def _canon_code(raw: str) -> str | None:
    phrase = raw.lower().replace("’", "'").replace(".", " ")
    phrase = phrase.replace(" and ", " & ")
    phrase = _WS.sub(" ", phrase).strip()
    # Drop the jurisdiction prefix and any leading citation noise.
    phrase = re.sub(r"^(see|also|e\s*g|cf|the|under|in|of)\s+", "", phrase).strip()
    phrase = re.sub(r"^(tex|texas)\s+", "", phrase).strip()
    while phrase and phrase not in CODE_ALIASES:
        # Trailing words are the code name; leading ones are sentence debris.
        parts = phrase.split(" ", 1)
        if len(parts) == 1:
            return None
        phrase = parts[1]
    return CODE_ALIASES.get(phrase)


def extract_statute_cites(text: str) -> list[dict]:
    """Texas code and TAC citations in opinion text (pure over the text).

    Returns dicts with the pincite (``cite``) and the section-level statute
    node it belongs to (``statute``), because an edge should point at the
    section, not at "§1.201(b)(35)".
    """
    flat = _WS.sub(" ", text.replace("­", ""))
    out: dict[str, dict] = {}
    for m in STATUTE_RE.finditer(flat):
        code = _canon_code(m.group(1))
        if not code:
            continue
        section = m.group(2).rstrip(".,;")
        cite = f"{code} Code §{section}"
        base = section.split("(")[0]
        out.setdefault(
            cite,
            {
                "cite": cite,
                "statute": f"{code} Code §{base}",
                "code": code,
                "section": base,
                "kind": "statute",
            },
        )
    for m in TAC_RE.finditer(flat):
        section = m.group(2).rstrip(".,;")
        cite = f"{m.group(1)} TAC §{section}"
        out.setdefault(
            cite,
            {"cite": cite, "statute": cite, "code": "TAC", "section": section, "kind": "rule"},
        )
    return list(out.values())


def is_rule_challenge(cites: list[dict]) -> bool:
    """True when the opinion cites Gov't Code §2001.038 (APA rule challenge)."""
    return any(
        c["code"] == "Government" and c["section"] == RULE_CHALLENGE_SECTION for c in cites
    )


def pdf_text(pdf_bytes: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


# ------------------------------------------------------------------- storage

def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def store_statute_cites(
    conn: sqlite3.Connection, opinion_id: str, cites: list[dict], doc_id: str | None
) -> int:
    """opinion_cite rows + court_opinion->interprets->statute edges.

    Provenance is 'derived' on every edge: the audit is explicit that nothing
    in the source structurally says an opinion construes a statute.
    """
    for c in cites:
        dbx.upsert(
            conn,
            "opinion_cite",
            {"opinion_id": opinion_id, "cite_type": c["kind"], "cite": c["cite"]},
            ["opinion_id", "cite_type", "cite"],
            update_cols=[],
        )
        dst_type = "rule" if c["kind"] == "rule" else "statute"
        dbx.add_edge(
            conn, "court_opinion", opinion_id, "interprets", dst_type, c["statute"],
            "derived", doc_id,
        )
    if is_rule_challenge(cites):
        dbx.add_edge(
            conn, "court_opinion", opinion_id, "rule_challenge_under", "statute",
            RULE_CHALLENGE_CITE, "derived", doc_id,
        )
        conn.execute(
            "UPDATE court_opinion_meta SET rule_challenge=1 WHERE opinion_id=?", (opinion_id,)
        )
    return len(cites)


def store_cl_opinion(conn: sqlite3.Connection, rec: dict, doc_id: str | None) -> None:
    dbx.upsert(
        conn,
        "court_opinion",
        {
            "id": rec["id"],
            "court": rec.get("court_id"),
            "docket": rec.get("docket"),
            "style": rec.get("style"),
            "date_filed": rec.get("date_filed"),
            "citation": rec["citations"][0] if rec.get("citations") else None,
            "kind": rec.get("kind"),
            "doc_id": doc_id,
        },
        ["id"],
    )
    dbx.upsert(
        conn,
        "court_opinion_meta",
        {
            "opinion_id": rec["id"],
            "source": "courtlistener",
            "cluster_id": rec.get("cluster_id"),
            "docket_id": rec.get("docket_id"),
            "court_id": rec.get("court_id"),
            "judge_raw": str(rec.get("author_id") or "") or None,
            "status": rec.get("status"),
            "per_curiam": int(bool(rec.get("per_curiam"))),
            "cite_count": rec.get("cite_count"),
            "sha1": rec.get("sha1"),
            "download_url": rec.get("download_url"),
            "authority": AUTHORITY.get(rec.get("court_id") or "", "B"),
        },
        ["opinion_id"],
    )
    for cite in rec.get("citations", []):
        dbx.upsert(
            conn,
            "opinion_cite",
            {"opinion_id": rec["id"], "cite_type": "reporter", "cite": cite},
            ["opinion_id", "cite_type", "cite"],
            update_cols=[],
        )
    for cited in rec.get("cites", []):
        dbx.upsert(
            conn,
            "opinion_cite",
            {"opinion_id": rec["id"], "cite_type": "case", "cite": cited},
            ["opinion_id", "cite_type", "cite"],
            update_cols=[],
        )
        # The citation graph is a structured CourtListener field: explicit.
        dbx.add_edge(
            conn, "court_opinion", rec["id"], "cites", "court_opinion", cited, "explicit", doc_id
        )
    if rec.get("court_id"):
        dbx.add_edge(
            conn, "court_opinion", rec["id"], "decided_by", "court", rec["court_id"],
            "explicit", doc_id,
        )


def store_biz_opinion(conn: sqlite3.Connection, rec: dict, doc_id: str | None) -> None:
    dbx.upsert(
        conn,
        "court_opinion",
        {
            "id": rec["id"],
            "court": "texbusct",
            "docket": rec.get("docket"),
            "style": rec.get("style"),
            "date_filed": rec.get("date_filed"),
            "citation": rec["cite"],
            "kind": rec.get("kind"),
            "doc_id": doc_id,
        },
        ["id"],
    )
    dbx.upsert(
        conn,
        "court_opinion_meta",
        {
            "opinion_id": rec["id"],
            "source": "txcourts",
            "court_id": "texbusct",
            "division": rec.get("division"),
            "judge_raw": rec.get("judge"),
            "download_url": rec.get("pdf_url"),
            "summary": rec.get("summary"),
            "summary_authoritative": 0,
            "authority": AUTHORITY["texbusct"],
        },
        ["opinion_id"],
    )
    dbx.upsert(
        conn,
        "opinion_cite",
        {"opinion_id": rec["id"], "cite_type": "reporter", "cite": rec["cite"]},
        ["opinion_id", "cite_type", "cite"],
        update_cols=[],
    )
    dbx.add_edge(
        conn, "court_opinion", rec["id"], "decided_by", "court", "texbusct", "explicit", doc_id
    )


def record_freshness(
    conn: sqlite3.Connection, court: str, rows: list[dict], total: int | None = None
) -> dict:
    """Store what the feed's leading edge actually was, per the audit's
    CourtListener-lag caveat. A stale feed must be visible, not assumed."""
    max_date = freshness(rows)
    stat = {
        "court": court,
        "max_date_filed": max_date,
        "observed_at": _now(),
        "sample_size": len(rows),
        "total_available": total,
        "lag_days": _lag_days(max_date),
    }
    dbx.upsert(conn, "court_source_freshness", stat, ["court"])
    return stat


@register
class CourtsConnector(Connector):
    name = "courts"
    tier = 2
    cadence = "weekly"

    DDL = """
    CREATE TABLE IF NOT EXISTS court_opinion_meta (
        opinion_id  TEXT PRIMARY KEY REFERENCES court_opinion(id),
        source      TEXT NOT NULL,            -- courtlistener|txcourts
        cluster_id  TEXT,
        docket_id   TEXT,
        court_id    TEXT,
        division    TEXT,                     -- Business Court division number
        judge_raw   TEXT,
        status      TEXT,                     -- CourtListener Published/Unpublished
        per_curiam  INTEGER,
        cite_count  INTEGER,
        sha1        TEXT,                     -- change detection on the PDF
        download_url TEXT,
        summary     TEXT,                     -- Business Court staff summary
        summary_authoritative INTEGER DEFAULT 0,   -- always 0: page disclaims them
        rule_challenge INTEGER DEFAULT 0,     -- cites Gov't Code §2001.038
        authority   TEXT                      -- A/B/C per audit §7
    );

    CREATE TABLE IF NOT EXISTS court_source_freshness (
        court           TEXT PRIMARY KEY,
        max_date_filed  TEXT,                 -- leading edge actually observed
        observed_at     TEXT,
        sample_size     INTEGER,
        total_available INTEGER,
        lag_days        INTEGER
    );
    """

    # ------------------------------------------------------------ ingestion
    def sync_courtlistener(
        self, conn: sqlite3.Connection, court: str = "tex", **params
    ) -> dict:
        url = f"{CL_SEARCH}?court={court}&format=json"
        for k, v in params.items():
            url += f"&{k}={v}"
        resp = fetcher().get(url)
        if resp.status_code != 200:
            # 429 is routine on the anonymous API (measured: one search per
            # ~23 minutes). Surface it instead of failing the whole run.
            return {
                "court": court,
                "status": resp.status_code,
                "opinions": 0,
                "throttled": resp.status_code == 429,
            }
        doc_id = f"courts:courtlistener:search:{court}"
        store_document(
            conn, doc_id=doc_id, source_family="courts", content=resp.content, url=url,
            doc_type="courtlistener_search", authority=AUTHORITY.get(court, "B"),
        )
        rows = parse_courtlistener(resp.content)
        for rec in rows:
            store_cl_opinion(conn, rec, doc_id)
        total = json.loads(resp.content.decode("utf-8", errors="replace")).get("count")
        stat = record_freshness(conn, court, rows, total)
        conn.commit()
        return {
            "court": court,
            "status": 200,
            "opinions": len(rows),
            "throttled": False,
            "with_dates": sum(1 for r in rows if r.get("date_filed")),
            "cite_rows": sum(len(r["cites"]) + len(r["citations"]) for r in rows),
            "max_date_filed": stat["max_date_filed"],
            "lag_days": stat["lag_days"],
            "total_available": total,
        }

    def poll_business_court(
        self, conn: sqlite3.Connection, pdf_samples: int = 0
    ) -> dict:
        """Poll the one listing page (never crawl — 720s crawl-delay) and
        optionally pull N opinion PDFs, which is where statute cites live."""
        resp = fetcher().get(BIZCOURT_OPINIONS)
        resp.raise_for_status()
        doc_id = "courts:txcourts:businesscourt:opinions"
        store_document(
            conn, doc_id=doc_id, source_family="courts", content=resp.content,
            url=BIZCOURT_OPINIONS, doc_type="businesscourt_listing",
            authority=AUTHORITY["texbusct"],
        )
        rows = parse_bizcourt_listing(resp.content)
        for rec in rows:
            store_biz_opinion(conn, rec, doc_id)
        conn.commit()

        pdfs, cites = 0, 0
        for rec in rows[:pdf_samples]:
            if not rec.get("pdf_url"):
                continue
            cites += self.ingest_opinion_pdf(conn, rec)
            pdfs += 1
        stat = record_freshness(conn, "texbusct", rows, len(rows))
        conn.commit()
        return {
            "court": "texbusct",
            "entries": len(rows),
            "with_cite": sum(1 for r in rows if r.get("cite")),
            "pdfs": pdfs,
            "statute_cites": cites,
            "max_date_filed": stat["max_date_filed"],
        }

    def ingest_opinion_pdf(self, conn: sqlite3.Connection, rec: dict) -> int:
        """Fetch one opinion PDF, store the artifact, then derive statute cites."""
        resp = fetcher().get(rec["pdf_url"])
        resp.raise_for_status()
        doc_id = f"courts:opinion:{rec['id']}"
        store_document(
            conn, doc_id=doc_id, source_family="courts", content=resp.content,
            url=rec["pdf_url"], native_id=rec.get("docket"), doc_type="opinion_pdf",
            published_at=rec.get("date_filed"), authority=AUTHORITY.get(rec["court"], "C"),
        )
        conn.execute("UPDATE court_opinion SET doc_id=? WHERE id=?", (doc_id, rec["id"]))
        cites = extract_statute_cites(pdf_text(resp.content))
        n = store_statute_cites(conn, rec["id"], cites, doc_id)
        conn.commit()
        return n

    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """Weekly: CourtListener for the indexed courts, direct poll for the
        courts it doesn't index. Request budget is explicit."""
        courts = kwargs.get("courts") or list(CL_COURTS)
        pdf_samples = int(kwargs.get("pdf_samples", 1))
        cl = [self.sync_courtlistener(conn, c) for c in courts]
        biz = self.poll_business_court(conn, pdf_samples=pdf_samples)
        return {
            "courtlistener": cl,
            "business_court": biz,
            "opinions": conn.execute("SELECT COUNT(*) c FROM court_opinion").fetchone()["c"],
            "cites": conn.execute("SELECT COUNT(*) c FROM opinion_cite").fetchone()["c"],
            "freshness": [
                dict(r) for r in conn.execute(
                    "SELECT court, max_date_filed, lag_days FROM court_source_freshness"
                )
            ],
        }

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """<=3 live requests: one CourtListener search, the Business Court
        listing, and one opinion PDF."""
        cl = self.sync_courtlistener(conn, "tex")
        biz = self.poll_business_court(conn, pdf_samples=1)
        stats = {
            "cl_opinions": cl["opinions"],
            "cl_status": cl["status"],
            "cl_throttled": cl.get("throttled", False),
            "cl_freshness": cl.get("max_date_filed"),
            "cl_lag_days": cl.get("lag_days"),
            "cl_cite_rows": cl.get("cite_rows", 0),
            "biz_entries": biz["entries"],
            "biz_with_cite": biz["with_cite"],
            "biz_statute_cites": biz["statute_cites"],
            "biz_latest": biz["max_date_filed"],
        }
        biz_ok = biz["entries"] >= 3 and biz["with_cite"] >= 3
        if stats["cl_throttled"]:
            # Anonymous CourtListener throttling is a known operating condition,
            # not a broken source; the first-mover half must still pass.
            return SmokeResult(
                ok=biz_ok,
                detail=(
                    f"CourtListener throttled (429); Business Court {biz['entries']} entries, "
                    f"latest {biz['max_date_filed']}, {biz['statute_cites']} statute cites"
                ),
                stats=stats,
            )
        cl_ok = cl["opinions"] >= 5 and cl["with_dates"] >= 5 and cl["cite_rows"] >= 5
        return SmokeResult(
            ok=cl_ok and biz_ok,
            detail=(
                f"CourtListener tex: {cl['opinions']} opinions, freshness "
                f"{cl['max_date_filed']} ({cl['lag_days']}d lag of {cl['total_available']} "
                f"indexed); Business Court: {biz['entries']} entries, latest "
                f"{biz['max_date_filed']}, {biz['statute_cites']} statute cites"
            ),
            stats=stats,
        )
