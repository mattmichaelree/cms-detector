"""Courts connector tests.

Fixtures are live captures (Aug 26, 2026):
  * `cl_search_tex.json` / `cl_search_texcrimapp.json` — CourtListener v4
    search responses for SCOTX and the Court of Criminal Appeals;
  * `businesscourt_opinions.html` — the whole Business Court opinions listing
    (2024 Tex. Bus. 1 through 2026 Tex. Bus. 60);
  * one Business Court opinion PDF, for the statute-citation extractor.

Every assertion below is on a value that actually appears in those bytes.
"""

from __future__ import annotations

import re

import pytest

from lobbybook.core import db as dbx
from lobbybook.core.docstore import store_document
from lobbybook.sources.courts import (
    extract_statute_cites,
    freshness,
    is_rule_challenge,
    parse_bizcourt_listing,
    parse_courtlistener,
    pdf_text,
    store_biz_opinion,
    store_cl_opinion,
    store_statute_cites,
    unfetchable_download_urls,
)

BIZ_PDF = "25-bc01b-0030-preston-hollow-capital-v-truist-bank-2026-tex-bus-59.pdf"

# The capture date of the fixtures — the reference point for freshness claims.
CAPTURED = "2026-08-26"


def _fx(fixtures, name: str) -> bytes:
    return (fixtures / "courts" / name).read_bytes()


def _doc(conn, fixtures, doc_id: str, name: str) -> str:
    """The framework contract: the artifact lands in the docstore before any
    row references it (court_opinion.doc_id is a real foreign key)."""
    store_document(
        conn, doc_id=doc_id, source_family="courts", content=_fx(fixtures, name),
        doc_type="test_fixture",
    )
    return doc_id


@pytest.fixture()
def cl_tex(fixtures):
    return parse_courtlistener(_fx(fixtures, "cl_search_tex.json"))


@pytest.fixture()
def biz(fixtures):
    return parse_bizcourt_listing(_fx(fixtures, "businesscourt_opinions.html"))


# ------------------------------------------------------------- CourtListener

def test_courtlistener_parses_real_scotx_opinions(cl_tex):
    assert len(cl_tex) == 20
    lead = cl_tex[0]
    assert lead["id"] == "cl:11140910"
    assert lead["cluster_id"] == "10674323"
    assert lead["docket"] == "23-0679"
    assert lead["style"] == (
        "Fort Bend Independent School District v. Ken Paxton, "
        "Attorney General of the State of Texas"
    )
    assert lead["date_filed"] == "2025-09-19"
    assert lead["court_id"] == "tex"
    # per_curiam is its own kind even though `type` says concurrence-opinion.
    assert lead["kind"] == "per_curiam"
    assert lead["status"] == "Published"
    assert lead["sha1"] == "80ccf949d00b865362757596a843a2056ad46fc4"
    assert lead["download_url"] == "https://www.txcourts.gov/media/1461283/230679c.pdf"
    assert all(r["date_filed"] for r in cl_tex)


def test_courtlistener_citation_graph_is_carried_as_opinion_ids(cl_tex):
    lead = cl_tex[0]
    assert lead["cites"] == ["cl:1521281", "cl:1662534", "cl:2332908", "cl:9423065", "cl:9810719"]
    # 19 of the 20 sampled clusters carry outbound cites — this is the explicit
    # half of the citation graph, before any statute parsing.
    assert sum(1 for r in cl_tex if r["cites"]) == 19


def test_multi_opinion_clusters_keep_one_row_per_opinion(cl_tex):
    """Cactus Water v. COG Operating hands down a lead opinion and a
    concurrence under one docket; kind is per-opinion, so are the rows."""
    cactus = [r for r in cl_tex if r["docket"] == "23-0676"]
    assert len(cactus) == 2
    assert {r["kind"] for r in cactus} == {"majority", "concurrence"}
    assert len({r["id"] for r in cactus}) == 2


def test_scotx_feed_freshness_is_recorded_not_assumed(cl_tex):
    """The audit's caveat: CourtListener lags. The leading edge of the SCOTX
    sample was Sept 19, 2025 — eleven months before the fixture was captured."""
    assert freshness(cl_tex) == "2025-09-19"
    assert freshness(cl_tex) < CAPTURED


