"""TEC — Texas Ethics Commission bulk campaign-finance and lobby-activity data.

Spec: docs/texas-politics-audit/03-deep-dives/14-tec.md.

TEC publishes no API. Everything of value ships as two nightly-rebuilt ZIPs
whose links live on the legacy search pages. Four audited facts shape this
module, and each one is a defence against a specific way of being wrong:

1. **Never hardcode the ZIP path.** The legacy front end (Apache 2.4.6/PHP
   5.4) intermittently 404s its own documented static paths while the
   CloudFront delivery host stays healthy, so the current URL is *resolved
   from the search-page HTML* every run. The CF page still carries the dead
   ``/data/search/cf/TEC_CF_CSV.zip`` link inside an HTML comment — comments
   are stripped before anchors are read, or the resolver would pick the
   corpse.
2. **Never download the campaign-finance ZIP to find out what changed.** It
   is ~1.04 GB compressed / 9.13 GB uncompressed across 139 members. The
   nightly change-detection primitive here is a *ranged* read of the ZIP
   tail: End-Of-Central-Directory + central directory give every member's
   name, sizes, CRC and local-header offset for about 32 KB of traffic. A
   diff of that listing between nights says exactly which shards moved.
   Individual small members (the record-layout readme, the expenditure-code
   table) are then pulled by ranged-fetching their local header + compressed
   bytes and raw-inflating with ``zlib.decompressobj(-15)`` — verified live.
3. **The two exports disagree about amendments.** Campaign finance keeps
   superseded rows in place and flags them with ``infoOnlyFlag='Y'``, and
   ships ``COR*`` correction-affidavit form types alongside. The lobby export
   silently *drops* superseded originals ("Information from reports which
   have been superseded by corrected reports is not included" —
   LobbyLAR-ReadMe.txt). So a CF row must never be counted without consulting
   its flag, and a lobby row's absence is not evidence it never existed.
4. **Two shard families exist to prevent double counting.** ``cont_ss.csv``
   (special session) and ``cont_t.csv`` (daily pre-election, formerly
   "telegram") hold transactions that are *re-reported on the next regular
   report* — CFS-ReadMe.txt says so verbatim. Summing every contribution file
   double-counts them. Every loaded row therefore carries ``schedule`` =
   main/ss/t so a total can exclude the re-reported shards by construction.

Parsers are pure functions over bytes; every artifact is stored in the
document store before it is parsed. The 17 MB lobby ZIP is the only bulk
download and it lands under ``var/`` — never in ``fixtures/`` or git.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import struct
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.core.fetch import fetcher
from lobbybook.core.registry import Connector, SmokeResult, register

CF_SEARCH = "https://www.ethics.state.tx.us/search/cf/"
LOBBY_SEARCH = "https://www.ethics.state.tx.us/search/lobby/"
CF_ZIP_FILENAME = "TEC_CF_CSV.zip"
LA_ZIP_FILENAME = "TEC_LA_CSV.zip"

#: Bytes of ZIP tail pulled to find the central directory. The CF directory
#: measured 8,355 bytes for 139 members, so this is ~250x headroom; if the
#: directory still starts before the tail a second ranged read fetches it.
TAIL_BYTES = 2 * 1024 * 1024

#: The lobby ZIP is the only file we are willing to download whole (17.2 MB
#: measured). Anything materially bigger is a signal the product changed.
LA_MAX_BYTES = 64 * 1024 * 1024

#: Load caps. LaSub is ~210k rows (loaded whole at this cap); LaCvr is ~285k
#: rows / 82 MB and is deliberately capped — the slice loaded and the cap that
#: produced it are both recorded in ``tec_load_state`` so no downstream count
#: can be mistaken for a complete one.
LASUB_CAP = 400_000
LACVR_CAP = 25_000

#: Members small enough to be worth a ranged extraction from the 1 GB CF ZIP.
CF_SMALL_MEMBERS = ("CFS-ReadMe.txt", "expn_catg.csv")
#: Refuse a ranged extraction above this (uncompressed) size.
MAX_MEMBER_BYTES = 4 * 1024 * 1024


# --------------------------------------------------------------- URL resolution
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_ANCHOR_RE = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ASOF_RE = re.compile(r"As\s+of\s+(\d{1,2})/(\d{1,2})/(\d{4})", re.I)


def strip_comments(html: str) -> str:
    """Drop HTML comments. Load-bearing: the CF search page keeps a stale
    ``/data/search/cf/TEC_CF_CSV.zip`` link commented out next to the live
    one, and it 404s."""
    return _COMMENT_RE.sub(" ", html)


def _text(fragment: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", fragment)).strip()


def find_bulk_zip(content: bytes | str, filename: str, base_url: str = "") -> dict | None:
    """Locate the live bulk-ZIP anchor for ``filename`` on a TEC search page.

    Returns ``{"url", "label", "as_of", "as_of_iso"}`` or None. Absolute
    (CloudFront) hrefs win over site-relative ones: the delivery host is the
    half of TEC's stack that stays up.
    """
    html = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    candidates = []
    for anchor in _ANCHOR_RE.finditer(strip_comments(html)):
        href, inner = anchor.group(1).strip(), anchor.group(2)
        if href.rsplit("/", 1)[-1].split("?")[0].lower() != filename.lower():
            continue
        label = _text(inner)
        absolute = href.lower().startswith(("http://", "https://"))
        candidates.append((0 if absolute else 1, href if absolute else urljoin(base_url, href), label))
    if not candidates:
        return None
    _, url, label = sorted(candidates, key=lambda c: c[0])[0]
    m = _ASOF_RE.search(label)
    as_of = f"{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else None
    iso = f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else None
    return {"url": url, "label": label, "as_of": as_of, "as_of_iso": iso}


# ------------------------------------------------------------- ZIP structures
EOCD_SIG = b"PK\x05\x06"
EOCD64_SIG = b"PK\x06\x06"
EOCD64_LOC_SIG = b"PK\x06\x07"
CEN_SIG = b"PK\x01\x02"
LOC_SIG = b"PK\x03\x04"


@dataclass(frozen=True)
class ZipMember:
    name: str
    method: int
    compressed_size: int
    uncompressed_size: int
    header_offset: int
    crc32: int


def parse_eocd(tail: bytes, file_size: int) -> dict:
    """Parse the End-Of-Central-Directory record out of a ZIP's tail bytes.

    ``file_size`` is the whole archive's length (from the HEAD), which is what
    turns absolute central-directory offsets into offsets into ``tail``.
    ZIP64 is handled: the CF archive is under 4 GB today, but it grows every
    night and crossing that line must not silently break the prober.
    """
    idx = tail.rfind(EOCD_SIG)
    if idx < 0:
        raise ValueError("no End-Of-Central-Directory signature in tail")
    _, _, _, _, entries, cd_size, cd_offset, comment_len = struct.unpack(
        "<IHHHHIIH", tail[idx : idx + 22]
    )
    tail_start = file_size - len(tail)
    zip64 = False
    if entries == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
        loc = tail.rfind(EOCD64_LOC_SIG, 0, idx)
        if loc < 0:
            raise ValueError("ZIP64 sentinel values but no ZIP64 EOCD locator in tail")
        _, _, eocd64_offset, _ = struct.unpack("<IIQI", tail[loc : loc + 20])
        rel = eocd64_offset - tail_start
        if not (0 <= rel < len(tail)) or tail[rel : rel + 4] != EOCD64_SIG:
            raise ValueError("ZIP64 EOCD record falls outside the fetched tail")
        fields = struct.unpack("<IQHHIIQQQQ", tail[rel : rel + 56])
        entries, cd_size, cd_offset = fields[7], fields[8], fields[9]
        zip64 = True
    return {
        "entries": entries,
        "cd_size": cd_size,
        "cd_offset": cd_offset,
        "tail_start": tail_start,
        "comment_len": comment_len,
        "zip64": zip64,
    }


def _zip64_extra(extra: bytes, usize: int, csize: int, offset: int) -> tuple[int, int, int]:
    """Replace 0xFFFFFFFF sentinels from the ZIP64 extended-information field."""
    pos = 0
    while pos + 4 <= len(extra):
        hid, hlen = struct.unpack("<HH", extra[pos : pos + 4])
        body = extra[pos + 4 : pos + 4 + hlen]
        if hid == 0x0001:
            cur = 0
            if usize == 0xFFFFFFFF and cur + 8 <= len(body):
                usize = struct.unpack("<Q", body[cur : cur + 8])[0]
                cur += 8
            if csize == 0xFFFFFFFF and cur + 8 <= len(body):
                csize = struct.unpack("<Q", body[cur : cur + 8])[0]
                cur += 8
            if offset == 0xFFFFFFFF and cur + 8 <= len(body):
                offset = struct.unpack("<Q", body[cur : cur + 8])[0]
            break
        pos += 4 + hlen
    return usize, csize, offset


def parse_central_directory(data: bytes) -> list[ZipMember]:
    """Central-directory bytes -> one ZipMember per archive member."""
    members: list[ZipMember] = []
    pos = 0
    while pos + 46 <= len(data) and data[pos : pos + 4] == CEN_SIG:
        (
            _sig, _vmade, _vneed, _flags, method, _mtime, _mdate, crc,
            csize, usize, nlen, elen, clen, _dstart, _iattr, _eattr, offset,
        ) = struct.unpack("<IHHHHHHIIIHHHHHII", data[pos : pos + 46])
        name = data[pos + 46 : pos + 46 + nlen].decode("utf-8", errors="replace")
        extra = data[pos + 46 + nlen : pos + 46 + nlen + elen]
        usize, csize, offset = _zip64_extra(extra, usize, csize, offset)
        members.append(
            ZipMember(
                name=name, method=method, compressed_size=csize,
                uncompressed_size=usize, header_offset=offset, crc32=crc,
            )
        )
        pos += 46 + nlen + elen + clen
    return members


def local_data_offset(header: bytes, header_offset: int) -> int:
    """Absolute offset of a member's compressed bytes, from its local header.

    The local header's name/extra lengths differ from the central directory's,
    so this cannot be skipped — that is the classic ranged-extraction bug.
    """
    if header[:4] != LOC_SIG:
        raise ValueError("not a ZIP local file header")
    nlen, elen = struct.unpack("<HH", header[26:30])
    return header_offset + 30 + nlen + elen


def inflate_member(raw: bytes, method: int) -> bytes:
    """Raw-inflate a member's compressed bytes (no zlib/gzip wrapper)."""
    if method == 0:
        return raw
    if method == 8:
        return zlib.decompressobj(-15).decompress(raw)
    raise ValueError(f"unsupported ZIP compression method {method}")


