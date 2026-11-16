# data/public — the published dataset

Output of `make export` (export.py): incidents.csv/json, classification and
role tables, sources.csv (metadata + capped excerpts only),
merged_id_redirects.csv, datapackage.json, export_manifest.json. Since the
data-collection stage these files are COMMITTED — they are the publishable
dataset. Only records meeting ALL publication rules
(docs/editorial_and_legal_protocol.md §5) ever appear here; verify file
sha256 values against export_manifest.json before reuse.

`git_commit` in the manifest is the commit the export was built from, which is
the parent of the commit that contains these files: a commit cannot name itself.

The working database is not published. Its full copy, with every claim,
decision and rationale behind these files, is the ledger in `data/ledger/`.
CI rebuilds a database from that ledger on every push and checks that exporting
it gives exactly these files (docs/database_recovery.md).
