"""Database connection factory, migration runner, and schema snapshot.

Role in the evidence flow: provides the storage substrate every layer writes
to. Every connection enforces foreign keys and WAL journaling; migrations are
plain numbered SQL files applied in order and tracked with checksums in
``schema_migrations``, so the schema itself is reproducible evidence.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_DB_PATH = Path("database/mining_accidents.sqlite")
DEFAULT_MIGRATIONS_DIR = Path("database/migrations")
DEFAULT_SCHEMA_SNAPSHOT = Path("database/schema.sql")

SNAPSHOT_HEADER = (
    "-- database/schema.sql — GENERATED snapshot of the current schema.\n"
    "-- Do not edit by hand: regenerate by applying migrations (make db).\n"
    "-- Canonical history lives in database/migrations/.\n"
)


class MigrationError(RuntimeError):
    """Raised when the migration history on disk and in the DB disagree."""


def utc_now_iso() -> str:
    """UTC timestamp in the project's ISO 8601 audit format."""
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection with the engine settings required by the spec."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            checksum TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _migration_files(migrations_dir: Path) -> list[Path]:
    return sorted(p for p in migrations_dir.glob("*.sql") if p.stem[:1].isdigit())


def apply_migrations(
    conn: sqlite3.Connection,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
) -> list[str]:
    """Apply pending migrations in filename order; return applied versions.

    A migration already recorded in ``schema_migrations`` is verified against
    its checksum and skipped; a checksum mismatch aborts (history was edited,
    which the immutability posture forbids).
    """
    migrations_dir = Path(migrations_dir)
    _ensure_migrations_table(conn)
    recorded = {
        row["version"]: row["checksum"]
        for row in conn.execute("SELECT version, checksum FROM schema_migrations")
    }
    applied: list[str] = []
    for path in _migration_files(migrations_dir):
        version, _, description = path.stem.partition("_")
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if version in recorded:
            if recorded[version] != checksum:
                raise MigrationError(
                    f"Migration {path.name} was modified after being applied "
                    f"(checksum mismatch). Migrations are immutable; add a new one."
                )
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations (version, description, applied_at, checksum) "
            "VALUES (?, ?, ?, ?)",
            (version, description or path.stem, utc_now_iso(), checksum),
        )
        conn.commit()
        applied.append(version)
    return applied


def dump_schema(conn: sqlite3.Connection) -> str:
    """Deterministic SQL text of the live schema (for the snapshot file)."""
    rows = conn.execute(
        """
        SELECT type, name, sql FROM sqlite_master
        WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
        ORDER BY CASE type
            WHEN 'table' THEN 0 WHEN 'index' THEN 1 WHEN 'trigger' THEN 2 ELSE 3
        END, name
        """
    ).fetchall()
    statements = [row["sql"].strip() + ";" for row in rows]
    return SNAPSHOT_HEADER + "\n" + "\n\n".join(statements) + "\n"


def write_schema_snapshot(
    conn: sqlite3.Connection,
    snapshot_path: str | Path = DEFAULT_SCHEMA_SNAPSHOT,
) -> Path:
    snapshot_path = Path(snapshot_path)
    snapshot_path.write_text(dump_schema(conn), encoding="utf-8")
    return snapshot_path


def create_database(
    db_path: str | Path = DEFAULT_DB_PATH,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
    snapshot_path: str | Path | None = DEFAULT_SCHEMA_SNAPSHOT,
) -> list[str]:
    """Create (or upgrade) the database and refresh the schema snapshot."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        applied = apply_migrations(conn, migrations_dir)
        if snapshot_path is not None:
            write_schema_snapshot(conn, snapshot_path)
    finally:
        conn.close()
    return applied
