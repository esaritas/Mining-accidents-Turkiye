"""Field validators and Pandera schemas for CSV/dataframe boundaries.

Role in the evidence flow: everything crossing a file boundary (manual import
CSVs, vocabulary CSVs, export frames) is validated here before it can become
evidence, and vocabulary-driven codes are checked against the versioned CSVs
that are their source of truth.
"""

from __future__ import annotations

from pathlib import Path

import pandera.pandas as pa
from dateutil import parser as date_parser

from mining_accidents import vocabularies

DEFAULT_EXCERPT_MAX_WORDS = 40


class ValidationError(ValueError):
    """Raised when a value fails project validation rules."""


def validate_excerpt_word_cap(
    excerpt: str | None, max_words: int = DEFAULT_EXCERPT_MAX_WORDS
) -> str | None:
    """Enforce the copyright excerpt cap (editorial_and_legal_protocol.md §4).

    Overlong excerpts are rejected, never silently truncated — truncation
    would alter evidence.
    """
    if excerpt is None:
        return None
    words = excerpt.split()
    if len(words) > max_words:
        raise ValidationError(
            f"Evidence excerpt has {len(words)} words; the cap is {max_words}. "
            "Store metadata + reference instead of a longer quotation."
        )
    return excerpt


def validate_province_code(code: str | None, vocab_dir: str | Path | None = None) -> str | None:
    """Province codes must exist in turkey_admin_areas.csv (01-81)."""
    if code is None:
        return None
    if code not in vocabularies.codes("turkey_admin_areas", vocab_dir):
        raise ValidationError(f"Unknown province code: {code!r}")
    return code


def validate_classification_code(
    classification_system: str,
    classification_code: str,
    vocab_dir: str | Path | None = None,
) -> str:
    """project_* classification codes must exist in their backing vocabulary.

    External systems (ESAW, ICSE, NACE) are not validated here: their code
    lists are not project vocabularies and are never invented by the project.
    """
    vocab_name = vocabularies.PROJECT_CLASSIFICATION_VOCABULARIES.get(classification_system)
    if vocab_name is None:
        return classification_code
    if classification_code not in vocabularies.codes(vocab_name, vocab_dir):
        raise ValidationError(
            f"Code {classification_code!r} is not in vocabulary {vocab_name!r} "
            f"(system {classification_system!r})"
        )
    return classification_code


def validate_iso_datetime(value: str | None, field_name: str = "datetime") -> str | None:
    """Parseability check for ISO 8601 text timestamps."""
    if value is None:
        return None
    try:
        date_parser.isoparse(value)
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"{field_name}: not ISO 8601: {value!r}") from exc
    return value


# ---------------------------------------------------------------------------
# Pandera schemas — file boundaries
# ---------------------------------------------------------------------------

_optional_str = pa.Column(str, nullable=True, required=False, coerce=True)

#: Manual-import CSV of source documents (adapters/manual.py).
source_documents_file_schema = pa.DataFrameSchema(
    {
        "source_organization": pa.Column(str, pa.Check.str_length(min_value=1), coerce=True),
        "title": pa.Column(str, pa.Check.str_length(min_value=1), coerce=True),
        "document_type": _optional_str,
        "url": _optional_str,
        "publication_date": _optional_str,
        "retrieved_at": _optional_str,
        "language": _optional_str,
        "author": _optional_str,
        "content_hash": pa.Column(
            str,
            pa.Check.str_matches(r"^[0-9a-f]{64}$"),
            nullable=True,
            required=False,
            coerce=True,
        ),
        "local_raw_path": _optional_str,
        "archived_reference": _optional_str,
        "licence_or_reuse_notes": _optional_str,
        "source_tier": pa.Column(
            "Int64", pa.Check.in_range(1, 3), nullable=True, required=False, coerce=True
        ),
        "access_status": _optional_str,
        "notes": _optional_str,
    },
    strict=False,
    coerce=True,
)

#: Manual-import CSV of claims (adapters/manual.py).
claims_file_schema = pa.DataFrameSchema(
    {
        "source_document_hash": pa.Column(
            str, pa.Check.str_matches(r"^[0-9a-f]{64}$"), nullable=True, coerce=True
        ),
        "incident_id": pa.Column("Int64", nullable=True, required=False, coerce=True),
        "claim_subject_type": pa.Column(
            str,
            pa.Check.isin(
                [
                    "incident",
                    "facility",
                    "organization",
                    "casualty",
                    "classification",
                    "recommendation",
                ]
            ),
            coerce=True,
        ),
        "field_name": pa.Column(str, pa.Check.str_length(min_value=1), coerce=True),
        "raw_value": _optional_str,
        "normalized_value": _optional_str,
        "unit": _optional_str,
        "page_number": _optional_str,
        "section_reference": _optional_str,
        "short_evidence_excerpt": _optional_str,
        "extraction_method": pa.Column(
            str,
            pa.Check.isin(
                [
                    "manual",
                    "html_parser",
                    "pdf_text",
                    "pdf_table",
                    "api",
                    "structured_file",
                    "ai_assisted",
                    "ocr_assisted",
                    "other",
                ]
            ),
            coerce=True,
        ),
        "extractor_version": _optional_str,
        "assertion_status": _optional_str,
        "confidence_score": pa.Column(
            float, pa.Check.in_range(0.0, 1.0), nullable=True, required=False, coerce=True
        ),
        "review_status": _optional_str,
    },
    strict=False,
    coerce=True,
)
