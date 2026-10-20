# Environmental harm: scope protocol

**STATUS: PROPOSED — awaiting editorial decision.** Registered in
`docs/open_questions.md` #34. Adopted as working scope on the project owner's
instruction of 2026-10-20; every rule below may change on review.

## Why this exists

Until 2026-10-20 the register documented fatal accidents only, and said so
nowhere. Two consequences, both found by the quality audit of the same date:

- The İliç record existed because nine people died. That the event was a
  cyanide heap-leach failure whose material reached a stream in the Euphrates
  basin was recorded as an event mechanism and nothing else.
- The Şebinkarahisar tailings-dam collapse of 18 November 2021 was held out of
  scope with the rationale "no reported fatalities", so more than 4,500 tonnes
  of chemical waste reaching a reservoir appeared nowhere.

A reader could not tell whether the absence of environmental incidents was a
scope decision or a gap. It was a scope decision, and it was undocumented.

## What is in scope

An **environmental incident** is an event at a mining, quarrying or ore
processing site where an assessed source documents either:

1. material leaving the containment built to hold it (a tailings dam, a
   leach pad, a pond, a waste heap, a pipeline), or
2. material reaching ground, water or air outside the site boundary.

Admitted mechanisms are the `environmental_mechanisms` vocabulary: tailings
dam failure, heap leach failure, chemical release, waste rock slide, water
discharge, dust or air release, subsidence.

## What is out of scope, deliberately

- **Fines, prosecutions, licence cancellations framed as sanctions, and
  anything a source frames as fault.** This register documents what happened,
  not who should answer for it (hard constraint 7). Where a ministry halted
  production, that is recorded as a documented consequence of the event
  (`production_suspension`), not as a penalty, and the effect carries the
  status of the source that states it.
- **Routine permitted discharge and ordinary operation.** An EIA (ÇED)
  decision, a capacity increase or an objection to one is not an incident.
- **Harm asserted without an event.** A claim that a site is damaging an area
  over time, with no documented release, has no date and no containment
  failure, and does not belong in an incident register.
- **Climate and land-use effects of mining in general.** Out of scope at any
  foreseeable stage of this project.

## How a record is built

Identically to a fatal accident, through the same pipeline: source document ->
claim -> reviewer decision -> canonical value. The differences are three.

1. **Its own identifier series, `TR-ENV-YYYY-NNNN`**, so an identifier never
   reads as the other kind of record.
2. **Its own publication threshold.** `ENVIRONMENTAL_CRITICAL_FIELDS` is the
   date and the province. There is no death toll to decide; a fatality count
   is not a critical field for this kind and is normally absent.
3. **Its own effects table.** `environmental_effects` holds what the sources
   record: material released with its quantity and unit where stated, what the
   release reached, the structure that failed, area or length affected, a
   water-quality finding, wildlife mortality. Each effect row cites one claim
   and carries its own assertion status.

An environmental record is **never added to a death toll**, and
`incidents.csv` stays the fatal-accident register. One real event can produce
both kinds of record: İliç 2024 is `TR-MINE-2024-0001` (nine deaths) and
`TR-ENV-2024-0001` (heap leach failure), joined by `related_incident_id`,
because the toll and the release are asserted by different sources and
reviewed separately.

## Quantities and disagreement

A quantity is recorded as the source states it, with its unit. Where sources
disagree, **both figures are recorded**, each with the assertion status its
source carries, and neither is selected. The Çöpler 2022 leak is the worked
example: 20 m³ as the operator stated it (`reported`) and 210 m³ as a lawyer
cited an expert report (`technical_finding`), side by side in
`environmental_effects.csv`. This register does not pick between them, and the
page shows both.

## Coverage, stated plainly

Three records at adoption, from open sources only, all 2021 or later. This is
far thinner than the fatal-accident register and is not a sample of anything.
The Ayvalık waste-heap collapse of December 2021 is well reported and is
**deliberately absent**: no source found states its date, and a date is a
publication-critical field, so it waits for one rather than being guessed.

## Open to editorial decision

- Whether regulatory penalties should be recorded as a separate, clearly
  labelled dimension rather than excluded (today they are excluded).
- Whether a severity scale for environmental incidents is wanted at all. None
  is proposed: the effects are heterogeneous (tonnes, cubic metres, a named
  stream) and any single ranking would be invented.
- Whether historic incidents before 2021 should be sought, and from which
  sources. Çevre ve Şehircilik Bakanlığı records, TMMOB chamber reports and
  court-appointed expert (bilirkişi) reports are the candidates.
