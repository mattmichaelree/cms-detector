"""LBB — Legislative Budget Board: fiscal notes, GAA riders, and the
Comptroller's Certification Revenue Estimate index.

Spec: docs/texas-politics-audit/03-deep-dives/08-lbb.md (+ 09-comptroller.md
for the CRE). Three corpora, three very different shapes:

  * **Fiscal notes** — statutorily mandated LBB estimates that live on TLO,
    not lbb.texas.gov: ``tlodocs/{session}/fiscalnotes/html/{BILLCODE}{V}.htm``.
    **A distinct note exists per bill version**, and the numbers move between
    them (the audit's version trap: 89R SB 2's Introduced and Engrossed notes
    disagree). Everything here is keyed on (session, bill, version code) so a
    citation can never be version-less.
  * **GAA riders** — the appropriations text layer. The full GAA PDF is >10MB
    (2026-27 measured at 13.1MB) and is therefore probed, never downloaded;
    the per-article rider dockets are small and carry a real text layer.
  * **CRE** — the Comptroller's certification estimates, one landing page per
    biennium plus mid-biennium revisions; the current biennium ships PDF+XLSX.

Parsers are pure functions over bytes; every fetched artifact is stored in the
document store before it is parsed.
"""

from __future__ import annotations

import re
import sqlite3
from html import unescape

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

TLO = "https://capitol.texas.gov"
LBB = "https://www.lbb.texas.gov"
CPA = "https://comptroller.texas.gov"

CRE_INDEX = f"{CPA}/transparency/reports/certification-revenue-estimate/"

#: TLO version letters, in the order a bill moves through them. 404 is the
#: normal answer for most of them on most bills.
VERSION_CODES = ("I", "H", "S", "E", "F")
VERSION_NAMES = {
    "I": "Introduced",
    "H": "House Committee Report",
    "S": "Senate Committee Report",
    "E": "Engrossed",
    "F": "Enrolled",
}

#: Nothing larger than this is pulled over the wire (audit failure mode: the
#: GAA PDFs blow past fetch limits).
MAX_DOWNLOAD = 5 * 1024 * 1024


# --------------------------------------------------------------- URL shapes
def bill_code(bill_type: str, number: int) -> str:
    """('SB', 2) → 'SB00002' — TLO's zero-padded document code."""
    return f"{bill_type.upper()}{int(number):05d}"


def fiscal_note_url(session: str, code: str, version: str, fmt: str = "html") -> str:
    ext = "htm" if fmt == "html" else "pdf"
    return f"{TLO}/tlodocs/{session}/fiscalnotes/{fmt}/{code.upper()}{version.upper()}.{ext}"


def gaa_url(start_year: int, end_year: int) -> str:
    return f"{LBB}/Documents/GAA/General_Appropriations_Act_{start_year}_{end_year}.pdf"


def bill_id(session: str, bill_type: str, number: int) -> str:
    return f"{session}-{bill_type.upper()}{int(number)}"


# ------------------------------------------------------------ HTML helpers
_TAG_RE = re.compile(r"<[^>]+>")
_TABLE_RE = re.compile(r"<table\b[^>]*>(.*?)</table>", re.I | re.S)
_TABLE_ID_RE = re.compile(r"<table\b[^>]*\bid\s*=\s*[\"']?([\w\-]+)", re.I)
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
_CELL_RE = re.compile(r"<(t[dh])\b[^>]*>(.*?)</\1>", re.I | re.S)
_ITALIC_RE = re.compile(r"<i\b[^>]*>(.*?)</i>", re.I | re.S)
_MONEY_RE = re.compile(r"^\(?\$\s*(-?[\d,]+(?:\.\d+)?)\)?$")
_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{1,2}),\s*(\d{4})\b"
)
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        "January February March April May June July August September October "
        "November December".split()
    )
}
_NO_SIGNIFICANT = "No significant fiscal implication to the State is anticipated"


