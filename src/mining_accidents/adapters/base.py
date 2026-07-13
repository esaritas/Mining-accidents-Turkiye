"""Abstract source-adapter contract.

Role in the evidence flow: adapters are the only components that ever touch
external sources; they produce immutable source documents and claim drafts,
never canonical values.

Adapter conduct rules (binding on every implementation; see also
docs/source_assessment_protocol.md §5):

1. Complete and record the source assessment BEFORE writing any fetch code;
   check permissions and robots directives first.
2. Identify honestly: descriptive user agent naming the project and contact.
3. Be conservative: low request rates, retries with backoff, response caching.
4. Store raw responses immutably with sha256 ``content_hash`` and
   ``retrieved_at``; a changed document is a NEW source_documents row.
5. Never bypass access controls, paywalls, or technical protection measures.
6. Never assume PDFs have text layers — route scanned or unreliable documents
   to the manual-review queue instead of trusting extraction.
7. Never fabricate missing values; absent data stays absent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from mining_accidents.models import (
    AssertionStatus,
    ClaimSubjectType,
    ExtractionMethod,
    ReviewStatus,
)

STUB_MESSAGE = (
    "Requires source assessment before implementation — see docs/source_assessment_protocol.md"
)


@dataclass(frozen=True)
class SourceAssessment:
    """Outcome of the pre-implementation assessment for one source."""

    source_key: str
    tier_proposed: int | None
    automated_collection_permitted: str  # yes | no | unclear
    access_notes: str
    coverage_notes: str = ""
    format_risks: str = ""


@dataclass
class ClaimDraft:
    """A not-yet-inserted claim produced by parsing a source document."""

    field_name: str
    raw_value: str | None = None
    normalized_value: str | None = None
    unit: str | None = None
    claim_subject_type: ClaimSubjectType = "incident"
    claim_subject_id: int | None = None
    incident_id: int | None = None
    page_number: str | None = None
    section_reference: str | None = None
    short_evidence_excerpt: str | None = None
    extraction_method: ExtractionMethod = "manual"
    extractor_version: str | None = None
    assertion_status: AssertionStatus = "unknown"
    confidence_score: float | None = None
    review_status: ReviewStatus = "pending"
    notes: dict[str, str] = field(default_factory=dict)


class SourceAdapter(ABC):
    """Contract every source adapter implements.

    Concrete network-facing adapters in the foundation build are stubs that
    raise ``NotImplementedError(STUB_MESSAGE)`` — no fetching happens until
    the source assessment is recorded.
    """

    #: registry key in config/sources.yml and docs/source_registry.csv
    source_key: str = ""
    adapter_version: str = "0.0.0"

    @abstractmethod
    def assess(self) -> SourceAssessment:
        """Return the recorded source assessment (never performed implicitly)."""

    @abstractmethod
    def fetch(self) -> list[int]:
        """Retrieve documents; return created source_document_ids."""

    @abstractmethod
    def parse(self, source_document_id: int) -> list[ClaimDraft]:
        """Extract claim drafts from a stored document."""
