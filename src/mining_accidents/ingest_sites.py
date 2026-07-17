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

from mining_accidents import geo, review
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
    """Copy claim-backed values onto the registry row, keeping provenance.

    Where the sources state coordinates but no admin area, the containing
    province is derived mechanically (point-in-polygon against public-domain
    reference geometry) and recorded as a derivation, never as a source
    assertion.
    """
    name = fields["facility_name_tr"].normalized_value
    commodity = fields.get("commodity_code")
    latitude = fields.get("latitude")
    longitude = fields.get("longitude")
    province = fields.get("province_code").normalized_value if fields.get("province_code") else None
    notes = "Registered from open structured sources (partial coverage)."
    if province is None and latitude and longitude:
        derived = geo.province_of_point(
            float(latitude.normalized_value), float(longitude.normalized_value)
        )
        if derived:
            province = derived
            notes += (
                " Province derived from source-stated coordinates "
                "(point-in-polygon, Natural Earth reference geometry)."
            )
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
            province,
            float(latitude.normalized_value) if latitude else None,
            float(longitude.normalized_value) if longitude else None,
            "facility_approximate" if latitude and longitude else None,
            fields.get("operational_status").normalized_value
            if fields.get("operational_status")
            else None,
            claim_ids["facility_name_tr"],
            notes,
            facility_id,
        ),
    )


def _generic_tokens() -> frozenset[str]:
    """Tokens too generic to identify a facility on their own: mining
    vocabulary AND province names (a province name locates, it does not
    identify a specific facility)."""
    from mining_accidents import vocabularies

    words = (
        "maden madeni madenleri mine mines mining coal kömür kömürü ocağı "
        "ocakları ocak işletmesi işletmeleri sahası tesisi quarry taş altın "
        "gümüş bakır demir krom bor linyit antik"
    ).split()
    provinces = [e.label_tr for e in vocabularies.load_vocabulary("turkey_admin_areas")]
    return frozenset(normalize_tr(w) for w in words + provinces)


_LINK_RATIONALE = (
    "Deterministic facility link (documented rule, STATUS: PROPOSED — "
    "docs/open_questions.md #19 note): every distinctive token of the "
    "facility's name appears in the incident title AND the stated provinces "
    "match, with exactly one candidate facility. Coordinates are the "
    "facility's source-stated coordinates; precision is therefore "
    "facility_approximate by construction. Supersedable like any decision."
)


def link_incident_facilities(conn: sqlite3.Connection, reviewer: str) -> int:
    """Give coordinate-less incidents their facility's coordinates.

    Conservative blocking rule: all distinctive name tokens of a registered
    facility appear in the incident title, provinces match, and exactly one
    facility qualifies. Recorded as manual_override decisions referencing the
    facility's source claim — never a silent write.
    """
    from mining_accidents.models import ClaimDecision

    facilities = conn.execute(
        "SELECT facility_id, facility_name_tr, facility_name_normalized, province_code, "
        "latitude, longitude, source_claim_id FROM facilities "
        "WHERE latitude IS NOT NULL AND province_code IS NOT NULL "
        "AND source_claim_id IS NOT NULL"
    ).fetchall()
    incidents = conn.execute(
        "SELECT incident_id, canonical_title_tr_normalized, province_code FROM incidents "
        "WHERE latitude IS NULL AND province_code IS NOT NULL"
    ).fetchall()
    generic = _generic_tokens()
    linked = 0
    for incident in incidents:
        title_tokens = set((incident["canonical_title_tr_normalized"] or "").split())
        matches = []
        for facility in facilities:
            if facility["province_code"] != incident["province_code"]:
                continue
            distinctive = [
                token
                for token in (facility["facility_name_normalized"] or "").split()
                if token not in generic
            ]
            if distinctive and all(token in title_tokens for token in distinctive):
                matches.append(facility)
        if len({m["facility_id"] for m in matches}) != 1:
            continue  # ambiguous or no match: never guessed
        facility = matches[0]
        if review.get_active_decision(conn, incident["incident_id"], "latitude") is not None:
            continue
        for field_name, value in (
            ("latitude", f"{facility['latitude']:.6f}"),
            ("longitude", f"{facility['longitude']:.6f}"),
            ("coordinate_precision", "facility_approximate"),
        ):
            review.record_decision(
                conn,
                ClaimDecision(
                    incident_id=incident["incident_id"],
                    field_name=field_name,
                    decision="manual_override",
                    manual_value=value,
                    rationale=_LINK_RATIONALE,
                    rationale_claim_ids=[facility["source_claim_id"]],
                    reviewer=reviewer,
                ),
            )
        conn.execute(
            "UPDATE incidents SET facility_id = ? WHERE incident_id = ?",
            (facility["facility_id"], incident["incident_id"]),
        )
        review.log_review_action(
            conn,
            reviewer,
            "incident_facility_linked",
            "incident",
            incident["incident_id"],
            after_summary=f"facility {facility['facility_id']} ({facility['facility_name_tr']})",
            notes=_LINK_RATIONALE,
        )
        linked += 1
    conn.commit()
    return linked


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
    if reviewer:
        link_incident_facilities(conn, reviewer)
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
    """Adapter output -> facilities/organizations/roles (network-free half).

    Documents are grouped per site QID: the structured item is authoritative;
    a linked article document only contributes coordinate claims where the
    item has none (extraction-method priority: api over html_parser).
    """
    summary = SitesSummary(documents=len(set(document_ids)))
    groups: dict[str, list[int]] = {}
    for doc_id in dict.fromkeys(document_ids):
        doc = conn.execute(
            "SELECT notes FROM source_documents WHERE source_document_id = ?", (doc_id,)
        ).fetchone()
        qid = next(
            (t[4:] for t in (doc["notes"] or "").split() if t.startswith("qid=")),
            None,
        )
        if qid:
            groups.setdefault(qid, []).append(doc_id)

    for qid, doc_ids in sorted(groups.items()):
        doc_drafts: list[tuple[int, object]] = []
        for doc_id in doc_ids:
            for draft in adapter.parse(doc_id, conn):
                doc_drafts.append((doc_id, draft))
        fields: dict[str, tuple[int, ClaimDraft]] = {}
        for doc_id, draft in doc_drafts:
            if draft.claim_subject_type != "facility":
                continue
            current = fields.get(draft.field_name)
            # The structured item (api) outranks article infoboxes.
            if current is None or (
                current[1].extraction_method != "api" and draft.extraction_method == "api"
            ):
                fields[draft.field_name] = (doc_id, draft)
        if "facility_name_tr" not in fields:
            continue
        facility_id, created = _upsert_facility(
            conn, f"wikidata:{qid}", fields["facility_name_tr"][1].normalized_value or qid
        )
        summary.facilities_created += int(created)
        summary.facilities_updated += int(not created)

        claim_ids: dict[str, int] = {}
        for field_name in _FACILITY_FIELDS:
            entry = fields.get(field_name)
            if entry is None:
                continue
            claim_id, new = _insert_subject_claim(conn, entry[0], facility_id, entry[1])
            claim_ids[field_name] = claim_id
            summary.claims_created += int(new)
        _write_facility_values(conn, facility_id, {k: v[1] for k, v in fields.items()}, claim_ids)

        for doc_id, draft in doc_drafts:
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
