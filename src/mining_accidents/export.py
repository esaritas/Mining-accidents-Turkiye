"""Public export builder.

Role in the evidence flow: the final gate. Only incidents meeting ALL seven
publication rules (docs/editorial_and_legal_protocol.md §5) leave the
database, any critical quality finding aborts the export, and outputs are
deterministic (stable sort keys, fixed column orders) so re-runs on identical
data are byte-identical. The manifest timestamp honors ``SOURCE_DATE_EPOCH``
for reproducible builds (docs/open_questions.md implementation note D).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from mining_accidents import quality
from mining_accidents.models import ENVIRONMENTAL_CRITICAL_FIELDS, PUBLICATION_CRITICAL_FIELDS
from mining_accidents.provenance import get_git_commit
from mining_accidents.validators import DEFAULT_EXCERPT_MAX_WORDS
from mining_accidents.vocabularies import load_versions

DEFAULT_OUTPUT_DIR = Path("data/public")

INCIDENT_COLUMNS = [
    "public_incident_id",
    "canonical_title_tr",
    "canonical_title_en",
    "incident_start_datetime",
    "incident_end_datetime",
    "date_precision",
    "incident_status",
    "province_code",
    "province_name",
    "district_code",
    "settlement",
    "latitude",
    "longitude",
    "coordinate_precision",
    "location_uncertainty_m",
    "fatalities_current",
    "injuries_current",
    "missing_current",
    "casualty_status",
]

CLASSIFICATION_COLUMNS = [
    "public_incident_id",
    "classification_system",
    "classification_level",
    "classification_code",
    "classification_label_tr",
    "classification_label_en",
    "assertion_status",
]

ROLE_COLUMNS = [
    "public_incident_id",
    "organization_name_tr",
    "organization_type",
    "organization_country_code",
    "organization_country_label",
    "role",
    "valid_at_incident_date",
    "assertion_status",
]

SOURCE_COLUMNS = [
    "public_incident_id",
    "field_name",
    "source_organization",
    "title",
    "document_type",
    "url",
    "publication_date",
    "retrieved_at",
    "language",
    "source_tier",
    "short_evidence_excerpt",
]

FACILITY_COLUMNS = [
    "facility_ref",
    "facility_name_tr",
    "facility_type",
    "commodity_code",
    "commodity_label",
    "province_code",
    "province_name",
    "latitude",
    "longitude",
    "coordinate_precision",
    "operational_status",
    "source_url",
]

FACILITY_ROLE_COLUMNS = [
    "facility_ref",
    "facility_name_tr",
    "organization_name_tr",
    "organization_country_code",
    "organization_country_label",
    "role",
    "assertion_status",
]

ENVIRONMENTAL_COLUMNS = [
    "public_incident_id",
    "canonical_title_tr",
    "canonical_title_en",
    "incident_start_datetime",
    "date_precision",
    "province_code",
    "province_name",
    "latitude",
    "longitude",
    "coordinate_precision",
    "related_public_incident_id",
]

EFFECT_COLUMNS = [
    "public_incident_id",
    "effect_type",
    "measure_value",
    "measure_unit",
    "qualitative_value",
    "qualitative_value_en",
    "assertion_status",
    "effect_status",
]

REDIRECT_COLUMNS = ["merged_public_incident_id", "surviving_public_incident_id"]

CONFLICT_COLUMNS = ["public_incident_id", "field_name", "status"]


class ExportBlockedError(RuntimeError):
    """Raised when critical quality findings (or rule violations) block export."""


def _export_timestamp() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    moment = datetime.fromtimestamp(int(epoch), tz=UTC) if epoch else datetime.now(tz=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _active_decisions(conn: sqlite3.Connection, incident_id: int) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT d.* FROM claim_decisions d
        WHERE d.incident_id = ?
          AND NOT EXISTS (
              SELECT 1 FROM claim_decisions s WHERE s.supersedes_decision_id = d.decision_id
          )
        """,
        (incident_id,),
    ).fetchall()
    return {row["field_name"]: row for row in rows}


