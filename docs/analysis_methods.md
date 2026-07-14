# Analysis Methods

Methods behind the derived findings shown on the dashboard
(`src/mining_accidents/analysis.py`). **Every method here is
`STATUS: PROPOSED — awaiting editorial decision`** (open questions #17, #18).
None is a causal claim; raw counts are never labeled "risk"; rates appear
only with a documented exposure denominator.

## 1. Recording undercount (coverage gap)

For each year in the İSİG Meclisi series (2012–), compare the sector-wide
miner work-death total against deaths in this register's published incident
records. **These are different measures** — İSİG counts all miner work
deaths from all causes; the register counts deaths in publicly recorded,
reviewed incidents — so the gap is not an error estimate: it is the loss
that never became a publicly recorded incident. Register deaths are capped
at the İSİG total per year for the aggregate coverage figure (an incident's
deaths can span reporting conventions). The caveat text ships with the data
and must be displayed with it.

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

## 4. Cost-of-inaction baseline (the only forward-looking figure)

`projection()` takes the mean of the most recent İSİG years (default 8) and
a ~90% interval whose dispersion is never narrower than Poisson
(`sd = sqrt(max(sample variance, mean))`). It answers exactly one question:
*if nothing changes, roughly how many miners should Türkiye expect to lose
next year?* It is a naive continuation, not a forecast model and not fate —
displayed with the sentence that every one of these deaths is preventable.
Not suitable for any operational decision.

## Open questions

- #17 — projection methodology (basis window, interval choice, whether to
  show it at all) needs an editorial decision.
- #18 — TÜİK/TKİ sourcing for a real deaths-per-production series.
