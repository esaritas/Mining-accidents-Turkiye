-- 006_environmental_effect_status.sql
-- Whether a stated environmental effect was observed, reported, threatened,
-- modelled, or is unknown.
--
-- `assertion_status` already records WHO asserts an effect (reported, alleged,
-- technical_finding, official_finding). It does not record WHETHER the effect
-- happened, and the dashboard printed one label, "Reached", over every
-- receiving-environment row. One of those rows is the Kelkit Çayı river and its
-- plain, which its source describes as reported to be under threat
-- ("tehdit altında olduğu bildirildi"), so a threatened river was displayed as
-- a contaminated one. Another is a spill onto ground at a mine that stands on
-- the bank of the Euphrates, where proximity read as arrival.
--
-- Proximity, potential exposure and confirmed arrival are different claims and
-- now have different values. `observed` is reserved for an effect this project
-- can point to a measurement or direct observation for; nothing in the register
-- qualifies yet, which is itself worth being able to see.
--
-- STATUS: PROPOSED — awaiting editorial decision (open question 41).

ALTER TABLE environmental_effects ADD COLUMN effect_status TEXT
    NOT NULL DEFAULT 'unknown'
    CHECK (effect_status IN ('observed', 'reported', 'threatened', 'modelled', 'unknown'));