def publication_blockers(
    conn: sqlite3.Connection, incident_id: int, disclose_conflicts: bool = False
) -> list[str]:
    """Reasons the incident may NOT be published (empty list = eligible).

    Implements the seven-rule threshold. ``published`` is accepted alongside
    ``publishable`` for rule 7 so already-published records keep exporting.
    """
    row = conn.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
    if row is None:
        return ["incident does not exist"]
    blockers: list[str] = []

    if row["verification_status"] != "reviewed":  # rule 1
        blockers.append("verification_status is not 'reviewed'")
    if row["publication_status"] not in ("publishable", "published"):  # rule 7
        blockers.append("publication_status is not 'publishable' (editorial sign-off missing)")
    if not row["public_incident_id"]:
        blockers.append("no public_incident_id assigned")

    active = _active_decisions(conn, incident_id)
    critical = (
        ENVIRONMENTAL_CRITICAL_FIELDS
        if row["incident_kind"] == "environmental"
        else PUBLICATION_CRITICAL_FIELDS
    )
    for field in critical:  # rules 2, 3, 6
        decision = active.get(field)
        if decision is None:
            blockers.append(f"no accepted decision for {field}")
        elif decision["decision"] == "defer":
            if not disclose_conflicts:
                blockers.append(f"deferred decision on {field} without conflict disclosure")
        elif decision["decision"] not in ("accept_claim", "manual_override"):
            blockers.append(f"decision on {field} is {decision['decision']}, not an acceptance")

    undecided_rows = conn.execute(  # rule 4
        """
        SELECT COUNT(*) FROM incident_classifications
        WHERE incident_id = ? AND classification_system LIKE 'project_%'
          AND review_status = 'reviewed' AND source_claim_id IS NULL
        """,
        (incident_id,),
    ).fetchone()[0]
    if undecided_rows:
        blockers.append("reviewed project classification rows lack source_claim_id")

    if (row["latitude"] is not None or row["longitude"] is not None) and not row[
        "coordinate_precision"
    ]:  # rule 5
        blockers.append("coordinates present without a stated coordinate_precision")

    return blockers


def _disclosed_conflicts(conn: sqlite3.Connection, incident_id: int) -> list[dict[str, str]]:
    active = _active_decisions(conn, incident_id)
    return [
        {"field_name": field, "status": "deferred_conflict"}
        for field, decision in sorted(active.items())
        if decision["decision"] == "defer"
    ]


def _cap_excerpt(excerpt: str | None) -> str | None:
    """Belt-and-suspenders at the boundary: never export an overlong excerpt."""
    if excerpt is None:
        return None
    words = excerpt.split()
    if len(words) > DEFAULT_EXCERPT_MAX_WORDS:
        return None  # omitted entirely rather than truncated evidence
    return excerpt


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({col: row.get(col) for col in columns})
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _province_labels() -> dict[str, str]:
    from mining_accidents.vocabularies import load_vocabulary

    return {e.code: e.label_tr for e in load_vocabulary("turkey_admin_areas")}


def _collect_incident_rows(conn: sqlite3.Connection, ids: list[int]) -> list[dict[str, object]]:
    provinces = _province_labels()
    rows = []
    for incident_id in ids:
        row = conn.execute(
            "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
        ).fetchone()
        record = {col: row[col] for col in INCIDENT_COLUMNS if col != "province_name"}
        record["province_name"] = provinces.get(row["province_code"] or "", "")
        rows.append(record)
    return sorted(rows, key=lambda r: r["public_incident_id"])


