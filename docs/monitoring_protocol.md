# Monitoring Protocol

**STATUS: PROPOSED — awaiting editorial decision (register #35).**

How the register is kept current. The rule the whole project rests on does not
bend for recency: nothing becomes a published value without a reviewer's
decision on a claim quoted from a source document. So the monthly check finds
and prepares; a human decides.

## 1. Two layers, because one of them cannot be automated

**The sweep** runs every month in `.github/workflows/monthly-check.yml`, as
deterministic Python with no model involved (`make check`, or
`mining-accidents monthly-check`). It reads the sources whose registry
assessment permits automated collection, compares what they state against the
committed public export, and writes a report. It opens no database of record:
the ingest writes into a throwaway database outside the checkout, with no
reviewer, so it creates evidence rows and no decisions. It touches nothing under
`dashboard/`, so it never triggers a deployment.

**The review pass** is a human-directed step. It covers what the sweep cannot:
news discovery, the chamber bulletins, the company operating the mine on the
day, and environmental effects. Press reporting is retrieved article by article
because that is how the `news` registry entry is assessed, and crawling it would
contradict that assessment. Each article is fetched once, hashed, and its quote
machine-checked against the retrieved text before any claim is written, as
`scripts/incident_operators.py` does.

## 2. What is swept, and how often

| Source | Standing | Cadence | How |
|---|---|---|---|
| Wikidata | assessed, CC0, API permitted | monthly | SPARQL, in the workflow |
| Wikipedia (tr/en, incl. the list article) | assessed, CC BY-SA, API permitted | monthly | parse API, in the workflow |
| İSİG Meclisi reports | assessed 2026-10-26, reuse with attribution | monthly | report index, in the workflow; **aggregate only** |
| News (the outlets already cited) | assessed, individual retrieval only | monthly | search, then one fetch per article, in review |
| TMMOB Maden Mühendisleri Odası | assessed 2026-10-16 | monthly | new bulletins, each PDF fetched on its own, in review |
| Official statements, TBMM | `TO_ASSESS` | not yet | assessment first; adapters stay stubs |
| GEM wiki | assessed 2026-10-15 | quarterly | site layer, not accidents |
| SGK, TÜİK, TKİ | `TO_ASSESS` | annual | denominators only, never incident level |
| MAPEG | no open bulk registry | blocked | open question #19 |

## 3. What the İSİG reports can and cannot give

The Assembly publishes monthly: a month total with breakdowns by branch of work
("Madencilik işkolunda 7 işçi"), by cause, by age band and by province. It
publishes **no per-incident rows**, and its province breakdown spans every
branch together. So the reports are an aggregate source, like SGK: they feed
`aggregate_occupational_statistics` and never incidents, claims or decisions.

What they are worth is still considerable. They give a monthly denominator to
measure this register's coverage against, they are the only swept source with a
genuine monthly rhythm, and a month with an unusual mining figure is a lead for
the review pass to follow in the press.

Two handling rules are enforced in `adapters/isig.py`:

- Every report ends with the names of the dead. Parsing stops at the memorial
  sentence, so no name reaches a figure, an excerpt or an export. The page as
  retrieved stays in `data/raw/` alone, which is never committed and never
  exported (`privacy_and_persons_protocol.md` §2).
- The Assembly states its counts as lower bounds, compiled from the press and
  from workplace networks, and counts all work deaths from all causes. The
  comparability note travels with every row, and the two series are never added
  or subtracted.

## 4. How a candidate is classified

A stated event is compared with the published export on the register's own
blocking key, province plus date, at **the precision the source states**: a
source saying "August 2004" has not contradicted a register holding 9 August
2004, so matching it day to day would invent a disagreement. Both kinds of
published record are compared against, or every environmental record would read
as a missing accident.

| Reason | Meaning |
|---|---|
| `absent_from_register` | The sources state an event with a date and the export holds nothing matching it. |
| `toll_differs` | Matched to a published record, but the stated death toll is not among the published figures. |
| `date_differs` | A record of the same name exists and the stated date disagrees with it. |
| `undated_source_entry` | No date and no name match, so the check can neither call it missing nor confirm it is held (open question #25). |

## 5. Settled disagreements stay visible

`docs/monitoring_known_disagreements.csv` declares disagreements already on the
record, each with how it stands (`decided`, or `disclosed` and still open), when
it was recorded, and the open question that carries it. A declared row keeps a
settled matter out of the review queue without hiding it: the report still
prints it under "Already known". This is not conflict resolution in code. The
conflict remains recorded, the decision that settled it is cited, and nothing is
promoted or demoted by the check.

## 6. What reaches the page

`monitor.summary()` puts the check's own facts in the dashboard payload: when
the sources were last swept, which ones, the newest published record, and how
many candidates are waiting. The waiting count is recomputed against the current
export at build time, so a candidate that has since been published stops being
counted without the check having to run again.

A candidate has no reviewed standing, so it is never named, dated or given a
death toll on the page. Only the count appears.

## 7. Limits stated on the page

- A month in which the sweep finds nothing means the swept sources published
  nothing new, not that nothing happened.
- The sweep reports and never publishes.
- Incident-level recency rests on press reporting, which is followed up by hand.

## Open questions

- Register #35 — this protocol, and whether the monthly cadence, the declared
  disagreements file and the waiting count shown on the page are the right
  shape.
- Register #23 — recency. Partly answered: the İSİG series is now taken from the
  publisher and is monthly, but it is aggregate, so it measures the gap rather
  than filling it.
- Whether the direct İSİG monthly series should replace the Wikipedia-transcribed
  annual series behind the published coverage chart. It does not today: that
  series is an explicit editorial selection, and `analysis.isig_aggregates()`
  excludes the monthly rows by institution and by classification.
