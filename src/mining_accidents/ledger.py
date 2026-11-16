"""Text ledger of the working database.

Role in the evidence flow: durability. The working database holds everything
the public export leaves out (unselected claims, decisions with their
rationales, the review log, casualty observation history) and it is excluded
from git. On 2026-11-11 the only copy was lost with the container that held it
(docs/qc_audit_2026_11_11.md section 2). The ledger is the answer: every table
is written as one JSON-lines file, in primary-key order, with no timestamp of
its own, so the dump is a pure function of the database content and two dumps
of the same database are byte-identical. The files are committed beside the
export, and the database is rebuilt from them with :func:`load`.

The ledger records, it never decides: loading inserts the rows exactly as they
were dumped, primary keys included, and runs no review logic.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from mining_accidents.database import create_database, get_connection

DEFAULT_LEDGER_DIR = Path("data/ledger")
MANIFEST_NAME = "ledger_manifest.json"

#: Tables that describe the schema itself and are rebuilt by the migrations.
_SKIPPED_TABLES = frozenset({"schema_migrations"})


class LedgerError(RuntimeError):
    """Raised when a ledger and a database disagree."""


def table_names(conn: sqlite3.Connection) -> list[str]:
    """Every data table, in name order."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows if row[0] not in _SKIPPED_TABLES]


def _table_lines(conn: sqlite3.Connection, table: str) -> list[str]:
    cursor = conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')  # noqa: S608
    columns = [d[0] for d in cursor.description]
    return [
        json.dumps(dict(zip(columns, row, strict=True)), ensure_ascii=False, sort_keys=True)
        for row in cursor
    ]


def _schema_version(conn: sqlite3.Connection) -> str:
    return str(conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0])


