# Database recovery and the ledger

How the working database is kept safe, how to rebuild it, and what was and was
not recovered after it was lost on 11 November 2026.

## The short version

The working database (`database/mining_accidents.sqlite`) is not in git. Its
durable copy is the **ledger** in `data/ledger/`: every table written as one
JSON-lines file, in primary-key order. The ledger is committed with every
export, and CI proves on every push that it rebuilds a database whose export is
the committed one.

To get a working database on a fresh machine:

```
python3 -m pip install -e ".[dev]"
python3 -m mining_accidents.cli ledger-load      # or: make restore
```

`ledger-load` never overwrites an existing database. It checks every file
against the hash in `data/ledger/ledger_manifest.json` first.

## Day to day

| When | Do | Why |
|---|---|---|
| After any change to the database | `make export` | The export command writes the ledger beside the export, so the two cannot drift |
| After a change that is not exported yet (claims at `needs_review`, a sweep's aggregate rows) | `make ledger` | Unexported work is still work; commit `data/ledger/` |
| Before trusting a checkout | `make verify-ledger` | Loads the ledger, dumps it again, exports from it, compares every file |

Commit `data/ledger/` together with `data/public/`. A push that changes one
without the other fails CI.

## What the ledger is and is not

- It is a faithful copy: primary keys, timestamps and review statuses are kept,
  and loading runs no review logic. The round trip (dump, load, dump) is
  byte-identical, and a test holds it to that.
- The immutability triggers come from the migrations, not from the ledger, so a
  rebuilt database refuses the same updates and deletes as the original.
- A claim extracted with AI assistance can only enter the claims table as
  `needs_review` (constraint 5). The loader honours that: it inserts such a
  claim as `needs_review` and then sets the status the ledger records, which is
  how the claim came to be in the first place.
- It holds no victim's name and nothing private. It does hold the reviewer
  recorded on each decision.
- `data/raw/` (retrieved pages and PDFs) is still not committed, because most
  of it is other publishers' copyright. Each document's hash is in the ledger.
  The Wikipedia and Wikidata revisions behind the published citations are kept
  under `data/archive/` with a permanent link each, because those licences
  permit it.

## What happened on 11 November 2026

The database lived in one cloud container. The container was replaced during
the quality audit and the database went with it, along with 15 MB of retrieved
pages. No copy existed. Open question 22 had named this risk a month earlier.

Lost: 963 claims (799 never reviewed), 301 decisions with their rationales and
supersession chains, the review log, the casualty observation history and the
evidence added on 29 October.

Kept, because it was committed: the public export of 29 October (commit
`46154be`), the page, the scripts, and the candidate evidence staged in
`data/staging/evidence_2026_10_29/`.

## How it was rebuilt

In this order, on 15 and 16 November 2026. Each step is a script in the
repository and can be read.

| # | Step | Script | Result |
|---|---|---|---|
| 1 | Archive the Wikimedia revisions that were current when each citation was retrieved | `scripts/archive_wikimedia_revisions.py` | 26 revisions under `data/archive/`, each with its hash and permanent link |
| 2 | Rebuild the database from the export | `scripts/restore_database_2026_11.py` | 52 fatal and 3 environmental records, 271 decisions, 494 claims, 117 documents |
| 3 | Replay the 29 October evidence from the live sources | `scripts/amasra_casualty_revision.py`, `scripts/organization_validity.py` | Assembly record, TTK chronology and their claims back, with hashes |
| 4 | Evidence pass | `scripts/evidence_2026_11_15.py` | See open questions 44 to 48 |
| 5 | Export and ledger | `make export` | The first committed ledger |

Step 2 was proved before it was trusted: exporting the rebuilt database, with
no change of any kind, reproduced all 14 files of the 29 October export byte
for byte. The database then kept differs from that export in one deliberate
way, made in the same step: a parliamentary citation whose title named the
member who gave the speech now reads without the name.

## What the restoration did not bring back

Said here and in the database itself, so nobody reads a restored row as more
than it is.

- **The claims that were not selected.** Only the claim behind each published
  value was rebuilt. Rival claims that were on file (a second toll, a second
  date) are gone unless a source swept since states them again. The monthly
  check compares the sources with the register and reports such differences.
- **The original rationales and decision dates.** Each restored decision says
  in its rationale that it repeats the decision active at the export and that
  the original reasoning was not recoverable. The reviewer is the one who made
  the original decisions and who authorised the restoration.
- **The bytes of non-Wikimedia documents.** Eleven cited documents (news
  articles, two parliamentary speeches, a chamber bulletin) have no content
  hash: the retrieved bytes are lost and no archive of them was kept. Their
  notes begin `RESTORED_FROM_EXPORT`.
- **Rows the export published without a citation** (classifications,
  organization roles, environmental effects, site records). Each now cites the
  export file that listed it, with that file's hash, because that file is the
  only surviving evidence that the register held the row.
- **Links between incidents and facilities**, which were never exported.

## A rule changed to make this possible

STATUS: PROPOSED — awaiting editorial decision (open question 46).

Quality check QC-C08 treats a cited document with no content hash as a critical
finding that blocks the export. A restored document cannot have a hash. Rather
than invent one, the check now reports such a document as warning QC-W08 when,
and only when, its notes begin `RESTORED_FROM_EXPORT`. Any other document
without a hash still blocks the export. The eleven restored documents without a
hash are listed by `make qc`, and each should in time be replaced by a fresh
retrieval with a claim and a superseding decision.