def test_cca_feed_is_the_stale_one_the_audit_warned_about(fixtures):
    rows = parse_courtlistener(_fx(fixtures, "cl_search_texcrimapp.json"))
    assert {r["court_id"] for r in rows} == {"texcrimapp"}
    assert freshness(rows) == "2025-09-24"
    # ~11 months stale at capture: do not present this feed as current.
    assert (2026 - 2025) * 12 + (8 - 9) >= 11
    hernandez = [r for r in rows if r["docket"] == "PD-0836-24"]
    assert hernandez and hernandez[0]["style"] == "HERNANDEZ, LUZALBERT v. the State of Texas"


def test_no_texas_opinion_in_any_sample_carries_a_reporter_citation(cl_tex, fixtures):
    """The audit expected `citations[]` to carry reporter + Tex. Sup. Ct. J. +
    LEXIS cites. Across 60 records in three live responses spanning 2014-2025,
    every one of `citation`, `lexisCite` and `neutralCite` came back empty — so
    a reporter cite may never be a required key, and `court_opinion.citation`
    is null for CourtListener rows until another source supplies one."""
    older = parse_courtlistener(_fx(fixtures, "cl_search_tex_2014.json"))
    cca = parse_courtlistener(_fx(fixtures, "cl_search_texcrimapp.json"))
    assert len(cl_tex) + len(older) + len(cca) == 60
    assert all(r["citations"] == [] for r in cl_tex + older + cca)


def test_older_backfill_pdf_links_all_point_at_denylisted_tames(cl_tex, fixtures):
    """Compliance trap in the data itself: every PDF link in the 2014 sample
    is a TAMES RetrieveDocument.aspx URL — the host that is robots
    `Disallow: /`. Recent records link to the courts' own /media/ paths, which
    are fetchable. A full-text backfill must therefore check the link host,
    not assume CourtListener links are followable."""
    older = parse_courtlistener(_fx(fixtures, "cl_search_tex_2014.json"))
    blocked = unfetchable_download_urls(older)
    assert len(blocked) == len(older) == 20
    assert blocked[0].startswith("http://www.search.txcourts.gov/RetrieveDocument.aspx")
    assert unfetchable_download_urls(cl_tex) == []
    assert cl_tex[0]["download_url"].startswith("https://www.txcourts.gov/media/")


def test_courtlistener_mislabels_the_older_texas_backfill(fixtures):
    """Everything in the 2014 `court=tex` sample is labelled "Texas Supreme
    Court", but the dockets are CCA (AP-/WR-/PD-) and COA (10-14-...-CR)
    numbers. court_id alone is not trustworthy provenance on old records."""
    older = parse_courtlistener(_fx(fixtures, "cl_search_tex_2014.json"))
    assert {r["court_id"] for r in older} == {"tex"}
    dockets = {r["docket"] for r in older}
    assert "AP-76,936" in dockets            # Court of Criminal Appeals
    assert "10-14-00110-CR" in dockets       # 10th Court of Appeals
    # Not one docket in the sample has the SCOTX shape ("23-0679"): the whole
    # 2014 slice is criminal-side work filed under the SCOTX court id.
    assert not [d for d in dockets if re.fullmatch(r"\d{2}-\d{4}", d or "")]


# ------------------------------------------------------------- Business Court

def test_bizcourt_listing_parses_the_whole_corpus(biz):
    assert len(biz) == 123
    assert all(b["cite"] for b in biz)
    assert all(b["date_filed"] for b in biz)
    assert all(b["pdf_url"].startswith("https://www.txcourts.gov/media/") for b in biz)
    assert biz[0]["cite"] == "2026 Tex. Bus. 60"
    assert biz[-1]["cite"] == "2024 Tex. Bus. 1"


