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
