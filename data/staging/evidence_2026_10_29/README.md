# Evidence correction packet — 29 October 2026

This packet contains six retrieved source-document metadata records and seven
AI-assisted candidate claims. **All claims remain `needs_review`.** It is not
a set of human decisions and does not replace the canonical public export.

The public-ID column is resolved against the existing working database by:

```bash
python scripts/stage_evidence_2026_10_29.py --db-path database/mining_accidents.sqlite
```

Run from the repository root with the project installed. The command refuses
an absent database, unknown target IDs or pre-approved claims; repeat runs do
not duplicate identical evidence. It never promotes values, inserts decisions
or marks records publishable. Do not feed `claims.csv` directly to the generic
CSV importer: `public_incident_id` must first be mapped to the local integer ID.

Source hashes identify the fetched HTML/PDF bytes. Full documents and victim
names are not committed. The six sources were downloaded and inspected during
the evidence pass; the TBMM passage is on printed page 74. Excerpts are short,
and each source's combined excerpts in this packet remain below 25 words.

## Proposed human decisions

| Record | Field | Existing snapshot | Source-supported proposal | Qualification |
|---|---|---|---|---|
| TR-MINE-2022-0001 | Fatalities | 42, disputed | 43; add a dated observation | TBMM statement 6 April 2023 describes a delayed death; do not label medically certified/final without that evidence |
| TR-MINE-1990-0002 | Fatalities/citation | 68, missing field citation | Retain 68 with chamber evidence and a recorded rationale | Preserve conflicting 66 claim and explain why the chamber statement is preferred |
| TR-MINE-2014-0012 | Fatalities/citation | 2; monitoring finds 1 | Retain 2 with dated update evidence | Contemporary report records the second recovery later the same day |
| TR-MINE-2026-0001 | Injuries | Unknown | 2 as reported on 2 October 2026 | No implication about long-term outcomes |
| TR-MINE-2026-0001 | Mechanism | Uncoded | roof_or_ground_collapse | Source describes collapse but explicitly cannot establish definitive causes |
| TR-MINE-2026-0001 | Fatalities/citation | 5, initial | Add chamber corroboration of 5 | Do not infer a final casualty status solely from this statement |
| TR-MINE-1983-0002 | Date | 10 April 1983 | Keep unresolved; review candidate 11 April | TTK chronology conflicts with the existing date; no automatic date replacement |

## Still requiring research

- Armutçuk 1983 operator and Kozlu 1983 organization role: TTK's institutional
  history describes its later establishment and predecessor EKİ/TKİ structure.
  This supports flagging an anachronism, not inventing a replacement legal role.
- Environmental original technical reports, date-supporting passages and the
  qualifier on the Şebinkarahisar release quantity.
- March 2022 Muğla monitoring candidate: exact event identity and original source.

A named human reviewer must inspect sources and conflicting claims, then use
the existing review functions/CLI. For casualties, append observations and
supersede decisions; never overwrite history. Create the source-backed
classification only after review. Regenerate the public export/dashboard and
close or revise each corresponding public evidence notice in the same release.

The original working database is deliberately excluded from Git and was not
available in this checkout. No replacement database or reviewer identity has
been fabricated.
