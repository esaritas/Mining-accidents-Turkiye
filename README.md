# Turkey Mining & Quarrying Accidents Database — foundation

Evidence-management foundation for a database of **fatal mining, quarrying,
and mine-associated processing/waste facility accidents in Türkiye
(2010-present)**.

> **What this repository is:** schema, controlled vocabularies, claim/decision
> review machinery, quality checks, and public-export tooling.
>
> **What it is not (yet):** it contains **no factual incident data**, no
> scrapers, and no dashboard. All fixtures are synthetic (`TEST-` prefixed).
> See [`CLAUDE.md`](CLAUDE.md) for the seven hard constraints that govern all
> work here, and [`docs/open_questions.md`](docs/open_questions.md) for
> unresolved editorial decisions.

## Evidence flow (core principle)

```
source document → extracted claim → reviewer decision → canonical incident value → public export
```

An incident row is a *reviewed synthesis*, never an original source of truth.
Every publicly displayed important value (date, province, fatalities, causes,
company roles, coordinates) must trace to at least one claim selected through
a recorded reviewer decision. Conflicting claims coexist permanently; the
decision layer (`claim_decisions`) records what was selected and why.

## Setup

```bash
make install   # pip install -e .[dev]  (Python >= 3.11)
make db        # create database/mining_accidents.sqlite from migrations
make test      # pytest with coverage
make lint      # ruff check + format check
```

## Command reference

| Command | What it does |
|---|---|
| `make db` | Apply migrations; regenerate `database/schema.sql` snapshot |
| `make import-example` | Import clearly-labeled synthetic `TEST-` demo data into a separate staging DB |
| `make qc` | Run quality checks → `data/interim/quality_report.json` (non-zero exit on critical) |
| `make export` | Build public export → `data/public/` (aborted by any critical QC finding) |
| `make packets` | Generate review packets for incidents with claims |
| `make test` / `make lint` / `make clean` | Test suite / lint / cleanup |

The `mining-accidents` CLI (Typer) exposes the same operations with options —
`python -m mining_accidents.cli --help`. Thin wrappers live in `scripts/`.

## Architecture

```
                    ┌─────────────────────────────────────────────────────┐
                    │                     evidence layer (append-only)    │
 manual CSV/YAML ──▶│  source_documents ──▶ claims          ingestion_runs│
 (adapters/manual)  └───────────┬─────────────┬────────────────────────---┘
 stub adapters:                 │             │  human review (manual_review_protocol)
 sgk/tmmob/tbmm/isig            │             ▼
 (NotImplementedError           │   ┌──────────────────┐   review_log (append-only)
  until source assessment)      │   │  claim_decisions │──▶ audit trail
                                │   └────────┬─────────┘
                                │            │ promotion by code only (review.py)
                                ▼            ▼
                    ┌─────────────────────────────────────────────┐
                    │ canonical layer: incidents,                 │
                    │ casualty_observations (single canonical),   │
                    │ classifications (4 axes), organization roles│
                    └───────────────┬─────────────────────────────┘
                                    │ quality.py (critical findings block)
                                    ▼
                    ┌─────────────────────────────────────────────┐
                    │ export.py — 7-rule publication threshold    │
                    │ data/public/ + datapackage + manifest       │
                    └─────────────────────────────────────────────┘
```

Key modules (`src/mining_accidents/`): `database.py` (connections,
checksummed migrations, schema snapshot) · `models.py` (Pydantic v2 per
table) · `validators.py` (+ Pandera file-boundary schemas) ·
`normalization.py` (Turkish-aware casefolding — never plain `.lower()`) ·
`vocabularies.py` (versioned CSV vocabularies as source of truth) ·
`entity_resolution.py` (duplicate *candidates*, never auto-merge) ·
`geography.py` (precision semantics, bbox heuristic) · `provenance.py`
(sha256, run records) · `review.py` (decisions → canonical) · `quality.py` ·
`export.py` · `packets.py` · `cli.py`.

## Data directories

`data/raw/` immutable raw evidence (never committed) · `data/staging/` import
inputs · `data/interim/` regenerable reports · `data/reviewed/` completed
review packets · `data/public/` export target · `data/vocabularies/`
controlled vocabularies · `data/review_packets/` generated packets + twelve
empty `PILOT-*` slot templates.

## Governance

- **Immutability:** evidence tables are append-only (SQLite triggers);
  corrections are new rows; migrations are checksummed and never edited.
- **No silent conflict resolution:** canonical values exist only through
  recorded reviewer decisions with rationales.
- **AI/OCR restraint:** machine-assisted claims enter as `needs_review` and
  cannot become canonical without human review (trigger + model + QC).
- **Privacy:** no victim names anywhere; excerpts redacted to initials;
  coordinate restraint for informal operations
  ([`docs/privacy_and_persons_protocol.md`](docs/privacy_and_persons_protocol.md)).
- **Respectful framing:** no leaderboards, no gamification, anywhere.

## Next stage (not in this build)

1. **Assess the TBMM parliamentary research reports source first**
   (registry key `tbmm`): Tier-1 public record, long-form, low legal risk,
   rich in investigation findings and recommendations. Confirm access terms
   per [`docs/source_assessment_protocol.md`](docs/source_assessment_protocol.md)
   before writing any fetch code.
2. Resolve open questions #1 (licence) and #9 (second reviewer) before any
   real data enters the pipeline.
3. Populate the twelve pilot review packets once source documents exist.

## Licence and citation

The licence is deliberately undecided (open question #1) — see
[`LICENSE`](LICENSE). Cite via [`CITATION.cff`](CITATION.cff).
