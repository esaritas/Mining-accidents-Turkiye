# Research and visual review

Implemented against the existing 2026-07-25 export; no new source review or
canonical death-count corrections are claimed. The working database is absent.

- Verify manifest hashes and incident CSV/JSON parity before rebuilding data.
  New exports also hash incidents.json. Snapshot refresh rejects mixed timestamps.
- Carry field-level citation metadata into record details. Show disputed and
  unstated toll status explicitly; do not silently treat an unknown status as final.
- Restrict annual context to the named source, full calendar years, deaths unit,
  and unclassified observations. Reject ambiguous duplicate years.
- Present incident and sector totals in separate aligned panels. Their different
  populations cannot support subtraction into a count of missing people.
- Show province totals with proportional circle areas. Only facility-level
  precision permits individual point placement; coarse locations remain grouped.
  Province symbols represent totals, not accident coordinates or risk rates.
- Replace the long animated introduction with a short evidence-led narrative,
  source limitations, snapshot date, and location/completeness indicators.
- Preserve historical rate observations as a source table, not a country ranking.
  Missing years remain missing; separate observations are not invented ranges.
- Keep Turkish/English, filterable downloads, keyboard record access, and an
  accessible annual data table. Browser checks cover desktop and mobile layout.

Remaining research priorities: primary-source corroboration of disputed tolls;
reviewed location precision; source-population definitions; missing-record
discovery under the established source-assessment workflow. These require human
editorial decisions, not automatic promotion of extracted claims.

Rebuild presentation without the private database:

```sh
mining-accidents refresh-research-data
mining-accidents build-artifact --from-data-js dashboard/data.js
```
