"""Active-sites ingestion: Wikidata site items -> facilities registry.

Role in the evidence flow: routes the ``wikidata_sites`` adapter output into
``facilities``, ``organizations`` and ``facility_organization_roles``. The
facilities table is a *context registry*, not incident evidence: every stored
value keeps its ``source_claim_id`` and each registration is signed off in
``review_log`` under a named human reviewer — but the incident
``claim_decisions`` machinery stays incident-scoped by design
(docs/data_dictionary.md). Conflicting future site sources will be handled by
new claims plus a documented refresh, never silent overwrites of evidence.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from mining_accidents import review
from mining_accidents.adapters.base import ClaimDraft
from mining_accidents.adapters.wikidata_sites import WikidataSitesAdapter
from mining_accidents.database import utc_now_iso
from mining_accidents.models import IngestionRun
from mining_accidents.normalization import normalize_tr
from mining_accidents.provenance import record_ingestion_run

_SIGNOFF_NOTE = (
    "Site registered from Wikidata (CC0, tier-3) per project-owner directive "
    "of 2026-07-15. Open structured sources document a fraction of licensed "
    "operations; coverage is labeled partial wherever this layer is shown."
)

#: facility-subject claim fields written onto the facilities row.
_FACILITY_FIELDS = (
    "facility_name_tr",
    "facility_type",
    "commodity_code",
    "province_code",
    "latitude",
    "longitude",
    "operational_status",
)


@dataclass
class SitesSummary:
    run_id: int | None = None
    documents: int = 0
    facilities_created: int = 0
    facilities_updated: int = 0
    claims_created: int = 0
    organizations_created: int = 0
    roles_created: int = 0


def _insert_subject_claim(
    conn: sqlite3.Connection, source_document_id: int, subject_id: int, draft: ClaimDraft
) -> tuple[int, bool]:
    """Insert one facility/organization-subject claim (no incident linkage).

    Returns (claim_id, created). Idempotent on (document, subject, field,
    value) so re-runs corroborate instead of duplicating.
    """
    existing = conn.execute(
        "SELECT claim_id FROM claims WHERE source_document_id = ? AND claim_subject_type = ? "
        "AND claim_subject_id = ? AND field_name = ? AND normalized_value IS ?",
        (
            source_document_id,
            draft.claim_subject_type,
            subject_id,
            draft.field_name,
            draft.normalized_value,
        ),
    ).fetchone()
    if existing:
        return int(existing["claim_id"]), False
    cur = conn.execute(
        """
        INSERT INTO claims (
            source_document_id, claim_subject_type, claim_subject_id, field_name,
            raw_value, normalized_value, section_reference, extraction_method,
            extractor_version, assertion_status, review_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_document_id,
            draft.claim_subject_type,
            subject_id,
            draft.field_name,
            draft.raw_value,
            draft.normalized_value,
            draft.section_reference,
            draft.extraction_method,
            draft.extractor_version,
            draft.assertion_status,
            draft.review_status,
        ),
    )
    return int(cur.lastrowid), True


def _upsert_facility(conn: sqlite3.Connection, external_ref: str, name: str) -> tuple[int, bool]:
    row = conn.execute(
        "SELECT facility_id FROM facilities WHERE external_ref = ?", (external_ref,)
    ).fetchone()
    if row:
        return int(row["facility_id"]), False
    cur = conn.execute(
        "INSERT INTO facilities (facility_name_tr, facility_name_normalized, external_ref) "
        "VALUES (?, ?, ?)",
        (name, normalize_tr(name), external_ref),
    )
    return int(cur.lastrowid), True


def _upsert_organization(
    conn: sqlite3.Connection,
    name: str,
    external_ref: str | None,
    country_code: str | None,
    country_label: str | None,
) -> tuple[int, bool]:
    row = None
    if external_ref:
        row = conn.execute(
            "SELECT organization_id FROM organizations WHERE external_ref = ?", (external_ref,)
        ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT organization_id FROM organizations WHERE organization_name_normalized = ?",
            (normalize_tr(name),),
        ).fetchone()
    if row:
        org_id = int(row["organization_id"])
        if country_code or country_label or external_ref:
            conn.execute(
                "UPDATE organizations SET country_code = COALESCE(?, country_code), "
                "country_label = COALESCE(?, country_label), "
                "external_ref = COALESCE(?, external_ref) WHERE organization_id = ?",
                (country_code, country_label, external_ref, org_id),
            )
        return org_id, False
    cur = conn.execute(
        "INSERT INTO organizations (organization_name_tr, organization_name_normalized, "
        "organization_type, country_code, country_label, external_ref) "
        "VALUES (?, ?, 'unknown', ?, ?, ?)",
        (name, normalize_tr(name), country_code, country_label, external_ref),
    )
    return int(cur.lastrowid), True


