"""Public correction notices: editorial context, never canonical claims/decisions.

The dated notices disclose evidence gaps while the working database and named
human reviewer are unavailable. They do not change incident values or totals.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
from pathlib import Path

DEFAULT_NOTES = Path("data/reference/evidence_notices.json")


def load_notes(path: Path = DEFAULT_NOTES) -> list[dict[str, object]]:
    if not path.exists():
        return []
    notes = json.loads(path.read_text(encoding="utf-8"))
    seen = set()
    for note in notes:
        if note["id"] in seen:
            raise ValueError(f"Duplicate evidence notice: {note['id']}")
        seen.add(note["id"])
        if note["status"] != "pending_human_review":
            raise ValueError("Correction notices cannot masquerade as reviewed decisions")
        for lang in ("en", "tr"):
            if not note.get(f"text_{lang}"):
                raise ValueError("Evidence notices require both languages")
        if not note.get("public_incident_id") or not note.get("checked_at"):
            raise ValueError("Evidence notice needs an incident and a check date")
        if not note.get("sources") or any(
            not str(source.get("url", "")).startswith("https://") for source in note["sources"]
        ):
            raise ValueError("Evidence notices need HTTPS source links")
    return notes


def stage_packet(conn: sqlite3.Connection, packet: Path):
    """Import candidate evidence only, resolving stable IDs in the real DB.

    All targets and review states are checked before writing. Repeating this
    operation does not duplicate identical candidate claims. No reviewer is
    impersonated and no publication/decision function is called.
    """
    from mining_accidents.adapters.manual import import_files

    with (packet / "claims.csv").open(encoding="utf-8", newline="") as fh:
        candidates = list(csv.DictReader(fh))
    rows = []
    for candidate in candidates:
        row = dict(candidate)
        public_id = row.pop("public_incident_id")
        target = conn.execute(
            "SELECT incident_id FROM incidents WHERE public_incident_id = ?", (public_id,)
        ).fetchone()
        if target is None:
            raise ValueError(f"Unknown incident {public_id}; no evidence was imported")
        if row["extraction_method"] != "ai_assisted" or row["review_status"] != "needs_review":
            raise ValueError("The staging packet must remain AI-assisted and unreviewed")
        row["incident_id"] = target[0]
        existing = conn.execute(
            "SELECT 1 FROM claims c JOIN source_documents s USING (source_document_id) "
            "WHERE c.incident_id = ? AND s.content_hash = ? AND c.field_name = ? "
            "AND c.normalized_value = ?",
            (target[0], row["source_document_hash"], row["field_name"], row["normalized_value"]),
        ).fetchone()
        if existing is None:
            rows.append(row)
    with tempfile.TemporaryDirectory(prefix="mining-evidence-") as directory:
        claims = Path(directory) / "claims.csv"
        if rows:
            with claims.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        return import_files(
            conn,
            documents_path=packet / "source_documents.csv",
            claims_path=claims if rows else None,
            actor="ai-assisted-evidence-staging",
        )