def test_bizcourt_entries_carry_real_values(biz):
    top = biz[0]
    assert top["id"] == "txcourts:2026-tex-bus-60"
    assert top["style"] == "Unimacts Global v. Ayr Energy"
    assert top["docket"] == "25-BC11A-0083"
    assert top["division"] == "11"
    assert top["judge"] == "Barnard"
    assert top["date_filed"] == "2026-08-17"
    assert top["kind"] == "memorandum"          # "(mem. op.)" on the listing line
    assert top["court"] == "texbusct"

    second = biz[1]
    assert second["cite"] == "2026 Tex. Bus. 59"
    assert second["style"] == "Preston Hollow Capital v. Truist Bank"
    assert second["docket"] == "25-BC01B-0030"
    assert second["judge"] == "Whitehill"
    assert second["kind"] == "opinion"
    assert second["pdf_url"].endswith(BIZ_PDF)

    first_ever = biz[-1]
    assert first_ever["style"] == "Energy Transfer v. Culberson Midstream"
    assert first_ever["docket"] == "24-BC01B-0005"
    assert first_ever["date_filed"] == "2024-10-30"


def test_bizcourt_is_the_courtlistener_gap(biz, cl_tex):
    """The point of this module: none of these opinions exist in the
    CourtListener corpus, which has no id for the Business Court at all."""
    assert {b["court"] for b in biz} == {"texbusct"}
    assert not {b["court"] for b in biz} & {r["court_id"] for r in cl_tex}


def test_staff_summaries_are_stored_but_never_authoritative(biz):
    preston = biz[1]
    assert preston["summary"].startswith(
        "This opinion addresses (i) whether Title 9 of the Texas Property Code"
    )
    # The page itself disclaims these; nothing may treat them as holding text.
    assert all(b["summary_authoritative"] is False for b in biz)


def test_typo_ridden_cause_numbers_are_normalized(biz):
    """Live listing typos: '25.BC01B-0049', '25-BC04B0017', '24-BC01B--0010',
    '25-BC-BC03A-0001'. All four normalize to the canonical cause-number shape."""
    by_cite = {b["cite"]: b["docket"] for b in biz}
    assert by_cite["2026 Tex. Bus. 24"] == "25-BC01B-0049"
    assert by_cite["2026 Tex. Bus. 6"] == "25-BC04B-0017"
    assert by_cite["2025 Tex. Bus. 21"] == "24-BC01B-0010"
    assert by_cite["2025 Tex. Bus. 10"] == "25-BC03A-0001"


def test_odd_byline_formats_still_yield_judge_and_date(biz):
    by_cite = {b["cite"]: b for b in biz}
    # "Adrogué, J." (accented), "Barnard , J." (split across two <em>s),
    # "Bouressa, J. | January 26. 2026" (period for the comma).
    assert by_cite["2026 Tex. Bus. 58"]["judge"] == "Adrogué"
    assert by_cite["2026 Tex. Bus. 25"]["judge"] == "Barnard"
    assert by_cite["2026 Tex. Bus. 3"]["date_filed"] == "2026-01-26"
    assert by_cite["2025 Tex. Bus. 34"]["date_filed"] == "2025-08-25"


# ------------------------------------------------- statute-citation extractor

def test_statute_cites_extracted_from_a_real_opinion_pdf(fixtures):
    """Preston Hollow Capital v. Truist Bank, 2026 Tex. Bus. 59 — a born-digital
    PDF (no OCR). The cites below are visible in the opinion text."""
    cites = extract_statute_cites(pdf_text(_fx(fixtures, BIZ_PDF)))
    got = {c["cite"] for c in cites}
    assert "Property Code §51.0001(8)" in got
    assert "Property Code §111.003" in got
    assert "Business & Commerce Code §1.201(b)(35)" in got   # spans a line break
    assert "Government Code §311.021(2)" in got              # Code Construction Act
    # The edge points at the section, not the pincite.
    section = {c["cite"]: c["statute"] for c in cites}
    assert section["Business & Commerce Code §1.201(b)(35)"] == "Business & Commerce Code §1.201"
    assert not is_rule_challenge(cites)


def test_defined_short_forms_are_not_minted_as_statute_nodes(fixtures):
    """That opinion says 'Trust Code § 112.001' dozens of times — an
    opinion-local short form for Title 9 of the Property Code. Guessing what
    those resolve to would poison the graph, so only named codes are kept."""
    cites = extract_statute_cites(pdf_text(_fx(fixtures, BIZ_PDF)))
    codes = {c["code"] for c in cites}
    assert codes <= {"Government", "Property", "Business & Commerce"}
    assert not any("Trust Code" in c["cite"] for c in cites)


