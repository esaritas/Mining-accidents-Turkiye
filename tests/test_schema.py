"""Schema behaviour: FK enforcement, CHECK constraints, immutability triggers.

All data here is synthetic (TEST- prefixed) per the project's hard constraints.
"""

from __future__ import annotations

import sqlite3

import pytest

from conftest import make_claim, make_incident, make_organization, make_source_document


def test_foreign_keys_pragma_is_on(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_all_expected_tables_exist(conn: sqlite3.Connection) -> None:
    expected = {
        "incidents",
        "casualty_observations",
        "source_documents",
        "claims",
        "claim_decisions",
        "facilities",
        "facility_aliases",
        "organizations",
        "organization_aliases",
        "incident_organization_roles",
        "incident_classifications",
        "recommendations",
        "source_registry",
        "ingestion_runs",
        "review_log",
        "incident_merge_log",
        "schema_migrations",
        "aggregate_occupational_statistics",
        "aggregate_employment",
        "aggregate_production",
        "aggregate_licence_context",
        "classification_concordance",
    }
    actual = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert expected <= actual


def test_foreign_key_enforced_on_claims(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        make_claim(conn, source_document_id=99999)


def test_check_constraint_rejects_bad_review_status(conn: sqlite3.Connection) -> None:
    doc = make_source_document(conn)
    with pytest.raises(sqlite3.IntegrityError):
        make_claim(conn, doc, review_status="approved")


def test_check_constraint_rejects_bad_publication_status(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        make_incident(conn, publication_status="live")


def test_confidence_score_bounds(conn: sqlite3.Connection) -> None:
    doc = make_source_document(conn)
    with pytest.raises(sqlite3.IntegrityError):
        make_claim(conn, doc, confidence_score=1.5)


def test_claims_content_update_rejected(conn: sqlite3.Connection) -> None:
    doc = make_source_document(conn)
    claim = make_claim(conn, doc)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE claims SET raw_value = '4' WHERE claim_id = ?", (claim,))


def test_claims_delete_rejected(conn: sqlite3.Connection) -> None:
    doc = make_source_document(conn)
    claim = make_claim(conn, doc)
    with pytest.raises(sqlite3.IntegrityError, match="never deleted"):
        conn.execute("DELETE FROM claims WHERE claim_id = ?", (claim,))


def test_claims_workflow_updates_allowed(conn: sqlite3.Connection) -> None:
    doc = make_source_document(conn)
    incident = make_incident(conn)
    claim = make_claim(conn, doc)
    conn.execute("UPDATE claims SET review_status = 'reviewed' WHERE claim_id = ?", (claim,))
    conn.execute("UPDATE claims SET incident_id = ? WHERE claim_id = ?", (incident, claim))
    conn.commit()
    row = conn.execute("SELECT review_status, incident_id FROM claims").fetchone()
    assert (row["review_status"], row["incident_id"]) == ("reviewed", incident)


def test_ai_assisted_claim_must_be_needs_review(conn: sqlite3.Connection) -> None:
    doc = make_source_document(conn)
    with pytest.raises(sqlite3.IntegrityError, match="needs_review"):
        make_claim(conn, doc, extraction_method="ai_assisted", review_status="pending")
    claim = make_claim(conn, doc, extraction_method="ocr_assisted", review_status="needs_review")
    assert claim > 0


def test_source_documents_immutable(conn: sqlite3.Connection) -> None:
    doc = make_source_document(conn)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE source_documents SET title = 'x' WHERE source_document_id = ?", (doc,))
    with pytest.raises(sqlite3.IntegrityError, match="never deleted"):
        conn.execute("DELETE FROM source_documents WHERE source_document_id = ?", (doc,))


def test_ingestion_runs_immutable(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO ingestion_runs (run_type, started_at, status) "
        "VALUES ('manual_import', '2099-01-01T00:00:00Z', 'completed')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE ingestion_runs SET status = 'failed'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM ingestion_runs")


def test_claim_decisions_append_only(conn: sqlite3.Connection) -> None:
    incident = make_incident(conn)
    conn.execute(
        "INSERT INTO claim_decisions (incident_id, field_name, decision, rationale, reviewer) "
        "VALUES (?, 'province_code', 'defer', 'TEST rationale', 'TEST-reviewer')",
        (incident,),
    )
    with pytest.raises(sqlite3.IntegrityError, match="supersede"):
        conn.execute("UPDATE claim_decisions SET rationale = 'edited'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM claim_decisions")


def test_claim_decisions_require_rationale_and_reviewer(conn: sqlite3.Connection) -> None:
    incident = make_incident(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO claim_decisions (incident_id, field_name, decision, rationale, reviewer) "
            "VALUES (?, 'province_code', 'defer', '   ', 'TEST-reviewer')",
            (incident,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO claim_decisions (incident_id, field_name, decision, rationale, reviewer) "
            "VALUES (?, 'province_code', 'defer', 'TEST rationale', '')",
            (incident,),
        )


def test_casualty_observations_figures_immutable(conn: sqlite3.Connection) -> None:
    incident = make_incident(conn)
    conn.execute(
        "INSERT INTO casualty_observations (incident_id, fatalities) VALUES (?, 2)",
        (incident,),
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE casualty_observations SET fatalities = 5")
    conn.execute("UPDATE casualty_observations SET is_current_canonical = 1")
    conn.commit()


def test_recommendations_origin_fixed_to_source_finding(conn: sqlite3.Connection) -> None:
    doc = make_source_document(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO recommendations (source_document_id, recommendation_text, origin) "
            "VALUES (?, 'TEST recommendation', 'project_commentary')",
            (doc,),
        )


def test_incident_org_role_uniqueness(conn: sqlite3.Connection) -> None:
    doc = make_source_document(conn)
    incident = make_incident(conn)
    org = make_organization(conn)
    claim = make_claim(conn, doc, incident_id=incident, field_name="operator")

    def add_role() -> None:
        conn.execute(
            "INSERT INTO incident_organization_roles "
            "(incident_id, organization_id, role, source_claim_id) VALUES (?, ?, 'operator', ?)",
            (incident, org, claim),
        )

    add_role()
    with pytest.raises(sqlite3.IntegrityError):
        add_role()


def test_review_log_append_only(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO review_log (actor, action, occurred_at) "
        "VALUES ('TEST-reviewer', 'test_action', '2099-01-01T00:00:00Z')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE review_log SET action = 'edited'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM review_log")
