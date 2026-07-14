# Turkey Mining & Quarrying Accidents Database — foundation build.
# All targets are thin wrappers over the Typer CLI (src/mining_accidents/cli.py).

PYTHON ?= python3
DB_PATH ?= database/mining_accidents.sqlite
EXAMPLE_DB ?= database/staging_example.sqlite

.PHONY: install db import-example ingest packets qc export dashboard test lint clean

install:
	$(PYTHON) -m pip install -e ".[dev]"

db:
	$(PYTHON) -m mining_accidents.cli create-db --db-path $(DB_PATH)

# Imports clearly-labeled synthetic demonstration data (TEST- prefixed) into a
# separate staging database. Never mixes with any real database.
import-example:
	$(PYTHON) -m mining_accidents.cli create-db --db-path $(EXAMPLE_DB)
	$(PYTHON) -m mining_accidents.cli import-manual \
		--db-path $(EXAMPLE_DB) \
		--documents data/staging/example_manual_import/source_documents.csv \
		--claims data/staging/example_manual_import/claims.csv

packets:
	$(PYTHON) -m mining_accidents.cli packets --db-path $(DB_PATH)

qc:
	$(PYTHON) -m mining_accidents.cli qc --db-path $(DB_PATH)

export:
	$(PYTHON) -m mining_accidents.cli export --db-path $(DB_PATH)

# Fetch the Wikidata/Wikipedia seed through the evidence pipeline.
# REVIEWER identifies the human authorizing the bulk decisions.
ingest:
	$(PYTHON) -m mining_accidents.cli ingest-wikidata --db-path $(DB_PATH) \
		$(if $(REVIEWER),--reviewer "$(REVIEWER)",)

dashboard:
	$(PYTHON) -m mining_accidents.cli build-dashboard --db-path $(DB_PATH)

test:
	$(PYTHON) -m pytest --cov=mining_accidents --cov-report=term-missing

lint:
	ruff check src tests scripts
	ruff format --check src tests scripts

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
