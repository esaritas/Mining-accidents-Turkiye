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


def make_publishable_incident(conn: sqlite3.Connection, seq_hint: str = "A") -> dict[str, Any]:
    """A fully synthetic incident satisfying all seven publication rules.

    Builds the complete evidence chain via the real review module:
    document -> claims -> decisions -> canonical values -> sign-off flags.
    """
    from mining_accidents import review
    from mining_accidents.models import ClaimDecision

    doc = make_source_document(
        conn,
        title=f"TEST synthetic report {seq_hint}",
        url=f"file:///dev/null/TEST-{seq_hint}",
        content_hash=(f"{ord(seq_hint):02x}" * 32),
    )
    incident = make_incident(
        conn,
        canonical_title_tr=f"TEST olay kaydı {seq_hint}",
        incident_status="in_scope",
        scope_rationale="TEST synthetic fixture",
        date_precision="exact_date",
    )
    claims = {
        "incident_start_datetime": make_claim(
            conn,
            doc,
            incident_id=incident,
            field_name="incident_start_datetime",
            raw_value="10 Mayıs 2099",
            normalized_value="2099-05-10T00:00:00+03:00",
            assertion_status="official_finding",
        ),
        "province_code": make_claim(
            conn,
            doc,
            incident_id=incident,
            field_name="province_code",
            raw_value="TEST ili",
            normalized_value="67",
            assertion_status="official_finding",
        ),
        "fatalities_current": make_claim(
            conn,
            doc,
            incident_id=incident,
            field_name="fatalities_current",
            raw_value="üç",
            normalized_value="3",
            assertion_status="official_finding",
        ),
    }
    for field, claim_id in claims.items():
        review.record_decision(
            conn,
            ClaimDecision(
                incident_id=incident,
                field_name=field,
                decision="accept_claim",
                selected_claim_id=claim_id,
                rationale="TEST synthetic decision",
                reviewer="TEST-reviewer",
            ),
        )
    public_id = review.assign_public_incident_id(conn, incident, actor="TEST-reviewer")

    classification_claim = make_claim(
        conn,
        doc,
        incident_id=incident,
        claim_subject_type="classification",
        field_name="event_mechanism",
        raw_value="göçük",
        normalized_value="roof_or_ground_collapse",
        assertion_status="official_finding",
    )
    insert(
        conn,
        "incident_classifications",
        incident_id=incident,
        classification_system="project_event_mechanism",
        classification_code="roof_or_ground_collapse",
        classification_label_tr="tavan/göçük",
        assertion_status="official_finding",
        source_claim_id=classification_claim,
        review_status="reviewed",
    )
    org = make_organization(conn, organization_name_tr=f"TEST Madencilik {seq_hint} A.Ş.")
    role_claim = make_claim(
        conn,
        doc,
        incident_id=incident,
        claim_subject_type="organization",
        field_name="operator",
        raw_value=f"TEST Madencilik {seq_hint} A.Ş.",
        assertion_status="reported",
    )
    insert(
        conn,
        "incident_organization_roles",
        incident_id=incident,
        organization_id=org,
        role="operator",
        source_claim_id=role_claim,
        assertion_status="reported",
        review_status="reviewed",
    )
    conn.execute(
        "UPDATE incidents SET verification_status = 'reviewed', publication_status = 'publishable' "
        "WHERE incident_id = ?",
        (incident,),
    )
    conn.commit()
    return {"incident": incident, "doc": doc, "org": org, "public_id": public_id, **claims}
