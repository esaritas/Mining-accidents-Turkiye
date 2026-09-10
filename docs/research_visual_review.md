# Research and visual review

## Follow-up: mining landscape and narrative timeline

The sites were not deleted from the data, but the previous redesign made them
hard to discover: accidents-only default, small site marks, no commodity key,
and omission of contextual features. The follow-up restores Both by default,
draws site marks above death circles, and adds commodity colours, type shapes,
an explicit site-type filter, and counts for point/grouped/unmapped sites.
All contextual features are retained and distinguished from mines/quarries.
No missing coordinates or operating status are invented. Identical coordinates
share a marker rather than being jittered into fictitious locations.

The timeline now leads with chronological chapters, numbered incident and
policy annotations, source-linked event cards, and selectable years containing
every published incident. A year can explicitly focus the map; otherwise the
timeline retains the full chronology independently of map filters. The separate
İSİG series remains available as expandable context, not as a substitute story.
Current toll status is retained in cards and year details. Milestone selection
is **STATUS: PROPOSED — awaiting editorial decision** (open question #20).

No canonical evidence or death counts changed in this follow-up.

## Earlier research-integrity changes

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
