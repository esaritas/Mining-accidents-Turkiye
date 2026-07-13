# Dashboard — public data contract (no dashboard code in this build)

This directory intentionally contains **no code**. It defines the contract
any future dashboard must honor when consuming `data/public/`.

## Input files

`incidents.csv` / `incidents.json`, `incident_classifications.csv`,
`incident_organization_roles.csv`, `sources.csv`,
`merged_id_redirects.csv`, `datapackage.json`, `export_manifest.json`.
Verify file sha256 values against `export_manifest.json` before rendering.

## Precision semantics (binding)

- Every coordinate pair ships with `coordinate_precision`
  (`exact_verified | facility_approximate | settlement | district_centroid |
  province_centroid | unknown`).
- **A point with precision worse than `facility_approximate` must never be
  rendered as an exact pin.** Use area shading, jittered/apologetic markers
  with explicit uncertainty affordances, or centroid symbols clearly labeled
  as centroids.
- `location_uncertainty_m`, where present, should drive marker radius.

## Uncertainty display duties (binding)

- Casualty figures carry `casualty_status`
  (`initial | revised | final | disputed`); display the status, and never
  present `initial`/`disputed` figures as settled.
- Every cause/factor/company-role row carries an `assertion_status`; an
  `alleged` value must be visibly marked as alleged, never rendered as
  established fact (presumption of innocence — see
  `docs/editorial_and_legal_protocol.md`).
- Records may appear in `disclosed_conflicts` structures; conflicts are shown,
  not averaged away.
- `merged_id_redirects.csv` must resolve old public IDs to surviving records
  (permalinks never break).

## Accessibility requirements (binding)

- WCAG 2.1 AA minimum: color contrast, keyboard navigation, screen-reader
  labels for all charts/maps, text alternatives for every visual encoding.
- Never encode meaning by color alone.

## Non-sensational design principles (binding)

- This data documents deaths. No leaderboards, no rankings framed as
  competition, no gamified counters, no animation that trivializes loss.
- Aggregations are documentation of harm; framing must be sober and
  respectful, and always link to sources and methodology.
