"""Platform connector tests.

The load-bearing test in this file is
:func:`test_same_number_lives_under_three_different_headings` — everything
else exists to keep that one honest.
"""

from __future__ import annotations

import pytest

from lobbybook.sources.platforms import (
    PARTIES,
    PlatformsConnector,
    blocked_parties,
    detect_cycle,
    number_collisions,
    parse_planks,
    parse_platform_index,
    parse_toc,
    policy,
    store_planks,
    subsection_spread,
)


@pytest.fixture(scope="module")
def index_html(pytestconfig) -> bytes:
    root = pytestconfig.rootpath / "fixtures" / "platforms"
    return (root / "rpt_platform_index.html").read_bytes()


@pytest.fixture(scope="module")
def platform_pdf(pytestconfig) -> bytes:
    root = pytestconfig.rootpath / "fixtures" / "platforms"
    return (root / "2024-RPT-Platform.pdf").read_bytes()


@pytest.fixture(scope="module")
def toc(platform_pdf):
    return parse_toc(platform_pdf)


@pytest.fixture(scope="module")
def planks(platform_pdf):
    # Module-scoped: pdfplumber walks 48 pages of word boxes, ~7s.
    return parse_planks(platform_pdf, party="RPT", cycle=2024)


# ------------------------------------------------------------------- index
def test_index_lists_every_advertised_edition(index_html):
    links = parse_platform_index(index_html)
    assert [link.cycle for link in links] == [2026, 2024, 2022, 2020]
    assert [link.kind for link in links] == ["pdf", "pdf", "pdf", "drive"]
    assert sum(1 for link in links if link.native_pdf) == 3
    # The 2020 platform is not self-hosted — it is a Google Drive link, so it
    # is discovered but never treated as a fetchable native PDF.
    drive = links[-1]
    assert drive.kind == "drive" and not drive.native_pdf
    assert drive.url.startswith("https://drive.google.com/file/d/")


def test_cycle_comes_from_the_filename_not_the_upload_path(index_html):
    """The 2022 platform lives under /uploads/2024/06/ — the upload year is a
    different fact from the convention cycle, and confusing them mislabels a
    whole platform."""
    links = {link.cycle: link for link in parse_platform_index(index_html)}
    assert links[2022].url == "https://texasgop.org/wp-content/uploads/2024/06/2022-RPT-Platform.pdf"
    assert "/uploads/2024/" in links[2022].url
    assert links[2024].url.endswith("2024-RPT-Platform.pdf")


def test_undated_party_documents_are_not_mistaken_for_platforms(index_html):
    """PERM-PLATFORM-as-Amended-by-Gen-Body-5.13.16.pdf is a party-structure
    handout: it says "platform" but carries no cycle year, so it is dropped
    rather than filed under whatever year it happened to be uploaded."""
    urls = [link.url for link in parse_platform_index(index_html)]
    assert not any("PERM-PLATFORM" in url for url in urls)
    assert not any("Legislative-Priorities" in url for url in urls)


def test_index_links_are_deduplicated(index_html):
    """Each PDF is linked twice — a button and an embedded viewer — and the
    2026 button uses an absolute URL while the viewer uses a relative one."""
    text = index_html.decode("utf-8", errors="replace")
    assert text.count("2026-Republican-Party-of-Texas-Platform-As-Approved.pdf") >= 2
    links = parse_platform_index(index_html)
    assert len({link.url for link in links}) == len(links)


def test_convention_drafts_are_flagged_and_never_native():
    """The audit's draft-vs-final hazard: a TEMPORARY file on the convention
    subdomain was superseded by the permanent file on the main domain."""
    html = (
        b'<a href="https://convention.texasgop.org/wp-content/uploads/'
        b'2024-TEMPORARY-Platform-FINAL.pdf">2024 Platform draft</a>'
    )
    (link,) = parse_platform_index(html)
    assert link.cycle == 2024
    assert link.draft is True
    assert link.native_pdf is False