def test_extractor_handles_the_live_citation_formats():
    text = (
        "The plaintiff sued under Tex. Gov't Code § 2001.038 seeking a "
        "declaration that the rule is invalid. See Texas Government Code "
        "Section 551.001; TEX. TAX CODE § 11.01; 22 TAC §501.52; and "
        "1 Tex. Admin. Code § 353.1155."
    )
    got = {c["cite"] for c in extract_statute_cites(text)}
    assert got == {
        "Government Code §2001.038",
        "Government Code §551.001",
        "Tax Code §11.01",
        "22 TAC §501.52",
        "1 TAC §353.1155",
    }
    kinds = {c["cite"]: c["kind"] for c in extract_statute_cites(text)}
    assert kinds["22 TAC §501.52"] == "rule"
    assert kinds["Tax Code §11.01"] == "statute"


def test_rule_challenge_hook_flags_section_2001_038():
    """§2001.038 is the APA declaratory action against a rule's validity —
    the 'did a court just strike my client's rule?' signal."""
    assert is_rule_challenge(
        extract_statute_cites("brought under Tex. Gov't Code § 2001.038(a)")
    )
    assert not is_rule_challenge(
        extract_statute_cites("brought under Tex. Gov't Code § 2001.174")
    )


# --------------------------------------------------------------- persistence

def test_courtlistener_rows_persist_with_meta_and_case_edges(conn, cl_tex, fixtures):
    doc = _doc(conn, fixtures, "courts:courtlistener:search:tex", "cl_search_tex.json")
    for rec in cl_tex:
        store_cl_opinion(conn, rec, doc)
    row = conn.execute("SELECT * FROM court_opinion WHERE id='cl:11140910'").fetchone()
    assert row["court"] == "tex" and row["docket"] == "23-0679"
    assert row["date_filed"] == "2025-09-19" and row["kind"] == "per_curiam"
    assert row["citation"] is None            # no reporter cite yet — see above
    meta = conn.execute(
        "SELECT * FROM court_opinion_meta WHERE opinion_id='cl:11140910'"
    ).fetchone()
    assert meta["source"] == "courtlistener" and meta["authority"] == "A"
    assert meta["sha1"] == "80ccf949d00b865362757596a843a2056ad46fc4"
    cites = conn.execute(
        "SELECT cite FROM opinion_cite WHERE opinion_id='cl:11140910' AND cite_type='case'"
    ).fetchall()
    assert len(cites) == 5
    edge = conn.execute(
        """SELECT provenance FROM edge WHERE src_id='cl:11140910' AND predicate='cites'
           AND dst_id='cl:1521281'"""
    ).fetchone()
    assert edge["provenance"] == "explicit"   # a structured CourtListener field


def test_business_court_rows_persist(conn, biz, fixtures):
    doc = _doc(
        conn, fixtures, "courts:txcourts:businesscourt:opinions",
        "businesscourt_opinions.html",
    )
    for rec in biz[:5]:
        store_biz_opinion(conn, rec, doc)
    row = conn.execute("SELECT * FROM court_opinion WHERE id='txcourts:2026-tex-bus-59'").fetchone()
    assert row["court"] == "texbusct"
    assert row["citation"] == "2026 Tex. Bus. 59"
    assert row["docket"] == "25-BC01B-0030"
    meta = conn.execute(
        "SELECT * FROM court_opinion_meta WHERE opinion_id='txcourts:2026-tex-bus-59'"
    ).fetchone()
    assert meta["division"] == "1" and meta["judge_raw"] == "Whitehill"
    assert meta["summary_authoritative"] == 0
    assert meta["authority"] == "C"           # persuasive, not binding (audit §7)