def diff_members(before: list[ZipMember] | dict, after: list[ZipMember] | dict) -> dict:
    """Nightly change detection: which members appeared, vanished or moved.

    Accepts either ZipMember lists or ``{name: (csize, usize, crc)}`` maps.
    """
    def norm(x):
        if isinstance(x, dict):
            return x
        return {m.name: (m.compressed_size, m.uncompressed_size, m.crc32) for m in x}

    a, b = norm(before), norm(after)
    return {
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
        "changed": sorted(n for n in set(a) & set(b) if a[n] != b[n]),
        "unchanged": sorted(n for n in set(a) & set(b) if a[n] == b[n]),
    }


# ----------------------------------------------------------- readme / codebook
_RECORD_HEAD_RE = re.compile(
    r"^Record #:\s*(\d+)\s+Record Name:\s*(\S+)\s+Length:\s*(\d+)\s*$", re.M
)
_FILES_RE = re.compile(r"^\s*Files?:\s*(.+)$", re.M)
_DESC_RE = re.compile(r"^Description:\s*(.*?)(?=^\s*Files?:|^\s*#\s+Field Name)", re.M | re.S)
_RULER_RE = re.compile(r"^(-{2,}(?:\s+-{2,})+)\s*$", re.M)


def _ruler_slices(ruler: str) -> list[slice]:
    """Column slices from a dashed ruler line, so the fixed-width field tables
    are read by their own declared widths rather than by guesswork."""
    out, pos = [], 0
    for run in ruler.split(" "):
        if not run:
            pos += 1
            continue
        out.append(slice(pos, pos + len(run)))
        pos += len(run) + 1
    return out


