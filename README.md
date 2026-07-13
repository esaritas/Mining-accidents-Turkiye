# Turkey Mining & Quarrying Accidents Database — foundation

Evidence-management foundation for a database of **fatal mining, quarrying,
and mine-associated processing/waste facility accidents in Türkiye
(2010-present)**.

> **What this repository is:** schema, controlled vocabularies, claim/decision
> review machinery, quality checks, and public-export tooling.
>
> **What it is not (yet):** it contains **no factual incident data**, no
> scrapers, and no dashboard. All fixtures are synthetic (`TEST-` prefixed).

See [`CLAUDE.md`](CLAUDE.md) for the project's hard constraints and
[`docs/open_questions.md`](docs/open_questions.md) for unresolved editorial
decisions. A full setup and architecture guide is added in the final build
phase.

## Quick start

```bash
make install   # install package + dev tools
make db        # create the SQLite database from migrations
make test      # run the test suite
```

## Evidence flow (core principle)

```
source document → extracted claim → reviewer decision → canonical incident value → public export
```

Every publicly displayed important value (date, province, fatalities, causes,
company roles, coordinates) must be traceable to at least one claim selected
through a recorded reviewer decision. Conflicting claims coexist permanently.
