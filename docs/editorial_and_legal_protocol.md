# Editorial and Legal Protocol

Framing, liability, and copyright rules for a project that documents deaths
and names organizations. Everything here is **PROPOSED** unless marked
binding; open items are registered in [`open_questions.md`](open_questions.md).

## 1. Respectful framing (binding)

This project documents deaths. No gamified language, no sensational field
names, no ranking or "leaderboard"-style outputs anywhere in code, docs, or
exports. Aggregations are presented as documentation of harm, not spectacle.

## 2. Presumption of innocence and company roles

- An `alleged` assertion status is **never rendered as established fact**.
  Export and any future dashboard must carry the assertion status alongside
  every organization role and cause row.
- `incident_organization_roles` records what sources assert (licence holder,
  operator, subcontractor…), each row tied to a `source_claim_id` and an
  `assertion_status`. The project itself asserts nothing.
- **Defamation risk:** `operator` and `licence_holder` attributions are the
  highest-risk fields. **STATUS: PROPOSED:** these reach `reviewed` only with
  a Tier 1–2 source or multiple independent Tier 3 sources, and are always
  displayed with their assertion status.

## 3. Source findings vs project commentary (binding)

The `recommendations` table stores **source findings only**
(`origin = 'source_finding'`, enforced by CHECK constraint). Project
analytical commentary lives in documentation, clearly signed as the
project's own analysis — never in evidence tables or data exports.

## 4. Copyright and excerpts

**STATUS: PROPOSED — awaiting editorial decision (register #7).**
Evidence excerpts (`short_evidence_excerpt`) are capped at **≤ 40 words**
(`config/project.yml → excerpts.max_words`). Where 40 words are insufficient,
store metadata + link/reference only. Full copyrighted articles are never
stored in public exports; `sources.csv` carries metadata and capped excerpts
only. Fair-quotation practice under Turkish copyright law (FSEK) needs legal
review.

## 5. Publication eligibility (binding; enforced in `export.py`)

A record enters the public export only if ALL hold:

1. `verification_status = 'reviewed'`;
2. accepted decisions exist for incident date and province;
3. `fatalities_current` traces to a selected claim via a decision;
4. every exported cause/factor/company-role row has `source_claim_id` and
   `review_status = 'reviewed'`;
5. coordinate precision stated (or coordinates omitted);
6. no `defer` decisions on publication-critical fields, OR the conflict is
   exported in a `disclosed_conflicts` structure;
7. `publication_status = 'publishable'` (editorial sign-off flag).

## 6. Corrections and takedowns

Corrections are new claims/decisions/observations — never edits. Takedown and
objection requests follow the process in
[`privacy_and_persons_protocol.md`](privacy_and_persons_protocol.md) §4 and
the `.github/ISSUE_TEMPLATE/takedown_request.md` intake form.

## Open questions

- Register #7 — excerpt cap and fair-quotation policy under Turkish practice.
- Register #9 — editorial board / second reviewer before `publishable`.
- Register #10 — hosting and takedown jurisdiction.
- Whether §2's evidence threshold for operator/licence-holder attribution is
  sufficient — **flagged as open, needs legal review**.
