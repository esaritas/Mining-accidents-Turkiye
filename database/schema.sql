-- database/schema.sql — GENERATED snapshot of the current schema.
-- Do not edit by hand: regenerate by applying migrations (make db).
-- Canonical history lives in database/migrations/.

CREATE TABLE aggregate_employment (
    aggregate_id INTEGER PRIMARY KEY,
    reporting_institution TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    classification_system TEXT,
    classification_code TEXT,
    classification_version TEXT,
    numerator REAL,
    denominator REAL,
    unit TEXT,
    source_document_id INTEGER REFERENCES source_documents (source_document_id),
    comparability_notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE aggregate_licence_context (
    aggregate_id INTEGER PRIMARY KEY,
    reporting_institution TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    classification_system TEXT,
    classification_code TEXT,
    classification_version TEXT,
    numerator REAL,
    denominator REAL,
    unit TEXT,
    source_document_id INTEGER REFERENCES source_documents (source_document_id),
    comparability_notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE aggregate_occupational_statistics (
    aggregate_id INTEGER PRIMARY KEY,
    reporting_institution TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    classification_system TEXT,
    classification_code TEXT,
    classification_version TEXT,
    numerator REAL,
    denominator REAL,
    unit TEXT,
    source_document_id INTEGER REFERENCES source_documents (source_document_id),
    comparability_notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE aggregate_production (
    aggregate_id INTEGER PRIMARY KEY,
    reporting_institution TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    classification_system TEXT,
    classification_code TEXT,
    classification_version TEXT,
    numerator REAL,
    denominator REAL,
    unit TEXT,
    source_document_id INTEGER REFERENCES source_documents (source_document_id),
    comparability_notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE casualty_observations (
    observation_id INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents (incident_id),
    fatalities INTEGER,
    injuries INTEGER,
    missing INTEGER,
    observation_as_of TEXT,
    source_claim_id INTEGER REFERENCES claims (claim_id),
    is_current_canonical INTEGER NOT NULL DEFAULT 0 CHECK (is_current_canonical IN (0, 1)),
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN
        ('pending', 'needs_review', 'reviewed')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE claim_decisions (
    decision_id INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents (incident_id),
    field_name TEXT NOT NULL,
    selected_claim_id INTEGER REFERENCES claims (claim_id),   -- nullable for reject/defer
    decision TEXT NOT NULL CHECK (decision IN
        ('accept_claim', 'reject_field', 'manual_override', 'defer')),
    manual_value TEXT,
    rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 0),
    rationale_claim_ids TEXT,                -- JSON array of supporting claim ids
    reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
    decision_date TEXT,
    supersedes_decision_id INTEGER REFERENCES claim_decisions (decision_id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE claims (
    claim_id INTEGER PRIMARY KEY,
    incident_id INTEGER REFERENCES incidents (incident_id),   -- nullable until linked
    source_document_id INTEGER NOT NULL REFERENCES source_documents (source_document_id),
    claim_subject_type TEXT NOT NULL CHECK (claim_subject_type IN
        ('incident', 'facility', 'organization', 'casualty', 'classification', 'recommendation')),
    claim_subject_id INTEGER,
    field_name TEXT NOT NULL,
    raw_value TEXT,
    normalized_value TEXT,
    unit TEXT,
    page_number TEXT,
    section_reference TEXT,
    short_evidence_excerpt TEXT,   -- word-capped; personal names redacted to initials
    extraction_method TEXT NOT NULL CHECK (extraction_method IN
        ('manual', 'html_parser', 'pdf_text', 'pdf_table', 'api', 'structured_file',
         'ai_assisted', 'ocr_assisted', 'other')),
    extractor_version TEXT,
    assertion_status TEXT NOT NULL DEFAULT 'unknown' CHECK (assertion_status IN
        ('reported', 'alleged', 'preliminary_finding', 'technical_finding',
         'official_finding', 'judicial_finding', 'disputed', 'withdrawn', 'unknown')),
    confidence_score REAL CHECK (confidence_score IS NULL
        OR (confidence_score >= 0.0 AND confidence_score <= 1.0)),
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN
        ('pending', 'needs_review', 'reviewed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE classification_concordance (
    concordance_id INTEGER PRIMARY KEY,
    from_system TEXT NOT NULL,
    from_code TEXT NOT NULL,
    from_version TEXT,
    to_system TEXT NOT NULL,
    to_code TEXT NOT NULL,
    to_version TEXT,
    mapping_quality TEXT CHECK (mapping_quality IS NULL OR mapping_quality IN
        ('exact', 'broader', 'narrower', 'approximate', 'unknown')),
    source_document_id INTEGER REFERENCES source_documents (source_document_id),
    comparability_notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE facilities (
    facility_id INTEGER PRIMARY KEY,
    facility_name_tr TEXT NOT NULL,
    facility_name_normalized TEXT,
    facility_type TEXT,
    province_code TEXT,
    district_code TEXT,
    settlement TEXT,
    latitude REAL,               -- WGS84; future geometry(Point, 4326)
    longitude REAL,
    coordinate_precision TEXT CHECK (coordinate_precision IS NULL OR coordinate_precision IN
        ('exact_verified', 'facility_approximate', 'settlement',
         'district_centroid', 'province_centroid', 'unknown')),
    location_uncertainty_m REAL,
    source_claim_id INTEGER REFERENCES claims (claim_id),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE facility_aliases (
    alias_id INTEGER PRIMARY KEY,
    facility_id INTEGER NOT NULL REFERENCES facilities (facility_id),
    alias TEXT NOT NULL,
    alias_normalized TEXT NOT NULL,
    alias_type TEXT NOT NULL CHECK (alias_type IN
        ('former_name', 'spelling_variant', 'local_name', 'abbreviation')),
    valid_from TEXT,
    valid_to TEXT,
    source_claim_id INTEGER REFERENCES claims (claim_id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE incident_classifications (
    classification_id INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents (incident_id),
    classification_system TEXT NOT NULL CHECK (classification_system IN
        ('project_hazard', 'project_event_mechanism', 'project_mode_of_harm',
         'project_contributing_condition', 'ESAW', 'ICSE', 'NACE', 'other')),
    classification_level TEXT,
    classification_code TEXT NOT NULL,       -- project_* codes validated against vocabularies
    classification_label_tr TEXT,
    classification_label_en TEXT,
    assertion_status TEXT NOT NULL DEFAULT 'unknown' CHECK (assertion_status IN
        ('reported', 'alleged', 'preliminary_finding', 'technical_finding',
         'official_finding', 'judicial_finding', 'disputed', 'withdrawn', 'unknown')),
    source_claim_id INTEGER REFERENCES claims (claim_id),
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN
        ('pending', 'needs_review', 'reviewed')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE incident_merge_log (
    merge_id INTEGER PRIMARY KEY,
    surviving_incident_id INTEGER NOT NULL REFERENCES incidents (incident_id),
    merged_incident_id INTEGER NOT NULL,
    merged_public_incident_id TEXT,          -- stays resolvable as a redirect in exports
    reason TEXT,
    reviewer TEXT NOT NULL,
    merged_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE incident_organization_roles (
    incident_organization_role_id INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents (incident_id),
    organization_id INTEGER NOT NULL REFERENCES organizations (organization_id),
    role TEXT NOT NULL CHECK (role IN
        ('licence_holder', 'owner', 'operator', 'subcontractor', 'employer',
         'public_authority', 'rescue_organization', 'other', 'unknown')),
    valid_at_incident_date INTEGER CHECK (valid_at_incident_date IS NULL
        OR valid_at_incident_date IN (0, 1)),
    source_claim_id INTEGER NOT NULL REFERENCES claims (claim_id),
    assertion_status TEXT NOT NULL DEFAULT 'unknown' CHECK (assertion_status IN
        ('reported', 'alleged', 'preliminary_finding', 'technical_finding',
         'official_finding', 'judicial_finding', 'disputed', 'withdrawn', 'unknown')),
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN
        ('pending', 'needs_review', 'reviewed')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (incident_id, organization_id, role)
);

CREATE TABLE incidents (
    incident_id INTEGER PRIMARY KEY,
    public_incident_id TEXT UNIQUE,          -- TR-MINE-YYYY-NNNN; assigned once, never reused
    canonical_title_tr TEXT,
    canonical_title_en TEXT,
    canonical_title_tr_normalized TEXT,
    incident_start_datetime TEXT,            -- local time with explicit offset
    incident_end_datetime TEXT,
    date_precision TEXT CHECK (date_precision IS NULL OR date_precision IN
        ('exact_datetime', 'exact_date', 'month', 'year', 'approximate')),
    incident_status TEXT NOT NULL DEFAULT 'scope_undetermined' CHECK (incident_status IN
        ('in_scope', 'out_of_scope', 'scope_undetermined')),
    scope_rationale TEXT,
    province_code TEXT,                      -- vocabulary: turkey_admin_areas.csv
    district_code TEXT,                      -- schema-ready; district vocabulary not yet shipped
    settlement TEXT,
    facility_id INTEGER REFERENCES facilities (facility_id),
    latitude REAL,                           -- WGS84; future geometry(Point, 4326)
    longitude REAL,
    coordinate_precision TEXT CHECK (coordinate_precision IS NULL OR coordinate_precision IN
        ('exact_verified', 'facility_approximate', 'settlement',
         'district_centroid', 'province_centroid', 'unknown')),
    location_uncertainty_m REAL,
    location_source_claim_id INTEGER REFERENCES claims (claim_id),
    fatalities_current INTEGER,              -- written only by review.py from decided observations
    injuries_current INTEGER,
    missing_current INTEGER,
    casualty_status TEXT CHECK (casualty_status IS NULL OR casualty_status IN
        ('initial', 'revised', 'final', 'disputed')),
    verification_status TEXT NOT NULL DEFAULT 'unverified' CHECK (verification_status IN
        ('unverified', 'in_review', 'reviewed')),
    publication_status TEXT NOT NULL DEFAULT 'draft' CHECK (publication_status IN
        ('draft', 'internal', 'publishable', 'published', 'withdrawn')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE ingestion_runs (
    run_id INTEGER PRIMARY KEY,
    run_type TEXT NOT NULL CHECK (run_type IN ('manual_import', 'adapter', 'migration', 'export')),
    adapter_name TEXT,
    adapter_version TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    input_reference TEXT,
    records_created INTEGER NOT NULL DEFAULT 0,
    records_skipped INTEGER NOT NULL DEFAULT 0,
    status TEXT,
    log_path TEXT,
    git_commit TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE organization_aliases (
    alias_id INTEGER PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations (organization_id),
    alias TEXT NOT NULL,
    alias_normalized TEXT NOT NULL,
    alias_type TEXT NOT NULL CHECK (alias_type IN
        ('former_name', 'spelling_variant', 'local_name', 'abbreviation')),
    valid_from TEXT,
    valid_to TEXT,
    source_claim_id INTEGER REFERENCES claims (claim_id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE organizations (
    organization_id INTEGER PRIMARY KEY,
    organization_name_tr TEXT NOT NULL,
    organization_name_normalized TEXT,
    organization_type TEXT NOT NULL DEFAULT 'unknown' CHECK (organization_type IN
        ('private_company', 'state_enterprise', 'public_authority', 'cooperative',
         'informal_operation', 'union_or_chamber', 'ngo', 'unknown', 'other')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE recommendations (
    recommendation_id INTEGER PRIMARY KEY,
    incident_id INTEGER REFERENCES incidents (incident_id),
    source_document_id INTEGER NOT NULL REFERENCES source_documents (source_document_id),
    recommendation_text TEXT NOT NULL,
    recommendation_category TEXT,
    responsible_actor TEXT,
    implementation_status TEXT NOT NULL DEFAULT 'unknown' CHECK (implementation_status IN
        ('unknown', 'proposed', 'partially_implemented', 'implemented', 'rejected')),
    -- Fixed by design: this table stores SOURCE findings only. Project analytical
    -- commentary lives in docs, never here (editorial_and_legal_protocol.md §3).
    origin TEXT NOT NULL DEFAULT 'source_finding' CHECK (origin = 'source_finding'),
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN
        ('pending', 'needs_review', 'reviewed')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE review_log (
    log_id INTEGER PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    before_summary TEXT,
    after_summary TEXT,
    occurred_at TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE schema_migrations (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            checksum TEXT NOT NULL
        );

CREATE TABLE source_documents (
    source_document_id INTEGER PRIMARY KEY,
    source_organization TEXT NOT NULL,
    title TEXT NOT NULL,
    document_type TEXT,
    url TEXT,
    publication_date TEXT,
    last_modified_date TEXT,
    retrieved_at TEXT,          -- NOT NULL for documents backing published claims (QC-enforced)
    language TEXT,
    author TEXT,
    content_hash TEXT,          -- sha256; NOT NULL for documents backing published claims (QC-enforced)
    local_raw_path TEXT,
    archived_reference TEXT,
    licence_or_reuse_notes TEXT,
    attribution_required INTEGER CHECK (attribution_required IN (0, 1)),
    source_tier INTEGER,
    access_status TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE source_registry (
    source_registry_id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    organization_or_family TEXT NOT NULL,
    family TEXT,
    tier_proposed INTEGER,
    url TEXT,
    access_status TEXT,
    automated_collection_permitted TEXT
        CHECK (automated_collection_permitted IN ('yes', 'no', 'unclear')),
    licence_or_reuse_notes TEXT,
    last_assessed TEXT,
    assessment_notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX idx_casualty_observations_incident ON casualty_observations (incident_id);

CREATE INDEX idx_claim_decisions_incident_field ON claim_decisions (incident_id, field_name);

CREATE INDEX idx_claims_incident_field ON claims (incident_id, field_name);

CREATE INDEX idx_claims_source_document ON claims (source_document_id);

CREATE INDEX idx_facility_aliases_normalized ON facility_aliases (alias_normalized);

CREATE INDEX idx_incidents_province ON incidents (province_code);

CREATE INDEX idx_incidents_publication_status ON incidents (publication_status);

CREATE INDEX idx_incidents_start ON incidents (incident_start_datetime);

CREATE INDEX idx_organization_aliases_normalized ON organization_aliases (alias_normalized);

CREATE INDEX idx_source_documents_hash ON source_documents (content_hash);

CREATE TRIGGER trg_casualty_observations_content_immutable
BEFORE UPDATE ON casualty_observations
WHEN NEW.observation_id IS NOT OLD.observation_id
    OR NEW.incident_id IS NOT OLD.incident_id
    OR NEW.fatalities IS NOT OLD.fatalities
    OR NEW.injuries IS NOT OLD.injuries
    OR NEW.missing IS NOT OLD.missing
    OR NEW.observation_as_of IS NOT OLD.observation_as_of
    OR NEW.source_claim_id IS NOT OLD.source_claim_id
    OR NEW.notes IS NOT OLD.notes
    OR NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT,
        'casualty_observations figures are immutable: revisions append new rows');
END;

CREATE TRIGGER trg_casualty_observations_no_delete
BEFORE DELETE ON casualty_observations
BEGIN
    SELECT RAISE(ABORT, 'casualty_observations are append-only: rows are never deleted');
END;

CREATE TRIGGER trg_claim_decisions_no_delete
BEFORE DELETE ON claim_decisions
BEGIN
    SELECT RAISE(ABORT, 'claim_decisions are append-only: rows are never deleted');
END;

CREATE TRIGGER trg_claim_decisions_no_update
BEFORE UPDATE ON claim_decisions
BEGIN
    SELECT RAISE(ABORT, 'claim_decisions are append-only: supersede with a new decision row');
END;

CREATE TRIGGER trg_claims_ai_ocr_needs_review
BEFORE INSERT ON claims
WHEN NEW.extraction_method IN ('ai_assisted', 'ocr_assisted')
    AND NEW.review_status <> 'needs_review'
BEGIN
    SELECT RAISE(ABORT, 'ai/ocr-assisted claims must be created with review_status=needs_review');
END;

CREATE TRIGGER trg_claims_content_immutable
BEFORE UPDATE ON claims
WHEN NEW.claim_id IS NOT OLD.claim_id
    OR NEW.source_document_id IS NOT OLD.source_document_id
    OR NEW.claim_subject_type IS NOT OLD.claim_subject_type
    OR NEW.claim_subject_id IS NOT OLD.claim_subject_id
    OR NEW.field_name IS NOT OLD.field_name
    OR NEW.raw_value IS NOT OLD.raw_value
    OR NEW.normalized_value IS NOT OLD.normalized_value
    OR NEW.unit IS NOT OLD.unit
    OR NEW.page_number IS NOT OLD.page_number
    OR NEW.section_reference IS NOT OLD.section_reference
    OR NEW.short_evidence_excerpt IS NOT OLD.short_evidence_excerpt
    OR NEW.extraction_method IS NOT OLD.extraction_method
    OR NEW.extractor_version IS NOT OLD.extractor_version
    OR NEW.assertion_status IS NOT OLD.assertion_status
    OR NEW.confidence_score IS NOT OLD.confidence_score
    OR NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'claims are append-only: only incident_id and review_status may change');
END;

CREATE TRIGGER trg_claims_no_delete
BEFORE DELETE ON claims
BEGIN
    SELECT RAISE(ABORT, 'claims are append-only: rows are never deleted');
END;

CREATE TRIGGER trg_facilities_updated_at
AFTER UPDATE ON facilities
BEGIN
    UPDATE facilities SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE facility_id = NEW.facility_id;
END;

CREATE TRIGGER trg_incident_classifications_updated_at
AFTER UPDATE ON incident_classifications
BEGIN
    UPDATE incident_classifications SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE classification_id = NEW.classification_id;
END;

CREATE TRIGGER trg_incident_merge_log_no_delete
BEFORE DELETE ON incident_merge_log
BEGIN
    SELECT RAISE(ABORT, 'incident_merge_log is append-only');
END;

CREATE TRIGGER trg_incident_merge_log_no_update
BEFORE UPDATE ON incident_merge_log
BEGIN
    SELECT RAISE(ABORT, 'incident_merge_log is append-only');
END;

CREATE TRIGGER trg_incident_organization_roles_updated_at
AFTER UPDATE ON incident_organization_roles
BEGIN
    UPDATE incident_organization_roles SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE incident_organization_role_id = NEW.incident_organization_role_id;
END;

CREATE TRIGGER trg_incidents_updated_at
AFTER UPDATE ON incidents
BEGIN
    UPDATE incidents SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE incident_id = NEW.incident_id;
END;

CREATE TRIGGER trg_ingestion_runs_no_delete
BEFORE DELETE ON ingestion_runs
BEGIN
    SELECT RAISE(ABORT, 'ingestion_runs is append-only: rows are never deleted');
END;

CREATE TRIGGER trg_ingestion_runs_no_update
BEFORE UPDATE ON ingestion_runs
BEGIN
    SELECT RAISE(ABORT, 'ingestion_runs is append-only: rows are inserted once, at run completion');
END;

CREATE TRIGGER trg_organizations_updated_at
AFTER UPDATE ON organizations
BEGIN
    UPDATE organizations SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE organization_id = NEW.organization_id;
END;

CREATE TRIGGER trg_recommendations_updated_at
AFTER UPDATE ON recommendations
BEGIN
    UPDATE recommendations SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE recommendation_id = NEW.recommendation_id;
END;

CREATE TRIGGER trg_review_log_no_delete
BEFORE DELETE ON review_log
BEGIN
    SELECT RAISE(ABORT, 'review_log is append-only');
END;

CREATE TRIGGER trg_review_log_no_update
BEFORE UPDATE ON review_log
BEGIN
    SELECT RAISE(ABORT, 'review_log is append-only');
END;

CREATE TRIGGER trg_source_documents_no_delete
BEFORE DELETE ON source_documents
BEGIN
    SELECT RAISE(ABORT, 'source_documents is append-only: rows are never deleted');
END;

CREATE TRIGGER trg_source_documents_no_update
BEFORE UPDATE ON source_documents
BEGIN
    SELECT RAISE(ABORT, 'source_documents is append-only: corrections create new rows');
END;

CREATE TRIGGER trg_source_registry_updated_at
AFTER UPDATE ON source_registry
BEGIN
    UPDATE source_registry SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE source_registry_id = NEW.source_registry_id;
END;
