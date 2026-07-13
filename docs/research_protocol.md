# Research Protocol

Defines what this project counts, how incidents are delimited, and how
evidence becomes canonical data. Every rule below is a **proposal** until an
editorial decision is recorded; proposals are registered in
[`open_questions.md`](open_questions.md).

Evidence flow (binding on all research work):

```
source document → extracted claim → reviewer decision → canonical incident value → public export
```

---

## 1. Unit of analysis — what is one incident?

**STATUS: PROPOSED — awaiting editorial decision.**
One incident = one initiating abnormal event at one facility within one
continuous time window. Secondary events occurring during rescue operations
(e.g., a second collapse while rescuers are underground) belong to the same
incident unless editorially split.

*Rationale:* aligns with how official investigations delimit events and avoids
double-counting casualties across cascading sub-events.

*Open question (register #5):* the exact splitting rule for cascading events
during rescue operations needs an editorial decision before pilot review.

## 2. Commuting / off-site transport

**STATUS: PROPOSED — awaiting editorial decision.**
Excluded from the MVP core scope. When encountered, record the incident with
`incident_status = 'out_of_scope'` and a `scope_rationale`, so the boundary
decision remains visible and reversible.

*Open question (register #4):* confirm exclusion.

## 3. Quarrying

**STATUS: PROPOSED.** Included. Quarries (taş ocakları, kum ocakları, mermer
ocakları) are within scope as extraction of solid minerals.

## 4. Mine-site processing facilities

**STATUS: PROPOSED.** Included when operationally tied to extraction
(preparation/washing plants, crushers, on-site workshops). Off-site
standalone processing is out of scope for MVP; record as `out_of_scope`
with rationale.

## 5. Tailings, heap-leach, and waste facilities

**STATUS: PROPOSED.** Included. Failures of tailings dams, heap-leach pads,
and mine-waste facilities are mine-associated incidents in scope.

## 6. Illegal / informal operations

**STATUS: PROPOSED.** Included, flagged via the contributing condition
`informal_or_illegal_operation`. Inclusion documents the phenomenon; the flag
keeps it analytically separable. See the privacy protocol for coordinate
restraint around small informal operations.

## 7. Rescue-worker deaths

**STATUS: PROPOSED — awaiting editorial decision.**
Counted within the originating incident's totals; distinguishable later in a
future person-level model.

*Open question (register #3):* whether MVP counting should separate
rescue-worker deaths from the incident total.

## 8. Delayed deaths

**STATUS: PROPOSED.** Counted if medically attributed to the incident.
Incident date ≠ death date; both are representable — `incidents` stores the
incident window, casualty timing lives in observations/claims.

## 9. Missing persons

**STATUS: PROPOSED.** Tracked separately in `missing_*` fields. Conversion
missing → fatality happens only via a **new** `casualty_observations` row,
never by editing an existing row.

## 10. Incident date vs date of death

Both supported (see §8). `incidents.incident_start_datetime` /
`incident_end_datetime` + `date_precision` describe the incident window.

## 11. Casualty revision rules

**Binding rule (schema-enforced):** never overwrite casualty figures. Each
revision appends a `casualty_observations` row. Exactly one row per incident
has `is_current_canonical = 1`, set only via a recorded claim decision.

## 12. Duplicate identification

**STATUS: PROPOSED.** Blocking key: same province + incident date within
±3 days + fuzzy facility-name match (normalized similarity ≥ 0.75; thresholds
in `config/project.yml`). Candidates are flagged by quality checks, reviewed
by a human, and merged only via `incident_merge_log`. Old public IDs are
preserved as redirects in exports — a public ID is never reused.

## 13. Source-quality tiers

See [`source_assessment_protocol.md`](source_assessment_protocol.md) and
`docs/source_registry.csv`. Proposed tiers: 1 = official/parliamentary,
2 = professional-chamber/civil-society/academic, 3 = news media. SGK
aggregate statistics are Tier 1 for **aggregates only**, never incident-level
evidence.

## 14. Publication eligibility

See [`editorial_and_legal_protocol.md`](editorial_and_legal_protocol.md) §5
and the enforced rules in `src/mining_accidents/export.py`. Summary: reviewed
identity, decided date/province/fatalities, source-backed classification and
role rows, stated coordinate precision, no undisclosed deferred conflicts on
publication-critical fields, and an editorial `publishable` sign-off.

---

## Open questions arising from this protocol

- Register #3 — rescue-worker death counting.
- Register #4 — commuting exclusion confirmation.
- Register #5 — incident-splitting rule for cascading events.
