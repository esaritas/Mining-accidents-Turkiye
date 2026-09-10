# Turkey Mining & Quarrying Accidents Database — foundation build.
# All targets are thin wrappers over the Typer CLI (src/mining_accidents/cli.py).

PYTHON ?= python3
DB_PATH ?= database/mining_accidents.sqlite
EXAMPLE_DB ?= database/staging_example.sqlite

.PHONY: install db import-example ingest ingest-sites packets qc export dashboard artifact test test-dashboard lint clean

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

# Fetch Wikidata mining-site items into the facilities context registry.
ingest-sites:
	$(PYTHON) -m mining_accidents.cli ingest-sites --db-path $(DB_PATH) \
		$(if $(REVIEWER),--reviewer "$(REVIEWER)",)

dashboard:
	$(PYTHON) -m mining_accidents.cli build-dashboard --db-path $(DB_PATH)
	$(PYTHON) -m mining_accidents.cli build-artifact --db-path $(DB_PATH)

# Template-only build: explicitly reuse the committed public payload, no DB needed.
artifact:
	$(PYTHON) -m mining_accidents.cli build-artifact --from-data-js dashboard/data.js

test-dashboard:
	npm ci --ignore-scripts
	npm test

test:
	$(PYTHON) -m pytest --cov=mining_accidents --cov-report=term-missing

lint:
	ruff check src tests scripts
	ruff format --check src tests scripts

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
