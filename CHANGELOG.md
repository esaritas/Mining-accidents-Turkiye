# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
semantic versioning once the project reaches a first release.

## [Unreleased]

### Changed: readability and language polish (2026-07-24, owner feedback)
- The record and site tables now scroll inside their panels (pinned headers,
  fixed max height) so a long list no longer pushes the rest of the page down.
- The Turkish text was rewritten for natural, fluent phrasing throughout
  (lede, captions, story chapters, tooltips, footer); stiff literal
  constructions and translationese were removed.
- Neutral, non-political framing: the "remembrance and accountability" wording
  became "remembrance and documentation" (TR: "anmak ve belgelemek"), and the
  speculative "If nothing changes" projection panel was removed. This is a
  documentation project, not an accountability instrument.
- No long dashes anywhere in display text: em/en dashes were replaced with
  commas, colons or sentence breaks across the page, the README and generated
  file headers. Project-assigned descriptive incident titles were retitled the
  same way through superseding claim_decisions (logged as `style_retitle` in
  docs/corrections_log.csv); no factual value changed, and the auto-title
  generator now uses a comma.

### Added — bilingual page & GitHub Pages (2026-07-18, owner feedback)
- The dashboard is fully bilingual: a Türkçe/English switcher in the nav
  (browser-language default, persisted), covering every caption, chapter,
  tooltip, table, legend, download and footer; dates and numbers follow the
  locale ("7 Mart 1983", "1.086"); mechanisms and policy events use their
  Turkish labels in Turkish. The map caption now states explicitly that a
  missing site diamond never means no mine — the sites layer holds only what
  open data documents.
- GitHub Pages workflow (.github/workflows/pages.yml): publishes the
  committed self-contained dashboard (dashboard/artifact.html) as the site
  index on every push; no build step, no external requests.

### Added — province color scale (2026-07-18, owner feedback)
- The map now represents every published record: provinces are shaded on a
  sequential red scale by people lost there (fixed breaks 1/5/20/100/300+,
  filter-aware, in both the SVG and Leaflet variants), so records without
  published coordinates are no longer hidden — hovering a province lists
  them, along with the province's documented site counts. The dashed
  province-summary circles are replaced by the shading; carnations continue
  to mark records with source-stated coordinates.

### Fixed — QA pass (2026-07-18)
- New automated checks: QC-W06 (exported site located outside Türkiye — the
  source's country statement is wrong) and QC-W07 (multiple exported sites
  sharing identical coordinates — source copy error). Both caught real
  defects on first run: Collum Coal Mine (in Zambia, erroneous P17=TR on
  Wikidata) is now OUT_OF_SCOPE and excluded; Sart altın madeni carried
  Mastra's exact coordinates — its coordinate-derived values are suppressed
  as COORD_CONFLICT. Editorial markers now survive mechanical re-parses.
- Contract compliance: `casualty_status='disputed'` is finally *displayed*
  — "toll disputed" badge in the records table, a sentence in map popups,
  and a column in the CSV download (Amasra).
- Display consistency: commodity labels unified to English (source wording
  kept in the tooltip); "not classified" → "not stated in sources"; chart
  gains a "people" unit label; identical-coordinate site pins are nudged
  apart so both stay visible; footer states records-in-review and
  withdrawn-after-audit counts with a pointer to the corrections log.

