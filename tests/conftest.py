"""Shared synthetic fixtures. TEST- prefixed data only — never real incidents.

Role in the evidence flow: builds tiny synthetic evidence chains
(source document -> claim -> decision) against a scratch database created
from the real migrations, so tests exercise the exact production schema.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mining_accidents import database

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "database" / "migrations"
VOCAB_DIR = REPO_ROOT / "data" / "vocabularies"


@pytest.fixture()
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A connection to a fresh database built from the real migrations."""
    db_path = tmp_path / "test.sqlite"
    connection = database.get_connection(db_path)
    database.apply_migrations(connection, MIGRATIONS_DIR)
    yield connection
    connection.close()


def insert(conn: sqlite3.Connection, table: str, **values: Any) -> int:
    cols = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    cur = conn.execute(
        f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", tuple(values.values())
    )
    conn.commit()
    return int(cur.lastrowid)


def make_source_document(conn: sqlite3.Connection, **overrides: Any) -> int:
    values: dict[str, Any] = {
        "source_organization": "TEST Kaynak Kurumu",
        "title": "TEST synthetic source document",
        "document_type": "other",
        "url": "file:///dev/null/TEST-document",
        "retrieved_at": "2099-01-02T00:00:00Z",
        "language": "tr",
        "content_hash": "0" * 64,
        "source_tier": 2,
        "notes": "Synthetic fixture — no factual content.",
    }
    values.update(overrides)
    return insert(conn, "source_documents", **values)


def make_incident(conn: sqlite3.Connection, **overrides: Any) -> int:
    values: dict[str, Any] = {
        "canonical_title_tr": "TEST olay kaydı",
        "incident_status": "in_scope",
        "verification_status": "unverified",
        "publication_status": "draft",
    }
    values.update(overrides)
    return insert(conn, "incidents", **values)


def make_claim(
    conn: sqlite3.Connection,
    source_document_id: int,
    incident_id: int | None = None,
    **overrides: Any,
) -> int:
    values: dict[str, Any] = {
        "incident_id": incident_id,
        "source_document_id": source_document_id,
        "claim_subject_type": "incident",
        "field_name": "fatalities_current",
        "raw_value": "3",
        "normalized_value": "3",
        "extraction_method": "manual",
        "assertion_status": "reported",
        "review_status": "pending",
        "short_evidence_excerpt": "TEST synthetic excerpt",
    }
    values.update(overrides)
    return insert(conn, "claims", **values)


def make_organization(conn: sqlite3.Connection, **overrides: Any) -> int:
    values: dict[str, Any] = {
        "organization_name_tr": "TEST Madencilik A.Ş.",
        "organization_type": "private_company",
    }
    values.update(overrides)
    return insert(conn, "organizations", **values)
