# Open Questions Register

Single register of unresolved editorial/design decisions. Nothing here may be
treated as settled in code, docs, or data. When a decision is made, record
the decision, decider, and date here, then update the relevant protocol.

| # | Question | Raised by | Status |
|---|----------|-----------|--------|
| 1 | **Licence choice.** Code: MIT vs Apache-2.0. Data: CC BY 4.0 vs ODbL. Affects reuse and attribution machinery. | Spec §14 | OPEN |
| 2 | **Person-level victim data & memorialization** vs KVKK/dignity constraints. MVP rule is *no names anywhere*; future memorialization needs editorial + legal review. | privacy_and_persons_protocol.md | OPEN |
| 3 | **Rescue-worker deaths:** counted inside the originating incident total or separable in MVP counting? | research_protocol.md §7 | OPEN |
| 4 | **Commuting incidents:** confirm exclusion from MVP core scope. | research_protocol.md §2 | OPEN |
| 5 | **Incident-splitting rule** for cascading events during rescue operations. | research_protocol.md §1 | OPEN |
| 6 | **District-level admin reference data:** authoritative list + versioning of boundary changes. Provinces ship; districts need sourcing. | data_dictionary.md | OPEN |
| 7 | **Excerpt length cap & fair-quotation policy** per Turkish copyright (FSEK) practice. Current proposal: ≤ 40 words. | editorial_and_legal_protocol.md §4 | OPEN |
| 8 | **ESAW/ILO mapping depth** for MVP. | cause_coding_protocol.md §3 | OPEN |
| 9 | **Editorial board / second-reviewer requirement** before `publishable`. | manual_review_protocol.md | OPEN |
| 10 | **Hosting and takedown jurisdiction** considerations. | privacy/editorial protocols | OPEN |

## Additional questions raised during protocol drafting

| # | Question | Raised by | Status |
|---|----------|-----------|--------|
| 11 | Bright-line definition of "operationally tied to extraction" for processing facilities (rule E5/I3). | inclusion_exclusion_rules.md | OPEN |
| 12 | Corroboration thresholds for single-source Tier 3 claims on publication-critical fields. | source_assessment_protocol.md §3 | OPEN |
| 13 | Severity/ordering semantics for contributing conditions (primary vs secondary factor). | cause_coding_protocol.md | OPEN |
| 14 | Mandatory rationale checklist for conflict decisions. | conflict_resolution_protocol.md §4 | OPEN |
| 15 | Takedown response-time commitment. | privacy_and_persons_protocol.md §4 | OPEN |
| 16 | Distinct content-reviewer vs editorial-approver identities on packet sign-off. | manual_review_protocol.md | OPEN |

## Implementation notes (conservative interpretations logged per spec §0.3)

| Ref | Ambiguity | Conservative interpretation taken |
|-----|-----------|-----------------------------------|
| A | Spec declares `claims` append-only **and** defines a `review_status` workflow on claims. | Claim *content* is frozen by trigger; only `review_status` may be updated. Alternative (separate review-events table) flagged in data_dictionary.md. |
| B | Spec gives one column template for all five aggregate-context tables, but `classification_concordance` is a code mapping. | Concordance gets from/to system+code columns; the four true aggregate tables follow the template verbatim. |
| C | `ingestion_runs` is append-only but has `finished_at`/`status`. | Run rows are inserted once, at completion, with final status — no in-place updates. |
| D | Byte-identical re-export vs manifest timestamp. | Data files are strictly deterministic; the manifest timestamp honors `SOURCE_DATE_EPOCH` when set (tests set it), otherwise uses current UTC time. |
