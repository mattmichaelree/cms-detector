"""LobbyBook CLI.

Usage:
    python -m lobbybook.cli init-db
    python -m lobbybook.cli sources
    python -m lobbybook.cli ingest <source> [--mode incremental|backfill] [key=value ...]
    python -m lobbybook.cli smoke [<source> ...]
    python -m lobbybook.cli demo <session> <bill>       # e.g. demo 89R HB1
"""

from __future__ import annotations

import argparse
import json
import sys

from lobbybook.core import db as dbx
from lobbybook.core import registry


def _kv(pairs: list[str]) -> dict:
    out = {}
    for p in pairs:
        if "=" not in p:
            raise SystemExit(f"expected key=value, got {p!r}")
        k, v = p.split("=", 1)
        out[k] = v
    return out


def cmd_init_db(_args) -> int:
    conn = dbx.connect()
    dbx.init_db(conn)
    print(f"initialized {dbx.db_path()}")
    return 0


def cmd_sources(_args) -> int:
    registry.load_all()
    for name in registry.names():
        c = registry.get(name)
        print(f"{name:<16} tier={c.tier}  cadence={c.cadence}")
    return 0


def cmd_ingest(args) -> int:
    conn = dbx.connect()
    dbx.init_db(conn)
    c = registry.get(args.source)
    fn = c.incremental if args.mode == "incremental" else c.backfill
    result = fn(conn, **_kv(args.params))
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_smoke(args) -> int:
    conn = dbx.connect()
    dbx.init_db(conn)
    names = args.source or registry.names()
    failures = 0
    for name in names:
        c = registry.get(name)
        try:
            r = c.smoke(conn)
        except NotImplementedError:
            print(f"[skip] {name}: no smoke test")
            continue
        except Exception as exc:  # noqa: BLE001 — smoke reports, never crashes the run
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        if r.ok:
            mark = "ok"
        elif r.blocked:
            # The source refused us; the connector is not at fault, so this
            # must not read as a bug and must not fail the run.
            mark = "blkd"
        else:
            mark = "FAIL"
            failures += 1
        print(f"[{mark:>4}] {name}: {r.detail}")
    return 1 if failures else 0


def cmd_sweep(args) -> int:
    """Run every connector matching a cadence/tier filter."""
    from lobbybook import orchestrator as orch

    conn = dbx.connect()
    dbx.init_db(conn)
    results = orch.sweep(
        conn,
        cadence=args.cadence,
        tier=args.tier,
        only_overdue=not args.force,
        mode=args.mode,
    )
    if not results:
        print("nothing due")
        return 0
    failures = 0
    for r in results:
        mark = "ok" if r.ok else "FAIL"
        failures += 0 if r.ok else 1
        print(f"[{mark:>4}] {r.connector:<16} {r.seconds:6.1f}s  {r.detail[:90]}")
    return 1 if failures else 0


def cmd_status(_args) -> int:
    from lobbybook import orchestrator as orch

    conn = dbx.connect()
    dbx.init_db(conn)
    print(f"{'connector':<16} {'tier':<5} {'cadence':<20} {'last success':<22} due")
    for row in orch.status(conn):
        print(
            f"{row['connector']:<16} {row['tier']:<5} {row['cadence']:<20} "
            f"{row['last_success'] or '-':<22} {'YES' if row['overdue'] else ''}"
        )
    return 0


def cmd_demo(args) -> int:
    """End-to-end dossier for one bill: TLO + fiscal + HRO + witnesses + journals."""
    conn = dbx.connect()
    dbx.init_db(conn)
    session, bill = args.session, args.bill
    from lobbybook.demo import build_dossier

    print(build_dossier(conn, session, bill))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lobbybook")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").set_defaults(fn=cmd_init_db)
    sub.add_parser("sources").set_defaults(fn=cmd_sources)
    p = sub.add_parser("ingest")
    p.add_argument("source")
    p.add_argument("--mode", choices=["incremental", "backfill"], default="incremental")
    p.add_argument("params", nargs="*")
    p.set_defaults(fn=cmd_ingest)
    p = sub.add_parser("smoke")
    p.add_argument("source", nargs="*")
    p.set_defaults(fn=cmd_smoke)
    p = sub.add_parser("sweep")
    p.add_argument("--cadence")
    p.add_argument("--tier", type=int)
    p.add_argument("--mode", choices=["incremental", "backfill"], default="incremental")
    p.add_argument("--force", action="store_true", help="run even if not overdue")
    p.set_defaults(fn=cmd_sweep)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    p = sub.add_parser("demo")
    p.add_argument("session")
    p.add_argument("bill")
    p.set_defaults(fn=cmd_demo)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
