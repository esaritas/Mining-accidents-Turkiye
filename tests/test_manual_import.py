"""Round-trip test of the manual importer (Phase 2 checkpoint).

Synthetic source documents + three conflicting TEST- claims import, appear in
the database with correct statuses, and the run is recorded.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from conftest import REPO_ROOT
from mining_accidents.adapters import manual
from mining_accidents.adapters.base import STUB_MESSAGE
from mining_accidents.adapters.isig import ISIGAdapter
from mining_accidents.adapters.sgk import SGKAdapter
from mining_accidents.adapters.tbmm import TBMMAdapter
from mining_accidents.adapters.tmmob import TMMOBAdapter

EXAMPLE_DIR = REPO_ROOT / "data" / "staging" / "example_manual_import"


def _import_examples(conn: sqlite3.Connection) -> manual.ImportResult:
    return manual.import_files(
        conn,
        documents_path=EXAMPLE_DIR / "source_documents.csv",
        claims_path=EXAMPLE_DIR / "claims.csv",
        actor="TEST-importer",
    )


def test_round_trip_import(conn: sqlite3.Connection) -> None:
    result = _import_examples(conn)
    assert result.documents_created == 2
    assert result.claims_created == 4
    assert result.records_skipped == 0

    docs = conn.execute("SELECT * FROM source_documents ORDER BY source_document_id").fetchall()
    assert len(docs) == 2
    assert all(d["content_hash"] and d["retrieved_at"] for d in docs)

    # Three conflicting fatality claims coexist — nothing resolved them.
    fatality_claims = conn.execute(
        "SELECT normalized_value, review_status, assertion_status FROM claims "
        "WHERE field_name = 'fatalities_current' ORDER BY claim_id"
    ).fetchall()
    assert [c["normalized_value"] for c in fatality_claims] == ["2", "3", "4"]
    assert all(c["review_status"] == "pending" for c in fatality_claims)
    assert fatality_claims[2]["assertion_status"] == "disputed"

    # The AI-assisted claim entered the mandatory review queue.
    ai_claim = conn.execute(
        "SELECT review_status FROM claims WHERE extraction_method = 'ai_assisted'"
    ).fetchone()
    assert ai_claim["review_status"] == "needs_review"

    run = conn.execute("SELECT * FROM ingestion_runs WHERE run_id = ?", (result.run_id,)).fetchone()
    assert run["run_type"] == "manual_import"
    assert run["records_created"] == 6
    assert run["status"] == "completed"
    assert run["adapter_name"] == "manual"


def test_reimport_skips_identical_documents(conn: sqlite3.Connection) -> None:
    _import_examples(conn)
    result = manual.import_files(
        conn, documents_path=EXAMPLE_DIR / "source_documents.csv", actor="TEST-importer"
    )
    assert result.documents_created == 0
    assert result.records_skipped == 2
    assert conn.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0] == 2


def test_same_url_different_hash_is_new_row(conn: sqlite3.Connection, tmp_path: Path) -> None:
    _import_examples(conn)
    redoc = tmp_path / "redoc.csv"
    redoc.write_text(
        "source_organization,title,url,retrieved_at,content_hash\n"
        "TEST Kaynak Kurumu,TEST synthetic report re-retrieved,"
        "file:///dev/null/TEST-DOC-A,2099-02-01T00:00:00Z," + "f" * 64 + "\n",
        encoding="utf-8",
    )
    result = manual.import_files(conn, documents_path=redoc, actor="TEST-importer")
    assert result.documents_created == 1  # changed content -> NEW row, never mutation
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM source_documents WHERE url = 'file:///dev/null/TEST-DOC-A'"
        ).fetchone()[0]
        == 2
    )


def test_overlong_excerpt_aborts_import(conn: sqlite3.Connection, tmp_path: Path) -> None:
    _import_examples(conn)
    bad = tmp_path / "bad_claims.csv"
    excerpt = " ".join(["kelime"] * 41)
    bad.write_text(
        "source_document_hash,claim_subject_type,field_name,raw_value,extraction_method,"
        "short_evidence_excerpt\n"
        f"{'4' * 0}49036086ece675075c16f2127a6412c8cf7e3d2722efce055809d04cd6eb83c3,"
        f"incident,fatalities_current,5,manual,{excerpt}\n",
        encoding="utf-8",
    )
    before = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    with pytest.raises(manual.ManualImportError, match="cap is 40"):
        manual.import_files(conn, claims_path=bad, actor="TEST-importer")
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == before


def test_claim_referencing_unknown_document_aborts(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    orphan = tmp_path / "orphan_claims.csv"
    orphan.write_text(
        "source_document_hash,claim_subject_type,field_name,raw_value,extraction_method\n"
        + "a" * 64
        + ",incident,fatalities_current,5,manual\n",
        encoding="utf-8",
    )
    with pytest.raises(manual.ManualImportError, match="unknown source document"):
        manual.import_files(conn, claims_path=orphan, actor="TEST-importer")
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0


def test_yaml_import(conn: sqlite3.Connection, tmp_path: Path) -> None:
    docs_yaml = tmp_path / "docs.yml"
    docs_yaml.write_text(
        "- source_organization: TEST Kurum\n"
        "  title: TEST YAML document\n"
        "  url: file:///dev/null/TEST-YAML\n"
        "  retrieved_at: '2099-01-02T00:00:00Z'\n"
        f"  content_hash: {'b' * 64}\n",
        encoding="utf-8",
    )
    result = manual.import_files(conn, documents_path=docs_yaml, actor="TEST-importer")
    assert result.documents_created == 1


def test_network_adapters_are_stubs() -> None:
    for adapter_cls in (SGKAdapter, TMMOBAdapter, TBMMAdapter, ISIGAdapter):
        adapter = adapter_cls()
        for method in (adapter.assess, adapter.fetch):
            with pytest.raises(NotImplementedError, match="source assessment"):
                method()
        with pytest.raises(NotImplementedError, match=STUB_MESSAGE[:30]):
            adapter.parse(1)