def _collect_environmental_rows(
    conn: sqlite3.Connection, ids: list[int]
) -> list[dict[str, object]]:
    """Environmental records, with the fatal record they belong to where there
    is one. Kept in their own file so the fatal-accident totals never silently
    absorb a different kind of event."""
    provinces = _province_labels()
    rows = []
    for incident_id in ids:
        row = conn.execute(
            "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
        ).fetchone()
        record = {
            col: row[col]
            for col in ENVIRONMENTAL_COLUMNS
            if col not in ("province_name", "related_public_incident_id")
        }
        record["province_name"] = provinces.get(row["province_code"] or "", "")
        related = None
        if row["related_incident_id"] is not None:
            related = conn.execute(
                "SELECT public_incident_id FROM incidents WHERE incident_id = ?",
                (row["related_incident_id"],),
            ).fetchone()
        record["related_public_incident_id"] = related["public_incident_id"] if related else None
        rows.append(record)
    return sorted(rows, key=lambda r: r["public_incident_id"])


def _collect_effects(conn: sqlite3.Connection, ids: list[int]) -> list[dict[str, object]]:
    placeholders = ",".join("?" for _ in ids) or "NULL"
    rows = conn.execute(
        f"""
        SELECT i.public_incident_id, e.effect_type, e.measure_value, e.measure_unit,
               e.qualitative_value, e.qualitative_value_en, e.assertion_status,
               e.effect_status
        FROM environmental_effects e
        JOIN incidents i ON i.incident_id = e.incident_id
        WHERE e.incident_id IN ({placeholders})
          AND e.review_status = 'reviewed' AND e.source_claim_id IS NOT NULL
        ORDER BY i.public_incident_id, e.effect_type, e.environmental_effect_id
        """,
        ids,
    ).fetchall()
    return [dict(row) for row in rows]


def _collect_classifications(conn: sqlite3.Connection, ids: list[int]) -> list[dict[str, object]]:
    placeholders = ",".join("?" for _ in ids) or "NULL"
    rows = conn.execute(
        f"""
        SELECT i.public_incident_id, c.classification_system, c.classification_level,
               c.classification_code, c.classification_label_tr, c.classification_label_en,
               c.assertion_status
        FROM incident_classifications c
        JOIN incidents i ON i.incident_id = c.incident_id
        WHERE c.incident_id IN ({placeholders})
          AND c.review_status = 'reviewed' AND c.source_claim_id IS NOT NULL
        ORDER BY i.public_incident_id, c.classification_system, c.classification_code
        """,
        ids,
    ).fetchall()
    return [dict(row) for row in rows]


def _collect_roles(conn: sqlite3.Connection, ids: list[int]) -> list[dict[str, object]]:
    placeholders = ",".join("?" for _ in ids) or "NULL"
    rows = conn.execute(
        f"""
        SELECT i.public_incident_id, o.organization_name_tr, o.organization_type,
               o.country_code AS organization_country_code,
               o.country_label AS organization_country_label,
               r.role, r.valid_at_incident_date, r.assertion_status
        FROM incident_organization_roles r
        JOIN incidents i ON i.incident_id = r.incident_id
        JOIN organizations o ON o.organization_id = r.organization_id
        WHERE r.incident_id IN ({placeholders})
          AND r.review_status = 'reviewed' AND r.source_claim_id IS NOT NULL
        ORDER BY i.public_incident_id, o.organization_name_tr, r.role
        """,
        ids,
    ).fetchall()
    return [dict(row) for row in rows]