# --------------------------------------------------------------------- TOC
def test_toc_hierarchy_is_read_from_the_indent(toc):
    sections = [entry.title for entry in toc if entry.level == 0]
    assert sections[:3] == ["Preamble", "Principles", "Constitutional Issues"]
    assert "Resolutions" in sections
    assert len(sections) == 12
    subs = [entry.title for entry in toc if entry.level == 1]
    assert "Preservation of Constitution" in subs
    # The keyword index at the back uses the same dot leaders; it must not
    # leak into the heading vocabulary.
    assert not any("....." in entry.title for entry in toc)


def test_subsection_titles_repeat_across_sections(toc):
    """`Parents' Rights` is a subsection of both Education and Health and
    Human Services — reason #2 the plank key needs its section."""
    subs = [entry.title for entry in toc if entry.level == 1]
    assert subs.count("Parents’ Rights") == 2


def test_cycle_is_derivable_from_the_document_itself(platform_pdf):
    assert detect_cycle(platform_pdf) == 2024


# ------------------------------------------------------------------ planks
def test_planks_parse_with_full_heading_stack(planks):
    assert len(planks) == 269  # 10 principles + 252 planks + 7 resolutions
    assert subsection_spread(planks) >= 40
    assert all(plank.section for plank in planks)
    # Never NULL/empty: a NULL inside a UNIQUE key duplicates rows instead of
    # upserting them, in SQLite and in Postgres alike.
    assert all(plank.subsection for plank in planks)
    assert all(plank.number.isdigit() for plank in planks)


def test_plank_text_is_verbatim(planks):
    by_key = {plank.key: plank for plank in planks}
    plank = by_key[("RPT", 2024, "Constitutional Issues", "Citizen Rights", "13")]
    assert plank.title == "National Popular Vote"
    assert plank.text.startswith(
        "National Popular Vote: The National Popular Vote Interstate Compact is a direct violation"
    )
    assert plank.page == 5
    assert plank.citation == (
        "RPT 2024 platform, Constitutional Issues › Citizen Rights, item 13"
    )


def test_lettered_subpoints_stay_with_their_plank(planks):
    """Plank 2's a)–h) sub-points are part of the plank, not orphan lines."""
    by_key = {plank.key: plank for plank in planks}
    plank = by_key[("RPT", 2024, "Constitutional Issues", "Preservation of Constitution", "2")]
    assert plank.title == "Amendments to the Texas Constitution"
    assert "term limits of twelve (12) years" in plank.text  # sub-point d)
    assert "Constitutional Carry" in plank.text  # sub-point g)


def test_same_number_lives_under_three_different_headings(planks):
    """THE point of the compound key.

    "RPT Plank 3" is not a citation. In the 2024 document alone, number 3 is
    a principle about sovereignty, a plank about Article 4 Section 4, and the
    resolution condemning the 2023 Paxton impeachment.
    """
    threes = {(p.section, p.subsection): p for p in planks if p.number == "3"}
    assert len(threes) == 3
    principle = threes[("Principles", "Principles")]
    plank = threes[("Constitutional Issues", "Preservation of Constitution")]
    resolution = threes[("Resolutions", "Resolutions")]
    assert principle.text == "Preserving individual, Texan, and American sovereignty and freedom."
    assert plank.text.startswith("Enforce the Constitution Article 4, Section 4:")
    assert "impeachment of Texas Attorney General Ken Paxton" in resolution.text

    collisions = number_collisions(planks)
    assert set(collisions) == {str(n) for n in range(1, 11)}
    assert collisions["3"] == [
        ("Constitutional Issues", "Preservation of Constitution"),
        ("Principles", "Principles"),
        ("Resolutions", "Resolutions"),
    ]


def test_numbering_runs_continuously_across_subsections(planks):
    """QA correction to the audit, recorded as a test so the next cycle is
    checked rather than assumed: in the 2024 final the plank series does NOT
    restart per subsection — it runs 1..252 straight through. The compound
    key is still mandatory, because the three *series* collide."""
    body = [p for p in planks if p.section not in ("Principles", "Resolutions")]
    assert [int(p.number) for p in body] == list(range(1, 253))
    assert len({(p.section, p.subsection) for p in body}) >= 38


