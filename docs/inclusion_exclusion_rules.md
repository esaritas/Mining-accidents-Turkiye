# Inclusion / Exclusion Rules

Operational checklist for the current published scope. Historical records
from 1983 onward are already included; coverage is partial throughout. The
former 2010-only MVP boundary is superseded. Environmental releases have a
separate track under `environmental_scope_protocol.md` (working scope adopted
20 October 2026). The schema records the outcome in `incidents.incident_status`
(`in_scope` | `out_of_scope` | `scope_undetermined`) and the reasoning in
`incidents.scope_rationale`. Borderline cases are never silently dropped:
they are recorded as `out_of_scope` or `scope_undetermined` with rationale.

## Fatal-incident track

**Working scope reconciled with the published register on 29 October 2026.**
Open borderline-case rules remain proposals; this alignment does not establish
completeness or authorize automatic publication of new evidence.

| # | Case | Rule |
|---|------|------|
| I1 | Underground and open-pit mining of solid minerals, Türkiye, historical series from 1983 onward, ≥1 fatality | Include |
| I2 | Quarrying (stone, sand, marble, aggregate) | Include |
| I3 | Mine-site processing facilities operationally tied to extraction | Include |
| I4 | Tailings dams, heap-leach pads, mine-waste facilities | Include |
| I5 | Illegal/informal extraction operations | Include; flag `informal_or_illegal_operation` |
| I6 | Rescue-worker deaths during response to an in-scope incident | Include within the incident (open question #3) |
| I7 | Delayed deaths medically attributed to an in-scope incident | Include |

## Exclusions and routing — retain the decision and rationale

| # | Case | Rule |
|---|------|------|
| E1 | Commuting / off-site transport to or from a mine | Exclude (open question #4) |
| E2 | Oil, gas, and geothermal extraction | Exclude (solid minerals only) |
| E3 | Non-fatal incidents, near misses, occupational disease | Exclude from MVP; schema accommodates later |
| E4 | Incidents before the current historical window (1983) | Historical expansion requires an explicit scope decision; retain candidates as scope_undetermined |
| E5 | Off-site standalone processing plants with no operational tie to extraction | Exclude |
| E6 | Acute environmental releases without worker fatality | Assess in the separate environmental track; never add environmental record counts to fatality totals |

## Undetermined

Use `scope_undetermined` when sources conflict on a scope-determining fact
(e.g., whether a facility is operationally tied to extraction). A
`scope_undetermined` incident is never publishable.

## Open questions

- Register #3, #4, #5 (see [`open_questions.md`](open_questions.md)).
- Whether E5's "operational tie" test needs a bright-line definition before
  pilot review — **flagged as open**.
