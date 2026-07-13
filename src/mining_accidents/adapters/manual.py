"""Manual-entry importer: CSV/YAML files -> source documents and claims.

Role in the evidence flow: the only implemented ingestion path in the
foundation build. Humans prepare document/claim files (data/staging/), this
module validates every row (Pandera at the file boundary, Pydantic per row),
inserts append-only evidence, and records the run in ``ingestion_runs``.

Rules enforced here:
  * evidence excerpts respect the word cap — overlong rows abort the import
    (rejected, never truncated);
  * AI/OCR-assisted claims are forced to ``needs_review`` (model + DB trigger);
  * a document with the same (url, content_hash) already stored is skipped,
    never duplicated; a same-url different-hash document becomes a NEW row;
  * the import is atomic: any invalid row aborts the whole file.
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pandera.errors
import yaml

from mining_accidents import validators
from mining_accidents.database import utc_now_iso
from mining_accidents.models import Claim, IngestionRun, SourceDocument
from mining_accidents.provenance import record_ingestion_run

ADAPTER_NAME = "manual"
ADAPTER_VERSION = "1.0.0"


class ManualImportError(ValueError):
    """Raised when an import file is invalid; nothing is inserted."""


@dataclass(frozen=True)
class ImportResult:
    run_id: int
    documents_created: int
    claims_created: int
    records_skipped: int


def _read_rows(path: Path) -> list[dict[str, str]]:
    """Read CSV or YAML into a list of string dicts ('' -> None later)."""
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    if path.suffix.lower() in (".yml", ".yaml"):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            raise ManualImportError(f"{path.name}: YAML import files must be a list of mappings")
        return [{str(k): v for k, v in row.items()} for row in loaded]
    raise ManualImportError(f"{path.name}: unsupported format (use .csv, .yml, or .yaml)")


def _clean(row: dict[str, object]) -> dict[str, object]:
    """Empty strings become None so optional model fields validate."""
    return {k: (None if v == "" else v) for k, v in row.items()}


def _validate_boundary(path: Path, rows: list[dict[str, object]], schema) -> None:
    """Pandera check at the file boundary (CSV only; YAML rows are per-row typed)."""
    if path.suffix.lower() != ".csv" or not rows:
        return
    frame = pd.DataFrame(rows).replace("", None)
    try:
        schema.validate(frame, lazy=True)
    except pandera.errors.SchemaErrors as exc:
        raise ManualImportError(f"{path.name}: schema violations:\n{exc.failure_cases}") from exc


def _parse_documents(path: Path) -> list[SourceDocument]:
    rows = _read_rows(path)
    _validate_boundary(path, rows, validators.source_documents_file_schema)
    docs: list[SourceDocument] = []
    for line_no, row in enumerate(rows, start=2):
        try:
            docs.append(SourceDocument(**_clean(row)))
        except Exception as exc:
            raise ManualImportError(f"{path.name} row {line_no}: {exc}") from exc
    return docs


def _parse_claims(path: Path, excerpt_max_words: int) -> list[tuple[str | None, Claim]]:
    """Return (source_document_hash, Claim) pairs, fully validated."""
    rows = _read_rows(path)
    _validate_boundary(path, rows, validators.claims_file_schema)
    claims: list[tuple[str | None, Claim]] = []
    for line_no, row in enumerate(rows, start=2):
        cleaned = _clean(row)
        doc_hash = cleaned.pop("source_document_hash", None)
        doc_id = cleaned.pop("source_document_id", None)
        if doc_hash is None and doc_id is None:
            raise ManualImportError(
                f"{path.name} row {line_no}: needs source_document_hash or source_document_id"
            )
        try:
            validators.validate_excerpt_word_cap(
                cleaned.get("short_evidence_excerpt"), excerpt_max_words
            )
            claim = Claim(source_document_id=int(doc_id) if doc_id is not None else 0, **cleaned)
        except Exception as exc:
            raise ManualImportError(f"{path.name} row {line_no}: {exc}") from exc
        claims.append((str(doc_hash) if doc_hash is not None else None, claim))
    return claims


def _find_document_id(conn: sqlite3.Connection, content_hash: str) -> int | None:
    row = conn.execute(
        "SELECT source_document_id FROM source_documents WHERE content_hash = ? "
        "ORDER BY source_document_id DESC LIMIT 1",
        (content_hash,),
    ).fetchone()
    return int(row[0]) if row else None


def _insert_document(conn: sqlite3.Connection, doc: SourceDocument) -> int:
    data = doc.model_dump(exclude={"source_document_id"})
    data["attribution_required"] = (
        None if data["attribution_required"] is None else int(data["attribution_required"])
    )
    cols = ", ".join(data)
    placeholders = ", ".join("?" for _ in data)
    cur = conn.execute(
        f"INSERT INTO source_documents ({cols}) VALUES ({placeholders})",
        tuple(data.values()),
    )
    return int(cur.lastrowid)


def _insert_claim(conn: sqlite3.Connection, claim: Claim) -> int:
    data = claim.model_dump(exclude={"claim_id"})
    cols = ", ".join(data)
    placeholders = ", ".join("?" for _ in data)
    cur = conn.execute(f"INSERT INTO claims ({cols}) VALUES ({placeholders})", tuple(data.values()))
    return int(cur.lastrowid)


def import_files(
    conn: sqlite3.Connection,
    documents_path: str | Path | None = None,
    claims_path: str | Path | None = None,
    actor: str = "manual-import",
    excerpt_max_words: int = validators.DEFAULT_EXCERPT_MAX_WORDS,
) -> ImportResult:
    """Validate and import document/claim files; record the ingestion run.

    Validation happens before any insert; a defective row aborts the entire
    import so a file is either fully ingested or not at all.
    """
    started_at = utc_now_iso()
    documents = _parse_documents(Path(documents_path)) if documents_path else []
    claim_pairs = _parse_claims(Path(claims_path), excerpt_max_words) if claims_path else []

    documents_created = 0
    claims_created = 0
    skipped = 0
    try:
        for doc in documents:
            if doc.content_hash and (existing := _find_document_id(conn, doc.content_hash)):
                existing_url = conn.execute(
                    "SELECT url FROM source_documents WHERE source_document_id = ?",
                    (existing,),
                ).fetchone()[0]
                if existing_url == doc.url:
                    skipped += 1  # identical retrieval already stored
                    continue
            _insert_document(conn, doc)
            documents_created += 1

        for doc_hash, claim in claim_pairs:
            if doc_hash is not None:
                doc_id = _find_document_id(conn, doc_hash)
                if doc_id is None:
                    raise ManualImportError(
                        f"claim references unknown source document hash {doc_hash[:12]}…"
                    )
                claim = claim.model_copy(update={"source_document_id": doc_id})
            _insert_claim(conn, claim)
            claims_created += 1
    except Exception:
        conn.rollback()
        raise
    conn.commit()

    input_reference = ", ".join(str(p) for p in (documents_path, claims_path) if p is not None)
    run_id = record_ingestion_run(
        conn,
        IngestionRun(
            run_type="manual_import",
            adapter_name=ADAPTER_NAME,
            adapter_version=ADAPTER_VERSION,
            started_at=started_at,
            input_reference=input_reference,
            records_created=documents_created + claims_created,
            records_skipped=skipped,
            status="completed",
            notes=f"actor={actor}",
        ),
    )
    return ImportResult(
        run_id=run_id,
        documents_created=documents_created,
        claims_created=claims_created,
        records_skipped=skipped,
    )