# ----------------------------------------------------------------- storage
def test_all_colliding_rows_survive_storage(conn, planks):
    store_planks(conn, planks, doc_id=None)
    conn.commit()
    rows = conn.execute(
        "SELECT section, subsection, text FROM platform_plank "
        "WHERE party='RPT' AND cycle=2024 AND number='3' ORDER BY section"
    ).fetchall()
    assert len(rows) == 3
    assert [r["section"] for r in rows] == [
        "Constitutional Issues",
        "Principles",
        "Resolutions",
    ]
    total = conn.execute("SELECT COUNT(*) c FROM platform_plank").fetchone()["c"]
    assert total == len(planks)


def test_reingest_is_idempotent(conn, planks):
    store_planks(conn, planks, doc_id=None)
    store_planks(conn, planks, doc_id=None)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM platform_plank").fetchone()["c"] == len(planks)


def test_planks_link_to_their_document(conn, planks):
    from lobbybook.core.docstore import store_document

    store_document(
        conn, doc_id="platforms:RPT:2024:platform", source_family="platforms",
        content=b"%PDF-1.4 stub", doc_type="party_platform", authority="C",
    )
    store_planks(conn, planks[:5], doc_id="platforms:RPT:2024:platform")
    conn.commit()
    edges = conn.execute(
        "SELECT dst_id, provenance FROM edge WHERE predicate='contains' AND src_type='document'"
    ).fetchall()
    assert len(edges) == 5
    assert all(e["provenance"] == "explicit" for e in edges)
    assert edges[0]["dst_id"] == "RPT|2024|Principles|Principles|1"


# ------------------------------------------------------------- TDP is a wall
def test_tdp_policy_records_both_reasons_it_is_off_limits():
    tdp = policy("tdp")
    assert tdp.blocked_by_robots is True
    assert tdp.canonical_url_broken is True
    assert tdp.ingestable is False
    assert tdp.skip_reason == "blocked_by_robots+canonical_url_broken"
    assert "ClaudeBot" in tdp.note and "GPTBot" in tdp.note
    assert "404" in tdp.note
    # The audit's finding: the platform of record lived on Google Docs.
    assert "Google Docs" in tdp.off_domain_note
    assert "content diff" in tdp.off_domain_note
    assert blocked_parties() == ["tdp"]
    assert policy("rpt").ingestable is True


def test_tdp_is_skipped_without_any_fetch(conn, monkeypatch):
    """Not 'fetch and discard' — no request is issued at all."""
    import lobbybook.sources.platforms as mod

    def explode():
        raise AssertionError("texasdemocrats.org must never be fetched")

    monkeypatch.setattr(mod, "fetcher", explode)
    connector = PlatformsConnector()

    links, meta = connector.discover("tdp")
    assert links == []
    assert meta["skipped"] == "blocked_by_robots+canonical_url_broken"

    from lobbybook.sources.platforms import PlatformLink

    fake = PlatformLink(url=mod.TDP_PLATFORM_URL, cycle=2024, kind="pdf", label="TDP 2024")
    assert connector.ingest_platform(conn, fake, "tdp")["skipped"] == (
        "blocked_by_robots+canonical_url_broken"
    )

    result = connector.backfill(conn, parties=["tdp"])
    assert [s["party"] for s in result["skipped_parties"]] == ["tdp"]
    assert result["planks"] == 0


def test_every_party_policy_is_self_describing():
    for key, p in PARTIES.items():
        assert p.key == key and p.name and p.abbr and p.note
        if not p.ingestable:
            assert p.skip_reason


# -------------------------------------------------------------------- live
@pytest.mark.live
def test_platforms_live_smoke(conn):
    from lobbybook.core.registry import get

    result = get("platforms").smoke(conn)
    assert result.ok, result.detail
    assert result.stats["pdf_editions"] >= 2
    assert result.stats["planks"] >= 50
    assert result.stats["subsection_spread"] >= 3
    assert result.stats["colliding_numbers"] >= 1
    # /platform/ 301s to /official-documents-2/ — verified live, not assumed.
    assert "official-documents" in (result.stats["redirected_to"] or "")
