# Repository review — 2026-09-10

Reviewed baseline: `69c48463086f4110f24ce8d947d3c659ead17ee2`, on the default
branch `claude/project-setup-file-kuvfuu`. This is a technical review of the
repository and its committed public snapshot, not independent verification of
incident facts. The snapshot is dated 2026-07-25 and contains 51 incidents and
73 sites. All hashes listed in its export manifest match the committed files.

## Assessment and plan

The project has a useful foundation: immutable evidence, explicit review
decisions, publication gates, synthetic test fixtures, bilingual presentation,
source links, and clearly identified coverage limitations. Prioritize
reliability of the existing public page before extending the dataset or adding
new predictive analysis.

The first implementation follows five priorities: consistent downloads,
safe rendering of source text, explicit build inputs, consistency between
published records and derived totals, and executable regression checks.

## Findings addressed

| Priority | Finding | Change |
|---|---|---|
| High | JSON download ignored active filters although the page promised filtered downloads. | Filter incidents/sites and their linked citations/classifications; record the filters; explicitly separate whole-register/sector context. |
| High | Source titles and URLs were interpolated directly into HTML. Embedded JSON could terminate its script element with a literal closing script tag. | Escape source text at presentation boundaries, allow HTTP(S) source links only, and encode `<` when embedding JSON. Raw JSON source strings remain intact. |
| High | Any SQLite or missing-file error could silently substitute a stale `data.js` payload during artifact creation. | Database errors propagate. `--from-data-js` explicitly selects a template-only build without opening a database. |
| Medium | Coverage calculations and published counts could use newer or ineligible working-database records rather than the displayed export. | Dashboard calculations use the exact incident export loaded for the table; other aggregate context remains a separate input. The committed snapshot had no discrepancy. |
| Medium | Empty CSV downloads lost their schemas; CR-containing values were not quoted. Formula-like text could be interpreted by spreadsheet applications. | Stable column lists, CR-aware quoting, and text-only formula neutralization in convenience CSV downloads. Numeric values and canonical exports retain their semantics. |
| Medium | Year controls did not update shared URLs; blocked storage could prevent startup or language switching. | Synchronize both year controls; gracefully tolerate unavailable language storage. Disable year filters for an empty register. |
| Medium | CI checked neither dashboard interactions nor drift between the template and committed deployed artifact. | Add locked JSDOM development dependencies, seven executable interaction tests, and an artifact rebuild comparison. |
| Low | Setup documentation still described a foundation without real data or a dashboard. | Update the project description and document the fresh-clone template build. |

## Further recommendations

These are proposals, not editorial decisions or newly verified facts.

1. **Define and validate aggregate series before adding sources.**
   `analysis._isig_series` and `dashboard._aggregates` currently select every
   row with `unit = 'deaths'`; the analysis dictionary can overwrite multiple
   rows for the same year. Select a documented institution, sector, geography,
   period, and source revision explicitly, and reject ambiguous duplicates.
   Partial-year observations also need explicit handling. Do not automatically
   choose between conflicting sources.
2. **Complete the source and uncertainty review.** Resolve existing source
   corroboration tasks through the claim/decision pipeline. Add consistent
   initial/revised/disputed casualty labels across tables, details, and narrative;
   preserve and expose field-level citations and disclosed conflicts. Keep the
   national coverage limitation prominent. See existing open questions 12, 20,
   and 21; no source claims were changed in this technical pass.
3. **Reconcile analytical documentation with the current page.**
   `docs/analysis_methods.md` still describes a displayed forward-looking
   baseline and uses language implying deaths were never publicly recorded.
   The current dashboard omits that projection and describes under-representation
   in this register. Revise the proposed methodology through editorial review;
   country/year rate comparisons and capped coverage percentages require careful
   interpretation rather than being treated as comparable risk estimates.
4. **Strengthen export integrity.** Include `incidents.json` in future export
   manifests (it is currently omitted), validate the saved dashboard payload
   against the public export, and publish exports atomically. The new explicit
   template build intentionally reuses a snapshot; it does not certify freshness.
5. **Gate deployment and verify accessibility in real browsers.** Make Pages
   depend on successful CI rather than deploying independently. Perform desktop
   and mobile checks, especially record-detail focus handling, chart keyboard
   access, source-link activation, and reduced motion. JSDOM cannot establish
   WCAG compliance or visual quality. Consider a Python dependency lock after
   selecting supported environments.

## Validation and limits

- Baseline: 145 Python tests passed; Ruff checks passed.
- Updated: 151 Python tests and 7 JSDOM interaction tests passed; Ruff lint and
  format checks and vocabulary validation passed.
- Rebuilt the committed self-contained artifact explicitly from `data.js`;
  repeating that build produces identical bytes.
- Tests cover malicious synthetic text/URLs, script embedding, filters and
  downloads, year URL round-trips, blocked storage, empty exports, build errors,
  and a working database that differs from the public snapshot.
- Browser installation failed because its download endpoint returned HTTP 502.
  No full browser layout, screenshot, or accessibility audit is claimed.
- No new external incident evidence was fetched. The private working database
  is not part of the clone, so a full production evidence re-export was not run.
  Canonical data files and the saved `data.js` snapshot were not modified.

Changes are prepared on `codex/dashboard-reliability-review` for review against
the repository's default branch. This work does not merge or deploy the page.
