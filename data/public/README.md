# data/public — public export target

Output of `make export` (export.py): incidents.csv/json, classification and
role tables, sources.csv (metadata + capped excerpts only),
merged_id_redirects.csv, datapackage.json, export_manifest.json. Generated
files are gitignored; only records meeting ALL publication rules
(docs/editorial_and_legal_protocol.md §5) ever appear here.
