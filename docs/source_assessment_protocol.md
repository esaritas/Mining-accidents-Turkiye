# Source Assessment Protocol

How a source family is assessed before any adapter is implemented. **No
adapter beyond manual entry may be implemented until this assessment is
completed and recorded** for that source (`docs/source_registry.csv` +
`source_registry` table).

## 1. Assessment checklist (per source)

1. **Identity & authority** — who publishes it; official mandate or
   editorial standards; independence considerations.
2. **Access terms** — terms of service, robots directives, licence/reuse
   statements; `automated_collection_permitted` recorded as
   `yes | no | unclear`. When `no` or `unclear`, only manual collection
   with per-document notes is allowed.
3. **Coverage** — period covered, geographic and sectoral completeness,
   known systematic gaps.
4. **Granularity** — incident-level vs aggregate. Aggregate-only sources
   (e.g., SGK yearbooks) feed `aggregate_*` tables only, never incident rows.
5. **Stability** — do URLs persist; is there an archive; do documents change
   after publication (requires re-retrieval discipline: new
   `source_documents` row per retrieval, never mutation).
6. **Format risk** — text PDFs vs scanned images; scanned or unreliable
   documents are routed to the manual-review queue, never trusted OCR output.

## 2. Proposed tier model

**STATUS: PROPOSED — awaiting editorial decision.**

| Tier | Description | Examples (families, not endorsements) |
|------|-------------|----------------------------------------|
| 1 | Official public record | Ministry statements, TBMM reports, SGK (aggregates only) |
| 2 | Professional / civil society / academic | TMMOB Maden MO, İSİG Meclisi, peer-reviewed studies |
| 3 | News media | Reputable national/local outlets |

Tier informs *assessment priority and corroboration requirements*, not
automatic truth. A Tier 1 claim can still be superseded by a decision citing
better evidence; the `assertion_status` axis (reported → judicial_finding)
is independent of tier.

## 3. Corroboration rules

**STATUS: PROPOSED.** Publication-critical fields (date, province,
fatalities) sourced only from a single Tier 3 claim require either a second
independent source or an explicit reviewer decision acknowledging
single-source status in the rationale.

## 4. Re-assessment

Each registry entry carries `last_assessed`. Quality checks flag entries
older than the configured staleness window (default 365 days) or still
marked `TO_ASSESS`.

## 5. Adapter conduct rules (binding once adapters are built)

- Check permissions and robots directives first; descriptive user agent.
- Conservative rate limits, retries with backoff, response caching.
- Immutable raw storage with sha256 `content_hash`; `retrieved_at` recorded.
- Never bypass access controls. Never assume PDFs have text layers.
- Never fabricate missing values — absent data stays absent.

## Open questions

- Register #6 — sourcing an authoritative district list.
- Register #8 — ESAW/ILO mapping depth affects which sources need assessment.
- Whether Tier 2/3 single-source corroboration thresholds (§3) are strict
  enough — **flagged as open**.
