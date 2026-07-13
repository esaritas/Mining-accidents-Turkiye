# CLAUDE.md — project conventions for Claude Code sessions

## Purpose (two sentences)

This project builds an evidence-based database of fatal mining and quarrying
accidents in Türkiye (2010-present), where every published value is traceable
to source documents through reviewed claims. This repository currently
contains the **foundation only**: schema, vocabularies, review machinery, and
protocols — no factual incident data, no scraping, no dashboard.

## Seven global hard constraints (override everything else)

1. **No network access for data.** Never fetch, scrape, or verify external
   URLs as part of a build. All source adapters except `adapters/manual.py`
   are stubs that raise `NotImplementedError`.
2. **No factual data.** Never insert a real incident, casualty figure, company
   name, coordinate, or source document into the database or fixtures. All
   test fixtures use clearly synthetic data prefixed `TEST-`
   (e.g., incident `TEST-2099-0001`, organization `TEST Madencilik A.Ş.`).
3. **No invented methodology presented as settled.** Editorial rules are
   written as `STATUS: PROPOSED — awaiting editorial decision` in the docs and
   registered in `docs/open_questions.md`.
4. **No silent conflict resolution.** Canonical values come only from explicit
   `claim_decisions` rows. Never resolve claim conflicts in code.
5. **No AI/OCR auto-promotion.** Claims with `extraction_method` in
   (`ai_assisted`, `ocr_assisted`) are created with
   `review_status = 'needs_review'` and cannot become canonical without a
   human reviewer decision.
6. **Immutability.** `source_documents`, `claims`, and `ingestion_runs` are
   append-only (SQLite triggers enforce this). Corrections create new rows.
7. **Respectful framing.** This project documents deaths. No gamified
   language, no sensational field names, no leaderboard-style outputs
   anywhere in code, docs, or exports.

## Evidence flow

```
source document → extracted claim → reviewer decision → canonical incident value → public export
```

An incident row is a *reviewed synthesis*, never an original source of truth.
Conflicting claims coexist permanently; `claim_decisions` records which claim
was selected and why.

## Command cheat-sheet

```
make install         # pip install -e .[dev]
make db              # create database/mining_accidents.sqlite from migrations
make import-example  # synthetic TEST- demo data into a separate staging DB
make qc              # quality checks -> data/interim/quality_report.json
make export          # public export -> data/public/ (blocked by critical QC)
make packets         # generate review packets
make test            # pytest with coverage
make lint            # ruff check + format check
```

## Working conventions

- Python >= 3.11, type hints everywhere, `ruff` for lint/format, `pytest`.
- Conventional commits (e.g. `feat(phase-1): schema and vocabularies`).
- Every module docstring states its role in the evidence flow.
- Keep functions small; no module over ~400 lines without justification.
- **Never insert real data in tests.** Synthetic `TEST-` fixtures only.
- **Never resolve claim conflicts in code.** Decisions are human acts recorded
  in `claim_decisions`.
- Ambiguities: implement the most conservative interpretation and log it in
  `docs/open_questions.md`.

## Where decisions live

Unresolved editorial/design decisions: `docs/open_questions.md`.
Field-level meaning of every column: `docs/data_dictionary.md`.
