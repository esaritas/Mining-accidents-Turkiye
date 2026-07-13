"""Vocabulary CSV validity and SQL-CHECK/vocabulary synchronization."""

from __future__ import annotations

import re
import sqlite3

import pytest

from conftest import REPO_ROOT, VOCAB_DIR
from mining_accidents import vocabularies


def test_all_vocabularies_load_and_validate() -> None:
    counts = vocabularies.validate_all(VOCAB_DIR)
    assert set(counts) == set(vocabularies.VOCABULARY_FILES)
    assert all(count > 0 for count in counts.values())


def test_admin_areas_has_81_provinces() -> None:
    entries = vocabularies.load_vocabulary("turkey_admin_areas", VOCAB_DIR)
    assert len(entries) == 81
    codes = [e.code for e in entries]
    assert codes == [f"{i:02d}" for i in range(1, 82)]
    by_code = {e.code: e.label_tr for e in entries}
    # Spot-check Turkish characters preserved exactly.
    assert by_code["34"] == "İstanbul"
    assert by_code["21"] == "Diyarbakır"
    assert by_code["67"] == "Zonguldak"


def test_four_axis_vocabularies_match_spec_codes() -> None:
    assert "methane" in vocabularies.codes("hazards", VOCAB_DIR)
    assert "tailings_dam_failure" in vocabularies.codes("event_mechanisms", VOCAB_DIR)
    assert "poisoning_or_asphyxiation" in vocabularies.codes("modes_of_harm", VOCAB_DIR)
    conditions = vocabularies.codes("contributing_conditions", VOCAB_DIR)
    assert "informal_or_illegal_operation" in conditions
    assert "ppe_or_self_rescuer" in conditions


def test_unknown_vocabulary_rejected() -> None:
    with pytest.raises(vocabularies.VocabularyError):
        vocabularies.load_vocabulary("no_such_vocab", VOCAB_DIR)


def _check_values(table_sql: str, column: str) -> set[str]:
    """Extract the literal value list of `column ... CHECK (column IN (...))`."""
    pattern = re.compile(rf"{column}\s+IN\s*\(([^)]*)\)", re.IGNORECASE | re.DOTALL)
    match = pattern.search(table_sql)
    assert match, f"no CHECK IN list found for column {column}"
    return set(re.findall(r"'([^']*)'", match.group(1)))


@pytest.fixture()
def schema_sql(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        row["name"]: row["sql"]
        for row in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
    }


def test_sql_checks_stay_in_sync_with_vocabularies(schema_sql: dict[str, str]) -> None:
    """The SQL CHECK lists mirroring vocabulary CSVs must match them exactly.

    This is the sync test promised in docs/data_dictionary.md: workflow enums
    live in SQL, vocabulary-driven codes in CSVs — where both exist they agree.
    """
    assert _check_values(schema_sql["claims"], "assertion_status") == vocabularies.codes(
        "assertion_statuses", VOCAB_DIR
    )
    assert _check_values(schema_sql["claims"], "review_status") == vocabularies.codes(
        "review_statuses", VOCAB_DIR
    )
    assert _check_values(schema_sql["incidents"], "date_precision") == vocabularies.codes(
        "date_precisions", VOCAB_DIR
    )
    assert _check_values(schema_sql["incidents"], "coordinate_precision") == vocabularies.codes(
        "coordinate_precisions", VOCAB_DIR
    )
    assert _check_values(schema_sql["incident_organization_roles"], "role") == vocabularies.codes(
        "organization_roles", VOCAB_DIR
    )
    assert _check_values(schema_sql["organizations"], "organization_type") == vocabularies.codes(
        "organization_types", VOCAB_DIR
    )


def test_version_registry_covers_every_vocabulary_file() -> None:
    versions = {row["file"] for row in vocabularies.load_versions(VOCAB_DIR)}
    expected = set(vocabularies.VOCABULARY_FILES.values())
    assert expected <= versions


def test_no_real_data_in_vocab_dir() -> None:
    """The vocabularies directory holds reference data only — no incident files."""
    allowed_suffixes = {".csv", ".md"}
    for path in (REPO_ROOT / "data" / "vocabularies").iterdir():
        if path.name == ".gitkeep":
            continue
        assert path.suffix in allowed_suffixes
