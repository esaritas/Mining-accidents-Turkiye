"""Pydantic v2 models for every table.

Role in the evidence flow: importers and review logic validate rows through
these models before anything touches the database, so schema rules
(workflow enums, AI/OCR review posture, value bounds) hold at the
application boundary as well as in SQL. Vocabulary-driven codes (hazards,
admin areas, ...) are validated separately in ``validators.py`` against the
CSVs — see docs/data_dictionary.md.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReviewStatus = Literal["pending", "needs_review", "reviewed"]
AssertionStatus = Literal[
    "reported",
    "alleged",
    "preliminary_finding",
    "technical_finding",
    "official_finding",
    "judicial_finding",
    "disputed",
    "withdrawn",
    "unknown",
]
ExtractionMethod = Literal[
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
ClaimSubjectType = Literal[
    "incident", "facility", "organization", "casualty", "classification", "recommendation"
]
DecisionType = Literal["accept_claim", "reject_field", "manual_override", "defer"]
IncidentStatus = Literal["in_scope", "out_of_scope", "scope_undetermined"]
CasualtyStatus = Literal["initial", "revised", "final", "disputed"]
VerificationStatus = Literal["unverified", "in_review", "reviewed"]
PublicationStatus = Literal["draft", "internal", "publishable", "published", "withdrawn"]
DatePrecision = Literal["exact_datetime", "exact_date", "month", "year", "approximate"]
CoordinatePrecision = Literal[
    "exact_verified",
    "facility_approximate",
    "settlement",
    "district_centroid",
    "province_centroid",
    "unknown",
]
OrganizationType = Literal[
    "private_company",
    "state_enterprise",
    "public_authority",
    "cooperative",
    "informal_operation",
    "union_or_chamber",
    "ngo",
    "unknown",
    "other",
]
OrganizationRole = Literal[
    "licence_holder",
    "owner",
    "operator",
    "subcontractor",
    "employer",
    "public_authority",
    "rescue_organization",
    "other",
    "unknown",
]
ClassificationSystem = Literal[
    "project_hazard",
    "project_event_mechanism",
    "project_mode_of_harm",
    "project_contributing_condition",
    "ESAW",
    "ICSE",
    "NACE",
    "other",
]
AliasType = Literal["former_name", "spelling_variant", "local_name", "abbreviation"]
ImplementationStatus = Literal[
    "unknown", "proposed", "partially_implemented", "implemented", "rejected"
]
RunType = Literal["manual_import", "adapter", "migration", "export"]

#: Fields whose decisions gate publication (spec §11 rule 6).
PUBLICATION_CRITICAL_FIELDS = ("incident_start_datetime", "province_code", "fatalities_current")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceDocument(_Model):
    source_document_id: int | None = None
    source_organization: str
    title: str
    document_type: str | None = None
    url: str | None = None
    publication_date: str | None = None
    last_modified_date: str | None = None
    retrieved_at: str | None = None
    language: str | None = None
    author: str | None = None
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    local_raw_path: str | None = None
    archived_reference: str | None = None
    licence_or_reuse_notes: str | None = None
    attribution_required: bool | None = None
    source_tier: int | None = Field(default=None, ge=1, le=3)
    access_status: str | None = None
    notes: str | None = None


class Claim(_Model):
    claim_id: int | None = None
    incident_id: int | None = None
    source_document_id: int
    claim_subject_type: ClaimSubjectType = "incident"
    claim_subject_id: int | None = None
    field_name: str
    raw_value: str | None = None
    normalized_value: str | None = None
    unit: str | None = None
    page_number: str | None = None
    section_reference: str | None = None
    short_evidence_excerpt: str | None = None
    extraction_method: ExtractionMethod
    extractor_version: str | None = None
    assertion_status: AssertionStatus = "unknown"
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    review_status: ReviewStatus = "pending"

    @model_validator(mode="after")
    def _ai_ocr_needs_review(self) -> Claim:
        # Hard constraint 5: AI/OCR output is never trusted without human review.
        if self.extraction_method in ("ai_assisted", "ocr_assisted"):
            object.__setattr__(self, "review_status", "needs_review")
        return self


class ClaimDecision(_Model):
    decision_id: int | None = None
    incident_id: int
    field_name: str
    selected_claim_id: int | None = None
    decision: DecisionType
    manual_value: str | None = None
    rationale: str = Field(min_length=1)
    rationale_claim_ids: list[int] = Field(default_factory=list)
    reviewer: str = Field(min_length=1)
    decision_date: str | None = None
    supersedes_decision_id: int | None = None

    @model_validator(mode="after")
    def _decision_shape(self) -> ClaimDecision:
        if self.decision == "accept_claim" and self.selected_claim_id is None:
            raise ValueError("accept_claim requires selected_claim_id")
        if self.decision == "manual_override":
            if self.manual_value is None:
                raise ValueError("manual_override requires manual_value")
            if not self.rationale_claim_ids:
                raise ValueError(
                    "manual_override requires >=1 supporting claim in rationale_claim_ids"
                )
        return self


class Incident(_Model):
    incident_id: int | None = None
    public_incident_id: str | None = Field(default=None, pattern=r"^TR-MINE-\d{4}-\d{4}$")
    canonical_title_tr: str | None = None
    canonical_title_en: str | None = None
    canonical_title_tr_normalized: str | None = None
    incident_start_datetime: str | None = None
    incident_end_datetime: str | None = None
    date_precision: DatePrecision | None = None
    incident_status: IncidentStatus = "scope_undetermined"
    scope_rationale: str | None = None
    province_code: str | None = None
    district_code: str | None = None
    settlement: str | None = None
    facility_id: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    coordinate_precision: CoordinatePrecision | None = None
    location_uncertainty_m: float | None = Field(default=None, ge=0)
    location_source_claim_id: int | None = None
    fatalities_current: int | None = Field(default=None, ge=0)
    injuries_current: int | None = Field(default=None, ge=0)
    missing_current: int | None = Field(default=None, ge=0)
    casualty_status: CasualtyStatus | None = None
    verification_status: VerificationStatus = "unverified"
    publication_status: PublicationStatus = "draft"


class CasualtyObservation(_Model):
    observation_id: int | None = None
    incident_id: int
    fatalities: int | None = Field(default=None, ge=0)
    injuries: int | None = Field(default=None, ge=0)
    missing: int | None = Field(default=None, ge=0)
    observation_as_of: str | None = None
    source_claim_id: int | None = None
    is_current_canonical: bool = False
    review_status: ReviewStatus = "pending"
    notes: str | None = None


class Facility(_Model):
    facility_id: int | None = None
    facility_name_tr: str
    facility_name_normalized: str | None = None
    facility_type: str | None = None
    province_code: str | None = None
    district_code: str | None = None
    settlement: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    coordinate_precision: CoordinatePrecision | None = None
    location_uncertainty_m: float | None = Field(default=None, ge=0)
    source_claim_id: int | None = None
    notes: str | None = None


class FacilityAlias(_Model):
    alias_id: int | None = None
    facility_id: int
    alias: str
    alias_normalized: str
    alias_type: AliasType
    valid_from: str | None = None
    valid_to: str | None = None
    source_claim_id: int | None = None


class Organization(_Model):
    organization_id: int | None = None
    organization_name_tr: str
    organization_name_normalized: str | None = None
    organization_type: OrganizationType = "unknown"
    notes: str | None = None


class OrganizationAlias(_Model):
    alias_id: int | None = None
    organization_id: int
    alias: str
    alias_normalized: str
    alias_type: AliasType
    valid_from: str | None = None
    valid_to: str | None = None
    source_claim_id: int | None = None


class IncidentOrganizationRole(_Model):
    incident_organization_role_id: int | None = None
    incident_id: int
    organization_id: int
    role: OrganizationRole
    valid_at_incident_date: bool | None = None
    source_claim_id: int
    assertion_status: AssertionStatus = "unknown"
    review_status: ReviewStatus = "pending"
    notes: str | None = None


class IncidentClassification(_Model):
    classification_id: int | None = None
    incident_id: int
    classification_system: ClassificationSystem
    classification_level: str | None = None
    classification_code: str
    classification_label_tr: str | None = None
    classification_label_en: str | None = None
    assertion_status: AssertionStatus = "unknown"
    source_claim_id: int | None = None
    review_status: ReviewStatus = "pending"
    notes: str | None = None

    @model_validator(mode="after")
    def _project_rows_need_source_to_be_reviewed(self) -> IncidentClassification:
        if (
            self.classification_system.startswith("project_")
            and self.review_status == "reviewed"
            and self.source_claim_id is None
        ):
            raise ValueError(
                "project_* classification rows require source_claim_id to be 'reviewed'"
            )
        return self


class Recommendation(_Model):
    recommendation_id: int | None = None
    incident_id: int | None = None
    source_document_id: int
    recommendation_text: str
    recommendation_category: str | None = None
    responsible_actor: str | None = None
    implementation_status: ImplementationStatus = "unknown"
    origin: Literal["source_finding"] = "source_finding"
    review_status: ReviewStatus = "pending"
    notes: str | None = None


class SourceRegistryEntry(_Model):
    source_registry_id: int | None = None
    source_key: str
    organization_or_family: str
    family: str | None = None
    tier_proposed: int | None = Field(default=None, ge=1, le=3)
    url: str | None = None
    access_status: str | None = None
    automated_collection_permitted: Literal["yes", "no", "unclear"] | None = None
    licence_or_reuse_notes: str | None = None
    last_assessed: str | None = None
    assessment_notes: str | None = None


class IngestionRun(_Model):
    run_id: int | None = None
    run_type: RunType
    adapter_name: str | None = None
    adapter_version: str | None = None
    started_at: str
    finished_at: str | None = None
    input_reference: str | None = None
    records_created: int = Field(default=0, ge=0)
    records_skipped: int = Field(default=0, ge=0)
    status: str | None = None
    log_path: str | None = None
    git_commit: str | None = None
    notes: str | None = None


class ReviewLogEntry(_Model):
    log_id: int | None = None
    actor: str = Field(min_length=1)
    action: str = Field(min_length=1)
    entity_type: str | None = None
    entity_id: int | None = None
    before_summary: str | None = None
    after_summary: str | None = None
    occurred_at: str
    notes: str | None = None


class IncidentMergeLogEntry(_Model):
    merge_id: int | None = None
    surviving_incident_id: int
    merged_incident_id: int
    merged_public_incident_id: str | None = None
    reason: str | None = None
    reviewer: str = Field(min_length=1)
    merged_at: str
