# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
semantic versioning once the project reaches a first release.

## [Unreleased]

### Changed — map, marks & data completeness (2026-07-16, owner feedback)
- Vector map rebuilt on Natural Earth 10m admin-1 geometry
  (`data/reference/tur_provinces.geo.json`, public domain): all 81 province
  boundaries drawn per-path, replacing the coarse country outline.
- One-mark-one-person fields and map accident markers now render as small
  human figures (CSS-mask / SVG pictograms; figure size = people lost on the
  map); undercount marks are gray figures instead of hollow boxes.
- Data completeness: quarry class added to site discovery (Wikidata has no
  further TR items — 78 is everything open data documents); linked-article
  infobox coordinates fetched for site items without P625 (+4 sites located);
  province derived from source-stated coordinates by point-in-polygon
  (`geo.py`, recorded as a derivation — implementation note E); infobox
  injury counts (`yaralı sayısı=`) extracted and decided alongside deaths;
  `link_incident_facilities` copies facility coordinates onto incidents via
  recorded manual_override decisions under a strict name+province blocking
  rule (implementation note F, STATUS: PROPOSED — zero links with current
  generated titles, engages as named records arrive).

### Added — active-sites layer, explorer filters & story prologue (2026-07-15)
- Migration 002: facilities gain `commodity_code`/`commodity_label`,
  `operational_status`, `external_ref`; organizations gain home-country
  columns (`country_code`/`country_label`) and `external_ref`; new
  `facility_organization_roles` table mirrors the incident role table
  (claim-backed, assertion + review statuses). New vocabularies
  `facility_types.csv` and `commodities.csv`.
- `wikidata_sites` adapter + `ingest-sites` CLI/make target: mining and
  quarrying site items in Türkiye (SPARQL P31/P279* mine, P17 TR) become a
  claim-backed facilities *context registry* — name, type, commodity,
  location, province, operator/owner with the company's home country where
  the source states them. 75 sites registered; coverage honestly labeled
  partial (open question #19: GEM tracker and MAPEG licence data registered
  `TO_ASSESS` for fuller company/status coverage).
- Public export gains `facilities.csv` + `facility_organization_roles.csv`
  (reviewed role rows only, assertion status always shipped).
- Infobox operating-company extraction for accident articles
  (`işletmeci|işleten|operator=`), with a ≥2-independent-documents
  corroboration threshold before an incident operator role row is marked
  reviewed/exportable (current sources state operators in prose only, so
  none auto-published).
- Dashboard: scroll-driven story prologue (pinned one-mark-one-person canvas;
  chapters per era 1983→today, the single largest loss, the İSİG undercount
  ghosts; reduced-motion static fallback), interactive filter bar
  (province / mechanism / year range / site commodity) driving map and
  tables, active-sites map layer (muted diamonds; Accidents/Sites/Both
  toggle) in both Leaflet and SVG variants, and a documented-sites table
  with operator and company home country columns.

### Added
- Phase 0: repository scaffolding, protocol document templates, open-questions
  register, configuration files, issue templates.
- Phase 1: initial schema migration (all evidence/decision/canonical/audit
  tables, CHECK constraints, indices, append-only triggers), checksummed
  migration runner with `schema.sql` snapshot, 14 controlled-vocabulary CSVs
  (including the 81 provinces) with validating loader, `create-db` CLI.
- Phase 2: Pydantic v2 models for every table, Pandera schemas at CSV
  boundaries, Turkish-aware normalization (explicit İ/ı handling), geography
  precision rules, duplicate-candidate detection, provenance utilities,
  adapter contract with conduct rules, four stub adapters, fully implemented
  manual CSV/YAML importer with synthetic example data.
- Phase 3: reviewer-decision recording with supersession and code-only
  canonical promotion, quality-check suite (9 critical + 6 warning checks),
  seven-rule publication threshold with deterministic byte-identical exports
  (datapackage + sha256 manifest), review-packet generator.
- Phase 4: twelve empty pilot packet slots, CLI test coverage, full README
  with architecture and next-stage plan.
- Reviewer CLI (`decide`, `assign-public-id`, `merge`) so decisions are
  recorded through tooling as the manual review protocol requires,
  `import-registry` command synchronizing `docs/source_registry.csv` into the
  `source_registry` table watched by QC-W05, and a GitHub Actions CI workflow
  (lint, vocabulary validation, tests, schema-snapshot sync check).

### Changed — data-collection stage (project owner directive, 2026-07-13)
- Foundation constraints 1-2 (no network for data / no factual data)
  superseded for assessed open sources; recorded in CLAUDE.md and the source
  registry. Constraints 3-7 remain fully in force.

### Added — analysis layer & humane redesign (2026-07-14)
- `analysis.py`: recording-undercount (coverage gap vs İSİG totals), rate
  context with documented denominators (deaths per 100M tonnes, press-cited),
  curated policy timeline (`data/vocabularies/policy_events.csv`), and a
  cost-of-inaction baseline (Poisson-floored interval) — all documented in
  `docs/analysis_methods.md` as STATUS: PROPOSED (open questions #17, #18);
  incident-level ML prediction explicitly rejected as indefensible.
- Dashboard redesigned as a humane public record: one-mark-one-person hero
  (976 marks + 905 outlined marks for counted-but-unrecorded deaths),
  narrative sentences from data, "on this day" remembrance, undercount
  columns and policy markers on the chart, rate comparison, and an
  "If nothing changes" card. Adaptive map (Leaflet or embedded vector);
  `build-artifact` renders the same template into a committed
  self-contained `dashboard/artifact.html`.

### Added — data-collection stage
- Implemented Wikidata/Wikipedia adapter (polite rate-limited fetching,
  immutable raw storage, mechanical vs `ai_assisted` extraction honesty) and
  `ingest-wikidata` orchestration: claims → deterministic bulk accept
  decisions under a named human reviewer → scope → publication sign-off for
  complete records only.
- First real seed: 9 incidents, 23 source documents, 84 claims; 5 records
  published (Karadon 2010, Soma 2014, Amasra 2022, Çöpler/İliç 2024, Zara
  2025); prose-extracted values wait in the mandatory review queue.
- Committed public export in `data/public/` and a static dashboard
  (`dashboard/index.html` + generated `data.js`): precision-aware Leaflet map
  (vendored library), deaths-by-year chart, table view, light/dark modes,
  pipeline-status tiles.
- Historic extension + cause coding (project owner directive, 2026-07-14):
  navbox + list-article discovery on tr.wikipedia brings per-incident records
  back to 1983 (46 published incidents, 976 recorded deaths); pre-2010
  incidents are now in scope. Mechanical cause extraction populates the
  four-axis `incident_classifications` (Wikidata P31 classes + Turkish
  incident-type phrases -> event mechanism/hazard, 67 source-backed rows).
  Death sentences with multiple numbers are ambiguity-guarded into the
  human-review queue instead of auto-published; list bullets matching an
  existing incident (province + date ±3 days) attach as corroborating claims
  instead of duplicates. İSİG Meclisi annual miner-death totals (2012-2025)
  land in `aggregate_occupational_statistics` with comparability notes and
  appear on the dashboard as a clearly-labeled context series; the dashboard
  also gains a mechanism breakdown and per-record mechanism display.
