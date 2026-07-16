"""Controlled-vocabulary loader.

Role in the evidence flow: the versioned CSVs in ``data/vocabularies/`` are
the source of truth for every coded value. Validators and importers look
codes up here; application code never hard-codes vocabulary values outside
tests (stable *workflow* enums are the exception — they live as SQL CHECK
constraints, see docs/data_dictionary.md).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import cache
from pathlib import Path

DEFAULT_VOCAB_DIR = Path("data/vocabularies")

ENTRY_COLUMNS = (
    "code",
    "label_tr",
    "label_en",
    "definition",
    "examples",
    "version_added",
    "deprecated_in_version",
    "notes",
)

#: vocabulary name -> CSV filename. All follow ENTRY_COLUMNS;
#: vocabulary_versions.csv is a registry with its own shape (see load_versions).
VOCABULARY_FILES: dict[str, str] = {
    "hazards": "hazards.csv",
    "event_mechanisms": "event_mechanisms.csv",
    "modes_of_harm": "modes_of_harm.csv",
    "contributing_conditions": "contributing_conditions.csv",
    "organization_roles": "organization_roles.csv",
    "organization_types": "organization_types.csv",
    "source_types": "source_types.csv",
    "assertion_statuses": "assertion_statuses.csv",
    "review_statuses": "review_statuses.csv",
    "date_precisions": "date_precisions.csv",
    "coordinate_precisions": "coordinate_precisions.csv",
    "turkey_admin_areas": "turkey_admin_areas.csv",
    "nace_versions": "nace_versions.csv",
    "facility_types": "facility_types.csv",
    "commodities": "commodities.csv",
}

#: classification_system value -> vocabulary backing its codes.
PROJECT_CLASSIFICATION_VOCABULARIES: dict[str, str] = {
    "project_hazard": "hazards",
    "project_event_mechanism": "event_mechanisms",
    "project_mode_of_harm": "modes_of_harm",
    "project_contributing_condition": "contributing_conditions",
}


class VocabularyError(ValueError):
    """Raised when a vocabulary CSV is malformed."""


@dataclass(frozen=True)
class VocabularyEntry:
    code: str
    label_tr: str
    label_en: str
    definition: str
    examples: str
    version_added: str
    deprecated_in_version: str
    notes: str

    @property
    def is_deprecated(self) -> bool:
        return bool(self.deprecated_in_version.strip())


def _vocab_path(name: str, vocab_dir: str | Path | None) -> Path:
    if name not in VOCABULARY_FILES:
        raise VocabularyError(f"Unknown vocabulary: {name!r}")
    return Path(vocab_dir or DEFAULT_VOCAB_DIR) / VOCABULARY_FILES[name]


@cache
def _load_cached(path_str: str, name: str) -> tuple[VocabularyEntry, ...]:
    path = Path(path_str)
    if not path.exists():
        raise VocabularyError(f"Vocabulary file missing: {path}")
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = set(ENTRY_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise VocabularyError(f"{path.name}: missing columns {sorted(missing)}")
        entries: list[VocabularyEntry] = []
        seen: set[str] = set()
        for line_no, row in enumerate(reader, start=2):
            code = (row["code"] or "").strip()
            label_tr = (row["label_tr"] or "").strip()
            if not code:
                raise VocabularyError(f"{path.name}:{line_no}: empty code")
            if not label_tr:
                raise VocabularyError(f"{path.name}:{line_no}: code {code!r} lacks label_tr")
            if code in seen:
                raise VocabularyError(f"{path.name}:{line_no}: duplicate code {code!r}")
            seen.add(code)
            entries.append(
                VocabularyEntry(**{col: (row[col] or "").strip() for col in ENTRY_COLUMNS})
            )
    if not entries:
        raise VocabularyError(f"{path.name}: vocabulary is empty")
    return tuple(entries)


def load_vocabulary(name: str, vocab_dir: str | Path | None = None) -> tuple[VocabularyEntry, ...]:
    """Load and validate one vocabulary (unique codes, required labels)."""
    return _load_cached(str(_vocab_path(name, vocab_dir).resolve()), name)


def codes(
    name: str,
    vocab_dir: str | Path | None = None,
    include_deprecated: bool = False,
) -> frozenset[str]:
    """Set of valid codes for a vocabulary."""
    entries = load_vocabulary(name, vocab_dir)
    return frozenset(e.code for e in entries if include_deprecated or not e.is_deprecated)


def load_versions(vocab_dir: str | Path | None = None) -> list[dict[str, str]]:
    """Load the vocabulary version registry (file, version, date, change summary)."""
    path = Path(vocab_dir or DEFAULT_VOCAB_DIR) / "vocabulary_versions.csv"
    if not path.exists():
        raise VocabularyError(f"Vocabulary version registry missing: {path}")
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    required = {"file", "version", "date", "change_summary"}
    if rows and required - set(rows[0]):
        raise VocabularyError(f"vocabulary_versions.csv: missing columns {sorted(required)}")
    return rows


def validate_all(vocab_dir: str | Path | None = None) -> dict[str, int]:
    """Load every vocabulary; return name -> entry count. Raises on any defect."""
    counts = {name: len(load_vocabulary(name, vocab_dir)) for name in VOCABULARY_FILES}
    load_versions(vocab_dir)
    return counts
