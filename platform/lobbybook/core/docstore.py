"""Immutable document store.

Every fetched artifact lands here before parsing: a `document` row (identity)
plus `document_version` rows (content). Versions are content-addressed by
sha256 — refetching identical bytes is a no-op; changed bytes append a new
version (the audit's replaced-in-place PDFs become an explicit history
instead of silent loss).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def blob_root() -> Path:
    return Path(os.environ.get("LOBBYBOOK_BLOBS", "var/blobs"))


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def store_document(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    source_family: str,
    content: bytes,
    url: str | None = None,
    native_id: str | None = None,
    doc_type: str | None = None,
    session_id: str | None = None,
    published_at: str | None = None,
    authority: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
) -> tuple[str, bool]:
    """Store one artifact. Returns (doc_id, changed) — changed is False when
    the bytes match the latest stored version."""
    sha = hashlib.sha256(content).hexdigest()
    conn.execute(
        """INSERT INTO document (id, source_family, native_id, url, doc_type, session_id,
                                 published_at, authority)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             url=COALESCE(excluded.url, document.url),
             doc_type=COALESCE(excluded.doc_type, document.doc_type),
             published_at=COALESCE(excluded.published_at, document.published_at)""",
        (doc_id, source_family, native_id, url, doc_type, session_id, published_at, authority),
    )
    existing = conn.execute(
        "SELECT sha256 FROM document_version WHERE document_id=? ORDER BY version_no DESC LIMIT 1",
        (doc_id,),
    ).fetchone()
    if existing and existing["sha256"] == sha:
        return doc_id, False
    dup = conn.execute(
        "SELECT 1 FROM document_version WHERE document_id=? AND sha256=?", (doc_id, sha)
    ).fetchone()
    if dup:
        return doc_id, False

    version_no = 1 + (
        conn.execute(
            "SELECT COALESCE(MAX(version_no),0) AS n FROM document_version WHERE document_id=?",
            (doc_id,),
        ).fetchone()["n"]
    )
    rel = Path(sha[:2]) / sha[2:4] / sha
    path = blob_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(content)
    conn.execute(
        """INSERT INTO document_version
           (document_id, version_no, sha256, retrieved_at, blob_path, http_etag, http_last_modified)
           VALUES (?,?,?,?,?,?,?)""",
        (doc_id, version_no, sha, _now(), str(rel), etag, last_modified),
    )
    return doc_id, True


def load_latest(conn: sqlite3.Connection, doc_id: str) -> bytes | None:
    row = conn.execute(
        "SELECT blob_path FROM document_version WHERE document_id=? ORDER BY version_no DESC LIMIT 1",
        (doc_id,),
    ).fetchone()
    if not row:
        return None
    return (blob_root() / row["blob_path"]).read_bytes()
