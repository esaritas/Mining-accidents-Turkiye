# Inclusion / Exclusion Rules

Operational checklist for deciding whether a candidate incident is in MVP
scope. The schema records the outcome in `incidents.incident_status`
(`in_scope` | `out_of_scope` | `scope_undetermined`) and the reasoning in
`incidents.scope_rationale`. Borderline cases are never silently dropped:
they are recorded as `out_of_scope` or `scope_undetermined` with rationale.

## Included (MVP)

**STATUS: PROPOSED — awaiting editorial decision** for all rules below.

| # | Case | Rule |
|---|------|------|
| I1 | Underground and open-pit mining of solid minerals, Türkiye, 2010→present, ≥1 fatality | Include |
| I2 | Quarrying (stone, sand, marble, aggregate) | Include |
| I3 | Mine-site processing facilities operationally tied to extraction | Include |
| I4 | Tailings dams, heap-leach pads, mine-waste facilities | Include |
| I5 | Illegal/informal extraction operations | Include; flag `informal_or_illegal_operation` |
| I6 | Rescue-worker deaths during response to an in-scope incident | Include within the incident (open question #3) |
| I7 | Delayed deaths medically attributed to an in-scope incident | Include |

## Excluded (MVP) — record as `out_of_scope`, never discard

| # | Case | Rule |
|---|------|------|
| E1 | Commuting / off-site transport to or from a mine | Exclude (open question #4) |
| E2 | Oil, gas, and geothermal extraction | Exclude (solid minerals only) |
| E3 | Non-fatal incidents, near misses, occupational disease | Exclude from MVP; schema accommodates later |
| E4 | Incidents before 2010-01-01 | Exclude from MVP; schema accommodates later |
| E5 | Off-site standalone processing plants with no operational tie to extraction | Exclude |
| E6 | Environmental/community impacts without worker fatality | Exclude from MVP; schema accommodates later |

## Undetermined

Use `scope_undetermined` when sources conflict on a scope-determining fact
(e.g., whether a facility is operationally tied to extraction). A
`scope_undetermined` incident is never publishable.

## Open questions

- Register #3, #4, #5 (see [`open_questions.md`](open_questions.md)).
- Whether E5's "operational tie" test needs a bright-line definition before
  pilot review — **flagged as open**.
