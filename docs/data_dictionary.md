# Data Dictionary

Meaning of every table and load-bearing column. Kept in sync with
`database/schema.sql` (regenerated snapshot) and the vocabulary CSVs in
`data/vocabularies/`. Types are SQLite-affinity now, designed
forward-compatible with PostgreSQL/PostGIS (coordinates are REAL columns
documented as future `geometry(Point, 4326)`).

## Conventions

- Internal PKs: `INTEGER PRIMARY KEY` named `<entity>_id`.
- Public IDs: `public_incident_id` = `TR-MINE-YYYY-NNNN` (year of incident
  start + zero-padded sequence within year). Assigned once, never reused,
  preserved through merges via `incident_merge_log`.
- Timestamps: ISO 8601 text. Incident times are local with explicit offset
  (`YYYY-MM-DDTHH:MM:SS+03:00`) plus `date_precision`
  (`exact_datetime | exact_date | month | year | approximate`).
  Ingestion/audit timestamps are UTC.
- `created_at`/`updated_at` on mutable tables; append-only tables get
  `created_at` only plus update-blocking triggers.

### Enum enforcement (documented design choice)

Two mechanisms, chosen deliberately:

1. **Stable workflow enums** (statuses, decisions, extraction methods,
   precisions, subject/role/organization types) are enforced with SQL `CHECK`
   constraints in the migration. These values are structural to the state
   machine and change only via migration.
2. **Vocabulary-driven codes** (hazards, event mechanisms, modes of harm,
   contributing conditions, admin-area codes) are validated in the Python
   layer (`vocabularies.py` + `validators.py`) against the versioned CSVs,
   which are the source of truth. A test asserts the SQL CHECK lists that
   mirror vocabulary CSVs stay in sync.

## Immutability model

`source_documents`, `ingestion_runs`, `review_log`: fully append-only
(triggers reject UPDATE and DELETE).

`claims`: evidence content is immutable; only `review_status` (the claim
state machine) and `incident_id` (linking a claim to an incident, which the
spec allows to happen after creation) may be updated. A trigger rejects any
UPDATE touching another column, and all DELETEs.

`casualty_observations`: figures are immutable; only `is_current_canonical`
and `review_status` may change (set via decisions). DELETE rejected.

*Conservative-interpretation note:* the spec declares `claims` append-only
while also defining a `review_status` transition on claims; the resolution
above (content frozen, workflow column mutable) is the most conservative
reading and is logged in `open_questions.md` (implementation notes).

## Tables

### incidents — canonical reviewed record
One row per reviewed incident synthesis. Key columns:
`public_incident_id` (see conventions) · `canonical_title_tr/_en` (+
`canonical_title_tr_normalized` via `normalize_tr`) ·
`incident_start_datetime`/`incident_end_datetime` + `date_precision` ·
`incident_status` (`in_scope|out_of_scope|scope_undetermined`) +
`scope_rationale` · `province_code`/`district_code` (vocabulary codes) ·
`facility_id → facilities` · `latitude`/`longitude` (WGS84) +
`coordinate_precision` + `location_uncertainty_m` +
`location_source_claim_id → claims` · `fatalities_current`/
`injuries_current`/`missing_current` (copies of the canonical observation,
written only by `review.py`) · `casualty_status`
(`initial|revised|final|disputed`) · `verification_status`
(`unverified|in_review|reviewed`) · `publication_status`
(`draft|internal|publishable|published|withdrawn`).

### casualty_observations — append-only casualty history
One row per reported figure set: `fatalities`, `injuries`, `missing`,
`observation_as_of`, `source_claim_id`, `is_current_canonical` (0/1; at most
one per incident, set only via decision), `review_status`, `notes`.

### source_documents — append-only document registry
`source_organization`, `title`, `document_type`, `url`, `publication_date`,
`last_modified_date`, `retrieved_at`, `language`, `author`,
`content_hash` (sha256), `local_raw_path`, `archived_reference`,
`licence_or_reuse_notes`, `attribution_required`, `source_tier`,
`access_status`, `notes`. `retrieved_at` and `content_hash` are required for
any document backing a published claim (QC-enforced). Full copyrighted
articles never enter public exports.

### claims — append-only field-level assertions
`incident_id` (nullable until linked), `source_document_id` (NOT NULL),
`claim_subject_type`
(`incident|facility|organization|casualty|classification|recommendation`),
`claim_subject_id`, `field_name`, `raw_value`, `normalized_value`, `unit`,
`page_number`, `section_reference`, `short_evidence_excerpt` (word-capped,
names redacted to initials), `extraction_method`
(`manual|html_parser|pdf_text|pdf_table|api|structured_file|ai_assisted|ocr_assisted|other`),
`extractor_version`, `assertion_status`, `confidence_score` (0–1, nullable),
`review_status`. Trigger: `ai_assisted`/`ocr_assisted` claims must be
`needs_review` on insert.

