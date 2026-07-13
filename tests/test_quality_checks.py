"""Quality-check suite behaviour (synthetic TEST- data only).

reference_time is pinned to a synthetic 'now' so fixtures with far dates
behave deterministically.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from conftest import make_claim, make_incident, make_source_document
from mining_accidents import quality

NOW = "2100-01-01T00:00:00Z"  # synthetic reference clock for the fixtures


def _ids(findings: list[quality.QualityFinding]) -> set[str]:
    return {f.check_id for f in findings}


def test_clean_database_has_no_findings(conn: sqlite3.Connection) -> None:
    findings = quality.run_all_checks(conn, reference_time=NOW)
    assert findings == []
    assert not quality.has_critical(findings)


def test_invalid_dates_flagged(conn: sqlite3.Connection) -> None:
    make_incident(
        conn,
        incident_start_datetime="2099-05-10T00:00:00+03:00",
        incident_end_datetime="2099-05-09T00:00:00+03:00",
    )
    make_incident(conn, incident_start_datetime="2101-01-01T00:00:00+03:00")  # future
    make_incident(conn, incident_start_datetime="1750-01-01T00:00:00+03:00")  # pre-1800
    findings = quality.check_invalid_dates(conn, NOW)
    assert len(findings) == 3
    assert all(f.severity == "critical" for f in findings)


def test_negative_counts_flagged(conn: sqlite3.Connection) -> None:
    incident = make_incident(conn, fatalities_current=-1)
    conn.execute(
        "INSERT INTO casualty_observations (incident_id, fatalities) VALUES (?, -2)", (incident,)
    )
    findings = quality.check_negative_casualties(conn)
    assert len(findings) == 2


def test_unknown_province_flagged(conn: sqlite3.Connection) -> None:
    make_incident(conn, province_code="99")
    assert _ids(quality.check_admin_codes(conn)) == {"QC-C03"}


def test_exact_coordinates_need_source_claim(conn: sqlite3.Connection) -> None:
    make_incident(conn, latitude=39.0, longitude=32.8, coordinate_precision="exact_verified")
    assert _ids(quality.check_exact_coordinates_have_source(conn)) == {"QC-C04"}


def test_publishable_without_decisions_is_critical(conn: sqlite3.Connection) -> None:
    make_incident(conn, publication_status="publishable")
    findings = quality.check_publication_critical_decisions(conn)
    assert len(findings) == 3  # one per publication-critical field
    assert all(f.severity == "critical" for f in findings)


def test_unreviewed_ai_claim_selected_is_critical(conn: sqlite3.Connection) -> None:
    doc = make_source_document(conn)
    incident = make_incident(conn)
    ai_claim = make_claim(
        conn,
        doc,
        incident_id=incident,
        extraction_method="ai_assisted",
        review_status="needs_review",
    )
    # Bypass review.py guards deliberately to prove QC catches raw inserts.
    conn.execute(
        "INSERT INTO claim_decisions (incident_id, field_name, selected_claim_id, decision, "
        "rationale, reviewer) VALUES (?, 'fatalities_current', ?, 'accept_claim', 'TEST', 'T')",
        (incident, ai_claim),
    )
    assert _ids(quality.check_canonical_ai_claims_reviewed(conn)) == {"QC-C07"}


def test_cited_document_missing_hash_is_critical(conn: sqlite3.Connection) -> None:
    doc = make_source_document(conn, content_hash=None, retrieved_at=None)
    incident = make_incident(conn)
    claim = make_claim(conn, doc, incident_id=incident)
    conn.execute(
        "INSERT INTO claim_decisions (incident_id, field_name, selected_claim_id, decision, "
        "rationale, reviewer) VALUES (?, 'fatalities_current', ?, 'accept_claim', 'TEST', 'T')",
        (incident, claim),
    )
    findings = quality.check_cited_documents_complete(conn)
    assert _ids(findings) == {"QC-C08"}
    assert "retrieved_at" in findings[0].message and "content_hash" in findings[0].message


def test_reretrieval_hash_conflict(conn: sqlite3.Connection) -> None:
    make_source_document(conn, url="file:///TEST-X", retrieved_at="2099-01-01T00:00:00Z")
    make_source_document(
        conn, url="file:///TEST-X", retrieved_at="2099-01-01T00:00:00Z", content_hash="f" * 64
    )
    assert _ids(quality.check_reretrieval_hash_conflicts(conn)) == {"QC-C09"}


def test_bbox_and_conflicting_claims_are_warnings(conn: sqlite3.Connection) -> None:
    doc = make_source_document(conn)
    incident = make_incident(
        conn, latitude=48.85, longitude=2.35, coordinate_precision="settlement"
    )
    make_claim(conn, doc, incident_id=incident, normalized_value="2")
    make_claim(conn, doc, incident_id=incident, normalized_value="3")
    findings = quality.run_all_checks(conn, reference_time=NOW)
    assert not quality.has_critical(findings)
    assert {"QC-W01", "QC-W03"} <= _ids(findings)


def test_multiple_canonical_observations_warning(conn: sqlite3.Connection) -> None:
    incident = make_incident(conn)
    for fatalities in (2, 3):
        conn.execute(
            "INSERT INTO casualty_observations (incident_id, fatalities, is_current_canonical) "
            "VALUES (?, ?, 1)",
            (incident, fatalities),
        )
    assert _ids(quality.check_single_canonical_observation(conn)) == {"QC-W04"}


def test_stale_registry_warning(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO source_registry (source_key, organization_or_family, last_assessed) "
        "VALUES ('TEST-source', 'TEST family', '2098-01-01')"
    )
    conn.execute(
        "INSERT INTO source_registry (source_key, organization_or_family) "
        "VALUES ('TEST-never', 'TEST family')"
    )
    findings = quality.check_source_registry_freshness(conn, NOW)
    assert len(findings) == 2
    assert _ids(findings) == {"QC-W05"}


def test_report_written_and_shaped(conn: sqlite3.Connection, tmp_path: Path) -> None:
    make_incident(conn, province_code="99")
    findings = quality.run_all_checks(conn, reference_time=NOW)
    report_path = quality.write_report(findings, tmp_path / "quality_report.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["counts"]["critical"] == 1
    assert report["findings"][0]["check_id"] == "QC-C03"
