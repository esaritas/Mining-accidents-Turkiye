"""Source-registry loader and the reviewer CLI commands (synthetic data only)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from conftest import REPO_ROOT, make_claim, make_incident, make_source_document
from mining_accidents import database, provenance
from mining_accidents.cli import app

runner = CliRunner()


def test_registry_csv_loads_and_upserts(conn: sqlite3.Connection) -> None:
    csv_path = REPO_ROOT / "docs" / "source_registry.csv"
    created, updated = provenance.import_source_registry(conn, csv_path)
    assert created == 10 and updated == 0

    keys = {row["source_key"] for row in conn.execute("SELECT source_key FROM source_registry")}
    assert {"tbmm", "sgk", "manual", "isig_meclisi", "wikidata", "wikipedia"} <= keys

    # Second run updates in place instead of duplicating.
    created, updated = provenance.import_source_registry(conn, csv_path)
    assert created == 0 and updated == 10
    assert conn.execute("SELECT COUNT(*) FROM source_registry").fetchone()[0] == 10


def test_registry_entries_flagged_stale_by_qc(conn: sqlite3.Connection) -> None:
    from mining_accidents import quality

    provenance.import_source_registry(conn, REPO_ROOT / "docs" / "source_registry.csv")
    findings = quality.check_source_registry_freshness(conn, "2100-01-01T00:00:00Z")
    # Unassessed entries + assessments stale relative to the pinned clock.
    assert len(findings) == 10
    assert all(f.check_id == "QC-W05" for f in findings)


def _cli_db(tmp_path: Path) -> Path:
    db = tmp_path / "cli.sqlite"
    result = runner.invoke(app, ["create-db", "--db-path", str(db), "--no-snapshot"])
    assert result.exit_code == 0, result.output
    return db


def test_import_registry_command(tmp_path: Path) -> None:
    db = _cli_db(tmp_path)
    result = runner.invoke(app, ["import-registry", "--db-path", str(db)])
    assert result.exit_code == 0, result.output
    assert "10 created" in result.output


def test_decide_assign_merge_flow(tmp_path: Path) -> None:
    db = _cli_db(tmp_path)
    conn = database.get_connection(db)
    doc = make_source_document(conn)
    incident = make_incident(conn)
    claim = make_claim(
        conn,
        doc,
        incident_id=incident,
        field_name="incident_start_datetime",
        normalized_value="2099-05-10T00:00:00+03:00",
    )
    duplicate = make_incident(conn, incident_start_datetime="2099-05-11T00:00:00+03:00")
    conn.close()

    result = runner.invoke(
        app,
        [
            "decide",
            "--db-path",
            str(db),
            "--incident-id",
            str(incident),
            "--field",
            "incident_start_datetime",
            "--decision",
            "accept_claim",
            "--claim-id",
            str(claim),
            "--rationale",
            "TEST synthetic decision",
            "--reviewer",
            "TEST-reviewer",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Decision 1 recorded" in result.output

    # A second decision without supersession is rejected with a clear error.
    result = runner.invoke(
        app,
        [
            "decide",
            "--db-path",
            str(db),
            "--incident-id",
            str(incident),
            "--field",
            "incident_start_datetime",
            "--decision",
            "defer",
            "--rationale",
            "TEST",
            "--reviewer",
            "TEST-reviewer",
        ],
    )
    assert result.exit_code == 1
    assert "supersedes_decision_id" in result.output

    result = runner.invoke(
        app,
        [
            "assign-public-id",
            "--db-path",
            str(db),
            "--incident-id",
            str(incident),
            "--actor",
            "TEST-reviewer",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "TR-MINE-2099-0001" in result.output

    result = runner.invoke(
        app,
        [
            "merge",
            "--db-path",
            str(db),
            "--surviving-id",
            str(incident),
            "--merged-id",
            str(duplicate),
            "--reason",
            "TEST duplicate",
            "--reviewer",
            "TEST-reviewer",
        ],
    )
    assert result.exit_code == 0, result.output

    conn = database.get_connection(db)
    assert (
        conn.execute(
            "SELECT incident_start_datetime FROM incidents WHERE incident_id = ?", (incident,)
        ).fetchone()[0]
        == "2099-05-10T00:00:00+03:00"
    )
    assert conn.execute("SELECT COUNT(*) FROM incident_merge_log").fetchone()[0] == 1
    conn.close()


def test_decide_rejects_invalid_decision_type(tmp_path: Path) -> None:
    db = _cli_db(tmp_path)
    conn = database.get_connection(db)
    incident = make_incident(conn)
    conn.close()
    result = runner.invoke(
        app,
        [
            "decide",
            "--db-path",
            str(db),
            "--incident-id",
            str(incident),
            "--field",
            "province_code",
            "--decision",
            "auto_resolve",  # not a decision type — no silent resolution exists
            "--rationale",
            "TEST",
            "--reviewer",
            "TEST-reviewer",
        ],
    )
    assert result.exit_code == 1
    assert "Decision rejected" in result.output