def _collect_sources(conn: sqlite3.Connection, ids: list[int]) -> list[dict[str, object]]:
    """Sources for active accepted values, including manual-override support.

    A manual override has no selected claim, but its supporting claims must
    still reach readers. Deferred/rejected and superseded decisions never do.
    """
    placeholders = ",".join("?" for _ in ids) or "NULL"
    rows = conn.execute(
        f"""
        SELECT i.public_incident_id, d.field_name, sd.source_organization, sd.title,
               sd.document_type, sd.url, sd.publication_date, sd.retrieved_at, sd.language,
               sd.source_tier, c.short_evidence_excerpt
        FROM claim_decisions d
        JOIN incidents i ON i.incident_id = d.incident_id
        JOIN claims c ON (
            (d.decision = 'accept_claim' AND c.claim_id = d.selected_claim_id)
            OR (d.decision = 'manual_override' AND c.claim_id IN (
                SELECT value FROM json_each(COALESCE(d.rationale_claim_ids, '[]'))
            ))
        )
        JOIN source_documents sd ON sd.source_document_id = c.source_document_id
        WHERE d.incident_id IN ({placeholders})
          AND (c.extraction_method NOT IN ('ai_assisted', 'ocr_assisted')
               OR c.review_status = 'reviewed')
          AND NOT EXISTS (
              SELECT 1 FROM claim_decisions s WHERE s.supersedes_decision_id = d.decision_id
          )
        ORDER BY i.public_incident_id, d.field_name, sd.source_organization, sd.title
        """,
        ids,
    ).fetchall()
    result = []
    for row in rows:
        entry = dict(row)
        entry["short_evidence_excerpt"] = _cap_excerpt(entry["short_evidence_excerpt"])
        result.append(entry)
    return result


def _collect_facilities(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Context-registry sites: claim-backed rows only (source_claim_id set).

    Coverage honesty: open structured sources document a fraction of licensed
    operations — the datapackage description and every display of this layer
    say so."""
    provinces = _province_labels()
    rows = conn.execute(
        """
        SELECT f.external_ref AS facility_ref, f.facility_name_tr, f.facility_type,
               f.commodity_code, f.commodity_label, f.province_code, f.latitude,
               f.longitude, f.coordinate_precision, f.operational_status, sd.url AS source_url
        FROM facilities f
        JOIN claims c ON c.claim_id = f.source_claim_id
        JOIN source_documents sd ON sd.source_document_id = c.source_document_id
        WHERE f.external_ref IS NOT NULL AND f.source_claim_id IS NOT NULL
          AND (f.notes IS NULL OR (f.notes NOT LIKE 'DUPLICATE of%'
               AND f.notes NOT LIKE 'OUT_OF_SCOPE%'))
        ORDER BY f.external_ref
        """
    ).fetchall()
    return [
        {**dict(row), "province_name": provinces.get(row["province_code"] or "", "")}
        for row in rows
    ]


def _collect_facility_roles(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT f.external_ref AS facility_ref, f.facility_name_tr,
               o.organization_name_tr, o.country_code AS organization_country_code,
               o.country_label AS organization_country_label, r.role, r.assertion_status
        FROM facility_organization_roles r
        JOIN facilities f ON f.facility_id = r.facility_id
        JOIN organizations o ON o.organization_id = r.organization_id
        WHERE r.review_status = 'reviewed' AND f.external_ref IS NOT NULL
        ORDER BY f.external_ref, o.organization_name_tr, r.role
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _collect_redirects(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Where a citation to a withdrawn identifier should now point.

    Derived from the incident ids in the merge log and the records' own
    publication status, never from ``merged_public_incident_id``. That column
    was stamped with the *survivor's* identifier rather than the merged one,
    so joining on it produced four self-redirects, the filter dropped them
    all, and four published identifiers resolved to nothing (quality audit
    2026-10-20, A1).

    Reading the ids also settles the other defect the audit found: the
    append-only log holds both directions for the same three merges, from a
    correction made on 2026-10-14. Direction is taken from the records
    themselves. A row counts only when the merged record really is withdrawn
    and the survivor really is published, which is true of one direction and
    false of the other.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT merged.public_incident_id AS merged_public_incident_id,
               survivor.public_incident_id AS surviving_public_incident_id
        FROM incident_merge_log m
        JOIN incidents merged ON merged.incident_id = m.merged_incident_id
        JOIN incidents survivor ON survivor.incident_id = m.surviving_incident_id
        WHERE merged.public_incident_id IS NOT NULL
          AND survivor.public_incident_id IS NOT NULL
          AND merged.public_incident_id <> survivor.public_incident_id
          AND merged.publication_status = 'withdrawn'
          AND survivor.publication_status IN ('publishable', 'published')
        ORDER BY merged.public_incident_id
        """
    ).fetchall()
    return [dict(row) for row in rows]