def parse_readme_records(data: bytes | str) -> list[dict]:
    """CFS-ReadMe.txt (or LobbyLAR-ReadMe.txt) -> one dict per record type.

    Each dict carries the record number/name/length, its CSV file names, the
    description, and the documented field order — which is exactly what a
    header row must be validated against before any shard is trusted.
    """
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    heads = list(_RECORD_HEAD_RE.finditer(text))
    records = []
    for i, m in enumerate(heads):
        block = text[m.end() : heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        files_m = _FILES_RE.search(block)
        desc_m = _DESC_RE.search(block)
        records.append(
            {
                "record_no": int(m.group(1)),
                "record_name": m.group(2),
                "length": int(m.group(3)),
                "files": [f.strip() for f in files_m.group(1).split(",")] if files_m else [],
                "description": _WS_RE.sub(" ", desc_m.group(1)).strip() if desc_m else "",
                "fields": _parse_field_table(block),
            }
        )
    return records


def _parse_field_table(block: str) -> list[dict]:
    """Read one fixed-width field table.

    The column widths are taken from the table's own dashed ruler and the
    column *meanings* from the header line above it, because the two readmes
    differ: CFS-ReadMe.txt carries a Start column, LobbyLAR-ReadMe.txt does
    not. Parsing by position alone silently reads Len as Start.
    """
    ruler = _RULER_RE.search(block)
    if not ruler:
        return []
    cols = _ruler_slices(ruler.group(1))
    header_line = block[: ruler.start()].rstrip("\r\n").rsplit("\n", 1)[-1]
    labels = [header_line[c].strip().lower() for c in cols]
    try:
        i_no, i_name = labels.index("#"), labels.index("field name")
    except ValueError:
        return []
    idx = {label: n for n, label in enumerate(labels)}
    fields: list[dict] = []
    for line in block[ruler.end() :].splitlines():
        if not line.strip():
            if fields:
                break
            continue
        num = line[cols[i_no]].strip()
        if not num.isdigit():
            # a description that wrapped onto its own line
            if fields:
                fields[-1]["description"] = (
                    fields[-1]["description"] + " " + line.strip()
                ).strip()
            continue

        def cell(label: str, ln=line) -> str:
            n = idx.get(label)
            return ln[cols[n]].strip() if n is not None and n < len(cols) else ""

        desc_n = idx.get("description")
        fields.append(
            {
                "no": int(num),
                "name": line[cols[i_name]].strip(),
                "type": cell("type"),
                "start": int(cell("start") or 0),
                "length": int(cell("len") or 0),
                "description": (
                    line[cols[desc_n].start :].strip() if desc_n is not None else ""
                ),
            }
        )
    return fields


def parse_expn_catg(data: bytes) -> list[dict]:
    """expn_catg.csv -> the closed expenditure-category vocabulary."""
    rows = _csv_dicts(data)
    return [
        {"code": r["expendCategoryCodeValue"].strip(), "label": r["expendCategoryCodeLabel"].strip()}
        for r in rows
        if r.get("expendCategoryCodeValue")
    ]


# ------------------------------------------------------------------- CSV plumbing
def _csv_reader(fh) -> csv.DictReader:
    return csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline=""))


def _csv_dicts(data: bytes) -> list[dict]:
    return list(_csv_reader(io.BytesIO(data)))