### claim_decisions — the only path to canonical values
`incident_id`, `field_name`, `selected_claim_id` (nullable for
reject/defer), `decision` (`accept_claim|reject_field|manual_override|defer`),
`manual_value`, `rationale` (NOT NULL), `rationale_claim_ids` (JSON array of
claim ids), `reviewer` (NOT NULL), `decision_date`, `supersedes_decision_id`.
Application code enforces one **active** decision per (incident, field).

### facilities / facility_aliases
Facility identity + name history. Aliases carry `alias_normalized`,
`alias_type` (`former_name|spelling_variant|local_name|abbreviation`),
`valid_from`, `valid_to`, `source_claim_id`.

Since migration 002 (active-sites layer, 2026-07-15) facilities also carry
`commodity_code`/`commodity_label` (vocabulary `commodities.csv`),
`operational_status` (`operating|closed|proposed|unknown` — `closed` only when
the source asserts a closure statement; never guessed "operating"),
`facility_type` codes from `facility_types.csv`, and `external_ref`
(idempotency key, e.g. `wikidata:Q...`). The facilities table is a **context
registry**, not incident evidence: values are written with their
`source_claim_id` plus a `review_log` sign-off under a named reviewer — the
incident `claim_decisions` machinery stays incident-scoped by design.
Coverage is partial (open structured sources only) and must be labeled as
such wherever the layer is displayed (open question #19).

### organizations / organization_aliases
Same pattern. `organization_type`:
`private_company|state_enterprise|public_authority|cooperative|informal_operation|union_or_chamber|ngo|unknown|other`.
Since migration 002: `country_code` (ISO 3166-1 alpha-2) / `country_label`
for the organization's home country as stated by the source, and
`external_ref` (e.g. `wikidata:Q...`).

### facility_organization_roles
Mirror of `incident_organization_roles` for sites: `role`
(`operator|owner|licence_holder`), `valid_from`/`valid_to`,
`source_claim_id` (NOT NULL), `assertion_status`, `review_status`, unique on
(facility_id, organization_id, role). Only `reviewed` rows are exported, and
assertion status ships with every row.

### incident_organization_roles
`role`
(`licence_holder|owner|operator|subcontractor|employer|public_authority|rescue_organization|other|unknown`),
`valid_at_incident_date`, `source_claim_id` (NOT NULL), `assertion_status`,
`review_status`, `notes`. Unique on (incident_id, organization_id, role).

### incident_classifications
`classification_system`
(`project_hazard|project_event_mechanism|project_mode_of_harm|project_contributing_condition|ESAW|ICSE|NACE|other`),
`classification_level`, `classification_code`, bilingual labels,
`assertion_status`, `source_claim_id`, `review_status`. `project_*` rows need
`source_claim_id` to reach `reviewed` (validator + QC rule).

### recommendations — source findings only
`recommendation_text`, `recommendation_category`, `responsible_actor`,
`implementation_status`
(`unknown|proposed|partially_implemented|implemented|rejected`),
`origin` CHECK-fixed to `source_finding`: the schema forbids storing
project-generated recommendations by design.

### source_registry
Registry of assessed sources: family, tier, access terms,
`automated_collection_permitted` (`yes|no|unclear`), `last_assessed`,
`assessment_notes`.

### ingestion_runs — append-only run log
`run_type` (`manual_import|adapter|migration|export`), adapter name/version,
started/finished timestamps, `input_reference`, `records_created`,
`records_skipped`, `status`, `log_path`, `git_commit`. Rows are inserted at
run completion (append-only means no status updates in place).

### review_log — append-only audit trail
`actor`, `action`, `entity_type`, `entity_id`, `before_summary`,
`after_summary`, `occurred_at`, `notes`.

### incident_merge_log
`surviving_incident_id`, `merged_incident_id`, `merged_public_incident_id`,
`reason`, `reviewer`, `merged_at`. Merged public IDs stay resolvable in
exports (`merged_id_redirects.csv`).

### schema_migrations
`version`, `description`, `applied_at`, `checksum` (sha256 of migration file).

### Aggregate context tables (schema only, empty in MVP)
`aggregate_occupational_statistics`, `aggregate_employment`,
`aggregate_production`, `aggregate_licence_context`: reporting institution,
period, classification system/code/version, numerator, denominator
(nullable), unit, `source_document_id`, `comparability_notes`.
Binding rules: raw counts are never labeled "risk"; rates only with a
documented exposure denominator; coverage analysis is a future phase.

`classification_concordance` maps codes between systems (from/to system,
code, version, mapping quality, `source_document_id`, `comparability_notes`).
*Deviation note:* the spec lists the same column template for all five
tables; a concordance is a mapping, so it carries from/to columns instead of
numerator/denominator. Logged in `open_questions.md` implementation notes.

## Open questions

- Register #6 — district-level admin reference sourcing (schema supports
  `district_code`; only provinces ship in `turkey_admin_areas.csv`).
- Whether `claims.review_status` mutability (see immutability model) should
  instead be modeled as an append-only claim-review-events table —
  **flagged as open**.
