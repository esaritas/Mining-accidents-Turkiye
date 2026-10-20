-- 004_environmental_classification_system.sql
-- Admit 'project_environmental_mechanism' to incident_classifications.
--
-- Migration 003 added environmental incidents but their mechanism had nowhere
-- to go: the classification_system CHECK admits four project systems and none
-- of them describes a tailings dam failing or a leach pad collapsing. Coding
-- those as 'other' would hide them from the vocabulary that backs every other
-- project classification.
--
-- SQLite cannot widen a CHECK in place, so the table is rebuilt. This is safe
-- here in a way it would not be for claims or source_documents: the table
-- carries no immutability trigger, only updated_at. Rows are copied with their
-- primary keys intact, so every source_claim_id reference still resolves and
-- nothing in the evidence chain moves.

PRAGMA foreign_keys = OFF;

CREATE TABLE incident_classifications_new (
    classification_id INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents (incident_id),
    classification_system TEXT NOT NULL CHECK (classification_system IN
        ('project_hazard', 'project_event_mechanism', 'project_mode_of_harm',
         'project_contributing_condition', 'project_environmental_mechanism',
         'ESAW', 'ICSE', 'NACE', 'other')),
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

INSERT INTO incident_classifications_new
SELECT classification_id, incident_id, classification_system, classification_level,
       classification_code, classification_label_tr, classification_label_en,
       assertion_status, source_claim_id, review_status, notes, created_at, updated_at
  FROM incident_classifications;

DROP TRIGGER trg_incident_classifications_updated_at;
DROP TABLE incident_classifications;
ALTER TABLE incident_classifications_new RENAME TO incident_classifications;

CREATE TRIGGER trg_incident_classifications_updated_at
AFTER UPDATE ON incident_classifications
BEGIN
    UPDATE incident_classifications SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE classification_id = NEW.classification_id;
END;

PRAGMA foreign_keys = ON;
