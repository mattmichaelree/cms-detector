from __future__ import annotations

import pytest

from lobbybook.sources.register import (
    parse_notice,
    section_action,
    split_notices,
    store_notice,
)


def _fixture(fixtures, name: str) -> bytes:
    return (fixtures / "register" / name).read_bytes()


def test_section_action_decodes_percent_encoded_paths():
    # Section files live under paths with literal spaces ("Adopted Rules/"),
    # which arrive percent-encoded once resolved to absolute URLs.
    assert section_action("https://x/archive/August212026/Adopted%20Rules/1.ADMIN.html") == "adopted"
    assert section_action("https://x/archive/August212026/Proposed Rules/1.ADMIN.html") == "proposed"
    assert section_action("https://x/archive/August212026/In%20Addition/In Addition.html") == "in_addition"


def test_notices_split_on_trd_terminator(fixtures):
    notices = split_notices(_fixture(fixtures, "proposed_1.ADMINISTRATION.html"))
    assert len(notices) == 2
    assert [n["trd"] for n in notices] == ["TRD-202603358", "TRD-202603359"]


def test_proposed_notice_fields(fixtures):
    notices = split_notices(_fixture(fixtures, "proposed_1.ADMINISTRATION.html"))
    rec = parse_notice(notices[1], "proposed", "August 21, 2026")
    assert rec["agency"] == "Texas Health and Human Services Commission"
    assert rec["tac_cite"] == "1 TAC §353.1155"
    assert rec["earliest_adoption"] == "September 20, 2026"
    assert "Government Code §524.0151" in rec["authority"]
    assert "Human Resources Code §32.021" in rec["authority"]
    # Amendment markup: additions <u>, deletions [<s>..</s>].
    assert rec["additions"] > 100 and rec["deletions"] > 100


def test_relative_comment_deadline_is_resolved(fixtures):
    """HHSC states deadlines relative to the issue date; the absolute date is
    what a lobbyist needs, so it is computed and flagged as derived."""
    notices = split_notices(_fixture(fixtures, "proposed_1.ADMINISTRATION.html"))
    rec = parse_notice(notices[0], "proposed", "August 21, 2026")
    assert rec["comment_end"] == "September 21, 2026"
    assert rec["comment_end_derived"] is True
    # Without an issue date there is nothing to resolve against — no guessing.
    bare = parse_notice(notices[0], "proposed", None)
    assert bare["comment_end"] is None


def test_adopted_notice_links_back_to_its_proposal(fixtures):
    notices = split_notices(_fixture(fixtures, "adopted_1.ADMINISTRATION.html"))
    rec = parse_notice(notices[0], "adopted", "August 21, 2026")
    assert rec["trd"] == "TRD-202603326"
    assert rec["effective"] == "August 27, 2026"
    assert rec["filed_date"] == "August 7, 2026"
    # The adoption names when its proposal published — the lifecycle link.
    assert rec["proposal_pub_date"] == "March 20, 2026"


def test_store_notice_writes_rows_and_authority_edges(conn, fixtures):
    notices = split_notices(_fixture(fixtures, "proposed_1.ADMINISTRATION.html"))
    rec = parse_notice(notices[1], "proposed", "August 21, 2026")
    store_notice(conn, rec, None, "August 21, 2026")
    row = conn.execute("SELECT * FROM rule_action WHERE trd=?", (rec["trd"],)).fetchone()
    assert row["action_type"] == "proposed" and row["tac_cite"] == "1 TAC §353.1155"
    cites = {r["statute_cite"] for r in conn.execute("SELECT statute_cite FROM rule_authority")}
    assert "Government Code §524.0151" in cites
    edges = conn.execute(
        "SELECT COUNT(*) c FROM edge WHERE predicate='authorized_by' AND provenance='explicit'"
    ).fetchone()["c"]
    assert edges == len(cites)
    # Re-storing the same notice must be idempotent.
    store_notice(conn, rec, None, "August 21, 2026")
    assert conn.execute("SELECT COUNT(*) c FROM rule_action").fetchone()["c"] == 1


def test_no_comments_received_yields_no_commenters(fixtures):
    notices = split_notices(_fixture(fixtures, "adopted_1.ADMINISTRATION.html"))
    for n in notices:
        rec = parse_notice(n, "adopted", "August 21, 2026")
        for name in rec["commenters"]:
            assert "did not receive" not in name.lower()


@pytest.mark.live
def test_register_live_smoke(conn):
    from lobbybook.core.registry import get

    r = get("register").smoke(conn)
    assert r.ok, r.detail
