-- 002_facilities_extension.sql
-- Active-sites layer (project owner directive, 2026-07-15): organizations
-- gain a home country; facilities gain commodity/status and an external
-- reference for idempotent ingestion; a facility<->organization role table
-- mirrors incident_organization_roles so operator/owner attributions stay
-- claim-backed with assertion and review statuses.

ALTER TABLE organizations ADD COLUMN country_code TEXT;    -- ISO 3166-1 alpha-2
ALTER TABLE organizations ADD COLUMN country_label TEXT;
ALTER TABLE organizations ADD COLUMN external_ref TEXT;    -- e.g. wikidata:Q...

ALTER TABLE facilities ADD COLUMN commodity_code TEXT;     -- vocabulary: commodities.csv
ALTER TABLE facilities ADD COLUMN commodity_label TEXT;
ALTER TABLE facilities ADD COLUMN operational_status TEXT
    CHECK (operational_status IS NULL OR operational_status IN
        ('operating', 'closed', 'proposed', 'unknown'));
ALTER TABLE facilities ADD COLUMN external_ref TEXT;

CREATE INDEX idx_facilities_external_ref ON facilities (external_ref);
CREATE INDEX idx_organizations_external_ref ON organizations (external_ref);

CREATE TABLE facility_organization_roles (
    facility_organization_role_id INTEGER PRIMARY KEY,
    facility_id INTEGER NOT NULL REFERENCES facilities (facility_id),
    organization_id INTEGER NOT NULL REFERENCES organizations (organization_id),
    role TEXT NOT NULL CHECK (role IN ('operator', 'owner', 'licence_holder')),
    valid_from TEXT,
    valid_to TEXT,
    source_claim_id INTEGER NOT NULL REFERENCES claims (claim_id),
    assertion_status TEXT NOT NULL DEFAULT 'unknown' CHECK (assertion_status IN
        ('reported', 'alleged', 'preliminary_finding', 'technical_finding',
         'official_finding', 'judicial_finding', 'disputed', 'withdrawn', 'unknown')),
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN
        ('pending', 'needs_review', 'reviewed')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (facility_id, organization_id, role)
);

CREATE TRIGGER trg_facility_organization_roles_updated_at
AFTER UPDATE ON facility_organization_roles
BEGIN
    UPDATE facility_organization_roles SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE facility_organization_role_id = NEW.facility_organization_role_id;
END;
