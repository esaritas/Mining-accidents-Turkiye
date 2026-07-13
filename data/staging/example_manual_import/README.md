# Synthetic demonstration import files

**Everything in this directory is fabricated (`TEST-` prefixed) and exists
only to demonstrate the manual import format.** No real incidents, sources,
organizations, or figures appear here — inserting real data requires the
protocols in `docs/` to be followed.

Usage: `make import-example` imports these files into a separate staging
database (`database/staging_example.sqlite`).

The three fatality claims deliberately conflict (2 vs 3 vs 4) to demonstrate
that conflicting claims coexist until a reviewer decision selects one, and
the `ai_assisted` claim demonstrates the forced `needs_review` status.
