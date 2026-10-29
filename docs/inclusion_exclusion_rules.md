# Inclusion / Exclusion Rules

Operational checklist for the current published scope. Historical records
from 1983 onward are already included; coverage is partial throughout. The
former 2010-only MVP boundary is superseded. Environmental releases have a
separate track under `environmental_scope_protocol.md` (working scope adopted
20 October 2026). The schema records the outcome in `incidents.incident_status`
(`in_scope` | `out_of_scope` | `scope_undetermined`) and the reasoning in
`incidents.scope_rationale`. Borderline cases are never silently dropped:
they are recorded as `out_of_scope` or `scope_undetermined` with rationale.

## What the register publishes today

Two kinds of record, kept apart and never combined into one count.

| Kind | Identifier | Publication threshold | Published |
|---|---|---|---|
| Fatal mining or quarrying accident | `TR-MINE-YYYY-NNNN` | date, province and a death toll, each from a recorded decision | 52 records, 1983-03-07 to 2026-10-01, every one with at least one death |
| Environmental harm at a mining site | `TR-ENV-YYYY-NNNN` | date and province; **no death toll** | 3 records, 2021 to 2024 |

Where an environmental event and a fatal accident are the same occurrence, the
deaths are counted once, in the fatal record, and the two are joined by
`related_incident_id`.

### Why 1983

1983 is where the assessed sources' coverage begins, not a judgement that
nothing earlier belongs here. The earliest published record is Armutçuk,
7 March 1983. Twenty-two of the forty-four calendar years from 1983 to 2026
hold no record at all, which is a statement about coverage and not about
safety.

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

## Not yet ruled on

Real scope questions the register has no rule for. They are listed rather than
answered, because inventing an answer and presenting it as settled is what
constraint 3 forbids.

- **Workers versus other people.** No rule distinguishes a worker from a
  contractor's employee, a visitor, or a resident killed by a mining event.
  Every published record happens to concern workers, as the sources describe
  them, but that is how the sources read and not a rule the register applied.
  Registered as open question #38.
- **Contractor and subcontractor deaths** are counted the same as the
  operator's own, because no assessed source separates them.
- **Long-latency disease** (E3) and **routine or chronic environmental harm**
  such as acid drainage, dust and groundwater depletion both await their own
  authorisation. Dust disease has a different latency, ascertainment and
  attribution from an acute accident, so folding it in would silently change
  what every published total means.

## Superseded rules, kept for the record

| # | Rule as first published | Superseded by |
|---|---|---|
| I1 | "2010→present" | Owner directive for the data-collection stage; the seed sources reach back to 1983 and the register publishes from 1983 |
| E4 | "Incidents before 2010-01-01 — exclude from MVP" | The same directive. Pre-2010 incidents are in scope and 1983-2009 records are published; E4 now governs anything before 1983 |
| E6 | "Environmental/community impacts without worker fatality — exclude from MVP" | Owner directive of 2026-10-20 that opened the environmental track |

## Open questions

- Register #3, #4, #5, #34, #38 (see [`open_questions.md`](open_questions.md)).
- Whether E5's "operational tie" test needs a bright-line definition before
  pilot review — **flagged as open**.