### Fixed — external audit corrections (2026-07-17, owner-forwarded)
Register: 51 published records / 1,086 deaths (was 46 / 976). Every action is
in `docs/corrections_log.csv` with original value, corrected value, and
rationale; unverifiable audit items are logged PENDING, never applied.
- **Parser root causes**: citation `<ref>` markup is stripped before date/
  death extraction (five records had carried a citation's *access date* as
  the accident date); monthly/aggregate summary bullets ("… ayında madenlerde
  yaşanan iş kazalarında…", "raporuna göre en az…", "iki ayrı kazada") are
  skipped entirely; death-verb coverage widened (ölürken/ölüm/yaşamını
  kaybet/çalışan); soft hyphens stripped; the article lead now contributes
  mechanisms alongside the infobox type (İliç: çökme AND heyelan).
- **Withdrawn**: the five false 2025-01-22 records, the conflated Bartın
  2014-11-01 record (split into Amasra/Bartın 2 deaths + Gelik/Zonguldak 1
  death, wagon collision), 25 never-published access-date/aggregate draft
  artifacts, and re-parse/title duplicates (merged with redirects).
- **Added to the register** (from the same assessed sources after the
  fixes): Yeni Çeltek 1990 (68), Yeni Çeltek 1983 (5), Küre 2004 (19),
  Odaköy/Dursunbey 2010 (17), Çöllolar 2011 (11), Şirvan 2016 (16), Gelik
  2024 (1), Mengen 2024 (1), Şirvan 2024 (3).
- **Amasra**: `casualty_status = disputed` (TBMM documents 43 cumulative
  deaths; assessed sources still say 42/27 — open question #20).
- **Soma**: `gas_explosion`/`methane` classifications demoted to the review
  queue; `fire` remains the established mechanism.
- **Sites**: commodity now chosen from ALL stated products plus the site's
  own name (Çöpler/Efemçukuru → gold, Çayeli/Murgul → copper); provinces
  from robust point-in-polygon with stated-vs-coordinates conflicts logged
  (Hasançelebi → Malatya); Soma Kömür Madeni → Manisa; Kışladağ duplicate
  merged; Garp Linyitleri marked operating directorate; ancient quarries
  and regional aggregates typed and kept off the operational map
  (facility_types v1.1).
- **Display**: dates render at recorded precision ("April 2005", never
  "2005-04-01"); the records table is labeled "Accident records currently
  documented in the project" — explicitly not a complete registry.

### Changed — carnations, commodity colors, names & downloads (2026-07-16, owner feedback)
- All person figures replaced with red carnations (karanfil) — the memorial
  flower: story marks, map accident markers (Leaflet + SVG), legend swatches.
  Red now consistently encodes loss across the page (marks, chart bars,
  mechanism/rate fills, accents); blue remains links only.
- Mining sites colored by commodity group — coal & lignite, metal ores,
  industrial minerals, not-stated — with a full map legend and colored chips
  in the sites table. Palette validated with the dataviz six-check validator
  (CVD + contrast) against the page surface.
- Province-name fixes: `province_centroids.csv` had Konya filed under Rize's
  plate code (53) and Uşak under Tunceli's (62), and Hakkâri misspelled —
  repaired and now validated 81/81 against `turkey_admin_areas.csv`. The
  dashboard resolves names from the full province vocabulary (centroids are
  fallback), and the public export gains `province_name` columns in
  `incidents.csv` and `facilities.csv`.
- "Take the data with you" panel: filter-aware CSV downloads (accident
  records, mining sites) and a JSON download of everything shown, generated
  client-side; caption points to the canonical checksummed export in
  `data/public/`.

### Changed — map, marks & data completeness (2026-07-16, owner feedback)
- Vector map rebuilt on Natural Earth 10m admin-1 geometry
  (`data/reference/tur_provinces.geo.json`, public domain): all 81 province
  boundaries drawn per-path, replacing the coarse country outline.
- One-mark-one-person fields and map accident markers now render as small
  human figures (CSS-mask / SVG pictograms; figure size = people lost on the
  map); undercount marks are gray figures instead of hollow boxes.
- Data completeness: quarry class added to site discovery (Wikidata has no
  further TR items — 78 is everything open data documents); linked-article
  infobox coordinates fetched for site items without P625 (+4 sites located);
  province derived from source-stated coordinates by point-in-polygon
  (`geo.py`, recorded as a derivation — implementation note E); infobox
  injury counts (`yaralı sayısı=`) extracted and decided alongside deaths;
  `link_incident_facilities` copies facility coordinates onto incidents via
  recorded manual_override decisions under a strict name+province blocking
  rule (implementation note F, STATUS: PROPOSED — zero links with current
  generated titles, engages as named records arrive).

### Added — active-sites layer, explorer filters & story prologue (2026-07-15)
- Migration 002: facilities gain `commodity_code`/`commodity_label`,
  `operational_status`, `external_ref`; organizations gain home-country
  columns (`country_code`/`country_label`) and `external_ref`; new
  `facility_organization_roles` table mirrors the incident role table
  (claim-backed, assertion + review statuses). New vocabularies
  `facility_types.csv` and `commodities.csv`.
- `wikidata_sites` adapter + `ingest-sites` CLI/make target: mining and
  quarrying site items in Türkiye (SPARQL P31/P279* mine, P17 TR) become a
  claim-backed facilities *context registry* — name, type, commodity,
  location, province, operator/owner with the company's home country where
  the source states them. 75 sites registered; coverage honestly labeled
  partial (open question #19: GEM tracker and MAPEG licence data registered
  `TO_ASSESS` for fuller company/status coverage).
- Public export gains `facilities.csv` + `facility_organization_roles.csv`
  (reviewed role rows only, assertion status always shipped).
- Infobox operating-company extraction for accident articles
  (`işletmeci|işleten|operator=`), with a ≥2-independent-documents
  corroboration threshold before an incident operator role row is marked
  reviewed/exportable (current sources state operators in prose only, so
  none auto-published).
- Dashboard: scroll-driven story prologue (pinned one-mark-one-person canvas;
  chapters per era 1983→today, the single largest loss, the İSİG undercount
  ghosts; reduced-motion static fallback), interactive filter bar
  (province / mechanism / year range / site commodity) driving map and
  tables, active-sites map layer (muted diamonds; Accidents/Sites/Both
  toggle) in both Leaflet and SVG variants, and a documented-sites table
  with operator and company home country columns.

### Added
- Phase 0: repository scaffolding, protocol document templates, open-questions
  register, configuration files, issue templates.
- Phase 1: initial schema migration (all evidence/decision/canonical/audit
  tables, CHECK constraints, indices, append-only triggers), checksummed
  migration runner with `schema.sql` snapshot, 14 controlled-vocabulary CSVs
  (including the 81 provinces) with validating loader, `create-db` CLI.
- Phase 2: Pydantic v2 models for every table, Pandera schemas at CSV
  boundaries, Turkish-aware normalization (explicit İ/ı handling), geography
  precision rules, duplicate-candidate detection, provenance utilities,
  adapter contract with conduct rules, four stub adapters, fully implemented
  manual CSV/YAML importer with synthetic example data.
- Phase 3: reviewer-decision recording with supersession and code-only
  canonical promotion, quality-check suite (9 critical + 6 warning checks),
  seven-rule publication threshold with deterministic byte-identical exports
  (datapackage + sha256 manifest), review-packet generator.
- Phase 4: twelve empty pilot packet slots, CLI test coverage, full README
  with architecture and next-stage plan.
- Reviewer CLI (`decide`, `assign-public-id`, `merge`) so decisions are
  recorded through tooling as the manual review protocol requires,
  `import-registry` command synchronizing `docs/source_registry.csv` into the
  `source_registry` table watched by QC-W05, and a GitHub Actions CI workflow
  (lint, vocabulary validation, tests, schema-snapshot sync check).

### Changed — data-collection stage (project owner directive, 2026-07-13)
- Foundation constraints 1-2 (no network for data / no factual data)
  superseded for assessed open sources; recorded in CLAUDE.md and the source
  registry. Constraints 3-7 remain fully in force.

### Added — analysis layer & humane redesign (2026-07-14)
- `analysis.py`: recording-undercount (coverage gap vs İSİG totals), rate
  context with documented denominators (deaths per 100M tonnes, press-cited),
  curated policy timeline (`data/vocabularies/policy_events.csv`), and a
  cost-of-inaction baseline (Poisson-floored interval) — all documented in
  `docs/analysis_methods.md` as STATUS: PROPOSED (open questions #17, #18);
  incident-level ML prediction explicitly rejected as indefensible.
- Dashboard redesigned as a humane public record: one-mark-one-person hero
  (976 marks + 905 outlined marks for counted-but-unrecorded deaths),
  narrative sentences from data, "on this day" remembrance, undercount
  columns and policy markers on the chart, rate comparison, and an
  "If nothing changes" card. Adaptive map (Leaflet or embedded vector);
  `build-artifact` renders the same template into a committed
  self-contained `dashboard/artifact.html`.

### Added — data-collection stage
- Implemented Wikidata/Wikipedia adapter (polite rate-limited fetching,
  immutable raw storage, mechanical vs `ai_assisted` extraction honesty) and
  `ingest-wikidata` orchestration: claims → deterministic bulk accept
  decisions under a named human reviewer → scope → publication sign-off for
  complete records only.
- First real seed: 9 incidents, 23 source documents, 84 claims; 5 records
  published (Karadon 2010, Soma 2014, Amasra 2022, Çöpler/İliç 2024, Zara
  2025); prose-extracted values wait in the mandatory review queue.
- Committed public export in `data/public/` and a static dashboard
  (`dashboard/index.html` + generated `data.js`): precision-aware Leaflet map
  (vendored library), deaths-by-year chart, table view, light/dark modes,
  pipeline-status tiles.
- Historic extension + cause coding (project owner directive, 2026-07-14):
  navbox + list-article discovery on tr.wikipedia brings per-incident records
  back to 1983 (46 published incidents, 976 recorded deaths); pre-2010
  incidents are now in scope. Mechanical cause extraction populates the
  four-axis `incident_classifications` (Wikidata P31 classes + Turkish
  incident-type phrases -> event mechanism/hazard, 67 source-backed rows).
  Death sentences with multiple numbers are ambiguity-guarded into the
  human-review queue instead of auto-published; list bullets matching an
  existing incident (province + date ±3 days) attach as corroborating claims
  instead of duplicates. İSİG Meclisi annual miner-death totals (2012-2025)
  land in `aggregate_occupational_statistics` with comparability notes and
  appear on the dashboard as a clearly-labeled context series; the dashboard
  also gains a mechanism breakdown and per-record mechanism display.
