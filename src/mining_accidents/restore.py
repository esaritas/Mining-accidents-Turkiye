"""Rebuild a working database from a committed public export.

Role in the evidence flow: recovery, and only recovery. On 2026-11-11 the
working database was lost and the public export was the only record left of
what the register held (docs/qc_audit_2026_11_11.md section 2). This module
turns that export back into documents, claims and decisions so that exporting
the rebuilt database reproduces the committed files byte for byte.

What it restores is what was published. For every published value that carried
a citation it re-creates the cited document, one claim stating the value and
the decision that selected it. Rows the export publishes without a citation
(classifications, organization roles, environmental effects, site records) get
a claim whose source is the export file itself, hashed, because that file is
now the only evidence that the register held them.

What it cannot restore is said in the database rather than hidden: restored
documents have no content hash (the retrieved bytes are gone) and carry
``RESTORED_FROM_EXPORT`` in their notes; restored decisions say in their
rationale that the original rationale and the unselected claims were not
recoverable. Decisions are recorded through :mod:`mining_accidents.review`
under the reviewer who authorises the restoration, never invented by this
code: each one repeats a decision that was active at the export.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from mining_accidents import review
from mining_accidents.database import create_database, get_connection, utc_now_iso
from mining_accidents.export import ENVIRONMENTAL_COLUMNS, INCIDENT_COLUMNS
from mining_accidents.models import ClaimDecision, IngestionRun
from mining_accidents.normalization import normalize_tr
from mining_accidents.provenance import (
    RESTORED_MARK,
    import_source_registry,
    record_ingestion_run,
    sha256_file,
)

EXTRACTOR_VERSION = "restore_from_export/1"
EXPORT_ORGANIZATION = "This register (public export)"

#: Decisions are replayed in this order so casualty observations are appended
#: in a stable sequence and coordinates follow the date and place.
_FIELD_ORDER = (
    "incident_start_datetime",
    "date_precision",
    "province_code",
    "canonical_title_tr",
    "canonical_title_en",
    "latitude",
    "longitude",
    "coordinate_precision",
    "fatalities_current",
    "injuries_current",
    "missing_current",
    "casualty_status",
)
_INT_COLUMNS = frozenset({"fatalities_current", "injuries_current", "missing_current"})
_FLOAT_COLUMNS = frozenset({"latitude", "longitude", "location_uncertainty_m"})
_CASUALTY_FIELDS = _INT_COLUMNS


class RestoreError(RuntimeError):
    """Raised when the export cannot be turned back into a database."""


@dataclass
class RestoreSummary:
    documents: int = 0
    claims: int = 0
    decisions: int = 0
    incidents: int = 0
    environmental: int = 0
    withdrawn: int = 0
    facilities: int = 0
    organizations: int = 0
    aggregates: int = 0
    notes: list[str] = field(default_factory=list)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _blank(value: str | None) -> str | None:
    return None if value in (None, "") else value


def _typed(column: str, value: str | None) -> object:
    value = _blank(value)
    if value is None:
        return None
    if column in _INT_COLUMNS:
        return int(value)
    if column in _FLOAT_COLUMNS:
        return float(value)
    return value


class _Restorer:
    def __init__(
        self,
        conn: sqlite3.Connection,
        public_dir: Path,
        reviewer: str,
        export_label: str,
        export_url_base: str | None,
        title_redactions: dict[str, str],
        observed_as_of: dict[str, str],
        archive: dict[tuple[str, str], dict],
    ) -> None:
        self.conn = conn
        self.public_dir = public_dir
        self.reviewer = reviewer
        self.export_label = export_label
        self.export_url_base = export_url_base
        self.title_redactions = title_redactions
        self.observed_as_of = observed_as_of
        self.archive = archive
        self.summary = RestoreSummary()
        self.now = utc_now_iso()
        self._documents: dict[tuple, int] = {}
        self._export_documents: dict[str, int] = {}
        self._organizations: dict[tuple, int] = {}
        self._incident_ids: dict[str, int] = {}
        manifest = json.loads((public_dir / "export_manifest.json").read_text(encoding="utf-8"))
        self.export_timestamp = manifest["export_timestamp"]
        self.rationale = (
            f"Restored from the public export of {self.export_timestamp[:10]} "
            f"({export_label}) after the working database was lost on 2026-11-11. "
            "This repeats the decision that was active at that export. The original "
            "rationale, its date and the claims it did not select were not recoverable."
        )

    # -- documents and claims ------------------------------------------------

    def _cited_document(self, row: dict[str, str]) -> int:
        """The document a published citation names, re-created without bytes."""
        title = self.title_redactions.get(row["title"], row["title"])
        key = (
            row["source_organization"],
            title,
            row["document_type"],
            row["url"],
            row["publication_date"],
            row["retrieved_at"],
            row["language"],
            row["source_tier"],
        )
        if key not in self._documents:
            note = (
                f"{RESTORED_MARK} {self.export_timestamp[:10]}: re-created from the "
                "citation in the public export. The bytes retrieved on the date shown "
                "were lost on 2026-11-11"
            )
            anchor = self.archive.get((row["url"], row["retrieved_at"]))
            if anchor:
                note += (
                    f". The content hash is of revision {anchor['revision_id']} "
                    f"({anchor['revision_timestamp']}), the revision that was current at "
                    f"the retrieval time, fetched again on {anchor['archived_at'][:10]}."
                )
            else:
                note += ", so this row has no content hash."
            cur = self.conn.execute(
                "INSERT INTO source_documents (source_organization, title, document_type, url, "
                "publication_date, retrieved_at, language, source_tier, content_hash, "
                "local_raw_path, archived_reference, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["source_organization"],
                    title,
                    _blank(row["document_type"]),
                    _blank(row["url"]),
                    _blank(row["publication_date"]),
                    _blank(row["retrieved_at"]),
                    _blank(row["language"]),
                    int(row["source_tier"]) if row["source_tier"] else None,
                    anchor["sha256"] if anchor else None,
                    anchor["path"] if anchor else None,
                    anchor["permalink"] if anchor else None,
                    note,
                ),
            )
            self._documents[key] = int(cur.lastrowid)
            self.summary.documents += 1
        return self._documents[key]

    def _export_document(self, name: str, directory: Path | None = None) -> int:
        """An export file as a source document: hashed, and all that is left."""
        if name not in self._export_documents:
            path = (directory or self.public_dir) / name
            url = f"{self.export_url_base}/{path.as_posix()}" if self.export_url_base else None
            cur = self.conn.execute(
                "INSERT INTO source_documents (source_organization, title, document_type, url, "
                "retrieved_at, language, content_hash, local_raw_path, notes) "
                "VALUES (?, ?, 'dataset', ?, ?, 'en', ?, ?, ?)",
                (
                    EXPORT_ORGANIZATION,
                    f"{path.as_posix()} ({self.export_label})",
                    url,
                    self.now,
                    sha256_file(path),
                    path.as_posix(),
                    f"{RESTORED_MARK} {self.export_timestamp[:10]}: this file is the only "
                    "surviving record of the rows it lists. The claims that originally "
                    "supported them were lost on 2026-11-11.",
                ),
            )
            self._export_documents[name] = int(cur.lastrowid)
            self.summary.documents += 1
        return self._export_documents[name]

    def _claim(
        self,
        document_id: int,
        subject_type: str,
        field_name: str,
        value: str | None,
        incident_id: int | None = None,
        excerpt: str | None = None,
        assertion_status: str = "reported",
        section: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO claims (incident_id, source_document_id, claim_subject_type, "
            "field_name, raw_value, normalized_value, section_reference, "
            "short_evidence_excerpt, extraction_method, extractor_version, assertion_status, "
            "review_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'structured_file', ?, ?, 'reviewed')",
            (
                incident_id,
                document_id,
                subject_type,
                field_name,
                value,
                value,
                section,
                _blank(excerpt),
                EXTRACTOR_VERSION,
                assertion_status or "unknown",
            ),
        )
        self.summary.claims += 1
        return int(cur.lastrowid)

    # -- incidents -----------------------------------------------------------

    def _restore_incident(
        self,
        record: dict[str, str],
        columns: list[str],
        kind: str,
        citations: list[dict[str, str]],
    ) -> int:
        public_id = record["public_incident_id"]
        cur = self.conn.execute(
            "INSERT INTO incidents (public_incident_id, incident_kind, incident_status) "
            "VALUES (?, ?, 'in_scope')",
            (public_id, kind),
        )
        incident_id = int(cur.lastrowid)
        self._incident_ids[public_id] = incident_id
        review.log_review_action(
            self.conn,
            actor=self.reviewer,
            action="restore_incident",
            entity_type="incident",
            entity_id=incident_id,
            after_summary=public_id,
            notes=f"{RESTORED_MARK}: identifier kept from {self.export_label}",
        )

        by_field: dict[str, list[dict[str, str]]] = {}
        for row in citations:
            by_field.setdefault(row["field_name"], []).append(row)
        unknown = set(by_field) - set(_FIELD_ORDER)
        if unknown:
            raise RestoreError(f"{public_id}: cited fields with no replay order: {sorted(unknown)}")
        for field_name in _FIELD_ORDER:
            rows = by_field.get(field_name)
            if not rows:
                continue
            value = record.get(field_name, "")
            claim_ids = [
                self._claim(
                    self._cited_document(row),
                    "casualty" if field_name in _CASUALTY_FIELDS else "incident",
                    field_name,
                    value,
                    incident_id=incident_id,
                    excerpt=row["short_evidence_excerpt"],
                    section="restored from sources.csv",
                )
                for row in rows
            ]
            observed = None
            if field_name in _CASUALTY_FIELDS:
                observed = self.observed_as_of.get(public_id, self.export_timestamp)
            if len(claim_ids) == 1:
                decision = ClaimDecision(
                    incident_id=incident_id,
                    field_name=field_name,
                    selected_claim_id=claim_ids[0],
                    decision="accept_claim",
                    rationale=self.rationale,
                    reviewer=self.reviewer,
                    observed_as_of=observed,
                )
            else:
                decision = ClaimDecision(
                    incident_id=incident_id,
                    field_name=field_name,
                    decision="manual_override",
                    manual_value=value,
                    rationale=self.rationale,
                    rationale_claim_ids=claim_ids,
                    reviewer=self.reviewer,
                    observed_as_of=observed,
                )
            review.record_decision(self.conn, decision)
            self.summary.decisions += 1

        # Values the export publishes without a citation of their own (a
        # generated title, an uncited status). They are copied as published
        # and logged, because no claim for them survives.
        current = self.conn.execute(
            "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
        ).fetchone()
        uncited = []
        for column in columns:
            if column in ("public_incident_id", "province_name", "related_public_incident_id"):
                continue
            wanted = _typed(column, record.get(column))
            if current[column] != wanted:
                self.conn.execute(
                    f"UPDATE incidents SET {column} = ? WHERE incident_id = ?",  # noqa: S608
                    (wanted, incident_id),
                )
                uncited.append(column)
        title = record.get("canonical_title_tr") or ""
        self.conn.execute(
            "UPDATE incidents SET canonical_title_tr_normalized = ?, "
            "verification_status = 'reviewed', publication_status = 'published' "
            "WHERE incident_id = ?",
            (normalize_tr(title) if title else None, incident_id),
        )
        if uncited:
            review.log_review_action(
                self.conn,
                actor=self.reviewer,
                action="restore_uncited_values",
                entity_type="incident",
                entity_id=incident_id,
                after_summary=", ".join(uncited),
                notes=f"{RESTORED_MARK}: published without a field citation; copied as published",
            )
        return incident_id

    def restore_incidents(self) -> None:
        citations: dict[str, list[dict[str, str]]] = {}
        for row in _read_csv(self.public_dir / "sources.csv"):
            citations.setdefault(row["public_incident_id"], []).append(row)
        for record in _read_csv(self.public_dir / "incidents.csv"):
            self._restore_incident(
                record,
                INCIDENT_COLUMNS,
                "fatal_accident",
                citations.get(record["public_incident_id"], []),
            )
            self.summary.incidents += 1

        env_citations: dict[str, list[dict[str, str]]] = {}
        for row in _read_csv(self.public_dir / "environmental_sources.csv"):
            env_citations.setdefault(row["public_incident_id"], []).append(row)
        environmental = _read_csv(self.public_dir / "environmental_incidents.csv")
        for record in environmental:
            self._restore_incident(
                record,
                ENVIRONMENTAL_COLUMNS,
                "environmental",
                env_citations.get(record["public_incident_id"], []),
            )
            self.summary.environmental += 1
        for record in environmental:
            related = record.get("related_public_incident_id")
            if related:
                self.conn.execute(
                    "UPDATE incidents SET related_incident_id = ? WHERE incident_id = ?",
                    (
                        self._incident_ids[related],
                        self._incident_ids[record["public_incident_id"]],
                    ),
                )

    def restore_withdrawn(self, withdrawn: dict[str, str]) -> None:
        """Identifiers that were withdrawn stay taken, and redirects stay valid."""
        redirects = _read_csv(self.public_dir / "merged_id_redirects.csv")
        reasons = dict(withdrawn)
        for row in redirects:
            reasons.setdefault(
                row["merged_public_incident_id"],
                f"Merged into {row['surviving_public_incident_id']} before the export of "
                f"{self.export_timestamp[:10]}; the merge reason was not recoverable.",
            )
        for public_id, reason in sorted(reasons.items()):
            kind = "environmental" if public_id.startswith("TR-ENV") else "fatal_accident"
            cur = self.conn.execute(
                "INSERT INTO incidents (public_incident_id, incident_kind, canonical_title_tr, "
                "scope_rationale, publication_status) VALUES (?, ?, ?, ?, 'withdrawn')",
                (
                    public_id,
                    kind,
                    f"Geri çekilen kayıt {public_id}",
                    f"{RESTORED_MARK}: withdrawn before the export. {reason}",
                ),
            )
            self._incident_ids[public_id] = int(cur.lastrowid)
            self.summary.withdrawn += 1
        for row in redirects:
            merged = row["merged_public_incident_id"]
            self.conn.execute(
                "INSERT INTO incident_merge_log (surviving_incident_id, merged_incident_id, "
                "merged_public_incident_id, reason, reviewer, merged_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self._incident_ids[row["surviving_public_incident_id"]],
                    self._incident_ids[merged],
                    merged,
                    f"{RESTORED_MARK}: {reasons[merged]}",
                    self.reviewer,
                    self.export_timestamp,
                ),
            )

    # -- rows published without a citation ----------------------------------

    def _restore_classifications(self, name: str) -> None:
        rows = _read_csv(self.public_dir / name)
        if not rows:
            return
        document_id = self._export_document(name)
        for row in rows:
            incident_id = self._incident_ids[row["public_incident_id"]]
            claim_id = self._claim(
                document_id,
                "classification",
                row["classification_system"],
                row["classification_code"],
                incident_id=incident_id,
                assertion_status=row["assertion_status"],
            )
            self.conn.execute(
                "INSERT INTO incident_classifications (incident_id, classification_system, "
                "classification_level, classification_code, classification_label_tr, "
                "classification_label_en, assertion_status, source_claim_id, review_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reviewed')",
                (
                    incident_id,
                    row["classification_system"],
                    _blank(row["classification_level"]),
                    row["classification_code"],
                    _blank(row["classification_label_tr"]),
                    _blank(row["classification_label_en"]),
                    row["assertion_status"],
                    claim_id,
                ),
            )

    def _organization(self, name: str, code: str, label: str, org_type: str | None) -> int:
        key = (name, code, label)
        if key not in self._organizations:
            cur = self.conn.execute(
                "INSERT INTO organizations (organization_name_tr, organization_name_normalized, "
                "organization_type, country_code, country_label) VALUES (?, ?, ?, ?, ?)",
                (name, normalize_tr(name), org_type or "unknown", _blank(code), _blank(label)),
            )
            self._organizations[key] = int(cur.lastrowid)
            self.summary.organizations += 1
        return self._organizations[key]

    def _restore_incident_roles(self) -> None:
        name = "incident_organization_roles.csv"
        rows = _read_csv(self.public_dir / name)
        if not rows:
            return
        document_id = self._export_document(name)
        for row in rows:
            incident_id = self._incident_ids[row["public_incident_id"]]
            organization_id = self._organization(
                row["organization_name_tr"],
                row["organization_country_code"],
                row["organization_country_label"],
                row["organization_type"],
            )
            claim_id = self._claim(
                document_id,
                "organization",
                row["role"],
                row["organization_name_tr"],
                incident_id=incident_id,
                assertion_status=row["assertion_status"],
            )
            valid = row["valid_at_incident_date"]
            self.conn.execute(
                "INSERT INTO incident_organization_roles (incident_id, organization_id, role, "
                "valid_at_incident_date, source_claim_id, assertion_status, review_status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'reviewed')",
                (
                    incident_id,
                    organization_id,
                    row["role"],
                    int(valid) if valid != "" else None,
                    claim_id,
                    row["assertion_status"],
                ),
            )

    def _restore_effects(self) -> None:
        name = "environmental_effects.csv"
        rows = _read_csv(self.public_dir / name)
        if not rows:
            return
        document_id = self._export_document(name)
        for row in rows:
            incident_id = self._incident_ids[row["public_incident_id"]]
            claim_id = self._claim(
                document_id,
                "incident",
                row["effect_type"],
                row["qualitative_value"] or row["measure_value"],
                incident_id=incident_id,
                assertion_status=row["assertion_status"],
            )
            self.conn.execute(
                "INSERT INTO environmental_effects (incident_id, effect_type, measure_value, "
                "measure_unit, qualitative_value, qualitative_value_en, source_claim_id, "
                "assertion_status, effect_status, review_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'reviewed')",
                (
                    incident_id,
                    row["effect_type"],
                    float(row["measure_value"]) if row["measure_value"] else None,
                    _blank(row["measure_unit"]),
                    _blank(row["qualitative_value"]),
                    _blank(row["qualitative_value_en"]),
                    claim_id,
                    row["assertion_status"],
                    row["effect_status"] or "unknown",
                ),
            )

    def _restore_facilities(self) -> None:
        facility_ids: dict[str, int] = {}
        for row in _read_csv(self.public_dir / "facilities.csv"):
            document_id = self._cited_document(
                {
                    "source_organization": "Wikidata"
                    if "wikidata.org" in row["source_url"]
                    else "Site register source",
                    "title": row["facility_ref"],
                    "document_type": "dataset",
                    "url": row["source_url"],
                    "publication_date": "",
                    "retrieved_at": "",
                    "language": "",
                    "source_tier": "",
                }
            )
            claim_id = self._claim(
                document_id, "facility", "facility_record", row["facility_name_tr"]
            )
            lat, lon = _blank(row["latitude"]), _blank(row["longitude"])
            cur = self.conn.execute(
                "INSERT INTO facilities (facility_name_tr, facility_name_normalized, "
                "facility_type, province_code, latitude, longitude, coordinate_precision, "
                "source_claim_id, commodity_code, commodity_label, operational_status, "
                "external_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["facility_name_tr"],
                    normalize_tr(row["facility_name_tr"]),
                    _blank(row["facility_type"]),
                    _blank(row["province_code"]),
                    float(lat) if lat else None,
                    float(lon) if lon else None,
                    _blank(row["coordinate_precision"]),
                    claim_id,
                    _blank(row["commodity_code"]),
                    _blank(row["commodity_label"]),
                    _blank(row["operational_status"]),
                    row["facility_ref"],
                ),
            )
            facility_ids[row["facility_ref"]] = int(cur.lastrowid)
            self.summary.facilities += 1

        name = "facility_organization_roles.csv"
        rows = _read_csv(self.public_dir / name)
        if not rows:
            return
        document_id = self._export_document(name)
        for row in rows:
            if row["facility_ref"] not in facility_ids:
                # The export lists roles for a site it leaves out of
                # facilities.csv (a duplicate or an out-of-scope entry). The
                # site is kept, marked so it stays out of the site list.
                claim_id = self._claim(
                    document_id, "facility", "facility_record", row["facility_name_tr"]
                )
                cur = self.conn.execute(
                    "INSERT INTO facilities (facility_name_tr, facility_name_normalized, "
                    "source_claim_id, external_ref, notes) VALUES (?, ?, ?, ?, ?)",
                    (
                        row["facility_name_tr"],
                        normalize_tr(row["facility_name_tr"]),
                        claim_id,
                        row["facility_ref"],
                        f"DUPLICATE of another site or OUT_OF_SCOPE at the export; "
                        f"{RESTORED_MARK}: absent from facilities.csv, present only in "
                        "facility_organization_roles.csv. See docs/corrections_log.csv.",
                    ),
                )
                facility_ids[row["facility_ref"]] = int(cur.lastrowid)
            organization_id = self._organization(
                row["organization_name_tr"],
                row["organization_country_code"],
                row["organization_country_label"],
                None,
            )
            claim_id = self._claim(
                document_id,
                "organization",
                row["role"],
                row["organization_name_tr"],
                assertion_status=row["assertion_status"],
            )
            self.conn.execute(
                "INSERT INTO facility_organization_roles (facility_id, organization_id, role, "
                "source_claim_id, assertion_status, review_status) "
                "VALUES (?, ?, ?, ?, ?, 'reviewed')",
                (
                    facility_ids[row["facility_ref"]],
                    organization_id,
                    row["role"],
                    claim_id,
                    row["assertion_status"],
                ),
            )

    def restore_uncited_rows(self) -> None:
        self._restore_classifications("incident_classifications.csv")
        self._restore_classifications("environmental_classifications.csv")
        self._restore_incident_roles()
        self._restore_effects()
        self._restore_facilities()

    # -- aggregate context ---------------------------------------------------

    def restore_aggregates(self, payload_path: Path) -> None:
        """Annual context series and rate figures, read back from the built
        dashboard payload, the only place they were published."""
        text = payload_path.read_text(encoding="utf-8")
        marker = "window.MINING_DATA = "
        payload = json.loads(text[text.index(marker) + len(marker) :].rstrip().rstrip(";"))
        document_id = self._export_document(payload_path.name, payload_path.parent)
        for row in payload.get("aggregates", []):
            year = int(row["year"])
            self.conn.execute(
                "INSERT INTO aggregate_occupational_statistics (reporting_institution, "
                "period_start, period_end, numerator, unit, source_document_id, "
                "comparability_notes) VALUES (?, ?, ?, ?, 'deaths', ?, ?)",
                (
                    row["institution"],
                    f"{year}-01-01",
                    f"{year}-12-31",
                    float(row["deaths"]),
                    document_id,
                    row["comparability_notes"],
                ),
            )
            self.summary.aggregates += 1
        unspecified: dict[str, int] = {}
        for row in payload.get("rate_context", []):
            year = row.get("year")
            version = None
            if year is None:
                index = unspecified.get(row["country"], 0)
                unspecified[row["country"]] = index + 1
                version = ("range_low", "range_high")[min(index, 1)]
            self.conn.execute(
                "INSERT INTO aggregate_occupational_statistics (reporting_institution, "
                "period_start, period_end, classification_system, classification_code, "
                "classification_version, numerator, denominator, unit, source_document_id, "
                "comparability_notes) VALUES (?, ?, ?, 'country', ?, ?, ?, ?, ?, ?, ?)",
                (
                    "Press figures via tr.wikipedia list article (cited therein)",
                    f"{year}-01-01" if year else None,
                    f"{year}-12-31" if year else None,
                    row["country"],
                    version,
                    float(row["value"]),
                    100_000_000.0,
                    row["unit"],
                    document_id,
                    row["comparability_notes"],
                ),
            )
            self.summary.aggregates += 1


def restore_from_export(
    db_path: str | Path,
    public_dir: str | Path = "data/public",
    reviewer: str = "",
    export_label: str = "committed export",
    export_url_base: str | None = None,
    payload_path: str | Path | None = None,
    withdrawn: dict[str, str] | None = None,
    title_redactions: dict[str, str] | None = None,
    observed_as_of: dict[str, str] | None = None,
    archive_index: str | Path | None = None,
    registry_csv: str | Path | None = "docs/source_registry.csv",
    migrations_dir: str | Path = "database/migrations",
) -> RestoreSummary:
    """Create ``db_path`` from the export in ``public_dir``. Never overwrites.

    ``reviewer`` is the person authorising the restoration; every restored
    decision is recorded under that name. ``withdrawn`` maps identifiers that
    were withdrawn without a merge to the reason. ``title_redactions`` replaces
    a published document title (used to drop a personal name from one).
    ``observed_as_of`` gives, per record, the date a casualty figure was
    observed where that is known; otherwise the export date is used.
    ``archive_index`` is the index written by
    scripts/archive_wikimedia_revisions.py: a cited page found in it gets the
    hash and permanent link of the revision current at its retrieval.
    """
    if not reviewer.strip():
        raise RestoreError("A reviewer must authorise the restoration")
    db_path, public_dir = Path(db_path), Path(public_dir)
    if db_path.exists() and db_path.stat().st_size > 0:
        raise RestoreError(f"{db_path} already exists; a restoration never overwrites")
    archive: dict[tuple[str, str], dict] = {}
    if archive_index is not None:
        for entry in json.loads(Path(archive_index).read_text(encoding="utf-8")):
            archive[(entry["url"], entry["retrieved_at"])] = entry
    started = utc_now_iso()
    create_database(db_path, migrations_dir, snapshot_path=None)
    conn = get_connection(db_path)
    try:
        if registry_csv is not None and Path(registry_csv).exists():
            import_source_registry(conn, registry_csv)
        restorer = _Restorer(
            conn,
            public_dir,
            reviewer.strip(),
            export_label,
            export_url_base,
            title_redactions or {},
            observed_as_of or {},
            archive,
        )
        restorer.restore_incidents()
        restorer.restore_withdrawn(withdrawn or {})
        restorer.restore_uncited_rows()
        if payload_path is not None:
            restorer.restore_aggregates(Path(payload_path))
        summary = restorer.summary
        review.log_review_action(
            conn,
            actor=reviewer.strip(),
            action="restore_from_export",
            notes=(
                f"{RESTORED_MARK}: database rebuilt from {export_label} "
                f"(export of {restorer.export_timestamp}). {summary.incidents} fatal and "
                f"{summary.environmental} environmental records, {summary.decisions} decisions, "
                f"{summary.claims} claims, {summary.documents} documents."
            ),
        )
        conn.commit()
        record_ingestion_run(
            conn,
            IngestionRun(
                run_type="migration",
                adapter_name="restore_from_export",
                adapter_version=EXTRACTOR_VERSION,
                started_at=started,
                input_reference=f"{public_dir.as_posix()} ({export_label})",
                records_created=summary.claims,
                status="completed",
                notes=f"{RESTORED_MARK}: see docs/database_recovery.md",
            ),
        )
        return summary
    finally:
        conn.close()
