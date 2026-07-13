# Conflict Resolution Protocol

How conflicting claims become (or fail to become) canonical values. The core
rule is absolute: **no silent conflict resolution**. Canonical values come
only from explicit `claim_decisions` rows made by a named reviewer.

## 1. State machine (implemented exactly in schema + code)

```
claims.review_status:    pending → needs_review → reviewed
claims.assertion_status: reported | alleged | preliminary_finding | technical_finding
                         | official_finding | judicial_finding | disputed | withdrawn | unknown

claim_decisions.decision: accept_claim | reject_field | manual_override | defer
```

## 2. Decision semantics

- **`accept_claim`** — `selected_claim_id` becomes the canonical source for
  that field. The canonical value is copied into `incidents` (or the relevant
  table) **by application code** (`review.py`), never by hand-editing.
- **`manual_override`** — the reviewer supplies a value not matching any claim
  verbatim (e.g., harmonized spelling). Requires a non-empty `rationale` and
  at least one supporting claim recorded in `rationale_claim_ids`.
- **`reject_field`** — no claim is acceptable; the field stays empty.
- **`defer`** — the field stays unresolved. A `defer` on a
  publication-critical field (`incident_start_datetime`, `province_code`,
  `fatalities_current`) blocks publication unless the conflict is disclosed
  in the export's `disclosed_conflicts` structure (config-gated, default off).

## 3. Supersession

A new decision on the same (incident, field) must set
`supersedes_decision_id`. Application code guarantees **exactly one active
decision per (incident_id, field_name)**; superseded decisions remain in the
table permanently as audit history.

## 4. What reviewers weigh

**STATUS: PROPOSED — awaiting editorial decision.** Guidance, not formula:

1. `assertion_status` strength (judicial/official findings generally
   outweigh initial reports — but recency and specificity matter);
2. source tier and independence (two independent Tier 2/3 sources can
   outweigh one stale Tier 1 statement);
3. proximity to the event (an investigation report over a same-day wire item
   for casualty totals; the reverse may hold for exact timing);
4. internal consistency with already-decided fields.

No automatic precedence order is encoded in software — every resolution is a
recorded human judgement with a rationale.

## 5. Casualty figures (special case)

Casualty revisions never overwrite: each figure is a `casualty_observations`
row. A decision selects which observation is `is_current_canonical = 1`
(exactly one per incident, enforced in code and checked by QC).
`missing → fatality` conversions are new observations.

## 6. AI/OCR-assisted claims

Claims with `extraction_method` in (`ai_assisted`, `ocr_assisted`) enter as
`needs_review` and **cannot be selected as canonical** until a human reviewer
marks them `reviewed`. Enforced by schema trigger + QC check.

## Open questions

- Register #9 — is a second reviewer required before `publishable`?
- Whether the weighing guidance in §4 should become a documented checklist
  with mandatory fields in the rationale — **flagged as open**.
