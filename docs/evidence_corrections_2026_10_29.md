# Evidence corrections — 29 October 2026

Prepared by Codex as AI-assisted research and implementation, following the
project owner's request to address the evidence problems first. This record
does not represent human adjudication of new canonical claims.

## Applied corrections

- Removed the claim that every visible value exposes a source and review
  decision; the public export does not contain that complete evidence chain.
- Removed the inference that the difference or ratio between the register and
  İSİG establishes missing incidents or a coverage percentage. The old 34%
  and near-complete-disaster-coverage conclusions are explicitly withdrawn in
  the dated audit, preserving their history and explaining the correction.
- Aligned scope documentation with the existing historical series from 1983
  and the environmental working scope adopted in October 2026.
- Replaced environmental “Reached” with “Reported or threatened receiving
  environment.” Explained release versus threat versus measured contamination,
  indirect reports of official/technical findings and competing quantities.
- Clarified that environmental records do not add fatalities to linked accident
  counts; removed wording that could imply these events had no deaths.
- Exposed missing casualty status, injury-data completeness, claim review and
  monitoring queues. Unknown classification/organization fields now say they
  are unrecorded in the snapshot, not absent from the original sources.
- Added nine bilingual, dated notices beside the affected records and in an
  overview disclosure. They contain sources and remain explicitly pending human
  review. Incident downloads carry their notices; canonical numbers are unchanged.
- Made existing short source excerpts visible in incident details and added a
  computed warning when a populated critical field has no public citation.
- Removed the incorrect Kozlu “deadliest in the series” metadata and stale
  Amasra casualty count from the separate policy chronology label. Updated the
  ILO source link after checking its ratification entry. The Gazette link's
  retrieval timeout remains disclosed rather than being marked verified.

## Code defects resolved

`export._collect_sources` previously followed only `selected_claim_id`.
Manual overrides use `rationale_claim_ids`, so their supporting citations
could disappear from an otherwise eligible export. Active manual overrides
now export those supporting sources; superseded/rejected/deferred decisions
remain excluded. This repairs future exports without fabricating a citation
for a canonical decision whose database is unavailable.

The review validator checked an AI/OCR claim selected directly, but did not
apply the same check to supporting claims in an override. It now rejects
unreviewed AI/OCR support for accepted canonical decisions as well. Synthetic
regression tests cover this boundary and citation preservation.

## Research findings and unresolved adjudication

| Issue | Research outcome | Publication status |
|---|---|---|
| Amasra 2022, 42 versus 43 | TBMM's 6 April 2023 transcript reports 43 after a delayed death | Proposed dated revision; canonical decision pending |
| Yeni Çeltek 1990, 68 versus 66 | Chamber statement of 7 February 2023 supports 68 | Source disclosed; citation/decision update pending |
| Amasra 2014, 2 versus 1 | Contemporary report's 13:35 update documents the second recovery | Existing 2 supported; conflict closure pending |
| Soma–İmbat 2026 | Chamber reports collapse, five deaths and two injuries; acknowledges investigative limits | Injury/mechanism additions and corroborating source staged |
| Kozlu 1983 date | TTK chronology gives 11 April; snapshot gives 10 April | Unresolved source conflict, visibly disclosed |
| Early-1983 TTK roles | Institutional history supports concern about historical attribution | Replacement legal roles still require evidence and review |
| Three environmental records | Certainty, source directness, date excerpts and quantity qualifiers need attention | Misleading presentation fixed; underlying claims still open |

Six source metadata rows, content hashes and seven candidate claims are in
[`data/staging/evidence_2026_10_29`](../data/staging/evidence_2026_10_29/README.md).
That packet gives the exact sources, proposals and guarded staging command.

## What did not change

The 52 canonical fatal-incident records, 1,091 recorded deaths, original export
timestamp and existing canonical evidence files are unchanged.

> **Superseded later the same day.** The Amasra toll has since moved from 42 to
> 43 by a reviewer decision on the Assembly's record of 6 April 2023, so the
> register publishes 52 records and 1,092 deaths, and the pending casualty
> notice `EV-20261029-01` has retired as resolved. See open question 20 and
> `scripts/amasra_casualty_revision.py`. The site map,
site types and timeline selection/layout are preserved. New notices do not
contribute to sums, classification counts or maps.

The working SQLite database is not tracked and was unavailable. Under
`manual_review_protocol.md`, AI-assisted claims require a named human reviewer
before canonical promotion. Accordingly, no human identity, approval or source
decision was invented and no database was reconstructed from incomplete exports.

## Remaining completion requirements

Supply the original working database and have a human reviewer adjudicate the
concrete packet. Stage the evidence, append casualty observations, record
superseding decisions/classifications and rebuild exports. Reconcile or close
the corresponding notices and monitoring candidates explicitly. Obtain original
environmental reports and resolve the historical entity/date conflicts rather
than treating the new disclosure as proof those facts are settled.

Automated verification includes synthetic review/export tests, bilingual DOM
interaction and download checks, public-export checksum validation and an
artifact reproduction check. These checks establish software behavior, not
independent verification of every historical incident or a visual accessibility
certification.
