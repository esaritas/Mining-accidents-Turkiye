# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
semantic versioning once the project reaches a first release.

## [Unreleased]

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
