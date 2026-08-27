"""Connector registry.

Each source module defines a Connector subclass and registers it. Connectors
may also register extra DDL (per-source staging tables) without touching
schema.sql — keeps swarm-built modules conflict-free.
"""

from __future__ import annotations

import importlib
import pkgutil
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field


@dataclass
class SmokeResult:
    ok: bool
    detail: str
    stats: dict = field(default_factory=dict)
    #: True when the source refused us rather than the connector misbehaving —
    #: a CDN challenge, a rate limit, a login wall. A blocked smoke is still not
    #: ``ok``, but it is not evidence of a bug, so the CLI reports it separately
    #: and does not fail the run on it. Anything else is ours to fix.
    blocked: bool = False


class Connector:
    """Base class. Subclasses set `name`, may set `DDL`, and implement any of
    backfill/incremental/smoke that make sense for the source."""

    name: str = "base"
    tier: int = 9
    cadence: str = "manual"
    DDL: str = ""

    def backfill(self, conn: sqlite3.Connection, **kwargs) -> dict:
        raise NotImplementedError

    def incremental(self, conn: sqlite3.Connection, **kwargs) -> dict:
        raise NotImplementedError

    def smoke(self, conn: sqlite3.Connection) -> SmokeResult:
        """One bounded live fetch proving the source is reachable and parseable."""
        raise NotImplementedError


_REGISTRY: dict[str, type[Connector]] = {}


def register(cls: type[Connector]) -> type[Connector]:
    _REGISTRY[cls.name] = cls
    return cls


def load_all() -> None:
    """Import every module in lobbybook.sources so registrations run."""
    import lobbybook.sources as pkg

    for mod in pkgutil.iter_modules(pkg.__path__):
        if not mod.name.startswith("_"):
            importlib.import_module(f"lobbybook.sources.{mod.name}")
    import lobbybook.spine  # noqa: F401  (spine registers its loaders too)


def get(name: str) -> Connector:
    load_all()
    return _REGISTRY[name]()


def names() -> list[str]:
    load_all()
    return sorted(_REGISTRY)


def iter_ddl() -> Iterator[str]:
    load_all()
    for cls in _REGISTRY.values():
        if cls.DDL:
            yield cls.DDL
