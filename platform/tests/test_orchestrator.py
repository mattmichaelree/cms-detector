from __future__ import annotations

from lobbybook import orchestrator as orch
from lobbybook.core.registry import Connector, SmokeResult, register


@register
class _FlakyConnector(Connector):
    """A source that is down — a normal Tuesday for state websites."""

    name = "_test_flaky"
    tier = 9
    cadence = "daily"

    def incremental(self, conn, **kwargs):
        raise RuntimeError("upstream 503")

    def smoke(self, conn):
        return SmokeResult(ok=False, detail="down")


@register
class _GoodConnector(Connector):
    name = "_test_good"
    tier = 9
    cadence = "daily"

    def incremental(self, conn, **kwargs):
        return {"rows": 3}


def test_run_records_success_and_clears_overdue(conn):
    assert orch.overdue(conn, "_test_good") is True
    r = orch.run_one(conn, "_test_good")
    assert r.ok and "rows" in r.detail
    assert orch.overdue(conn, "_test_good") is False
    assert orch.last_success(conn, "_test_good") is not None


def test_failure_is_recorded_not_raised(conn):
    r = orch.run_one(conn, "_test_flaky")
    assert r.ok is False
    assert "upstream 503" in r.detail
    # A failed run must not count as a success, so the source stays due.
    assert orch.overdue(conn, "_test_flaky") is True
    row = conn.execute(
        "SELECT error, ok FROM ingest_run WHERE connector='_test_flaky' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["ok"] == 0 and "RuntimeError" in row["error"]


def test_sweep_continues_past_a_failing_source(conn):
    results = orch.sweep(conn, tier=9)
    by_name = {r.connector: r for r in results}
    # Both ran even though one raised — one dead site cannot stall the sweep.
    assert by_name["_test_flaky"].ok is False
    assert by_name["_test_good"].ok is True


def test_static_cadence_is_load_once(conn):
    assert orch.overdue(conn, "spine_sessions") is True
    orch.run_one(conn, "spine_sessions", "backfill")
    assert orch.overdue(conn, "spine_sessions") is False


def test_not_implemented_is_not_a_failure(conn):
    """A connector without a backfill path is a gap, not an error — recording
    it as failure would make the sweep permanently red."""

    @register
    class _PartialConnector(Connector):
        name = "_test_partial"
        tier = 9
        cadence = "daily"

    r = orch.run_one(conn, "_test_partial", "backfill")
    assert r.ok is True and "not implemented" in r.detail


def test_status_covers_every_registered_connector(conn):
    rows = orch.status(conn)
    names = {r["connector"] for r in rows}
    for expected in ("tlo", "journals", "register", "tec", "spine_people"):
        assert expected in names
    assert all("cadence" in r and "overdue" in r for r in rows)
