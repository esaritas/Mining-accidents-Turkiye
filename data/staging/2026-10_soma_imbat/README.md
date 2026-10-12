# 2026-10-01 Soma (İmbat Madencilik) — staged evidence, awaiting review

Prepared 2026-10-12 from a press report supplied by the project owner. These
rows are **evidence only**: every claim is `ai_assisted` / `needs_review`,
because the values were read out of prose rather than from a structured
source, so none of them can become a canonical value without a recorded human
decision (CLAUDE.md constraint 5).

## What the source states

| Field | Value | Turkish evidence |
|---|---|---|
| Date | 2026-10-01 | "1 Ekim'de meydana gelen göçükte" |
| Province | Manisa (45), Soma district | "Manisa'nın Soma ilçesinde" |
| Deaths | 5 | "beş işçi hayatını kaybetmişti" |
| Mechanism | roof_or_ground_collapse | "göçük" |
| Operator | İmbat Madencilik | "İmbat Madencilik'e ait maden ocağında" |

The article is about arrests following the accident. **Only the incident facts
are extracted.** Who is charged, held or tried is outside what this project
records: it documents deaths and their sources, not responsibility, and the
public page states that it is "never a statement of cause or legal
responsibility". The operator name is kept as an organization claim with its
assertion status, not as a finding of fault.

Seven workers were reported trapped and two rescued. No injury count is stated,
so no `injuries_current` claim is made.

## To bring it into the register

    python -m mining_accidents.cli import-manual \
      --db-path database/mining_accidents.sqlite \
      --documents data/staging/2026-10_soma_imbat/source_documents.csv \
      --claims    data/staging/2026-10_soma_imbat/claims.csv

Then review the five claims (`make packets`), record decisions with
`mining-accidents decide`, assign a public id, and re-run `qc`, `export`,
`dashboard`.

Tier 3 single-source: per open question #12 the corroboration threshold for a
single Tier 3 source on publication-critical fields is itself unresolved. A
chamber (TMMOB) or official statement should be added before the death toll is
treated as settled.
