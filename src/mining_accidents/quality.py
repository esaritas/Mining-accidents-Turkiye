"""Quality-check suite.

Role in the evidence flow: the gate between the database and the public
export. Critical findings block export entirely; warnings surface issues for
reviewers. Results are written to ``data/interim/quality_report.json`` and
pretty-printed.

``reference_time`` exists so tests can pin "now" (synthetic fixtures use far
dates by design); production callers leave it None.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.table import Table

from mining_accidents import entity_resolution, geography, vocabularies
from mining_accidents.models import PUBLICATION_CRITICAL_FIELDS

Severity = Literal["critical", "warning", "info"]

DEFAULT_REPORT_PATH = Path("data/interim/quality_report.json")
REGISTRY_STALE_DAYS = 365


@dataclass(frozen=True)
class QualityFinding:
    check_id: str
    severity: Severity
    entity_ref: str
    message: str


def _now(reference_time: str | None) -> str:
    return reference_time or datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _incident_ref(row: sqlite3.Row) -> str:
    return row["public_incident_id"] or f"incident:{row['incident_id']}"


# ---------------------------------------------------------------------------
# Critical checks (block export)
# ---------------------------------------------------------------------------


def check_invalid_dates(
    conn: sqlite3.Connection, reference_time: str | None
) -> list[QualityFinding]:
    findings = []
    now = _now(reference_time)
    for row in conn.execute(
        """
        SELECT incident_id, public_incident_id, incident_start_datetime, incident_end_datetime
        FROM incidents WHERE incident_start_datetime IS NOT NULL
        """
    ):
        start, end = row["incident_start_datetime"], row["incident_end_datetime"]
        ref = _incident_ref(row)
        if end is not None and end < start:
            findings.append(
                QualityFinding("QC-C01", "critical", ref, f"end {end} before start {start}")
            )
        if start > now:
            findings.append(
                QualityFinding("QC-C01", "critical", ref, f"start {start} is in the future")
            )
        if start < "1800":
            findings.append(
                QualityFinding("QC-C01", "critical", ref, f"start {start} is before 1800")
            )
    return findings


def check_negative_casualties(conn: sqlite3.Connection) -> list[QualityFinding]:
    findings = []
    for row in conn.execute(
        """
        SELECT incident_id, public_incident_id, fatalities_current, injuries_current,
               missing_current
        FROM incidents
        WHERE COALESCE(fatalities_current, 0) < 0 OR COALESCE(injuries_current, 0) < 0
           OR COALESCE(missing_current, 0) < 0
        """
    ):
        findings.append(
            QualityFinding("QC-C02", "critical", _incident_ref(row), "negative casualty count")
        )
    for row in conn.execute(
        """
        SELECT observation_id FROM casualty_observations
        WHERE COALESCE(fatalities, 0) < 0 OR COALESCE(injuries, 0) < 0 OR COALESCE(missing, 0) < 0
        """
    ):
        findings.append(
            QualityFinding(
                "QC-C02",
                "critical",
                f"casualty_observation:{row['observation_id']}",
                "negative casualty count in observation",
            )
        )
    return findings


def check_admin_codes(conn: sqlite3.Connection) -> list[QualityFinding]:
    valid = vocabularies.codes("turkey_admin_areas")
    findings = []
    for row in conn.execute(
        "SELECT incident_id, public_incident_id, province_code FROM incidents "
        "WHERE province_code IS NOT NULL"
    ):
        if row["province_code"] not in valid:
            findings.append(
                QualityFinding(
                    "QC-C03",
                    "critical",
                    _incident_ref(row),
                    f"unknown province code {row['province_code']!r}",
                )
            )
    # District codes: no district vocabulary ships yet (open question #6);
    # the check activates once one exists.
    return findings


def check_exact_coordinates_have_source(conn: sqlite3.Connection) -> list[QualityFinding]:
    return [
        QualityFinding(
            "QC-C04",
            "critical",
            _incident_ref(row),
            "exact_verified coordinates without location_source_claim_id",
        )
        for row in conn.execute(
            "SELECT incident_id, public_incident_id FROM incidents "
            "WHERE coordinate_precision = 'exact_verified' AND location_source_claim_id IS NULL"
        )
    ]


def check_published_rows_have_source_claims(conn: sqlite3.Connection) -> list[QualityFinding]:
    findings = []
    for row in conn.execute(
        """
        SELECT i.incident_id, i.public_incident_id, c.classification_id
        FROM incidents i JOIN incident_classifications c ON c.incident_id = i.incident_id
        WHERE i.publication_status IN ('publishable', 'published')
          AND c.classification_system LIKE 'project_%' AND c.source_claim_id IS NULL
        """
    ):
        findings.append(
            QualityFinding(
                "QC-C05",
                "critical",
                _incident_ref(row),
                f"classification {row['classification_id']} lacks source_claim_id",
            )
        )
    # incident_organization_roles.source_claim_id is NOT NULL by schema; this
    # guards against rows inserted with foreign keys off.
    for row in conn.execute(
        """
        SELECT i.incident_id, i.public_incident_id, r.incident_organization_role_id AS role_id
        FROM incidents i JOIN incident_organization_roles r ON r.incident_id = i.incident_id
        WHERE i.publication_status IN ('publishable', 'published')
          AND r.source_claim_id IS NULL
        """
    ):
        findings.append(
            QualityFinding(
                "QC-C05",
                "critical",
                _incident_ref(row),
                f"organization role {row['role_id']} lacks source_claim_id",
            )
        )
    return findings


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


def check_publication_critical_decisions(
    conn: sqlite3.Connection, disclose_conflicts: bool = False
) -> list[QualityFinding]:
    findings = []
    for row in conn.execute(
        "SELECT incident_id, public_incident_id FROM incidents "
        "WHERE publication_status IN ('publishable', 'published')"
    ):
        active = _active_decisions(conn, row["incident_id"])
        for field in PUBLICATION_CRITICAL_FIELDS:
            decision = active.get(field)
            if decision is None:
                findings.append(
                    QualityFinding(
                        "QC-C06",
                        "critical",
                        _incident_ref(row),
                        f"no decision on publication-critical field {field!r}",
                    )
                )
            elif decision["decision"] == "defer" and not disclose_conflicts:
                findings.append(
                    QualityFinding(
                        "QC-C06",
                        "critical",
                        _incident_ref(row),
                        f"deferred decision on publication-critical field {field!r} "
                        "(conflict disclosure is disabled)",
                    )
                )
            elif decision["decision"] == "reject_field":
                findings.append(
                    QualityFinding(
                        "QC-C06",
                        "critical",
                        _incident_ref(row),
                        f"publication-critical field {field!r} was rejected",
                    )
                )
    return findings


def check_canonical_ai_claims_reviewed(conn: sqlite3.Connection) -> list[QualityFinding]:
    return [
        QualityFinding(
            "QC-C07",
            "critical",
            f"decision:{row['decision_id']}",
            f"selected claim {row['claim_id']} is {row['extraction_method']} but not reviewed",
        )
        for row in conn.execute(
            """
            SELECT d.decision_id, c.claim_id, c.extraction_method
            FROM claim_decisions d JOIN claims c ON c.claim_id = d.selected_claim_id
            WHERE d.decision = 'accept_claim'
              AND c.extraction_method IN ('ai_assisted', 'ocr_assisted')
              AND c.review_status != 'reviewed'
              AND NOT EXISTS (
                  SELECT 1 FROM claim_decisions s WHERE s.supersedes_decision_id = d.decision_id
              )
            """
        )
    ]


def check_cited_documents_complete(conn: sqlite3.Connection) -> list[QualityFinding]:
    """Documents behind decided or reviewed-and-published evidence need
    retrieved_at + content_hash; also surface any broken FKs."""
    findings = []
    for row in conn.execute(
        """
        SELECT DISTINCT sd.source_document_id, sd.retrieved_at, sd.content_hash
        FROM claims c
        JOIN source_documents sd ON sd.source_document_id = c.source_document_id
        WHERE c.claim_id IN (
            SELECT selected_claim_id FROM claim_decisions WHERE selected_claim_id IS NOT NULL
            UNION
            SELECT source_claim_id FROM incident_classifications
                WHERE source_claim_id IS NOT NULL
            UNION
            SELECT source_claim_id FROM incident_organization_roles
        )
        """
    ):
        missing = [
            name
            for name, value in (
                ("retrieved_at", row["retrieved_at"]),
                ("content_hash", row["content_hash"]),
            )
            if not value
        ]
        if missing:
            findings.append(
                QualityFinding(
                    "QC-C08",
                    "critical",
                    f"source_document:{row['source_document_id']}",
                    f"cited document missing {', '.join(missing)}",
                )
            )
    for violation in conn.execute("PRAGMA foreign_key_check"):
        findings.append(
            QualityFinding(
                "QC-C08",
                "critical",
                f"{violation[0]}:rowid={violation[1]}",
                f"broken foreign key to {violation[2]}",
            )
        )
    return findings


def check_reretrieval_hash_conflicts(conn: sqlite3.Connection) -> list[QualityFinding]:
    """Same url + same retrieved_at with different hashes means a document was
    re-recorded incorrectly instead of getting a new retrieval row."""
    return [
        QualityFinding(
            "QC-C09",
            "critical",
            f"url:{row['url']}",
            "conflicting content_hash values for the same url and retrieved_at",
        )
        for row in conn.execute(
            """
            SELECT url FROM source_documents
            WHERE url IS NOT NULL AND retrieved_at IS NOT NULL
            GROUP BY url, retrieved_at
            HAVING COUNT(DISTINCT content_hash) > 1
            """
        )
    ]


# ---------------------------------------------------------------------------
# Warning checks
# ---------------------------------------------------------------------------


def check_bbox(conn: sqlite3.Connection) -> list[QualityFinding]:
    findings = []
    for row in conn.execute(
        "SELECT incident_id, public_incident_id, latitude, longitude, coordinate_precision "
        "FROM incidents WHERE latitude IS NOT NULL OR longitude IS NOT NULL"
    ):
        for flag in geography.check_coordinates(
            row["latitude"], row["longitude"], row["coordinate_precision"]
        ):
            findings.append(QualityFinding("QC-W01", "warning", _incident_ref(row), flag))
    return findings


def check_duplicate_candidates(conn: sqlite3.Connection) -> list[QualityFinding]:
    return [
        QualityFinding(
            "QC-W02",
            "warning",
            f"incident:{c.incident_id_a}+incident:{c.incident_id_b}",
            f"duplicate candidate (province {c.province_code}, "
            f"{c.date_difference_days:.1f} days apart, similarity {c.name_similarity})",
        )
        for c in entity_resolution.find_duplicate_candidates(conn)
    ]


def check_conflicting_casualty_claims(conn: sqlite3.Connection) -> list[QualityFinding]:
    findings = []
    for row in conn.execute(
        """
        SELECT i.incident_id, i.public_incident_id,
               COUNT(DISTINCT COALESCE(c.normalized_value, c.raw_value)) AS distinct_values
        FROM incidents i JOIN claims c ON c.incident_id = i.incident_id
        WHERE c.field_name = 'fatalities_current'
        GROUP BY i.incident_id HAVING distinct_values > 1
        """
    ):
        if _active_decisions(conn, row["incident_id"]).get("fatalities_current") is None:
            findings.append(
                QualityFinding(
                    "QC-W03",
                    "warning",
                    _incident_ref(row),
                    f"{row['distinct_values']} conflicting fatality claims with no decision",
                )
            )
    return findings


def check_single_canonical_observation(conn: sqlite3.Connection) -> list[QualityFinding]:
    return [
        QualityFinding(
            "QC-W04",
            "warning",
            f"incident:{row['incident_id']}",
            f"{row['n']} casualty observations flagged is_current_canonical",
        )
        for row in conn.execute(
            "SELECT incident_id, COUNT(*) AS n FROM casualty_observations "
            "WHERE is_current_canonical = 1 GROUP BY incident_id HAVING n > 1"
        )
    ]


def check_source_registry_freshness(
    conn: sqlite3.Connection, reference_time: str | None
) -> list[QualityFinding]:
    findings = []
    now = datetime.fromisoformat(_now(reference_time).replace("Z", "+00:00"))
    stale_before = (now - timedelta(days=REGISTRY_STALE_DAYS)).strftime("%Y-%m-%d")
    for row in conn.execute("SELECT source_key, last_assessed FROM source_registry"):
        if not row["last_assessed"]:
            findings.append(
                QualityFinding(
                    "QC-W05",
                    "warning",
                    f"source_registry:{row['source_key']}",
                    "source never assessed (last_assessed empty)",
                )
            )
        elif row["last_assessed"] < stale_before:
            findings.append(
                QualityFinding(
                    "QC-W05",
                    "warning",
                    f"source_registry:{row['source_key']}",
                    f"assessment stale (last_assessed {row['last_assessed']})",
                )
            )
    return findings


def check_nace_versions(conn: sqlite3.Connection) -> list[QualityFinding]:
    findings = []
    for table in (
        "aggregate_occupational_statistics",
        "aggregate_employment",
        "aggregate_production",
        "aggregate_licence_context",
    ):
        for row in conn.execute(
            f"SELECT aggregate_id FROM {table} "
            "WHERE classification_system = 'NACE' AND classification_version IS NULL"
        ):
            findings.append(
                QualityFinding(
                    "QC-W06",
                    "warning",
                    f"{table}:{row['aggregate_id']}",
                    "NACE-coded aggregate without a classification_version "
                    "(incompatible-version comparisons cannot be detected)",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Runner / reporting
# ---------------------------------------------------------------------------


def run_all_checks(
    conn: sqlite3.Connection,
    reference_time: str | None = None,
    disclose_conflicts: bool = False,
) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    findings += check_invalid_dates(conn, reference_time)
    findings += check_negative_casualties(conn)
    findings += check_admin_codes(conn)
    findings += check_exact_coordinates_have_source(conn)
    findings += check_published_rows_have_source_claims(conn)
    findings += check_publication_critical_decisions(conn, disclose_conflicts)
    findings += check_canonical_ai_claims_reviewed(conn)
    findings += check_cited_documents_complete(conn)
    findings += check_reretrieval_hash_conflicts(conn)
    findings += check_bbox(conn)
    findings += check_duplicate_candidates(conn)
    findings += check_conflicting_casualty_claims(conn)
    findings += check_single_canonical_observation(conn)
    findings += check_source_registry_freshness(conn, reference_time)
    findings += check_nace_versions(conn)
    return findings


def has_critical(findings: list[QualityFinding]) -> bool:
    return any(f.severity == "critical" for f in findings)


def write_report(findings: list[QualityFinding], path: str | Path = DEFAULT_REPORT_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {
            severity: sum(1 for f in findings if f.severity == severity)
            for severity in ("critical", "warning", "info")
        },
        "findings": [asdict(f) for f in findings],
    }
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def print_report(findings: list[QualityFinding], console: Console | None = None) -> None:
    console = console or Console()
    if not findings:
        console.print("[green]Quality checks passed: no findings.[/green]")
        return
    table = Table(title="Quality findings")
    table.add_column("Check")
    table.add_column("Severity")
    table.add_column("Entity")
    table.add_column("Message")
    for f in sorted(findings, key=lambda f: (f.severity != "critical", f.check_id, f.entity_ref)):
        style = {"critical": "red", "warning": "yellow"}.get(f.severity, "")
        table.add_row(f.check_id, f"[{style}]{f.severity}[/{style}]", f.entity_ref, f.message)
    console.print(table)