# Frictionless Table Schema field descriptors per column (any column not
# listed defaults to a plain string). Shared across resources so a column
# means the same type everywhere it appears.
_DATE_PRECISIONS = ["exact_datetime", "exact_date", "month", "year", "approximate"]
_FIELD_TYPES: dict[str, dict[str, object]] = {
    "public_incident_id": {"type": "string", "constraints": {"required": True}},
    "canonical_title_tr": {"type": "string", "constraints": {"required": True}},
    "canonical_title_en": {"type": "string"},
    "incident_start_datetime": {"type": "datetime"},
    "incident_end_datetime": {"type": "datetime"},
    "date_precision": {"type": "string", "constraints": {"enum": _DATE_PRECISIONS}},
    "incident_status": {"type": "string"},
    "province_code": {"type": "string"},
    "province_name": {"type": "string"},
    "district_code": {"type": "string"},
    "settlement": {"type": "string"},
    "latitude": {"type": "number", "constraints": {"minimum": -90, "maximum": 90}},
    "longitude": {"type": "number", "constraints": {"minimum": -180, "maximum": 180}},
    "coordinate_precision": {"type": "string"},
    "location_uncertainty_m": {"type": "number", "constraints": {"minimum": 0}},
    "fatalities_current": {"type": "integer", "constraints": {"minimum": 0}},
    "injuries_current": {"type": "integer", "constraints": {"minimum": 0}},
    "missing_current": {"type": "integer", "constraints": {"minimum": 0}},
    "casualty_status": {"type": "string"},
    "assertion_status": {"type": "string"},
    "effect_status": {"type": "string"},
    "valid_at_incident_date": {"type": "integer", "constraints": {"minimum": 0, "maximum": 1}},
    "url": {"type": "string", "format": "uri"},
    "source_url": {"type": "string", "format": "uri"},
    "publication_date": {"type": "date"},
    "retrieved_at": {"type": "datetime"},
    "facility_ref": {"type": "string", "constraints": {"required": True}},
    "facility_name_tr": {"type": "string", "constraints": {"required": True}},
}

# Primary keys and cross-resource foreign keys (resource name without .csv).
_RESOURCE_KEYS: dict[str, dict[str, object]] = {
    "incidents": {"primaryKey": "public_incident_id"},
    "incident_classifications": {
        "foreignKeys": [
            _FK := {
                "fields": "public_incident_id",
                "reference": {"resource": "incidents", "fields": "public_incident_id"},
            }
        ],
    },
    "incident_organization_roles": {"foreignKeys": [_FK]},
    "sources": {"foreignKeys": [_FK]},
    "facilities": {"primaryKey": "facility_ref"},
    "facility_organization_roles": {
        "foreignKeys": [
            {
                "fields": "facility_ref",
                "reference": {"resource": "facilities", "fields": "facility_ref"},
            }
        ],
    },
    "merged_id_redirects": {
        "primaryKey": "merged_public_incident_id",
        "foreignKeys": [
            {
                "fields": "surviving_public_incident_id",
                "reference": {"resource": "incidents", "fields": "public_incident_id"},
            }
        ],
    },
    "disclosed_conflicts": {"foreignKeys": [_FK]},
    "environmental_incidents": {"primaryKey": "public_incident_id"},
    "environmental_effects": {
        "foreignKeys": [
            {
                "fields": "public_incident_id",
                "reference": {
                    "resource": "environmental_incidents",
                    "fields": "public_incident_id",
                },
            }
        ],
    },
}


def _field_descriptor(col: str) -> dict[str, object]:
    return {"name": col, **_FIELD_TYPES.get(col, {"type": "string"})}