def dump(conn: sqlite3.Connection, ledger_dir: str | Path = DEFAULT_LEDGER_DIR) -> dict:
    """Write every non-empty table to ``<table>.jsonl`` and a manifest.

    Files for tables that have become empty are removed, so the directory
    always mirrors the database exactly.
    """
    ledger_dir = Path(ledger_dir)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    tables: dict[str, dict[str, object]] = {}
    for table in table_names(conn):
        lines = _table_lines(conn, table)
        path = ledger_dir / f"{table}.jsonl"
        if not lines:
            path.unlink(missing_ok=True)
            continue
        text = "\n".join(lines) + "\n"
        path.write_text(text, encoding="utf-8")
        tables[table] = {
            "rows": len(lines),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
    manifest = {"db_schema_version": _schema_version(conn), "tables": tables}
    (ledger_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def read_manifest(ledger_dir: str | Path = DEFAULT_LEDGER_DIR) -> dict:
    path = Path(ledger_dir) / MANIFEST_NAME
    if not path.exists():
        raise LedgerError(f"No ledger manifest at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _check_files(ledger_dir: Path, manifest: dict) -> None:
    for table, entry in manifest["tables"].items():
        path = ledger_dir / f"{table}.jsonl"
        if not path.exists():
            raise LedgerError(f"Ledger file missing: {path.name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise LedgerError(f"{path.name} does not match the hash in the ledger manifest")


def load(
    ledger_dir: str | Path = DEFAULT_LEDGER_DIR,
    db_path: str | Path = "database/mining_accidents.sqlite",
    migrations_dir: str | Path = "database/migrations",
) -> dict[str, int]:
    """Build a database at ``db_path`` from the ledger. Refuses to overwrite.

    The schema comes from the migrations, the rows from the ledger. Foreign
    keys are checked once everything is in, because rows are inserted table by
    table and a table may point at one loaded after it.
    """
    ledger_dir, db_path = Path(ledger_dir), Path(db_path)
    if db_path.exists() and db_path.stat().st_size > 0:
        raise LedgerError(f"{db_path} already exists; the ledger never overwrites a database")
    manifest = read_manifest(ledger_dir)
    _check_files(ledger_dir, manifest)
    create_database(db_path, migrations_dir, snapshot_path=None)
    conn = get_connection(db_path)
    try:
        version = _schema_version(conn)
        if version != manifest["db_schema_version"]:
            raise LedgerError(
                f"Ledger was written at schema {manifest['db_schema_version']}, "
                f"migrations give {version}"
            )
        conn.execute("PRAGMA foreign_keys = OFF")
        counts: dict[str, int] = {}
        known = set(table_names(conn))
        for table in sorted(manifest["tables"]):
            if table not in known:
                raise LedgerError(f"Ledger table {table!r} is not in the schema")
            rows = [
                json.loads(line)
                for line in (ledger_dir / f"{table}.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            for row in rows:
                columns = sorted(row)
                values = dict(row)
                # The schema lets an AI- or OCR-assisted claim into the table
                # only as needs_review (constraint 5). A claim reviewed since is
                # therefore loaded the way it came to be: inserted as
                # needs_review, then set to the status the ledger records.
                later_status = None
                if (
                    table == "claims"
                    and values.get("extraction_method") in ("ai_assisted", "ocr_assisted")
                    and values.get("review_status") != "needs_review"
                ):
                    later_status = values["review_status"]
                    values["review_status"] = "needs_review"
                conn.execute(
                    f'INSERT INTO "{table}" ({", ".join(columns)}) '  # noqa: S608
                    f"VALUES ({', '.join('?' for _ in columns)})",
                    [values[c] for c in columns],
                )
                if later_status is not None:
                    conn.execute(
                        "UPDATE claims SET review_status = ? WHERE claim_id = ?",
                        (later_status, values["claim_id"]),
                    )
            counts[table] = len(rows)
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise LedgerError(f"{len(broken)} broken foreign key(s) after loading the ledger")
        return counts
    finally:
        conn.close()


def differences(conn: sqlite3.Connection, ledger_dir: str | Path = DEFAULT_LEDGER_DIR) -> list[str]:
    """Tables whose ledger file differs from the database. Empty means in step."""
    ledger_dir = Path(ledger_dir)
    with tempfile.TemporaryDirectory() as scratch:
        fresh = dump(conn, scratch)
        try:
            committed = read_manifest(ledger_dir)
        except LedgerError:
            return ["(no ledger manifest)"]
        if fresh["db_schema_version"] != committed["db_schema_version"]:
            return ["(schema version)"]
        changed = []
        for table in sorted(set(fresh["tables"]) | set(committed["tables"])):
            if fresh["tables"].get(table) != committed["tables"].get(table):
                changed.append(table)
        return changed


def verify(
    ledger_dir: str | Path = DEFAULT_LEDGER_DIR,
    public_dir: str | Path = "data/public",
    migrations_dir: str | Path = "database/migrations",
    reference_time: str | None = None,
) -> list[str]:
    """Prove the committed ledger and the committed export are one register.

    Loads the ledger into a scratch database, dumps it again (the round trip
    must be byte-identical) and builds the public export from it (every data
    file must match the committed one). Returns the problems found.
    """
    import os
    from datetime import datetime

    from mining_accidents import export

    ledger_dir, public_dir = Path(ledger_dir), Path(public_dir)
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as scratch:
        scratch_db = Path(scratch) / "ledger.sqlite"
        load(ledger_dir, scratch_db, migrations_dir)
        conn = get_connection(scratch_db)
        try:
            problems += [f"ledger round trip differs: {t}" for t in differences(conn, ledger_dir)]
            manifest = json.loads((public_dir / "export_manifest.json").read_text("utf-8"))
            stamp = datetime.fromisoformat(manifest["export_timestamp"].replace("Z", "+00:00"))
            previous = os.environ.get("SOURCE_DATE_EPOCH")
            os.environ["SOURCE_DATE_EPOCH"] = str(int(stamp.timestamp()))
            try:
                rebuilt = export.build_public_export(
                    conn, Path(scratch) / "export", reference_time=reference_time
                )
            except export.ExportBlockedError as exc:
                return [*problems, f"export from the ledger is blocked: {exc}"]
            finally:
                if previous is None:
                    os.environ.pop("SOURCE_DATE_EPOCH", None)
                else:
                    os.environ["SOURCE_DATE_EPOCH"] = previous
            for name, digest in sorted(rebuilt["file_sha256"].items()):
                committed = public_dir / name
                if not committed.exists():
                    problems.append(f"{name}: in the ledger's export, missing from {public_dir}")
                elif hashlib.sha256(committed.read_bytes()).hexdigest() != digest:
                    problems.append(f"{name}: committed export differs from the ledger's")
        finally:
            conn.close()
    return problems
