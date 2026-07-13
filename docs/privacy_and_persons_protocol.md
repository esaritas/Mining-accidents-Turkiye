# Privacy and Persons Protocol

This project will inevitably encounter the names of deceased workers and
details about their families. This protocol governs personal data before any
collection begins.

## 1. Legal and ethical posture

- **KVKK (Law No. 6698):** the status of deceased persons' data under KVKK is
  contested; protections attach most clearly to living persons. This project
  does **not** rely on that ambiguity: relatives' rights (privacy of grief,
  reputational interests of families) and human dignity apply regardless of
  the deceased's formal KVKK status.
- **Data minimization** is the default posture everywhere: collect and store
  the minimum personal information necessary to document the incident.
- *This section describes the project's understanding, not legal advice;
  legal review is an open question (register #2, #10).*

## 2. MVP rule — no person-level data

**STATUS: PROPOSED — awaiting editorial decision (register #2).**

- **No person-level table. No victim names anywhere in the database or
  exports.**
- Names appearing inside evidence text are **redacted to initials** in
  `short_evidence_excerpt` (e.g., "A.Y."). The unredacted original stays only
  in the immutable raw document store (`data/raw/`, never committed, never
  exported).
- Ages, hometowns, and family details are recorded only when aggregated and
  non-identifying, and only when needed for scope decisions.

## 3. Memorialization vs privacy (major open question)

Documenting deaths respectfully may eventually argue **for** naming — many
memorial projects do, and families sometimes want names remembered. This is
a genuine trade-off between dignity-through-remembrance and privacy/consent,
and it **requires editorial and possibly legal review before any change**.
Registered as open question #2. Until then: no names.

## 4. Takedown, objection, and correction process

**STATUS: PROPOSED.**

1. Intake via `.github/ISSUE_TEMPLATE/takedown_request.md` (or private
   channel once hosting exists — register #10).
2. Acknowledge within a defined period (proposed: 7 days).
3. Assess against this protocol; err toward the requester for anything
   touching identifiable persons or grieving families.
4. Outcome recorded in `review_log`; content changes happen through new
   claims/decisions (never silent edits), and exports are rebuilt.

## 5. Coordinates and small informal operations

Precise coordinates of small informal/illegal operations can identify the
individuals who worked (and died) there. **STATUS: PROPOSED:** for incidents
flagged `informal_or_illegal_operation`, publish coordinates at no better
than `settlement` precision unless an editorial decision records why finer
precision is safe.

## Open questions

- Register #2 — person-level data and memorialization.
- Register #10 — hosting/takedown jurisdiction.
- Response-time commitment in §4 — **flagged as open**.