def _datapackage(resources: list[tuple[str, list[str]]]) -> dict[str, object]:
    return {
        "profile": "tabular-data-package",
        "name": "turkey-mining-accidents-public-export",
        "title": "Turkey Mining & Quarrying Accidents Database, public export",
        "description": (
            "Reviewed, source-traceable records of fatal mining and quarrying "
            "accidents in Türkiye. Every value traces to source documents through "
            "recorded reviewer decisions. Most records are seeded from tertiary "
            "open sources (Wikidata, Wikipedia) and await corroboration from "
            "official or professional-chamber sources; this is a partial research "
            "register, not a complete national registry. Assertion statuses must "
            "be displayed; 'alleged' is never established fact. Conditional rule: "
            "when latitude or longitude is present, coordinate_precision must also "
            "be present. facilities.csv is a context registry from open structured "
            "sources (Wikidata) covering only a fraction of licensed operations, "
            "not a complete register. See validation_report.json for a "
            "machine-readable check of these constraints."
        ),
        "resources": [
            {
                "name": name.removesuffix(".csv"),
                "path": name,
                "profile": "tabular-data-resource",
                "schema": {
                    "fields": [_field_descriptor(col) for col in columns],
                    **_RESOURCE_KEYS.get(name.removesuffix(".csv"), {}),
                },
            }
            for name, columns in resources
        ],
    }


def _validate_rows(name: str, columns: list[str], rows: list[dict[str, object]]) -> list[dict]:
    """Check exported rows against the declared field types and constraints.

    A lightweight, dependency-free validator (no network, no Frictionless
    runtime): types, integer/number ranges, enums, required fields, plus the
    cross-field coordinate rule. Returns a list of violation records.
    """
    errors: list[dict] = []

    def add(i: int, field: str, rule: str, value: object) -> None:
        errors.append(
            {
                "resource": name,
                "row": i,
                "field": field,
                "rule": rule,
                "value": None if value is None else str(value),
            }
        )

    for i, row in enumerate(rows):
        for col in columns:
            spec = _FIELD_TYPES.get(col)
            if spec is None:
                continue
            value = row.get(col)
            cons = spec.get("constraints", {})
            blank = value is None or value == ""
            if blank:
                if cons.get("required"):
                    add(i, col, "required", value)
                continue
            typ = spec["type"]
            if typ == "integer":
                try:
                    n = int(value)
                except (TypeError, ValueError):
                    add(i, col, "type:integer", value)
                    continue
                if "minimum" in cons and n < cons["minimum"]:
                    add(i, col, f"minimum:{cons['minimum']}", value)
            elif typ == "number":
                try:
                    x = float(value)
                except (TypeError, ValueError):
                    add(i, col, "type:number", value)
                    continue
                if "minimum" in cons and x < cons["minimum"]:
                    add(i, col, f"minimum:{cons['minimum']}", value)
                if "maximum" in cons and x > cons["maximum"]:
                    add(i, col, f"maximum:{cons['maximum']}", value)
            if "enum" in cons and value not in cons["enum"]:
                add(i, col, "enum", value)
        # Cross-field rule: coordinates require a stated precision.
        if "latitude" in columns or "longitude" in columns:
            has_coord = row.get("latitude") not in (None, "") or row.get("longitude") not in (
                None,
                "",
            )
            if has_coord and row.get("coordinate_precision") in (None, ""):
                add(i, "coordinate_precision", "required_when_coordinates_present", None)
    return errors


def _validation_report(
    datasets: list[tuple[str, list[str], list[dict[str, object]]]],
) -> dict[str, object]:
    per_resource: dict[str, object] = {}
    total = 0
    for name, columns, rows in datasets:
        errs = _validate_rows(name.removesuffix(".csv"), columns, rows)
        total += len(errs)
        per_resource[name.removesuffix(".csv")] = {
            "rows": len(rows),
            "error_count": len(errs),
            "errors": errs[:200],
        }
    return {
        "generated_at": _export_timestamp(),
        "validator": "internal lightweight schema validator (types, ranges, enums, "
        "required fields, coordinate-precision conditional)",
        "valid": total == 0,
        "total_errors": total,
        "resources": per_resource,
    }