def _iso_date(raw: str | None) -> str | None:
    """TEC dates are yyyyMMdd strings; anything else is not a date."""
    s = (raw or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else None


def _money(raw: str | None) -> float | None:
    s = (raw or "").strip().replace(",", "").replace("$", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def filer_id(raw: str | None) -> str | None:
    """TEC filer IDs are 8-digit zero-padded across every filer type."""
    s = (raw or "").strip()
    if not s:
        return None
    return s.zfill(8) if s.isdigit() and len(s) <= 8 else s


# --------------------------------------------------------------- contributions
def schedule_for(source_name: str) -> str:
    """Which double-count family a contribution file belongs to.

    ``cont_ss.csv`` -> 'ss' (special session), ``cont_t.csv`` -> 't' (daily
    pre-election), ``contribs_##.csv`` -> 'main'. Rows in ss/t are re-reported
    on the next regular report, so only 'main' may be summed.
    """
    stem = source_name.rsplit("/", 1)[-1].lower()
    stem = stem[:-4] if stem.endswith(".csv") else stem
    if stem.endswith("_ss"):
        return "ss"
    if stem.endswith("_t"):
        return "t"
    return "main"


def contributor_name(row: dict) -> str | None:
    """One display string for a contributor with no persistent ID.

    ENTITY rows carry an organization name; INDIVIDUAL rows carry split name
    parts. Kept raw and unnormalised — entity resolution is a downstream
    problem and must not be pre-empted by lossy joining here.
    """
    kind = (row.get("contributorPersentTypeCd") or "").strip().upper()
    org = (row.get("contributorNameOrganization") or "").strip()
    if kind == "ENTITY" or (not kind and org):
        return org or None
    parts = [
        (row.get("contributorNamePrefixCd") or "").strip(),
        (row.get("contributorNameFirst") or "").strip(),
        (row.get("contributorNameLast") or "").strip(),
        (row.get("contributorNameSuffixCd") or "").strip(),
    ]
    joined = " ".join(p for p in parts if p)
    return joined or org or None


CONTRIB_COLS = (
    "id", "filer_id", "report_id", "contributor_raw", "employer_raw",
    "amount", "date", "superseded", "schedule",
)
CONTRIB_META_COLS = (
    "id", "form_type", "sched_form_type", "filer_type", "received_dt",
    "is_correction", "source_file",
)


def contribution_row(raw: dict, source_name: str) -> dict | None:
    """One RCPT record -> one flat row (canonical + amendment metadata).

    ``superseded`` comes straight from ``infoOnlyFlag`` (CF flags superseded
    rows in place rather than dropping them) and ``schedule`` from the source
    filename, so a total can exclude the re-reported shards without a join.
    """
    ident = (raw.get("contributionInfoId") or "").strip()
    if not ident.isdigit():
        return None
    form = (raw.get("formTypeCd") or "").strip()
    return {
        "id": int(ident),
        "filer_id": filer_id(raw.get("filerIdent")),
        "report_id": (raw.get("reportInfoIdent") or "").strip(),
        "contributor_raw": contributor_name(raw),
        "employer_raw": (raw.get("contributorEmployer") or "").strip() or None,
        "amount": _money(raw.get("contributionAmount")),
        "date": _iso_date(raw.get("contributionDt")),
        "superseded": 1 if (raw.get("infoOnlyFlag") or "").strip().upper() == "Y" else 0,
        "schedule": schedule_for(source_name),
        "form_type": form or None,
        "sched_form_type": (raw.get("schedFormTypeCd") or "").strip() or None,
        "filer_type": (raw.get("filerTypeCd") or "").strip() or None,
        "received_dt": _iso_date(raw.get("receivedDt")),
        "is_correction": 1 if form.upper().startswith("COR") else 0,
        "source_file": source_name.rsplit("/", 1)[-1],
    }


def parse_contribs(data: bytes, source_name: str) -> list[dict]:
    """Contribution CSV bytes -> rows. Pure; the filename supplies the
    schedule tag and nothing else about the environment is consulted."""
    out = []
    for raw in _csv_dicts(data):
        row = contribution_row(raw, source_name)
        if row is not None:
            out.append(row)
    return out


def countable_total(rows: list[dict], *, include_superseded: bool = False) -> float:
    """The only total that is safe to publish.

    Excludes the ``_ss``/``_t`` re-report families and (by default) rows the
    filer has already superseded with a corrected report.
    """
    return round(
        sum(
            r["amount"] or 0.0
            for r in rows
            if r["schedule"] == "main" and (include_superseded or not r["superseded"])
        ),
        2,
    )


# ----------------------------------------------------------------- lobby export
def lobby_subject_row(raw: dict) -> dict | None:
    ident = (raw.get("lobbySubjectmatterId") or "").strip()
    if not ident.isdigit():
        return None
    year = (raw.get("applicableYear") or "").strip()
    return {
        "id": int(ident),
        "report_id": (raw.get("reportInfoIdent") or "").strip(),
        "filer_id": filer_id(raw.get("filerIdent")),
        "filer_name": (raw.get("filerName") or "").strip() or None,
        "applicable_year": int(year) if year.isdigit() else None,
        "subject_code": (raw.get("subjectMatterCd") or "").strip() or None,
        "subject_label": (raw.get("subjectMatterCodeValue") or "").strip() or None,
        "form_type": (raw.get("lobbyFormType") or "").strip() or None,
    }


_LACVR_TOTALS = {
    "total_transportation": "totalExpendTransportation",
    "total_food": "totalExpendFood",
    "total_entertainment": "totalExpendEntertainment",
    "total_gift": "totalExpendGift",
    "total_award": "totalExpendAward",
    "total_event": "totalExpendEvent",
    "total_media": "totalExpendMedia",
}


def lobby_cover_row(raw: dict) -> dict | None:
    ident = (raw.get("reportInfoIdent") or "").strip()
    if not ident:
        return None
    year = (raw.get("applicableYear") or "").strip()
    row = {
        "report_id": ident,
        "filer_id": filer_id(raw.get("filerIdent")),
        "filer_name": (raw.get("filerName") or "").strip() or None,
        "filer_type": (raw.get("filerTypeCd") or "").strip() or None,
        "report_type": (raw.get("reportTypeCd") or "").strip() or None,
        "applicable_year": int(year) if year.isdigit() else None,
        # ELECTRONIC vs KEYED: KEYED rows are paper filings where TEC entered
        # only the cover totals, so their schedules are absent by design.
        "source_category": (raw.get("sourceCategoryCd") or "").strip() or None,
        "filed_dt": _iso_date(raw.get("filedDt")),
        "received_dt": _iso_date(raw.get("receivedDt")),
        "period_start": _iso_date(raw.get("periodStartDt")),
        "period_end": _iso_date(raw.get("periodEndDt")),
        "onbehalf_flag": (raw.get("onbehalfFlag") or "").strip() or None,
    }
    row.update({k: _money(raw.get(v)) for k, v in _LACVR_TOTALS.items()})
    return row


def parse_lasub(data: bytes, limit: int | None = None) -> list[dict]:
    return _collect(_csv_dicts(data), lobby_subject_row, limit)


def parse_lacvr(data: bytes, limit: int | None = None) -> list[dict]:
    return _collect(_csv_dicts(data), lobby_cover_row, limit)


def _collect(rows: Iterator[dict] | list[dict], fn, limit: int | None) -> list[dict]:
    out = []
    for raw in rows:
        row = fn(raw)
        if row is None:
            continue
        out.append(row)
        if limit is not None and len(out) >= limit:
            break
    return out


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def var_dir() -> Path:
    """Working directory for bulk downloads. Never fixtures/, never git."""
    root = Path(os.environ.get("LOBBYBOOK_VAR", "var")) / "tec"
    if "fixtures" in root.parts:
        raise ValueError(f"refusing to stage bulk downloads under fixtures: {root}")
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------- the connector
@register
class TECConnector(Connector):
    """Nightly TEC bulk sync: probe the 1 GB CF ZIP, download the 17 MB lobby ZIP."""

    name = "tec"
    tier = 0
    cadence = "nightly"

    DDL = """
    -- One snapshot row per (archive, member, as-of date). The nightly diff of
    -- member sizes/CRCs is the change-detection primitive that keeps a 9 GB
    -- corpus tractable without downloading it.
    CREATE TABLE IF NOT EXISTS tec_bulk_member (
        archive           TEXT NOT NULL,      -- 'cf' | 'lobby'
        name              TEXT NOT NULL,
        as_of             TEXT NOT NULL,      -- ISO date from the search page
        method            INTEGER,
        compressed_size   INTEGER,
        uncompressed_size INTEGER,
        header_offset     INTEGER,
        crc32             INTEGER,
        observed_at       TEXT NOT NULL,
        PRIMARY KEY (archive, name, as_of)
    );

    -- The closed expenditure vocabulary (expn_catg.csv), pulled by ranged
    -- extraction from the CF archive.
    CREATE TABLE IF NOT EXISTS tec_expend_category (
        code  TEXT PRIMARY KEY,
        label TEXT NOT NULL
    );

    -- The record layouts documented in CFS-ReadMe.txt / LobbyLAR-ReadMe.txt.
    CREATE TABLE IF NOT EXISTS tec_record_type (
        archive     TEXT NOT NULL,
        record_name TEXT NOT NULL,
        record_no   INTEGER,
        length      INTEGER,
        files       TEXT,
        field_count INTEGER,
        description TEXT,
        PRIMARY KEY (archive, record_name)
    );

    -- Amendment metadata for contributions. `contribution` stays canonical;
    -- the COR* correction-affidavit form type lives here because it is the
    -- signal that an earlier number was revised.
    CREATE TABLE IF NOT EXISTS tec_contribution_meta (
        id              INTEGER PRIMARY KEY,   -- contributionInfoId
        form_type       TEXT,
        sched_form_type TEXT,
        filer_type      TEXT,
        received_dt     TEXT,
        is_correction   INTEGER NOT NULL DEFAULT 0,
        source_file     TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_tec_contrib_meta_corr
        ON tec_contribution_meta(is_correction);

    -- Lobby activity: coded subject matter (Schedule A) and cover totals.
    CREATE TABLE IF NOT EXISTS tec_lobby_subject (
        id              INTEGER PRIMARY KEY,   -- lobbySubjectmatterId
        report_id       TEXT,
        filer_id        TEXT,
        filer_name      TEXT,
        applicable_year INTEGER,
        subject_code    TEXT,
        subject_label   TEXT,
        form_type       TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_tec_lobby_subject_code
        ON tec_lobby_subject(subject_code);
    CREATE INDEX IF NOT EXISTS idx_tec_lobby_subject_filer
        ON tec_lobby_subject(filer_id, applicable_year);

    CREATE TABLE IF NOT EXISTS tec_lobby_cover (
        report_id           TEXT PRIMARY KEY,
        filer_id            TEXT,
        filer_name          TEXT,
        filer_type          TEXT,
        report_type         TEXT,
        applicable_year     INTEGER,
        source_category     TEXT,              -- ELECTRONIC | KEYED (paper)
        filed_dt            TEXT,
        received_dt         TEXT,
        period_start        TEXT,
        period_end          TEXT,
        onbehalf_flag       TEXT,
        total_transportation REAL,
        total_food           REAL,
        total_entertainment  REAL,
        total_gift           REAL,
        total_award          REAL,
        total_event          REAL,
        total_media          REAL
    );

    -- Every cap that produced a partial load is recorded, so no downstream
    -- count can be mistaken for a complete one.
    CREATE TABLE IF NOT EXISTS tec_load_state (
        key        TEXT PRIMARY KEY,
        value      TEXT,
        updated_at TEXT
    );
    """

    # -- 1. URL resolution ------------------------------------------------
    def resolve_bulk_urls(self, conn: sqlite3.Connection | None = None) -> dict:
        """Both search pages -> the live ZIP URLs and their 'As of' labels.

        2 live requests. The URLs are never hardcoded: the audit found the
        legacy front end 404ing its own documented static paths.
        """
        out: dict[str, dict] = {}
        for key, page, filename in (
            ("cf", CF_SEARCH, CF_ZIP_FILENAME),
            ("lobby", LOBBY_SEARCH, LA_ZIP_FILENAME),
        ):
            resp = fetcher().get(page)
            resp.raise_for_status()
            if conn is not None:
                store_document(
                    conn, doc_id=f"tec:search_page:{key}", source_family="tec",
                    content=resp.content, url=page, doc_type="tec_search_page",
                    authority="D", etag=resp.headers.get("ETag"),
                    last_modified=resp.headers.get("Last-Modified"),
                )
            found = find_bulk_zip(resp.content, filename, base_url=page)
            if found is None:
                raise RuntimeError(f"no {filename} link on {page}")
            found["search_page"] = page
            out[key] = found
        if conn is not None:
            conn.commit()
        return out

    def probe(self, url: str) -> dict:
        resp = fetcher().head(url)
        size = resp.headers.get("Content-Length")
        return {
            "url": url,
            "status": resp.status_code,
            "size": int(size) if size and size.isdigit() else None,
            "last_modified": resp.headers.get("Last-Modified"),
            "etag": resp.headers.get("ETag"),
            "accept_ranges": resp.headers.get("Accept-Ranges"),
        }

    # -- 2. central-directory prober (no 1 GB download) -------------------
    def probe_central_directory(self, url: str, size: int, tail: int = TAIL_BYTES) -> dict:
        """Ranged-read the archive tail and parse its central directory.

        1 request normally (2 if the directory starts before the tail). Costs
        ~32 KB-2 MB against a 1.04 GB file and yields every member's name,
        sizes, CRC and local-header offset.
        """
        tail = min(tail, size)
        resp = fetcher().get_ranged(url, size - tail, size - 1)
        if resp.status_code not in (200, 206):
            raise RuntimeError(f"ranged tail read failed: HTTP {resp.status_code} for {url}")
        blob = resp.content
        eocd = parse_eocd(blob, size)
        requests = 1
        start = eocd["cd_offset"] - eocd["tail_start"]
        if start < 0:
            cd_resp = fetcher().get_ranged(
                url, eocd["cd_offset"], eocd["cd_offset"] + eocd["cd_size"] - 1
            )
            cd = cd_resp.content
            requests += 1
        else:
            cd = blob[start : start + eocd["cd_size"]]
        members = parse_central_directory(cd)
        if len(members) != eocd["entries"]:
            raise RuntimeError(
                f"central directory declared {eocd['entries']} entries, parsed {len(members)}"
            )
        return {
            "url": url,
            "size": size,
            "members": members,
            "count": len(members),
            "uncompressed_total": sum(m.uncompressed_size for m in members),
            "zip64": eocd["zip64"],
            "requests": requests,
            "bytes_read": len(blob) + (len(cd) if requests == 2 else 0),
        }

    def store_member_listing(
        self, conn: sqlite3.Connection, archive: str, listing: dict, as_of: str | None,
        last_modified: str | None = None,
    ) -> tuple[str, bool]:
        """Persist a member listing as a JSON document + snapshot rows."""
        as_of = as_of or _now()[:10]
        payload = {
            "archive": archive,
            "url": listing["url"],
            "as_of": as_of,
            "size": listing["size"],
            "last_modified": last_modified,
            "count": listing["count"],
            "uncompressed_total": listing["uncompressed_total"],
            "members": [asdict(m) for m in sorted(listing["members"], key=lambda m: m.name)],
        }
        content = json.dumps(payload, indent=1, sort_keys=True).encode("utf-8")
        doc_id = f"tec:{archive}:members"
        _, changed = store_document(
            conn, doc_id=doc_id, source_family="tec", content=content,
            url=listing["url"], doc_type="tec_zip_manifest", published_at=as_of,
            authority="D", last_modified=last_modified,
        )
        observed = _now()
        for m in listing["members"]:
            dbx.upsert(
                conn, "tec_bulk_member",
                {
                    "archive": archive, "name": m.name, "as_of": as_of, "method": m.method,
                    "compressed_size": m.compressed_size,
                    "uncompressed_size": m.uncompressed_size,
                    "header_offset": m.header_offset, "crc32": m.crc32,
                    "observed_at": observed,
                },
                ["archive", "name", "as_of"],
            )
        conn.commit()
        return doc_id, changed

    def member_changes(self, conn: sqlite3.Connection, archive: str = "cf") -> dict:
        """Diff the two most recent stored snapshots of an archive."""
        dates = [
            r["as_of"]
            for r in conn.execute(
                "SELECT DISTINCT as_of FROM tec_bulk_member WHERE archive=? "
                "ORDER BY as_of DESC LIMIT 2",
                (archive,),
            )
        ]
        if len(dates) < 2:
            return {"added": [], "removed": [], "changed": [], "unchanged": [],
                    "snapshots": dates}

        def snap(day):
            return {
                r["name"]: (r["compressed_size"], r["uncompressed_size"], r["crc32"])
                for r in conn.execute(
                    "SELECT name, compressed_size, uncompressed_size, crc32 "
                    "FROM tec_bulk_member WHERE archive=? AND as_of=?",
                    (archive, day),
                )
            }

        out = diff_members(snap(dates[1]), snap(dates[0]))
        out["snapshots"] = [dates[1], dates[0]]
        return out

    # -- 3. ranged member extraction --------------------------------------
    def fetch_member(self, url: str, member: ZipMember) -> bytes:
        """Pull one member out of a remote ZIP with two ranged requests.

        The local header must be read first: its name/extra lengths differ
        from the central directory's, so the data offset cannot be computed
        from the central directory alone.
        """
        if member.uncompressed_size > MAX_MEMBER_BYTES:
            raise ValueError(
                f"{member.name} is {member.uncompressed_size} bytes uncompressed; "
                f"above the {MAX_MEMBER_BYTES}-byte ranged-extraction cap"
            )
        head = fetcher().get_ranged(url, member.header_offset, member.header_offset + 29)
        if head.status_code not in (200, 206):
            raise RuntimeError(f"local header read failed: HTTP {head.status_code}")
        data_off = local_data_offset(head.content, member.header_offset)
        body = fetcher().get_ranged(url, data_off, data_off + member.compressed_size - 1)
        if body.status_code not in (200, 206):
            raise RuntimeError(f"member body read failed: HTTP {body.status_code}")
        raw = body.content[: member.compressed_size]
        out = inflate_member(raw, member.method)
        if zlib.crc32(out) != member.crc32:
            raise RuntimeError(f"CRC mismatch on ranged extraction of {member.name}")
        return out

    def ingest_cf_members(
        self, conn: sqlite3.Connection, listing: dict, names: tuple[str, ...] = CF_SMALL_MEMBERS,
        as_of: str | None = None,
    ) -> dict:
        """Ranged-extract the small CF members that carry the schema and the
        codebooks, store them as documents, and load what they define."""
        by_name = {m.name: m for m in listing["members"]}
        results: dict[str, dict] = {}
        for name in names:
            member = by_name.get(name)
            if member is None:
                results[name] = {"ok": False, "reason": "not in central directory"}
                continue
            try:
                data = self.fetch_member(listing["url"], member)
            except Exception as exc:  # noqa: BLE001 - failure mode is the finding
                results[name] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
                continue
            doc_id = f"tec:cf:member:{name}"
            _, changed = store_document(
                conn, doc_id=doc_id, source_family="tec", content=data,
                url=f"{listing['url']}#{name}", native_id=name,
                doc_type="tec_bulk_member", published_at=as_of, authority="D",
            )
            entry = {"ok": True, "bytes": len(data), "doc_id": doc_id, "changed": changed}
            if name.endswith("ReadMe.txt"):
                entry["records"] = self.load_record_types(conn, data, "cf")
            if name == "expn_catg.csv":
                entry["categories"] = self.load_expend_categories(conn, data)
            results[name] = entry
        conn.commit()
        return results

    def load_record_types(self, conn: sqlite3.Connection, data: bytes, archive: str) -> int:
        records = parse_readme_records(data)
        for rec in records:
            dbx.upsert(
                conn, "tec_record_type",
                {
                    "archive": archive, "record_name": rec["record_name"],
                    "record_no": rec["record_no"], "length": rec["length"],
                    "files": ",".join(rec["files"]), "field_count": len(rec["fields"]),
                    "description": rec["description"][:2000],
                },
                ["archive", "record_name"],
            )
        return len(records)

    def load_expend_categories(self, conn: sqlite3.Connection, data: bytes) -> int:
        cats = parse_expn_catg(data)
        for cat in cats:
            dbx.upsert(conn, "tec_expend_category", cat, ["code"])
        return len(cats)

    # -- 4. lobby ZIP sync -------------------------------------------------
    def sync_lobby_zip(
        self, conn: sqlite3.Connection, url: str | None = None, as_of: str | None = None,
        path: Path | None = None, lasub_cap: int = LASUB_CAP, lacvr_cap: int = LACVR_CAP,
        reuse: bool = True,
    ) -> dict:
        """Download TEC_LA_CSV.zip (17 MB) into var/, then load from it.

        The archive lands under ``var/tec/`` — never fixtures/, never git. Its
        readme is stored as a document, its member listing snapshotted like
        the CF one, LaSub.csv streamed in whole and LaCvr.csv streamed in up
        to ``lacvr_cap`` rows (cap recorded in tec_load_state).
        """
        if url is None:
            url = self.resolve_bulk_urls()["lobby"]["url"]
        target = Path(path) if path is not None else var_dir() / LA_ZIP_FILENAME
        downloaded = False
        if not (reuse and target.exists() and target.stat().st_size > 0):
            head = self.probe(url)
            if head["size"] is not None and head["size"] > LA_MAX_BYTES:
                return {"skipped": "too_large", **head}
            resp = fetcher().get(url)
            resp.raise_for_status()
            target.write_bytes(resp.content)
            downloaded = True
        stats = self.load_lobby_zip(
            conn, target, url=url, as_of=as_of, lasub_cap=lasub_cap, lacvr_cap=lacvr_cap
        )
        stats["downloaded"] = downloaded
        stats["path"] = str(target)
        stats["zip_bytes"] = target.stat().st_size
        return stats

    def load_lobby_zip(
        self, conn: sqlite3.Connection, path: Path, url: str | None = None,
        as_of: str | None = None, lasub_cap: int = LASUB_CAP, lacvr_cap: int = LACVR_CAP,
    ) -> dict:
        """Offline half of the lobby sync: everything that happens once the
        ZIP is on disk. Takes a path so it is testable without the network."""
        out: dict = {"as_of": as_of}
        with zipfile.ZipFile(path) as z:
            members = [
                ZipMember(
                    name=i.filename, method=i.compress_type,
                    compressed_size=i.compress_size, uncompressed_size=i.file_size,
                    header_offset=i.header_offset, crc32=i.CRC,
                )
                for i in z.infolist()
            ]
            listing = {
                "url": url or str(path), "size": Path(path).stat().st_size,
                "members": members, "count": len(members),
                "uncompressed_total": sum(m.uncompressed_size for m in members),
            }
            out["members"] = len(members)
            out["uncompressed_total"] = listing["uncompressed_total"]
            self.store_member_listing(conn, "lobby", listing, as_of)

            names = {m.name for m in members}
            readme = next((n for n in names if n.lower().endswith("readme.txt")), None)
            if readme:
                data = z.read(readme)
                store_document(
                    conn, doc_id=f"tec:lobby:member:{readme}", source_family="tec",
                    content=data, url=f"{url or path}#{readme}", native_id=readme,
                    doc_type="tec_bulk_member", published_at=as_of, authority="D",
                )
                out["readme"] = readme
                out["record_types"] = self.load_record_types(conn, data, "lobby")

            if "LaSub.csv" in names:
                out["subjects"] = self._stream_load(
                    conn, z, "LaSub.csv", lobby_subject_row, "tec_lobby_subject",
                    ["id"], lasub_cap,
                )
            if "LaCvr.csv" in names:
                out["covers"] = self._stream_load(
                    conn, z, "LaCvr.csv", lobby_cover_row, "tec_lobby_cover",
                    ["report_id"], lacvr_cap,
                )
        out["registrations"] = self.derive_registrations(conn)
        conn.commit()
        return out

    def _stream_load(
        self, conn: sqlite3.Connection, z: zipfile.ZipFile, name: str, fn,
        table: str, key: list[str], cap: int,
    ) -> dict:
        """Stream one member row-by-row (LaCvr.csv is 82 MB uncompressed —
        it is never materialised whole) and record the cap that stopped it."""
        loaded = seen = 0
        with z.open(name) as fh:
            for raw in _csv_reader(fh):
                seen += 1
                row = fn(raw)
                if row is None:
                    continue
                if loaded >= cap:
                    break
                dbx.upsert(conn, table, row, key)
                loaded += 1
        truncated = loaded >= cap
        self._set_state(conn, f"{name}:cap", cap)
        self._set_state(conn, f"{name}:loaded", loaded)
        self._set_state(conn, f"{name}:truncated", int(truncated))
        return {"loaded": loaded, "rows_read": seen, "cap": cap, "truncated": truncated}

    def _set_state(self, conn: sqlite3.Connection, key: str, value) -> None:
        dbx.upsert(
            conn, "tec_load_state",
            {"key": key, "value": str(value), "updated_at": _now()}, ["key"],
        )

    def derive_registrations(self, conn: sqlite3.Connection) -> int:
        """LaSub -> lobby_registration (filer x year x subject codes).

        This is the *activity*-report view of who lobbied on what. It is not
        the registration corpus: clients and compensation bands live only in
        the daily PDF/Excel lists, which have no bulk path at all — so
        client_raw and the comp columns stay NULL here rather than being
        filled with something that looks like an answer.
        """
        rows = conn.execute(
            "SELECT filer_id, applicable_year AS year, MAX(filer_name) AS name, "
            "GROUP_CONCAT(DISTINCT subject_code) AS codes "
            "FROM tec_lobby_subject "
            "WHERE filer_id IS NOT NULL AND applicable_year IS NOT NULL "
            "GROUP BY filer_id, applicable_year"
        ).fetchall()
        n = 0
        for r in rows:
            codes = ",".join(sorted({c for c in (r["codes"] or "").split(",") if c}))
            existing = conn.execute(
                "SELECT id FROM lobby_registration WHERE filer_id=? AND year=?",
                (r["filer_id"], r["year"]),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE lobby_registration SET lobbyist_raw=?, subjects=? WHERE id=?",
                    (r["name"], codes, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO lobby_registration "
                    "(filer_id, year, lobbyist_raw, client_raw, comp_low, comp_high, "
                    " comp_exact, subjects) VALUES (?,?,?,NULL,NULL,NULL,NULL,?)",
                    (r["filer_id"], r["year"], r["name"], codes),
                )
            n += 1
        return n

    # -- 5. contribution loader -------------------------------------------
    def load_contributions(
        self, conn: sqlite3.Connection, data: bytes, source_name: str,
        doc_id: str | None = None,
    ) -> dict:
        """Contribution CSV bytes -> `contribution` + `tec_contribution_meta`.

        Offline-testable end to end: nothing here touches the network.
        """
        rows = parse_contribs(data, source_name)
        for row in rows:
            dbx.upsert(conn, "contribution", {k: row[k] for k in CONTRIB_COLS}, ["id"])
            dbx.upsert(
                conn, "tec_contribution_meta",
                {k: row[k] for k in CONTRIB_META_COLS}, ["id"],
            )
            if row["filer_id"] and row["contributor_raw"]:
                dbx.add_edge(
                    conn, "contributor_name", row["contributor_raw"], "contributed_to",
                    "filer", row["filer_id"], "explicit", doc_id,
                    span=str(row["id"]),
                )
        conn.commit()
        schedule = schedule_for(source_name)
        return {
            "source_file": source_name.rsplit("/", 1)[-1],
            "schedule": schedule,
            "rows": len(rows),
            "superseded": sum(r["superseded"] for r in rows),
            "corrections": sum(r["is_correction"] for r in rows),
            "naive_total": round(sum(r["amount"] or 0.0 for r in rows), 2),
            "countable_total": countable_total(rows),
        }

    def totals(self, conn: sqlite3.Connection) -> dict:
        """The double-count guard, expressed as SQL: what a naive sum says vs
        what is actually safe to publish."""
        naive = conn.execute("SELECT COALESCE(SUM(amount),0) t FROM contribution").fetchone()["t"]
        main = conn.execute(
            "SELECT COALESCE(SUM(amount),0) t FROM contribution WHERE schedule='main'"
        ).fetchone()["t"]
        countable = conn.execute(
            "SELECT COALESCE(SUM(amount),0) t FROM contribution "
            "WHERE schedule='main' AND superseded=0"
        ).fetchone()["t"]
        by_schedule = {
            r["schedule"]: r["c"]
            for r in conn.execute(
                "SELECT schedule, COUNT(*) c FROM contribution GROUP BY schedule"
            )
        }
        return {
            "naive_total": round(naive, 2),
            "main_total": round(main, 2),
            "countable_total": round(countable, 2),
            "rows_by_schedule": by_schedule,
        }

    # -- orchestration -----------------------------------------------------
    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        """Nightly run: resolve URLs, probe the CF directory, refresh the small
        CF members, and (optionally) sync the lobby ZIP."""
        with_lobby = bool(kwargs.get("with_lobby", True))
        urls = self.resolve_bulk_urls(conn)
        cf_head = self.probe(urls["cf"]["url"])
        listing = self.probe_central_directory(urls["cf"]["url"], cf_head["size"])
        doc_id, changed = self.store_member_listing(
            conn, "cf", listing, urls["cf"]["as_of_iso"], cf_head["last_modified"]
        )
        out = {
            "cf": {
                "url": urls["cf"]["url"], "as_of": urls["cf"]["as_of"],
                "size": cf_head["size"], "last_modified": cf_head["last_modified"],
                "members": listing["count"],
                "uncompressed_total": listing["uncompressed_total"],
                "manifest_doc": doc_id, "manifest_changed": changed,
                "changes": self.member_changes(conn, "cf"),
            },
            "lobby": {"url": urls["lobby"]["url"], "as_of": urls["lobby"]["as_of"]},
        }
        out["cf"]["small_members"] = self.ingest_cf_members(
            conn, listing, as_of=urls["cf"]["as_of_iso"]
        )
        if with_lobby:
            out["lobby"].update(
                self.sync_lobby_zip(
                    conn, url=urls["lobby"]["url"], as_of=urls["lobby"]["as_of_iso"],
                    lasub_cap=int(kwargs.get("lasub_cap", LASUB_CAP)),
                    lacvr_cap=int(kwargs.get("lacvr_cap", LACVR_CAP)),
                )
            )
        return out

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """5 live requests: two search pages, two HEADs, one ranged tail read.

        Proves the whole no-API path works — the links resolve, both archives
        are live and range-capable, and the 1 GB campaign-finance archive's
        139-member manifest can be read without downloading it.
        """
        urls = self.resolve_bulk_urls(conn)
        cf_head = self.probe(urls["cf"]["url"])
        la_head = self.probe(urls["lobby"]["url"])
        listing = self.probe_central_directory(urls["cf"]["url"], cf_head["size"])
        self.store_member_listing(
            conn, "cf", listing, urls["cf"]["as_of_iso"], cf_head["last_modified"]
        )
        names = {m.name for m in listing["members"]}
        stats = {
            "cf_as_of": urls["cf"]["as_of"],
            "lobby_as_of": urls["lobby"]["as_of"],
            "cf_url": urls["cf"]["url"],
            "lobby_url": urls["lobby"]["url"],
            "cf_size": cf_head["size"],
            "lobby_size": la_head["size"],
            "cf_last_modified": cf_head["last_modified"],
            "lobby_last_modified": la_head["last_modified"],
            "members": listing["count"],
            "uncompressed_total": listing["uncompressed_total"],
            "bytes_read": listing["bytes_read"],
            "requests": 4 + listing["requests"],
            "contrib_shards": sorted(n for n in names if n.startswith(("contribs_", "cont_"))),
            "has_double_count_shards": {"cont_ss.csv", "cont_t.csv"} <= names,
        }
        ok = (
            cf_head["status"] == 200
            and la_head["status"] == 200
            and listing["count"] >= 130
            and stats["has_double_count_shards"]
        )
        detail = (
            f"CF as of {stats['cf_as_of']}: {cf_head['size']:,} B, {listing['count']} members, "
            f"{listing['uncompressed_total']:,} B uncompressed, read via "
            f"{listing['bytes_read']:,} ranged bytes; "
            f"lobby as of {stats['lobby_as_of']}: {la_head['size']:,} B; "
            f"{len(stats['contrib_shards'])} contribution shards incl. cont_ss/cont_t"
        )
        return SmokeResult(ok=ok, detail=detail, stats=stats)