def _text(html: str) -> str:
    """Tags out, entities decoded, whitespace normalised."""
    s = re.sub(r"<br\s*/?>", " ", html, flags=re.I)
    s = _TAG_RE.sub(" ", s)
    return re.sub(r"\s+", " ", unescape(s).replace("\xa0", " ")).strip()


def _div(html: str, div_id: str) -> str | None:
    """Innermost-safe grab of a <div id=...> body (LBB nests divs, so we take
    the opening tag's position and balance from there)."""
    m = re.search(r"<div[^>]*\bid\s*=\s*[\"']?" + re.escape(div_id) + r"[\"']?[^>]*>", html, re.I)
    if not m:
        return None
    depth, i = 1, m.end()
    for tok in re.finditer(r"<div\b|</div>", html[m.end():], re.I):
        depth += 1 if tok.group(0).lower().startswith("<div") else -1
        if depth == 0:
            i = m.end() + tok.start()
            break
    else:
        i = len(html)
    return html[m.end(): i]


def parse_money(raw: str) -> float | None:
    """'($4,821,000,000)' → -4821000000.0 · '$0' → 0.0 · '42.0' → None.

    Parenthesised is negative (accounting notation, and the LBB's rows are
    labelled 'Probable Net Positive/(Negative) Impact'). A cell without a
    currency sign is not money — the FTE column in every note looks numeric
    and must never land in fiscal_estimate.
    """
    s = (raw or "").strip().replace("\xa0", " ")
    s = re.sub(r"\s+", "", s)
    if not s or "$" not in s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    m = _MONEY_RE.match(s)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return -val if neg else val


def _parse_header_cell(cell_html: str) -> tuple[str, str, str | None]:
    """A fiscal-implications column header → (label, fund, fund_code).

    'Probable Savings/(Cost) from<br /><i>General Revenue Fund</i><br />1'
    → ('Probable Savings/(Cost) from', 'General Revenue Fund', '1')
    """
    it = _ITALIC_RE.search(cell_html)
    if it:
        fund = _text(it.group(1))
        label = _text(cell_html[: it.start()])
        tail = _text(cell_html[it.end():])
        code = tail if re.fullmatch(r"\d{1,4}", tail) else None
    else:
        fund, label, code = _text(cell_html), "", None
    return label, fund, code


def _fund_key(fund: str, code: str | None) -> str:
    return f"{fund} ({code})" if code else fund


def parse_fiscal_implications(html: str) -> list[dict]:
    """Every fiscal-implications table in a note.

    A table qualifies when its header row starts with 'Fiscal Year'; each
    later row starting with a 4-digit year contributes one cell per fund
    column. Notes carry more than one such table (GR-related summary + all
    funds + per-agency splits), so the table id travels with the rows.
    """
    tables: list[dict] = []
    for tm in _TABLE_RE.finditer(html):
        body = tm.group(1)
        tid_m = _TABLE_ID_RE.match(tm.group(0))
        tid = tid_m.group(1) if tid_m else f"table{len(tables) + 1}"
        rows = _ROW_RE.findall(body)
        if not rows:
            continue
        header = [(tag.lower(), h) for tag, h in _CELL_RE.findall(rows[0])]
        if not header or not _text(header[0][1]).lower().startswith("fiscal year"):
            continue
        columns = [_parse_header_cell(h) for _, h in header[1:]]
        table = {"table_id": tid, "columns": [], "rows": []}
        for label, fund, code in columns:
            table["columns"].append({"label": label, "fund": fund, "fund_code": code})
        for row in rows[1:]:
            cells = [_text(c) for _, c in _CELL_RE.findall(row)]
            if not cells or not re.fullmatch(r"\d{4}", cells[0]):
                continue
            table["rows"].append({"fiscal_year": int(cells[0]), "cells": cells[1:]})
        if table["rows"]:
            tables.append(table)
    return tables