def _write_facility_values(
    conn: sqlite3.Connection,
    facility_id: int,
    fields: dict[str, ClaimDraft],
    claim_ids: dict[str, int],
) -> None:
    """Copy claim-backed values onto the registry row, keeping provenance."""
    name = fields["facility_name_tr"].normalized_value
    commodity = fields.get("commodity_code")
    latitude = fields.get("latitude")
    longitude = fields.get("longitude")
    conn.execute(
        """
        UPDATE facilities SET
            facility_name_tr = ?, facility_name_normalized = ?, facility_type = ?,
            commodity_code = ?, commodity_label = ?, province_code = ?,
            latitude = ?, longitude = ?, coordinate_precision = ?,
            operational_status = ?, source_claim_id = ?, notes = ?
        WHERE facility_id = ?
        """,
        (
            name,
            normalize_tr(name or ""),
            fields.get("facility_type").normalized_value if fields.get("facility_type") else None,
            commodity.normalized_value if commodity else None,
            (commodity.notes.get("commodity_label") or None) if commodity else None,
            fields.get("province_code").normalized_value if fields.get("province_code") else None,
            float(latitude.normalized_value) if latitude else None,
            float(longitude.normalized_value) if longitude else None,
            "facility_approximate" if latitude and longitude else None,
            fields.get("operational_status").normalized_value
            if fields.get("operational_status")
            else None,
            claim_ids["facility_name_tr"],
            "Registered from open structured sources (partial coverage).",
            facility_id,
        ),
    )


def ingest_wikidata_sites(
    conn: sqlite3.Connection,
    reviewer: str | None = None,
    raw_dir: str | None = None,
) -> SitesSummary:
    """Fetch Wikidata mining-site items and register them as facilities.

    Without ``reviewer``, evidence rows (documents + claims) are still
    created but role rows stay ``pending`` and no sign-off is logged.
    """
    adapter = WikidataSitesAdapter(raw_dir) if raw_dir else WikidataSitesAdapter()
    started_at = utc_now_iso()
    document_ids = adapter.fetch(conn)
    summary = ingest_site_documents(conn, adapter, document_ids, reviewer)
    summary.run_id = record_ingestion_run(
        conn,
        IngestionRun(
            run_type="adapter",
            adapter_name=adapter.source_key,
            adapter_version=adapter.adapter_version,
            started_at=started_at,
            input_reference="wikidata SPARQL (P31/P279* Q820477, P17 Q43) + wbgetentities",
            records_created=summary.claims_created + summary.facilities_created,
            records_skipped=0,
            status="completed",
            notes=f"reviewer={reviewer or 'none'}",
        ),
    )
    return summary


def ingest_site_documents(
    conn: sqlite3.Connection,
    adapter: WikidataSitesAdapter,
    document_ids: list[int],
    reviewer: str | None = None,
) -> SitesSummary:
    """Adapter output -> facilities/organizations/roles (network-free half)."""
    summary = SitesSummary(documents=len(set(document_ids)))
    for doc_id in dict.fromkeys(document_ids):
        doc = conn.execute(
            "SELECT notes FROM source_documents WHERE source_document_id = ?", (doc_id,)
        ).fetchone()
        qid = next(
            (t[4:] for t in (doc["notes"] or "").split() if t.startswith("qid=")),
            None,
        )
        if not qid:
            continue
        drafts = adapter.parse(doc_id, conn)
        fields = {d.field_name: d for d in drafts if d.claim_subject_type == "facility"}
        if "facility_name_tr" not in fields:
            continue
        facility_id, created = _upsert_facility(
            conn, f"wikidata:{qid}", fields["facility_name_tr"].normalized_value or qid
        )
        summary.facilities_created += int(created)
        summary.facilities_updated += int(not created)

        claim_ids: dict[str, int] = {}
        for field_name in _FACILITY_FIELDS:
            draft = fields.get(field_name)
            if draft is None:
                continue
            claim_id, new = _insert_subject_claim(conn, doc_id, facility_id, draft)
            claim_ids[field_name] = claim_id
            summary.claims_created += int(new)
        _write_facility_values(conn, facility_id, fields, claim_ids)

        for draft in drafts:
            if draft.claim_subject_type != "organization":
                continue
            org_id, org_created = _upsert_organization(
                conn,
                draft.normalized_value or "",
                f"wikidata:{draft.notes['org_qid']}" if draft.notes.get("org_qid") else None,
                draft.notes.get("country_code") or None,
                draft.notes.get("country_label") or None,
            )
            summary.organizations_created += int(org_created)
            claim_id, _ = _insert_subject_claim(conn, doc_id, org_id, draft)
            role = draft.notes.get("role", "operator")
            exists = conn.execute(
                "SELECT 1 FROM facility_organization_roles WHERE facility_id = ? "
                "AND organization_id = ? AND role = ?",
                (facility_id, org_id, role),
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO facility_organization_roles (facility_id, organization_id, "
                    "role, source_claim_id, assertion_status, review_status) "
                    "VALUES (?, ?, ?, ?, 'reported', ?)",
                    (facility_id, org_id, role, claim_id, "reviewed" if reviewer else "pending"),
                )
                summary.roles_created += 1

        if reviewer:
            review.log_review_action(
                conn,
                reviewer,
                "facility_registered",
                "facility",
                facility_id,
                after_summary=f"wikidata:{qid} -> facility {facility_id}",
                notes=_SIGNOFF_NOTE,
            )
        conn.commit()
    return summary
