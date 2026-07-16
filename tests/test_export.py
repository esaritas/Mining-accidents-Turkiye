"""Export behaviour: QC gate, eligibility filtering, determinism, packets."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from conftest import make_incident, make_publishable_incident
from mining_accidents import export, packets

NOW = "2100-01-01T00:00:00Z"


@pytest.fixture(autouse=True)
def _fixed_epoch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "4102444800")  # 2100-01-01T00:00:00Z


def _build(conn: sqlite3.Connection, out: Path) -> dict[str, object]:
    return export.build_public_export(conn, out, reference_time=NOW)


def test_critical_qc_failure_aborts_export(conn: sqlite3.Connection, tmp_path: Path) -> None:
    make_publishable_incident(conn)
    make_incident(conn, province_code="99")  # QC-C03 critical
    with pytest.raises(export.ExportBlockedError, match="QC-C03"):
        _build(conn, tmp_path / "out")
    assert not (tmp_path / "out" / "incidents.csv").exists()


def test_cli_export_exits_nonzero_on_critical(conn: sqlite3.Connection, tmp_path: Path) -> None:
    make_incident(conn, province_code="99")
    with pytest.raises(export.ExportBlockedError):
        export.build_public_export(conn, tmp_path / "out")


def test_publishable_record_exports_and_below_threshold_excluded(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    fixture = make_publishable_incident(conn, "A")
    # Below-threshold record: reviewed but no editorial sign-off.
    make_incident(
        conn,
        canonical_title_tr="TEST eşik altı kayıt",
        verification_status="reviewed",
        publication_status="internal",
    )
    out = tmp_path / "out"
    manifest = _build(conn, out)
    assert manifest["row_counts"]["incidents"] == 1

    lines = (out / "incidents.csv").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # header + one record
    assert fixture["public_id"] in lines[1]
    assert "TEST eşik altı kayıt" not in "\n".join(lines)

    incidents = json.loads((out / "incidents.json").read_text(encoding="utf-8"))
    assert incidents[0]["public_incident_id"] == fixture["public_id"]
    assert incidents[0]["fatalities_current"] == 3

    classifications = (out / "incident_classifications.csv").read_text(encoding="utf-8")
    assert "roof_or_ground_collapse" in classifications

    roles = (out / "incident_organization_roles.csv").read_text(encoding="utf-8")
    assert "TEST Madencilik A A.Ş." in roles
    assert "reported" in roles  # assertion status always shipped

    sources = (out / "sources.csv").read_text(encoding="utf-8")
    assert "TEST synthetic report A" in sources

    datapackage = json.loads((out / "datapackage.json").read_text(encoding="utf-8"))
    assert {r["path"] for r in datapackage["resources"]} >= {
        "incidents.csv",
        "sources.csv",
        "facilities.csv",
        "facility_organization_roles.csv",
        "merged_id_redirects.csv",
    }
    # Sites context registry ships (empty here — no claim-backed facilities),
    # and the partial-coverage statement travels with the datapackage.
    assert (out / "facilities.csv").exists()
    assert (out / "facility_organization_roles.csv").exists()
    assert "not a complete register" in datapackage["description"]


def test_export_is_deterministic_byte_identical(conn: sqlite3.Connection, tmp_path: Path) -> None:
    make_publishable_incident(conn, "A")
    make_publishable_incident(conn, "B")
    out1, out2 = tmp_path / "run1", tmp_path / "run2"
    _build(conn, out1)
    _build(conn, out2)
    files1 = sorted(p.name for p in out1.iterdir())
    files2 = sorted(p.name for p in out2.iterdir())
    assert files1 == files2 and files1
    for name in files1:
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes(), name


def test_manifest_contents(conn: sqlite3.Connection, tmp_path: Path) -> None:
    make_publishable_incident(conn)
    out = tmp_path / "out"
    _build(conn, out)
    manifest = json.loads((out / "export_manifest.json").read_text(encoding="utf-8"))
    assert manifest["export_timestamp"] == "2100-01-01T00:00:00Z"
    assert manifest["db_schema_version"] == "002"
    assert set(manifest["file_sha256"]) >= {"incidents.csv", "datapackage.json"}
    assert all(len(h) == 64 for h in manifest["file_sha256"].values())
    assert manifest["vocabulary_versions"]["hazards.csv"] == "1.0"
    assert manifest["quality_findings"]["critical"] == 0


def test_merge_redirects_exported(conn: sqlite3.Connection, tmp_path: Path) -> None:
    from mining_accidents import review

    fixture_a = make_publishable_incident(conn, "A")
    fixture_b = make_publishable_incident(conn, "B")
    review.merge_incidents(
        conn,
        fixture_a["incident"],
        fixture_b["incident"],
        reason="TEST duplicate",
        reviewer="TEST-reviewer",
    )
    out = tmp_path / "out"
    manifest = _build(conn, out)
    assert manifest["row_counts"]["incidents"] == 1  # merged record withdrawn
    redirects = (out / "merged_id_redirects.csv").read_text(encoding="utf-8").splitlines()
    assert redirects[1] == f"{fixture_b['public_id']},{fixture_a['public_id']}"


def test_excerpt_cap_applied_at_export_boundary(conn: sqlite3.Connection, tmp_path: Path) -> None:
    fixture = make_publishable_incident(conn)
    # Force an overlong excerpt directly (bypassing the importer) to prove the
    # export boundary still refuses to ship it.
    overlong = " ".join(["kelime"] * 50)
    conn.execute(
        "INSERT INTO claims (incident_id, source_document_id, claim_subject_type, field_name, "
        "raw_value, normalized_value, extraction_method, short_evidence_excerpt, review_status) "
        "VALUES (?, ?, 'incident', 'settlement', 'TEST', 'TEST', 'manual', ?, 'reviewed')",
        (fixture["incident"], fixture["doc"], overlong),
    )
    claim_id = conn.execute("SELECT MAX(claim_id) FROM claims").fetchone()[0]
    from mining_accidents import review
    from mining_accidents.models import ClaimDecision

    review.record_decision(
        conn,
        ClaimDecision(
            incident_id=fixture["incident"],
            field_name="settlement",
            decision="accept_claim",
            selected_claim_id=claim_id,
            rationale="TEST",
            reviewer="TEST-reviewer",
        ),
    )
    out = tmp_path / "out"
    _build(conn, out)
    assert overlong not in (out / "sources.csv").read_text(encoding="utf-8")


def test_pilot_slots_and_incident_packets(conn: sqlite3.Connection, tmp_path: Path) -> None:
    paths = packets.create_pilot_slots(tmp_path / "packets")
    assert len(paths) == 12
    content = paths[0].read_text(encoding="utf-8")
    assert "large casualty count" in content
    assert "Reviewer sign-off" in content
    assert "EMPTY by design" in content

    fixture = make_publishable_incident(conn)
    generated = packets.generate_all(conn, tmp_path / "packets")
    assert [p.name for p in generated] == [f"{fixture['public_id']}.md"]
    packet = generated[0].read_text(encoding="utf-8")
    assert "Extracted claims" in packet
    assert "TEST synthetic report A" in packet
