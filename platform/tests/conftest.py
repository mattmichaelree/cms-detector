from __future__ import annotations

import os
from pathlib import Path

import pytest

from lobbybook.core import db as dbx

FIXTURES = Path(__file__).parent.parent / "fixtures"

LIVE = os.environ.get("LOBBYBOOK_LIVE") == "1"


def pytest_collection_modifyitems(config, items):
    if LIVE:
        return
    skip = pytest.mark.skip(reason="live tests disabled (set LOBBYBOOK_LIVE=1)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("LOBBYBOOK_BLOBS", str(tmp_path / "blobs"))
    c = dbx.connect(tmp_path / "test.db")
    dbx.init_db(c)
    yield c
    c.close()


@pytest.fixture()
def fixtures() -> Path:
    return FIXTURES
