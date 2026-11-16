"""Ledger and restoration tests. Synthetic TEST- data only.

Role in the evidence flow: proves the two recovery paths. The ledger must
rebuild a database whose export is byte-identical to the one it was dumped
beside, and a restoration from a public export must reproduce that export
while saying plainly what it could not recover.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from conftest import MIGRATIONS_DIR, make_publishable_incident
from mining_accidents import export, ledger, quality, restore, review
from mining_accidents.database import get_connection
from mining_accidents.provenance import RESTORED_MARK

NOW = "2099-06-01T00:00:00Z"


@pytest.fixture(autouse=True)
def _fixed_epoch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "4102444800")  # 2100-01-01T00:00:00Z


def _data_hashes(directory: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir())
        if path.name != "export_manifest.json"
    }


def _register(conn: sqlite3.Connection) -> None:
    first = make_publishable_incident(conn, "A")
    second = make_publishable_incident(conn, "B")
    review.merge_incidents(
        conn, first["incident"], second["incident"], "TEST duplicate", "TEST Reviewer"
    )


def test_ledger_round_trip_is_byte_identical(conn: sqlite3.Connection, tmp_path: Path) -> None:
    _register(conn)
    export.build_public_export(conn, tmp_path / "public", reference_time=NOW)
    first = ledger.dump(conn, tmp_path / "ledger")
    assert first["tables"]["claim_decisions"]["rows"] >= 6

    ledger.load(tmp_path / "ledger", tmp_path / "rebuilt.sqlite", MIGRATIONS_DIR)
    rebuilt = get_connection(tmp_path / "rebuilt.sqlite")
    try:
        assert ledger.differences(rebuilt, tmp_path / "ledger") == []
        export.build_public_export(rebuilt, tmp_path / "public2", reference_time=NOW)
        # Immutability survives the rebuild: the triggers come from the schema.
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            rebuilt.execute("DELETE FROM claims")
    finally:
        rebuilt.close()
    assert _data_hashes(tmp_path / "public") == _data_hashes(tmp_path / "public2")


def test_ledger_never_overwrites_and_detects_tampering(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    make_publishable_incident(conn, "A")
    ledger.dump(conn, tmp_path / "ledger")
    target = tmp_path / "rebuilt.sqlite"
    ledger.load(tmp_path / "ledger", target, MIGRATIONS_DIR)
    with pytest.raises(ledger.LedgerError, match="never overwrites"):
        ledger.load(tmp_path / "ledger", target, MIGRATIONS_DIR)

    claims = tmp_path / "ledger" / "claims.jsonl"
    claims.write_text(claims.read_text("utf-8").replace('"3"', '"4"', 1), encoding="utf-8")
    with pytest.raises(ledger.LedgerError, match="does not match the hash"):
        ledger.load(tmp_path / "ledger", tmp_path / "other.sqlite", MIGRATIONS_DIR)


def test_ledger_drops_files_for_emptied_tables(conn: sqlite3.Connection, tmp_path: Path) -> None:
    make_publishable_incident(conn, "A")
    stale = tmp_path / "ledger" / "recommendations.jsonl"
    stale.parent.mkdir()
    stale.write_text("{}\n", encoding="utf-8")
    manifest = ledger.dump(conn, tmp_path / "ledger")
    assert "recommendations" not in manifest["tables"]
    assert not stale.exists()


def test_verify_ties_the_ledger_to_the_committed_export(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    _register(conn)
    export.build_public_export(conn, tmp_path / "public", reference_time=NOW)
    ledger.dump(conn, tmp_path / "ledger")
    assert ledger.verify(tmp_path / "ledger", tmp_path / "public", MIGRATIONS_DIR, NOW) == []

    incidents = tmp_path / "public" / "incidents.csv"
    incidents.write_text(incidents.read_text("utf-8").replace(",3,", ",4,", 1), encoding="utf-8")
    problems = ledger.verify(tmp_path / "ledger", tmp_path / "public", MIGRATIONS_DIR, NOW)
    assert any("incidents.csv" in problem for problem in problems)


def test_restoration_reproduces_the_export_it_was_built_from(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    _register(conn)
    export.build_public_export(conn, tmp_path / "public", reference_time=NOW)

    summary = restore.restore_from_export(
        tmp_path / "restored.sqlite",
        tmp_path / "public",
        reviewer="TEST Reviewer",
        export_label="TEST export",
        registry_csv=None,
        migrations_dir=MIGRATIONS_DIR,
    )
    assert summary.incidents == 1 and summary.withdrawn == 1

    restored = get_connection(tmp_path / "restored.sqlite")
    try:
        export.build_public_export(restored, tmp_path / "public2", reference_time=NOW)
        assert _data_hashes(tmp_path / "public") == _data_hashes(tmp_path / "public2")

        cited = restored.execute(
            "SELECT content_hash, notes FROM source_documents WHERE title LIKE 'TEST synthetic%'"
        ).fetchall()
        assert cited and all(row["content_hash"] is None for row in cited)
        assert all(row["notes"].startswith(RESTORED_MARK) for row in cited)

        decisions = restored.execute("SELECT reviewer, rationale FROM claim_decisions").fetchall()
        assert {row["reviewer"] for row in decisions} == {"TEST Reviewer"}
        assert all("not recoverable" in row["rationale"] for row in decisions)

        # A lost hash is reported, never treated as a defect of the record.
        findings = quality.run_all_checks(restored, reference_time=NOW)
        assert not [f for f in findings if f.severity == "critical"]
        assert any(f.check_id == "QC-W08" for f in findings)

        # A withdrawn identifier stays taken after a restoration.
        withdrawn = restored.execute(
            "SELECT public_incident_id FROM incidents WHERE publication_status = 'withdrawn'"
        ).fetchall()
        assert len(withdrawn) == 1
    finally:
        restored.close()


def test_restoration_needs_a_reviewer_and_an_empty_target(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    make_publishable_incident(conn, "A")
    export.build_public_export(conn, tmp_path / "public", reference_time=NOW)
    with pytest.raises(restore.RestoreError, match="reviewer"):
        restore.restore_from_export(
            tmp_path / "x.sqlite", tmp_path / "public", reviewer=" ", registry_csv=None
        )
    target = tmp_path / "restored.sqlite"
    restore.restore_from_export(
        target,
        tmp_path / "public",
        reviewer="TEST Reviewer",
        registry_csv=None,
        migrations_dir=MIGRATIONS_DIR,
    )
    with pytest.raises(restore.RestoreError, match="never overwrites"):
        restore.restore_from_export(
            target, tmp_path / "public", reviewer="TEST Reviewer", registry_csv=None
        )


def test_restoration_can_drop_a_name_from_a_document_title(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    make_publishable_incident(conn, "A")
    export.build_public_export(conn, tmp_path / "public", reference_time=NOW)
    restore.restore_from_export(
        tmp_path / "restored.sqlite",
        tmp_path / "public",
        reviewer="TEST Reviewer",
        title_redactions={"TEST synthetic report A": "TEST synthetic report"},
        registry_csv=None,
        migrations_dir=MIGRATIONS_DIR,
    )
    restored = get_connection(tmp_path / "restored.sqlite")
    try:
        titles = {r[0] for r in restored.execute("SELECT title FROM source_documents")}
    finally:
        restored.close()
    assert "TEST synthetic report" in titles and "TEST synthetic report A" not in titles


def test_ledger_carries_a_reviewed_ai_assisted_claim(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    fixture = make_publishable_incident(conn, "A")
    conn.execute(
        "INSERT INTO claims (incident_id, source_document_id, claim_subject_type, field_name, "
        "raw_value, normalized_value, extraction_method, assertion_status, review_status) "
        "VALUES (?, ?, 'incident', 'injuries_current', '2', '2', 'ai_assisted', 'reported', "
        "'needs_review')",
        (fixture["incident"], fixture["doc"]),
    )
    conn.execute(
        "UPDATE claims SET review_status = 'reviewed' WHERE field_name = 'injuries_current'"
    )
    conn.commit()
    ledger.dump(conn, tmp_path / "ledger")
    ledger.load(tmp_path / "ledger", tmp_path / "rebuilt.sqlite", MIGRATIONS_DIR)
    rebuilt = get_connection(tmp_path / "rebuilt.sqlite")
    try:
        assert ledger.differences(rebuilt, tmp_path / "ledger") == []
        # The rule itself still holds in the rebuilt database.
        with pytest.raises(sqlite3.DatabaseError, match="needs_review"):
            rebuilt.execute(
                "INSERT INTO claims (source_document_id, claim_subject_type, field_name, "
                "extraction_method, review_status) VALUES (1, 'incident', 'x', 'ai_assisted', "
                "'reviewed')"
            )
    finally:
        rebuilt.close()
