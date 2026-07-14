# data/public — the published dataset

Output of `make export` (export.py): incidents.csv/json, classification and
role tables, sources.csv (metadata + capped excerpts only),
merged_id_redirects.csv, datapackage.json, export_manifest.json. Since the
data-collection stage these files are COMMITTED — they are the publishable
dataset. Only records meeting ALL publication rules
(docs/editorial_and_legal_protocol.md §5) ever appear here; verify file
sha256 values against export_manifest.json before reuse.