def parse_fiscal_note(content: bytes) -> dict:
    """Fiscal-note HTML → structured note.

    Handles both published forms: the table form (SB 2) and the bare
    'No significant fiscal implication to the State is anticipated' form
    (HB 796) — which is a finding, not a parse failure.
    """
    html = content.decode("utf-8", errors="replace")
    out: dict = {
        "bill": None,
        "session_label": None,
        "version_label": None,
        "date": None,
        "caption": None,
        "summary": None,
        "no_significant_impact": False,
        "two_year_net_impact": None,
        "tables": [],
        "estimates": [],
        "agencies": [],
        "lbb_staff": [],
    }

    hdr = _div(html, "divImpactType") or ""
    out["session_label"] = _text(hdr) or None

    in_re = _div(html, "divEditInRe") or ""
    if in_re:
        bm = re.search(r"<b>\s*([A-Z]{2,4}\s*\d+)\s*</b>", in_re, re.I)
        if bm:
            out["bill"] = re.sub(r"\s+", "", bm.group(1)).upper()
        cm = re.search(r"\(([^()]{5,400})\)", _text(in_re))
        if cm:
            out["caption"] = cm.group(1).strip()
        vm = re.findall(r"<b>\s*(As [^<]+?)\s*</b>", in_re, re.I)
        if vm:
            out["version_label"] = re.sub(r"\s+", " ", vm[-1]).strip()

    # The letter's date sits in the heading block, above the TO:/FROM: table.
    head = html[: html.find("divEditSalutation")] if "divEditSalutation" in html else html[:6000]
    dm = _DATE_RE.search(_text(head))
    if dm:
        out["date"] = f"{dm.group(3)}-{_MONTHS[dm.group(1)]:02d}-{int(dm.group(2)):02d}"

    summary = _text(_div(html, "divSumStmt") or "")
    out["summary"] = summary or None
    if _NO_SIGNIFICANT.lower() in summary.lower():
        out["no_significant_impact"] = True
    nm = re.search(r"impact of\s*(\(?\$[\d,]+\)?)", summary, re.I)
    if nm:
        val = parse_money(nm.group(1))
        if val is not None and re.search(r"negative impact", summary, re.I) and val > 0:
            val = -val
        out["two_year_net_impact"] = val

    out["tables"] = parse_fiscal_implications(html)

    # Flatten to (year, fund, amount). Fund labels repeat across tables (the
    # GR summary and the all-funds table both report General Revenue), so a
    # label reused by a later table is disambiguated with its table id — the
    # rows are different estimates and must not collide on the primary key.
    owner: dict[str, str] = {}
    for table in out["tables"]:
        keys = []
        for col in table["columns"]:
            key = _fund_key(col["fund"], col["fund_code"])
            if owner.setdefault(key, table["table_id"]) != table["table_id"]:
                key = f"{key} [{table['table_id']}]"
            keys.append(key)
        for row in table["rows"]:
            for key, cell in zip(keys, row["cells"], strict=False):
                amount = parse_money(cell)
                if amount is None:
                    continue  # FTE counts and blanks are not fiscal estimates
                out["estimates"].append(
                    {
                        "fiscal_year": row["fiscal_year"],
                        "fund": key,
                        "amount": amount,
                        "table_id": table["table_id"],
                    }
                )

    agencies = _text(_div(html, "divEditAgySource") or "")
    for part in agencies.split(","):
        am = re.match(r"\s*(\d{3})\s+(.+?)\s*$", part)
        if am:
            out["agencies"].append((am.group(1), am.group(2)))
    staff = _text(_div(html, "divEditLBBSource") or "")
    out["lbb_staff"] = [s.strip() for s in staff.split(",") if s.strip()]
    return out


# ------------------------------------------------------------- GAA riders
_RIDER_HDR = re.compile(r"Sec\.\s*(\d+\.\d+)\.\s*")
#: A conference-committee rider docket prints Senate and House side by side,
#: so the same section header appears twice on one extracted line.
_TWO_COL = re.compile(r"Sec\.\s*(\d+\.\d+)\.[^\n]*Sec\.\s*\1\.")


