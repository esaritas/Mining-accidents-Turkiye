-- 003_environmental_incidents.sql
-- Environmental harm from mining (project owner directive, 2026-10-20).
--
-- Until now the register documented fatal accidents only, and said so nowhere:
-- the İliç 2024 record existed because nine people died, while the cyanide
-- heap-leach failure that killed them was recorded as an event mechanism and
-- nothing else, and the Şebinkarahisar tailings-dam collapse of 2021 was held
-- out of scope for having no deaths (quality audit 2026-10-20, section D3).
--
-- Design. An environmental incident is an incident: it happens at a place on a
-- date, it is asserted by sources, and every value about it must come from a
-- claim selected by a reviewer decision. Giving it its own table would mean
-- rebuilding `claims` to widen a CHECK constraint, which would disturb the
-- append-only evidence chain for no analytical gain. Instead `incidents` gains
-- a kind. Every existing row is a fatal_accident; the export keeps
-- incidents.csv to that kind alone, so published totals are unchanged, and
-- publishes environmental records in their own file.
--
-- One real event can be both: İliç 2024 killed nine people and moved
-- cyanide-bearing material. Those are two records, each with its own evidence,
-- joined by related_incident_id, because the death toll and the spill are
-- asserted by different sources and reviewed separately.

ALTER TABLE incidents ADD COLUMN incident_kind TEXT NOT NULL DEFAULT 'fatal_accident'
    CHECK (incident_kind IN ('fatal_accident', 'environmental'));

-- The other side of one event: a spill linked to the accident that caused it,
-- or an accident linked to the spill. Not a merge: both records stay separate.
ALTER TABLE incidents ADD COLUMN related_incident_id INTEGER
    REFERENCES incidents (incident_id);

CREATE INDEX idx_incidents_kind ON incidents (incident_kind);

-- What an environmental incident did, as the sources state it. Physical
-- effects only: what was released, where it went, how much ground or water it
-- touched. Fines, prosecutions and licence cancellations are deliberately out
-- of scope here, as everywhere else in this register (hard constraint 7).
CREATE TABLE environmental_effects (
    environmental_effect_id INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents (incident_id),
    effect_type TEXT NOT NULL,          -- vocabulary: environmental_effect_types.csv
    measure_value REAL,                 -- nullable: many effects are stated without a number
    measure_unit TEXT,                  -- tonne, m3, ha, km, day
    qualitative_value TEXT,             -- e.g. the watercourse a release reached
    source_claim_id INTEGER NOT NULL REFERENCES claims (claim_id),
    assertion_status TEXT NOT NULL DEFAULT 'unknown' CHECK (assertion_status IN
        ('reported', 'alleged', 'preliminary_finding', 'technical_finding',
         'official_finding', 'judicial_finding', 'disputed', 'withdrawn', 'unknown')),
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN
        ('pending', 'needs_review', 'reviewed')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX idx_environmental_effects_incident ON environmental_effects (incident_id);

CREATE TRIGGER trg_environmental_effects_updated_at
AFTER UPDATE ON environmental_effects
BEGIN
    UPDATE environmental_effects
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
     WHERE environmental_effect_id = NEW.environmental_effect_id;
END;
