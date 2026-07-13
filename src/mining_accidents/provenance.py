"""Provenance utilities: content hashing, git identity, ingestion-run records.

Role in the evidence flow: every document gets a sha256 content hash, and
every import/export operation is recorded permanently in ``ingestion_runs``
(append-only: one row, inserted at run completion, with final status —
see docs/open_questions.md implementation note C).
"""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
from pathlib import Path

from mining_accidents.database import utc_now_iso
from mining_accidents.models import IngestionRun


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_git_commit() -> str | None:
    """Current repo commit for run/export provenance; None outside a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and commit else None


def record_ingestion_run(conn: sqlite3.Connection, run: IngestionRun) -> int:
    """Insert a completed run record (append-only) and return its run_id."""
    if run.finished_at is None:
        run = run.model_copy(update={"finished_at": utc_now_iso()})
    if run.git_commit is None:
        run = run.model_copy(update={"git_commit": get_git_commit()})
    cur = conn.execute(
        """
        INSERT INTO ingestion_runs (
            run_type, adapter_name, adapter_version, started_at, finished_at,
            input_reference, records_created, records_skipped, status,
            log_path, git_commit, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run.run_type,
            run.adapter_name,
            run.adapter_version,
            run.started_at,
            run.finished_at,
            run.input_reference,
            run.records_created,
            run.records_skipped,
            run.status,
            run.log_path,
            run.git_commit,
            run.notes,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)
