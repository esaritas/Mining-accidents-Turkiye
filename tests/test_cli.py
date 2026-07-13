"""End-to-end CLI flows against a scratch database (synthetic data only)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import REPO_ROOT
from mining_accidents.cli import app

runner = CliRunner()
EXAMPLE_DIR = REPO_ROOT / "data" / "staging" / "example_manual_import"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    db = tmp_path / "cli.sqlite"
    result = runner.invoke(
        app,
        ["create-db", "--db-path", str(db), "--no-snapshot"],
    )
    assert result.exit_code == 0, result.output
    return db


def test_create_db_and_idempotent_rerun(db_path: Path, tmp_path: Path) -> None:
    assert db_path.exists()
    result = runner.invoke(app, ["create-db", "--db-path", str(db_path), "--no-snapshot"])
    assert result.exit_code == 0
    assert "up to date" in result.output


def test_validate_vocabularies_command() -> None:
    result = runner.invoke(app, ["validate-vocabularies"])
    assert result.exit_code == 0, result.output
    assert "All vocabularies valid" in result.output


def test_import_qc_export_packets_flow(db_path: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "import-manual",
            "--db-path",
            str(db_path),
            "--documents",
            str(EXAMPLE_DIR / "source_documents.csv"),
            "--claims",
            str(EXAMPLE_DIR / "claims.csv"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Imported" in result.output

    report = tmp_path / "quality_report.json"
    result = runner.invoke(app, ["qc", "--db-path", str(db_path), "--report-path", str(report)])
    assert result.exit_code == 0, result.output
    assert report.exists()

    # Nothing is publishable yet: export runs but ships zero incidents.
    out_dir = tmp_path / "public"
    result = runner.invoke(app, ["export", "--db-path", str(db_path), "--output-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    assert "0 incidents" in result.output
    assert (out_dir / "export_manifest.json").exists()

    packet_dir = tmp_path / "packets"
    result = runner.invoke(
        app,
        ["packets", "--db-path", str(db_path), "--output-dir", str(packet_dir), "--pilot-slots"],
    )
    assert result.exit_code == 0, result.output
    assert len(list(packet_dir.glob("PILOT-*.md"))) == 12


def test_qc_exits_nonzero_on_critical(db_path: Path, tmp_path: Path) -> None:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO incidents (province_code) VALUES ('99')")
    conn.commit()
    conn.close()
    result = runner.invoke(
        app,
        ["qc", "--db-path", str(db_path), "--report-path", str(tmp_path / "r.json")],
    )
    assert result.exit_code == 1

    result = runner.invoke(
        app, ["export", "--db-path", str(db_path), "--output-dir", str(tmp_path / "public")]
    )
    assert result.exit_code == 1
    assert "Export blocked" in result.output


def test_import_requires_input(db_path: Path) -> None:
    result = runner.invoke(app, ["import-manual", "--db-path", str(db_path)])
    assert result.exit_code == 2