def _rider_sections(buf: str) -> list[tuple[str, str, str]]:
    heads = list(_RIDER_HDR.finditer(buf))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(buf)
        body = buf[m.end(): end].strip()
        if not body:
            continue
        title = re.sub(r"\s+", " ", re.split(r"\.(?:\s|$)", body, maxsplit=1)[0]).strip()
        out.append((m.group(1), title, body))
    return out


def parse_riders(pdf_bytes: bytes) -> list[dict]:
    """Rider-packet PDF bytes → [{section_no, title, text}].

    Pure over bytes. Two-column comparison dockets are split into their
    Senate/House halves before section splitting, otherwise the columns
    interleave line-by-line and every rider comes out doubled; single-column
    pages are read whole. Sections that appear in both halves are merged on
    the section number, keeping the fuller text.
    """
    import io

    import pdfplumber

    left: list[str] = []
    right: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if _TWO_COL.search(text):
                mid = page.width / 2
                left.append(page.crop((0, 0, mid, page.height)).extract_text() or "")
                right.append(page.crop((mid, 0, page.width, page.height)).extract_text() or "")
            else:
                left.append(text)

    merged: dict[str, dict] = {}
    for buf in ("\n".join(left), "\n".join(right)):
        for section_no, title, body in _rider_sections(buf):
            prev = merged.get(section_no)
            if prev is None or len(body) > len(prev["text"]):
                merged[section_no] = {"section_no": section_no, "title": title, "text": body}
    return sorted(
        merged.values(),
        key=lambda r: [int(p) for p in r["section_no"].split(".")],
    )


# ----------------------------------------------------------------- the CRE
_LINK_RE = re.compile(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_BIENNIUM_RE = re.compile(
    r"/certification-revenue-estimate/(\d{4}-\d{2})(?:-(update|revised[\w-]*))?/?$", re.I
)


def parse_cre_index(content: bytes) -> list[dict]:
    """CRE index HTML → one row per estimate edition.

    Each biennium has a landing page; mid-biennium revisions get their own
    ('-update') page — the Comptroller's version trap, and the reason
    revision is part of the identity rather than a footnote.
    """
    html = content.decode("utf-8", errors="replace")
    seen: set[str] = set()
    out: list[dict] = []
    for href, label_html in _LINK_RE.findall(html):
        url = href if href.startswith("http") else f"{CPA}{href}" if href.startswith("/") else None
        if not url:
            continue
        label = _text(label_html)
        bm = _BIENNIUM_RE.search(href.split("?")[0])
        if bm:
            biennium, revision = bm.group(1), bm.group(2)
            rm = re.search(r"Revised\s+([A-Za-z]+\s+\d{4})", label, re.I)
            if rm:
                revision = rm.group(1)
            kind = "cre"
        elif re.search(r"/certification-revenue-estimate/[\d-]+/.*\.(pdf|xlsx)$", href, re.I):
            fm = re.search(r"/certification-revenue-estimate/(\d{4}-\d{2})", href)
            biennium = fm.group(1) if fm else None
            revision = None
            kind = "cre_xlsx" if href.lower().endswith(".xlsx") else "cre_pdf"
        else:
            continue
        key = f"{kind}:{biennium}:{revision or ''}:{url}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "id": f"{kind}:{biennium}" + (f":{revision}" if revision else ""),
                "kind": kind,
                "biennium": biennium,
                "revision": revision,
                "url": url,
                "label": label,
            }
        )
    return out


