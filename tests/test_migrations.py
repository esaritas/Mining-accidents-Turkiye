"""Migration runner behaviour and schema-snapshot fidelity."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from conftest import MIGRATIONS_DIR, REPO_ROOT
from mining_accidents import database


def _fresh_db(tmp_path: Path, name: str = "m.sqlite") -> sqlite3.Connection:
    conn = database.get_connection(tmp_path / name)
    database.apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def test_migrations_apply_and_are_recorded(tmp_path: Path) -> None:
    conn = database.get_connection(tmp_path / "a.sqlite")
    applied = database.apply_migrations(conn, MIGRATIONS_DIR)
    assert applied, "expected at least one migration to apply"
    rows = conn.execute(
        "SELECT version, checksum, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert [r["version"] for r in rows] == applied
    assert all(len(r["checksum"]) == 64 for r in rows)
    conn.close()


def test_reapply_is_idempotent(tmp_path: Path) -> None:
    conn = _fresh_db(tmp_path)
    assert database.apply_migrations(conn, MIGRATIONS_DIR) == []
    conn.close()


def test_modified_migration_is_rejected(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    src = migrations / "001_test.sql"
    src.write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);\n")
    conn = database.get_connection(tmp_path / "b.sqlite")
    database.apply_migrations(conn, migrations)
    src.write_text("CREATE TABLE t2 (id INTEGER PRIMARY KEY);\n")
    with pytest.raises(database.MigrationError, match="checksum"):
        database.apply_migrations(conn, migrations)
    conn.close()


def test_snapshot_matches_migration_replay(tmp_path: Path) -> None:
    """database/schema.sql (committed snapshot) == schema from replaying migrations."""
    snapshot_file = REPO_ROOT / "database" / "schema.sql"
    assert snapshot_file.exists(), "run `make db` to generate database/schema.sql"
    conn = _fresh_db(tmp_path)
    replayed = database.dump_schema(conn)
    conn.close()
    assert snapshot_file.read_text(encoding="utf-8") == replayed


def test_wal_journal_mode(tmp_path: Path) -> None:
    conn = database.get_connection(tmp_path / "c.sqlite")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()
