# Analysis Methods

Methods behind the derived findings shown on the dashboard
(`src/mining_accidents/analysis.py`). **Every method here is
`STATUS: PROPOSED — awaiting editorial decision`** (open questions #17, #18).
None is a causal claim; raw counts are never labeled "risk"; rates appear
only with a documented exposure denominator.

## 1. Parallel annual context (no inferred coverage gap)

For each year in the İSİG Meclisi series (2012–), compare the sector-wide
miner work-death total against deaths in this register's published incident
records. **These are different measures** — İSİG counts all miner work
deaths from all causes; the register counts deaths in publicly recorded,
reviewed incidents. Their difference is neither an error estimate nor a count
of deaths missing from this register. The dashboard now shows separate aligned
panels, without subtraction or capping. Missing observations are not zeros.
The legacy `coverage_gap()` helper is retained for compatibility but is not
published in the dashboard payload or used for the visual narrative.

*Why not incident-level ML/prediction:* the register currently holds ~50
notability-biased records; any model trained on it would predict newsworthiness,
not danger. Rejected on methodological and ethical grounds.

## 2. Rate context (documented denominators only)

Deaths per 100 million tonnes of coal produced, as cited (with references)
in the retrieved source text: Türkiye 710 (2000) and 722 (2008); China 127
(2008) and 37 (2013); United States 1–6 (year unspecified in source).
Extracted mechanically, stored in `aggregate_occupational_statistics` with
the citing document, denominator, and comparability notes (methodologies
differ across countries; indicative only). A proper Türkiye time series
requires assessing TÜİK/TKİ production statistics — registered as
`TO_ASSESS` (open question #18).

## 3. Policy timeline

Curated public-record events (`data/vocabularies/policy_events.csv`): major
disasters in the register, Law No. 6552 (post-Soma omnibus amendments,
Official Gazette 2014-09-11), and the ratification of ILO Convention C176
(2015; in force for Türkiye 2016). Shown as **descriptive markers** on the
time series. The chart makes no before/after causal claim; readers can see
what the series did around each event and draw their own questions.

## 4. Legacy continuation calculation (not displayed)

`projection()` takes the mean of the most recent İSİG years (default 8) and
a ~90% interval whose dispersion is never narrower than Poisson
(`sd = sqrt(max(sample variance, mean))`). It answers exactly one question:
*if nothing changes, roughly how many miners should Türkiye expect to lose
next year?* It is a naive continuation, not a forecast model and not fate —
displayed with the sentence that every one of these deaths is preventable.
Not suitable for any operational decision. This legacy helper is not shown on
the redesigned dashboard; publication remains subject to editorial review.

## 5. Documented-hazard matrix (STATUS: PROPOSED)

`analysis.hazard_matrix()` reads **only the public export**, so anyone holding
`data/public/` can rebuild it. It produces two tables.

**Mechanism against severity.** Rows are the reported event mechanism
(`project_event_mechanism` classifications; the `project_hazard` system is a
different axis and is never mixed in). Columns are the deaths recorded in a
single incident, in four bands: 1, 2-9, 10-49, 50 or more. A cell holds the
number of records. Bands are the breaks in this record (one death; a small
group; a shift; a national disaster), not a severity scale imported from
another framework; open question #29 asks whether to adopt a published scale
instead.

**Mechanism against place.** Rows are provinces, ordered by documented deaths,
with the number of mining sites the register currently documents in the same
province beside them. Sites come from open sources only, so the two numbers
are not proportional and must never be read as a rate.

Rules this method follows:

- **Both axes are counts of what is documented here.** Neither is a
  probability, a hazard rating, or a safety assessment of a site, a company or
  a province. The matrix has the shape of a risk matrix because frequency
  against consequence is the useful shape; it is a record, not a forecast.
- **A record appears in every mechanism row its sources document.** Kozlu 1992
  is an explosion, a fire and a collapse. Rows therefore sum to more than the
  number of records, and shares of deaths sum to more than 100%. The caption
  on the panel states this.
- **Records with no coded mechanism are a visible row**, labelled as a coding
  gap and always sorted last, never folded into "other".
- **An empty cell means nothing of that kind is documented here**, which is a
  statement about this register and not about the world. 30 documented sites
  sit in 21 provinces with no accident record at all; the panel prints that
  number next to the table.
- **No mechanism is attributed to a site.** Only one published record is linked
  to a facility, so a per-site hazard profile would have to be inferred from
  the commodity or the method. That inference is not made.
- Mechanisms describe the reported event, never a root cause
  (`cause_coding_protocol.md`).

## 6. Organizations at the time of the incident

`incident_organization_roles` rows carry `valid_at_incident_date = 1` and the
id of the claim that supports them. Each is a statement by the cited source
about who held or ran the mine on the day, with the quoted excerpt on the
claim. They are **not findings of responsibility**: courts decide that, this
register does not, and no individual is ever named. Where a source separates
the licence holder, the operator and a subcontractor, each is recorded under
its own role, because that distinction is the substance of the question.
Coverage is only as wide as the fetched documents: an incident whose sources
say "a private operation" keeps no role at all rather than one inferred from
whoever runs the site today.

## Open questions

- #17, projection methodology (basis window, interval choice, whether to
  show it at all) needs an editorial decision.
- #18, TÜİK/TKİ sourcing for a real deaths-per-production series.
- #29, severity bands and the whole documented-hazard matrix need an
  editorial decision: whether the bands stay as the register's own breaks or
  adopt a published severity scale, and whether the province table belongs
  beside a partial site layer at all.
- #30, licence holders are largely unavailable from open sources; MAPEG
  holds the register and does not publish it.
