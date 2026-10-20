-- 005_environmental_effect_english.sql
-- An English rendering for an environmental effect's qualitative value.
--
-- `qualitative_value` holds the project's own short description of what a
-- release reached or what failed, written in Turkish. On the English page that
-- put Turkish sentences under English labels ("Structure that failed: İkinci
-- atık barajının iç seti"), which is the language mixing the project owner
-- reported on 2026-10-20.
--
-- Place names stay Turkish in both languages, because they are names. What
-- gains an English form is the description around them.

ALTER TABLE environmental_effects ADD COLUMN qualitative_value_en TEXT;
