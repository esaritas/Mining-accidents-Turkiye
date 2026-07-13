# Cause Coding Protocol

How incident circumstances are classified. Four **separated axes** — never a
single generic "cause" field. Controlled vocabularies (versioned CSVs in
`data/vocabularies/`) supply the only permitted codes.

## 1. The four axes

1. **Hazard** (`hazards.csv`) — the energy or condition present
   (e.g., `methane`, `unstable_ground`, `water_ingress`).
2. **Event mechanism** (`event_mechanisms.csv`) — the abnormal event
   (e.g., `gas_explosion`, `roof_or_ground_collapse`, `flooding_or_inrush`).
3. **Mode of harm** (`modes_of_harm.csv`) — how people were harmed
   (e.g., `poisoning_or_asphyxiation`, `crushing`, `drowning`).
4. **Contributing condition** (`contributing_conditions.csv`) — systemic
   factors, coded **only when source-backed**
   (e.g., `ventilation`, `ground_support`, `informal_or_illegal_operation`).

## 2. Binding rules

- **An event mechanism is not a root cause and not a statement of legal
  responsibility.** Nothing in this classification asserts fault, negligence,
  or liability by any person or organization.
- Every classification row requires `source_claim_id`, `assertion_status`,
  and `review_status`. Rows in the four `project_*` systems cannot reach
  `review_status = 'reviewed'` without a non-null `source_claim_id`
  (schema-adjacent rule enforced by validators).
- Multiple values per axis per incident are allowed (e.g., `gas_explosion`
  followed by `fire`).
- Contributing conditions are recorded only when a source explicitly supports
  them — never inferred by the project.
- `unknown` is a legitimate, honest code on any axis; `other` requires a
  note explaining what it stands for.

## 3. External classification mappings

**STATUS: PROPOSED — awaiting editorial decision.**
Map to ILO/Eurostat ESAW concepts where a defensible mapping exists, via
`incident_classifications` rows with `classification_system = 'ESAW'` (or
`ICSE`, `NACE`). Turkey-specific project labels remain **primary**; external
codes are secondary annotations. Mapping depth for MVP is open question #8.

## 4. Coding workflow

1. Extract source statements about circumstances as claims
   (`claim_subject_type = 'classification'`).
2. A coder proposes axis codes referencing the supporting claim.
3. A reviewer confirms (`review_status = 'reviewed'`) or contests.
4. Conflicting codings coexist; the export includes only reviewed,
   source-backed rows.

## Open questions

- Register #8 — ESAW/ILO mapping depth for MVP.
- Whether `contributing_condition` codes need severity/ordering semantics
  (primary vs secondary factor) — **flagged as open; MVP treats them as an
  unordered set**.