def test_statute_edges_are_marked_derived(conn, fixtures):
    """Nothing in the source says 'this opinion construes §X' — the edge comes
    out of citation parsing, so it may only ever be provenance 'derived'."""
    biz = parse_bizcourt_listing(_fx(fixtures, "businesscourt_opinions.html"))
    rec = biz[1]
    doc = _doc(conn, fixtures, "courts:opinion:" + rec["id"], BIZ_PDF)
    store_biz_opinion(conn, rec, doc)
    cites = extract_statute_cites(pdf_text(_fx(fixtures, BIZ_PDF)))
    n = store_statute_cites(conn, rec["id"], cites, doc)
    assert n >= 4
    rows = conn.execute(
        """SELECT provenance, dst_id FROM edge
           WHERE src_id=? AND predicate='interprets'""",
        (rec["id"],),
    ).fetchall()
    assert rows and {r["provenance"] for r in rows} == {"derived"}
    assert "Property Code §51.0001" in {r["dst_id"] for r in rows}
    stored = conn.execute(
        "SELECT cite FROM opinion_cite WHERE opinion_id=? AND cite_type='statute'", (rec["id"],)
    ).fetchall()
    assert "Government Code §311.021(2)" in {r["cite"] for r in stored}


def test_rule_challenge_is_flagged_on_the_row_and_as_an_edge(conn):
    dbx.upsert(
        conn,
        "court_opinion",
        {"id": "cl:test", "court": "tex", "docket": "25-0001", "style": "X v. TCEQ",
         "date_filed": "2026-01-01", "citation": None, "kind": "majority", "doc_id": None},
        ["id"],
    )
    dbx.upsert(
        conn, "court_opinion_meta",
        {"opinion_id": "cl:test", "source": "courtlistener", "rule_challenge": 0}, ["opinion_id"],
    )
    cites = extract_statute_cites(
        "a suit for declaratory judgment under Tex. Gov't Code § 2001.038 challenging "
        "the validity of 30 TAC §39.405"
    )
    store_statute_cites(conn, "cl:test", cites, None)
    meta = conn.execute(
        "SELECT rule_challenge FROM court_opinion_meta WHERE opinion_id='cl:test'"
    ).fetchone()
    assert meta["rule_challenge"] == 1
    edge = conn.execute(
        "SELECT * FROM edge WHERE src_id='cl:test' AND predicate='rule_challenge_under'"
    ).fetchone()
    assert edge["dst_id"] == "Government Code §2001.038"
    assert edge["provenance"] == "derived"
    # The challenged rule itself lands as a rule node, not a statute node.
    rule = conn.execute(
        "SELECT dst_type FROM edge WHERE src_id='cl:test' AND dst_id='30 TAC §39.405'"
    ).fetchone()
    assert rule["dst_type"] == "rule"


# --------------------------------------------------------------- compliance

def test_fetcher_refuses_tames_and_researchtx():
    """Compliance regression test. TAMES (search.txcourts.gov) is robots
    `Disallow: /` and re:SearchTX is bot-walled; the audit's posture is that
    the attorney/party/amicus layer needs an OCA data arrangement, not a
    scraper. The denylist must refuse both before any bytes move."""
    from lobbybook.core.fetch import DeniedURL, fetcher

    f = fetcher()
    with pytest.raises(DeniedURL):
        f.get("https://search.txcourts.gov/Case.aspx?cn=23-0679&coa=cossup")
    with pytest.raises(DeniedURL):
        f.get("https://research.txcourts.gov/CourtRecordsSearch/")
    # The public listing pages this connector does use are not denied.
    f._check_denylist("https://www.txcourts.gov/businesscourt/opinions/")


# --------------------------------------------------------------------- live

@pytest.mark.live
def test_smoke_live(conn):
    from lobbybook.core.registry import get

    result = get("courts").smoke(conn)
    assert result.ok, result.detail
    stats = result.stats
    # Business Court: the half that must always work — no API, no throttle.
    assert stats["biz_entries"] >= 3
    assert stats["biz_with_cite"] >= 3
    assert stats["biz_statute_cites"] >= 1
    if stats["cl_throttled"]:
        pytest.skip(f"CourtListener anonymous search throttled: {result.detail}")
    assert stats["cl_opinions"] >= 5
    assert stats["cl_cite_rows"] >= 5
    assert stats["cl_freshness"]                 # reported, never assumed current
    print(result.detail)