def build_public_export(
    conn: sqlite3.Connection,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    reference_time: str | None = None,
    disclose_conflicts: bool = False,
) -> dict[str, object]:
    """Run QC, apply the publication threshold, and write the export.

    Raises ExportBlockedError on any critical quality finding.
    """
    findings = quality.run_all_checks(
        conn, reference_time=reference_time, disclose_conflicts=disclose_conflicts
    )
    criticals = [f for f in findings if f.severity == "critical"]
    if criticals:
        summary = "; ".join(f"{f.check_id} {f.entity_ref}: {f.message}" for f in criticals[:5])
        raise ExportBlockedError(
            f"{len(criticals)} critical quality finding(s) block the export: {summary}"
        )

    candidate_ids = [
        row["incident_id"]
        for row in conn.execute(
            "SELECT incident_id FROM incidents "
            "WHERE publication_status IN ('publishable', 'published')"
        )
    ]
    eligible_all = [
        incident_id
        for incident_id in candidate_ids
        if not publication_blockers(conn, incident_id, disclose_conflicts)
    ]
    kinds = {
        row["incident_id"]: row["incident_kind"]
        for row in conn.execute("SELECT incident_id, incident_kind FROM incidents")
    }
    # incidents.csv is the fatal-accident register and stays that way; an
    # environmental record never enters the death counts.
    eligible_ids = [i for i in eligible_all if kinds.get(i) != "environmental"]
    environmental_ids = [i for i in eligible_all if kinds.get(i) == "environmental"]

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    incidents = _collect_incident_rows(conn, eligible_ids)
    classifications = _collect_classifications(conn, eligible_ids)
    roles = _collect_roles(conn, eligible_ids)
    sources = _collect_sources(conn, eligible_ids)
    environmental = _collect_environmental_rows(conn, environmental_ids)
    effects = _collect_effects(conn, environmental_ids)
    environmental_classifications = _collect_classifications(conn, environmental_ids)
    environmental_sources = _collect_sources(conn, environmental_ids)
    facilities = _collect_facilities(conn)
    facility_roles = _collect_facility_roles(conn)
    redirects = _collect_redirects(conn)
    conflicts: list[dict[str, object]] = []
    if disclose_conflicts:
        by_public_id = {
            row["public_incident_id"]: row_id
            for row_id, row in zip(
                eligible_ids,
                (
                    conn.execute(
                        "SELECT public_incident_id FROM incidents WHERE incident_id = ?", (i,)
                    ).fetchone()
                    for i in eligible_ids
                ),
                strict=True,
            )
        }
        for public_id in sorted(by_public_id):
            for conflict in _disclosed_conflicts(conn, by_public_id[public_id]):
                conflicts.append({"public_incident_id": public_id, **conflict})

    _write_csv(output_dir / "incidents.csv", INCIDENT_COLUMNS, incidents)
    _write_json(output_dir / "incidents.json", incidents)
    _write_csv(output_dir / "incident_classifications.csv", CLASSIFICATION_COLUMNS, classifications)
    _write_csv(output_dir / "incident_organization_roles.csv", ROLE_COLUMNS, roles)
    _write_csv(output_dir / "sources.csv", SOURCE_COLUMNS, sources)
    _write_csv(output_dir / "facilities.csv", FACILITY_COLUMNS, facilities)
    _write_csv(
        output_dir / "facility_organization_roles.csv", FACILITY_ROLE_COLUMNS, facility_roles
    )
    _write_csv(output_dir / "environmental_incidents.csv", ENVIRONMENTAL_COLUMNS, environmental)
    _write_csv(output_dir / "environmental_effects.csv", EFFECT_COLUMNS, effects)
    _write_csv(
        output_dir / "environmental_classifications.csv",
        CLASSIFICATION_COLUMNS,
        environmental_classifications,
    )
    _write_csv(output_dir / "environmental_sources.csv", SOURCE_COLUMNS, environmental_sources)
    _write_csv(output_dir / "merged_id_redirects.csv", REDIRECT_COLUMNS, redirects)
    if disclose_conflicts:
        _write_csv(output_dir / "disclosed_conflicts.csv", CONFLICT_COLUMNS, conflicts)

    resources = [
        ("incidents.csv", INCIDENT_COLUMNS),
        ("incident_classifications.csv", CLASSIFICATION_COLUMNS),
        ("incident_organization_roles.csv", ROLE_COLUMNS),
        ("sources.csv", SOURCE_COLUMNS),
        ("facilities.csv", FACILITY_COLUMNS),
        ("facility_organization_roles.csv", FACILITY_ROLE_COLUMNS),
        ("merged_id_redirects.csv", REDIRECT_COLUMNS),
        ("environmental_incidents.csv", ENVIRONMENTAL_COLUMNS),
        ("environmental_effects.csv", EFFECT_COLUMNS),
        ("environmental_classifications.csv", CLASSIFICATION_COLUMNS),
        ("environmental_sources.csv", SOURCE_COLUMNS),
    ]
    if disclose_conflicts:
        resources.append(("disclosed_conflicts.csv", CONFLICT_COLUMNS))
    _write_json(output_dir / "datapackage.json", _datapackage(resources))

    # Machine-readable validation of the exported rows against the schema.
    datasets = [
        ("incidents.csv", INCIDENT_COLUMNS, incidents),
        ("incident_classifications.csv", CLASSIFICATION_COLUMNS, classifications),
        ("incident_organization_roles.csv", ROLE_COLUMNS, roles),
        ("sources.csv", SOURCE_COLUMNS, sources),
        ("facilities.csv", FACILITY_COLUMNS, facilities),
        ("facility_organization_roles.csv", FACILITY_ROLE_COLUMNS, facility_roles),
        ("merged_id_redirects.csv", REDIRECT_COLUMNS, redirects),
        ("environmental_incidents.csv", ENVIRONMENTAL_COLUMNS, environmental),
        ("environmental_effects.csv", EFFECT_COLUMNS, effects),
        (
            "environmental_classifications.csv",
            CLASSIFICATION_COLUMNS,
            environmental_classifications,
        ),
        ("environmental_sources.csv", SOURCE_COLUMNS, environmental_sources),
    ]
    if disclose_conflicts:
        datasets.append(("disclosed_conflicts.csv", CONFLICT_COLUMNS, conflicts))
    validation = _validation_report(datasets)
    _write_json(output_dir / "validation_report.json", validation)

    schema_version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    manifest = {
        "export_timestamp": _export_timestamp(),
        "git_commit": get_git_commit(),
        "db_schema_version": schema_version,
        "row_counts": {
            "incidents": len(incidents),
            "incident_classifications": len(classifications),
            "incident_organization_roles": len(roles),
            "sources": len(sources),
            "facilities": len(facilities),
            "facility_organization_roles": len(facility_roles),
            "merged_id_redirects": len(redirects),
            "environmental_incidents": len(environmental),
            "environmental_effects": len(effects),
            **({"disclosed_conflicts": len(conflicts)} if disclose_conflicts else {}),
        },
        "file_sha256": {
            name: _sha256(output_dir / name)
            for name, _ in [
                *resources,
                ("incidents.json", []),
                ("datapackage.json", []),
                ("validation_report.json", []),
            ]
        },
        "vocabulary_versions": {row["file"]: row["version"] for row in load_versions()},
        "quality_findings": {
            "critical": 0,
            "warning": sum(1 for f in findings if f.severity == "warning"),
        },
        "schema_validation": {
            "valid": validation["valid"],
            "total_errors": validation["total_errors"],
        },
    }
    _write_json(output_dir / "export_manifest.json", manifest)
    return manifest