# ---------------------------------------------------------------- connector
@register
class LBBConnector(Connector):
    """Fiscal notes (tier 0, polled in session) + riders + CRE."""

    name = "lbb"
    tier = 0
    cadence = "daily_in_session"

    DDL = """
    CREATE TABLE IF NOT EXISTS gaa_rider (
        id         INTEGER PRIMARY KEY,
        biennium   TEXT,
        article    TEXT,
        section_no TEXT,
        title      TEXT,
        text       TEXT,
        doc_id     TEXT,
        UNIQUE (biennium, article, section_no)
    );

    CREATE TABLE IF NOT EXISTS revenue_estimate (
        id        TEXT PRIMARY KEY,
        kind      TEXT,
        biennium  TEXT,
        revision  TEXT,
        url       TEXT,
        doc_id    TEXT,
        size_bytes INTEGER
    );

    CREATE INDEX IF NOT EXISTS idx_gaa_rider_section ON gaa_rider(section_no);
    """

    # -- fiscal notes ----------------------------------------------------
    def ingest_fiscal_note(
        self, conn: sqlite3.Connection, session: str, billcode: str, version: str
    ) -> dict | None:
        """One (session, bill, version) fiscal note → fiscal_note +
        fiscal_estimate rows. Returns None when TLO has no note for that
        version (404 is the normal answer for most version letters)."""
        version = version.upper()
        url = fiscal_note_url(session, billcode, version)
        resp = fetcher().get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()

        doc_id = f"lbb:fiscalnote:{session}:{billcode.upper()}{version}"
        _, changed = store_document(
            conn,
            doc_id=doc_id,
            source_family="lbb",
            content=resp.content,
            url=url,
            native_id=f"{billcode.upper()}{version}",
            doc_type="fiscal_note",
            session_id=session,
            authority="A",
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )
        parsed = parse_fiscal_note(resp.content)
        stats = self.store_fiscal_note(conn, session, billcode, version, parsed, doc_id)
        conn.commit()
        stats["changed"] = changed
        stats["url"] = url
        return stats

    def store_fiscal_note(
        self,
        conn: sqlite3.Connection,
        session: str,
        billcode: str,
        version: str,
        parsed: dict,
        doc_id: str,
    ) -> dict:
        m = re.match(r"([A-Z]{2,4})0*(\d+)$", billcode.upper())
        if not m:
            raise ValueError(f"unparseable bill code: {billcode!r}")
        btype, number = m.group(1), int(m.group(2))
        bid = bill_id(session, btype, number)

        dbx.ensure_session(conn, session)
        bill_row = {"id": bid, "session_id": session, "bill_type": btype, "number": number}
        if parsed.get("caption"):
            bill_row["caption"] = parsed["caption"]
            dbx.upsert(conn, "bill", bill_row, ["id"], update_cols=["caption"])
        else:
            dbx.upsert(conn, "bill", bill_row, ["id"], update_cols=[])
        dbx.upsert(
            conn,
            "bill_version",
            {
                "bill_id": bid,
                "stage_code": version,
                "stage_name": VERSION_NAMES.get(version),
                "date": parsed.get("date"),
                "doc_id": None,
            },
            ["bill_id", "stage_code"],
            update_cols=[],
        )
        dbx.upsert(
            conn,
            "fiscal_note",
            {
                "bill_id": bid,
                "version_code": version,
                "date": parsed.get("date"),
                "doc_id": doc_id,
                "summary": parsed.get("summary"),
            },
            ["bill_id", "version_code"],
        )
        note_id = conn.execute(
            "SELECT id FROM fiscal_note WHERE bill_id=? AND version_code=?", (bid, version)
        ).fetchone()["id"]

        for est in parsed["estimates"]:
            dbx.upsert(
                conn,
                "fiscal_estimate",
                {
                    "fiscal_note_id": note_id,
                    "fiscal_year": est["fiscal_year"],
                    "fund": est["fund"],
                    "amount": est["amount"],
                },
                ["fiscal_note_id", "fiscal_year", "fund"],
            )

        note_key = f"{bid}:{version}"
        dbx.add_edge(conn, "bill_version", note_key, "has_fiscal_note", "fiscal_note",
                     note_key, "explicit", doc_id)
        for fund in sorted({e["fund"] for e in parsed["estimates"]}):
            dbx.add_edge(conn, "fiscal_note", note_key, "estimates_impact_to", "fund",
                         fund, "explicit", doc_id)
        for code, name in parsed["agencies"]:
            dbx.add_edge(conn, "fiscal_note", note_key, "cites", "agency_code", code,
                         "explicit", doc_id, span=name)
        return {
            "bill_id": bid,
            "version": version,
            "note_id": note_id,
            "estimates": len(parsed["estimates"]),
            "fiscal_years": sorted({e["fiscal_year"] for e in parsed["estimates"]}),
            "agencies": [c for c, _ in parsed["agencies"]],
            "no_significant_impact": parsed["no_significant_impact"],
            "two_year_net_impact": parsed["two_year_net_impact"],
            "doc_id": doc_id,
        }

    def ingest_bill_fiscal_notes(
        self,
        conn: sqlite3.Connection,
        session: str,
        billtype: str,
        number: int,
        versions: tuple[str, ...] = VERSION_CODES,
    ) -> dict:
        """Sweep a bill's version letters. Most 404 — that is coverage data,
        not an error: the set of versions that DO have notes is exactly the
        set of stages at which the LBB re-scored the bill."""
        code = bill_code(billtype, number)
        found: dict[str, dict] = {}
        missing: list[str] = []
        for version in versions:
            stats = self.ingest_fiscal_note(conn, session, code, version)
            if stats is None:
                missing.append(version)
            else:
                found[version] = stats
        return {
            "bill": bill_id(session, billtype, number),
            "found": found,
            "versions": sorted(found),
            "missing": missing,
        }

    def backfill(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """backfill(session='89R', bills=[('SB', 2), ('HB', 796)])"""
        session = kwargs.get("session", "89R")
        bills = kwargs.get("bills") or []
        out = {}
        for btype, num in bills:
            out[f"{btype}{num}"] = self.ingest_bill_fiscal_notes(conn, session, btype, num)
        return {"session": session, "bills": out}

    # -- riders ----------------------------------------------------------
    def probe(self, url: str) -> dict:
        """HEAD only — used for artifacts we refuse to download blind."""
        resp = fetcher().head(url)
        size = resp.headers.get("Content-Length")
        return {
            "url": url,
            "status": resp.status_code,
            "size": int(size) if size and size.isdigit() else None,
            "content_type": resp.headers.get("Content-Type"),
            "too_large": bool(size and size.isdigit() and int(size) > MAX_DOWNLOAD),
        }

    def ingest_riders(
        self,
        conn: sqlite3.Connection,
        url: str,
        biennium: str,
        article: str,
        content: bytes | None = None,
    ) -> dict:
        """Rider packet → gaa_rider rows. Pass `content` to parse bytes you
        already have; otherwise the packet is size-probed before download."""
        doc_id = f"lbb:riders:{biennium}:{article}"
        if content is None:
            probe = self.probe(url)
            if probe["too_large"]:
                return {"skipped": "too_large", **probe}
            resp = fetcher().get(url)
            resp.raise_for_status()
            content = resp.content
        store_document(
            conn,
            doc_id=doc_id,
            source_family="lbb",
            content=content,
            url=url,
            doc_type="gaa_rider_packet",
            authority="A",
        )
        riders = parse_riders(content)
        for rider in riders:
            dbx.upsert(
                conn,
                "gaa_rider",
                {
                    "biennium": biennium,
                    "article": article,
                    "section_no": rider["section_no"],
                    "title": rider["title"],
                    "text": rider["text"],
                    "doc_id": doc_id,
                },
                ["biennium", "article", "section_no"],
            )
        conn.commit()
        return {"biennium": biennium, "article": article, "riders": len(riders), "doc_id": doc_id}

    # -- CRE -------------------------------------------------------------
    def ingest_cre(self, conn: sqlite3.Connection, download_data: bool = True) -> dict:
        """CRE index → revenue_estimate rows; the current biennium's PDF and
        XLSX are probed, and the XLSX stored only if it is under the download
        cap (and only when the server declares a size — an undeclared length
        is treated as too large, not as permission)."""
        resp = fetcher().get(CRE_INDEX)
        resp.raise_for_status()
        index_doc = "lbb:cre:index"
        store_document(
            conn,
            doc_id=index_doc,
            source_family="cpa",
            content=resp.content,
            url=CRE_INDEX,
            doc_type="cre_index",
            authority="A",
        )
        entries = parse_cre_index(resp.content)
        probes: dict[str, dict] = {}
        downloaded: list[str] = []
        # Only the current biennium's files are probed; the archive's ~20
        # editions are catalogued from the index alone (one request, not 20).
        current = max((e["biennium"] for e in entries if e["biennium"]), default=None)
        for entry in entries:
            doc_id = None
            size = None
            if entry["kind"] in ("cre_pdf", "cre_xlsx") and entry["biennium"] == current:
                probe = self.probe(entry["url"])
                probes[entry["kind"]] = probe
                size = probe["size"]
                if (
                    download_data
                    and entry["kind"] == "cre_xlsx"
                    and size is not None
                    and size <= MAX_DOWNLOAD
                ):
                    data = fetcher().get(entry["url"])
                    if data.status_code == 200:
                        doc_id = f"lbb:cre:data:{entry['biennium']}"
                        store_document(
                            conn,
                            doc_id=doc_id,
                            source_family="cpa",
                            content=data.content,
                            url=entry["url"],
                            doc_type="cre_data",
                            authority="A",
                        )
                        downloaded.append(entry["url"])
            dbx.upsert(
                conn,
                "revenue_estimate",
                {
                    "id": entry["id"],
                    "kind": entry["kind"],
                    "biennium": entry["biennium"],
                    "revision": entry["revision"],
                    "url": entry["url"],
                    "doc_id": doc_id or (index_doc if entry["kind"] == "cre" else None),
                    "size_bytes": size,
                },
                ["id"],
            )
        conn.commit()
        bienniums = sorted({e["biennium"] for e in entries if e["biennium"]})
        return {
            "entries": len(entries),
            "bienniums": bienniums,
            "revisions": [e["id"] for e in entries if e["revision"]],
            "probes": probes,
            "downloaded": downloaded,
        }

    # -- smoke -----------------------------------------------------------
    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """The version trap, proven live: 89R SB 2's Introduced and Engrossed
        fiscal notes are separate documents with different numbers."""
        code = bill_code("SB", 2)
        results = {}
        for version in ("I", "E"):
            stats = self.ingest_fiscal_note(conn, "89R", code, version)
            if stats is None:
                return SmokeResult(ok=False, detail=f"89R SB2 version {version} not found")
            results[version] = stats

        totals = {}
        for version, stats in results.items():
            rows = conn.execute(
                "SELECT fiscal_year, fund, amount FROM fiscal_estimate WHERE fiscal_note_id=?",
                (stats["note_id"],),
            ).fetchall()
            totals[version] = {(r["fiscal_year"], r["fund"]): r["amount"] for r in rows}

        years = {v: {y for y, _ in t} for v, t in totals.items()}
        has_table = any(len(y) >= 3 for y in years.values())
        shared = set(totals["I"]) & set(totals["E"])
        differing = {k: (totals["I"][k], totals["E"][k]) for k in shared if totals["I"][k] != totals["E"][k]}
        ok = bool(results) and has_table and bool(differing)
        sample = sorted(differing.items())[:3]
        detail = (
            f"89R SB2: versions {sorted(results)}; "
            f"FY {sorted(years['I'])} (I) / {sorted(years['E'])} (E); "
            f"{len(differing)} of {len(shared)} shared cells differ between I and E; "
            f"two-year net I={results['I']['two_year_net_impact']} "
            f"E={results['E']['two_year_net_impact']}; sample={sample}"
        )
        return SmokeResult(
            ok=ok,
            detail=detail,
            stats={
                "versions": sorted(results),
                "estimates": {v: s["estimates"] for v, s in results.items()},
                "fiscal_years": {v: sorted(y) for v, y in years.items()},
                "differing_cells": len(differing),
                "shared_cells": len(shared),
                "two_year_net_impact": {
                    v: s["two_year_net_impact"] for v, s in results.items()
                },
                "sample_differences": [
                    {"fiscal_year": k[0], "fund": k[1], "introduced": a, "engrossed": b}
                    for (k, (a, b)) in sample
                ],
            },
        )
