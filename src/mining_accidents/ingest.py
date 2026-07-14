"""Seed ingestion: adapter output -> incidents + claims (+ optional decisions).

Role in the evidence flow: turns adapter fetch/parse results into linked
evidence rows, and — only when a human reviewer identity is supplied — records
bulk *accept* decisions under a documented, deterministic source-priority
rule. Unreviewed ``ai_assisted`` claims are never selected; incomplete
records stay unpublished. Everything is auditable in ``claim_decisions`` and
``review_log``, and every decision can later be superseded per the conflict
resolution protocol.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from mining_accidents import review
from mining_accidents.adapters.base import ClaimDraft
from mining_accidents.adapters.wikidata import WikidataAdapter
from mining_accidents.database import utc_now_iso
from mining_accidents.models import ClaimDecision, IngestionRun
from mining_accidents.normalization import normalize_tr
from mining_accidents.provenance import record_ingestion_run

#: field -> decision order. Wikipedia infobox values (html_parser) are the
#: current-revision figures and win over the structured item; ai_assisted is
#: never auto-selected (hard constraint 5).
_METHOD_PRIORITY = {"html_parser": 0, "api": 1}

_DECIDED_FIELDS = (
    "canonical_title_tr",
    "canonical_title_en",
    "incident_start_datetime",
    "date_precision",
    "province_code",
    "fatalities_current",
    "latitude",
    "longitude",
)
_PUBLICATION_FIELDS = ("incident_start_datetime", "province_code", "fatalities_current")

_BULK_RATIONALE = (
    "Bulk-accepted from tier-3 seed sources (priority: Wikipedia infobox > "
    "Wikidata item) per project-owner directive of 2026-07-13. Single-pass "
    "seeding; value awaits corroboration against Tier 1-2 sources and may be "
    "superseded per docs/conflict_resolution_protocol.md."
)


@dataclass
class IngestSummary:
    run_id: int | None = None
    documents: int = 0
    incidents_created: int = 0
    claims_created: int = 0
    decisions_recorded: int = 0
    published: list[str] = field(default_factory=list)
    unpublished: dict[str, list[str]] = field(default_factory=dict)
    claims_needing_review: int = 0


def _insert_claim(
    conn: sqlite3.Connection, incident_id: int, source_document_id: int, draft: ClaimDraft
) -> bool:
    """Insert one claim; returns False when an identical claim already exists."""
    existing = conn.execute(
        "SELECT 1 FROM claims WHERE incident_id = ? AND source_document_id = ? "
        "AND field_name = ? AND normalized_value IS ?",
        (incident_id, source_document_id, draft.field_name, draft.normalized_value),
    ).fetchone()
    if existing:
        return False
    conn.execute(
        """
        INSERT INTO claims (
            incident_id, source_document_id, claim_subject_type, claim_subject_id,
            field_name, raw_value, normalized_value, unit, page_number,
            section_reference, short_evidence_excerpt, extraction_method,
            extractor_version, assertion_status, confidence_score, review_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            incident_id,
            source_document_id,
            draft.claim_subject_type,
            draft.claim_subject_id,
            draft.field_name,
            draft.raw_value,
            draft.normalized_value,
            draft.unit,
            draft.page_number,
            draft.section_reference,
            draft.short_evidence_excerpt,
            draft.extraction_method,
            draft.extractor_version,
            draft.assertion_status,
            draft.confidence_score,
            draft.review_status,
        ),
    )
    return True


def _find_or_create_incident(
    conn: sqlite3.Connection, qid: str, title_tr: str | None, title_en: str | None
) -> tuple[int, bool]:
    marker = f"wikidata:{qid}"
    row = conn.execute(
        "SELECT incident_id FROM incidents WHERE scope_rationale LIKE ?", (f"%{marker}%",)
    ).fetchone()
    if row:
        return int(row["incident_id"]), False
    title = title_tr or title_en or qid
    cur = conn.execute(
        "INSERT INTO incidents (canonical_title_tr, canonical_title_en, "
        "canonical_title_tr_normalized, incident_status, scope_rationale) "
        "VALUES (?, ?, ?, 'scope_undetermined', ?)",
        (
            title_tr or title,
            title_en,
            normalize_tr(title),
            f"Seeded from {marker}; scope set after date/fatality decisions.",
        ),
    )
    return int(cur.lastrowid), True


def _qid_of(notes: str | None) -> str | None:
    for token in (notes or "").split():
        if token.startswith("qid="):
            return token[4:]
    return None


def ingest_wikidata(
    conn: sqlite3.Connection,
    reviewer: str | None = None,
    publish: bool = True,
    raw_dir: str | None = None,
) -> IngestSummary:
    """Fetch, link, and (optionally) bulk-decide the Wikidata/Wikipedia seed.

    Without ``reviewer``, only evidence rows are created — no decisions, no
    publication. With ``reviewer``, deterministic bulk accepts are recorded in
    that human identity's name.
    """
    started_at = utc_now_iso()
    adapter = WikidataAdapter(raw_dir) if raw_dir else WikidataAdapter()
    summary = IngestSummary()

    document_ids = adapter.fetch(conn)
    summary.documents = len(set(document_ids))

    docs_by_qid: dict[str, list[sqlite3.Row]] = {}
    for doc_id in dict.fromkeys(document_ids):
        row = conn.execute(
            "SELECT * FROM source_documents WHERE source_document_id = ?", (doc_id,)
        ).fetchone()
        qid = _qid_of(row["notes"])
        if qid:
            docs_by_qid.setdefault(qid, []).append(row)

    incident_ids: dict[str, int] = {}
    for qid, docs in sorted(docs_by_qid.items()):
        drafts_by_doc = {
            doc["source_document_id"]: adapter.parse(doc["source_document_id"], conn)
            for doc in docs
        }
        titles = {
            draft.field_name: draft.normalized_value
            for drafts in drafts_by_doc.values()
            for draft in drafts
            if draft.field_name.startswith("canonical_title")
        }
        incident_id, created = _find_or_create_incident(
            conn, qid, titles.get("canonical_title_tr"), titles.get("canonical_title_en")
        )
        incident_ids[qid] = incident_id
        summary.incidents_created += int(created)
        for doc_id, drafts in drafts_by_doc.items():
            for draft in drafts:
                summary.claims_created += int(_insert_claim(conn, incident_id, doc_id, draft))
    conn.commit()

    if reviewer:
        for qid, incident_id in sorted(incident_ids.items()):
            summary.decisions_recorded += _bulk_decide(conn, incident_id, reviewer)
            _set_scope(conn, incident_id, reviewer)
            if publish:
                public_id_or_blockers = _publish_if_complete(conn, incident_id, reviewer)
                if isinstance(public_id_or_blockers, str):
                    summary.published.append(public_id_or_blockers)
                else:
                    summary.unpublished[qid] = public_id_or_blockers

    summary.claims_needing_review = conn.execute(
        "SELECT COUNT(*) FROM claims WHERE review_status = 'needs_review'"
    ).fetchone()[0]
    summary.run_id = record_ingestion_run(
        conn,
        IngestionRun(
            run_type="adapter",
            adapter_name=adapter.source_key,
            adapter_version=adapter.adapter_version,
            started_at=started_at,
            input_reference="wikidata SPARQL + wbgetentities + wikipedia parse API",
            records_created=summary.claims_created + summary.incidents_created,
            records_skipped=0,
            status="completed",
            notes=f"reviewer={reviewer or 'none'} publish={publish}",
        ),
    )
    return summary


def _bulk_decide(conn: sqlite3.Connection, incident_id: int, reviewer: str) -> int:
    decisions = 0
    for field_name in _DECIDED_FIELDS:
        if review.get_active_decision(conn, incident_id, field_name) is not None:
            continue
        candidates = conn.execute(
            """
            SELECT claim_id, extraction_method, normalized_value FROM claims
            WHERE incident_id = ? AND field_name = ?
              AND NOT (extraction_method IN ('ai_assisted', 'ocr_assisted')
                       AND review_status != 'reviewed')
            ORDER BY claim_id
            """,
            (incident_id, field_name),
        ).fetchall()
        if not candidates:
            continue
        chosen = min(
            candidates,
            key=lambda c: (_METHOD_PRIORITY.get(c["extraction_method"], 9), c["claim_id"]),
        )
        distinct_values = {c["normalized_value"] for c in candidates}
        rationale = _BULK_RATIONALE
        if len(distinct_values) > 1:
            rationale += f" NOTE: {len(distinct_values)} distinct values were present."
        review.record_decision(
            conn,
            ClaimDecision(
                incident_id=incident_id,
                field_name=field_name,
                decision="accept_claim",
                selected_claim_id=chosen["claim_id"],
                rationale=rationale,
                reviewer=reviewer,
            ),
        )
        decisions += 1

    # Coordinates decided -> precision must be stated (publication rule 5).
    incident = conn.execute(
        "SELECT latitude, longitude, coordinate_precision FROM incidents WHERE incident_id = ?",
        (incident_id,),
    ).fetchone()
    if (
        incident["latitude"] is not None
        and incident["coordinate_precision"] is None
        and review.get_active_decision(conn, incident_id, "coordinate_precision") is None
    ):
        lat_decision = review.get_active_decision(conn, incident_id, "latitude")
        review.record_decision(
            conn,
            ClaimDecision(
                incident_id=incident_id,
                field_name="coordinate_precision",
                decision="manual_override",
                manual_value="facility_approximate",
                rationale=(
                    "Seed coordinates locate the facility/settlement, not a "
                    "verified exact point; conservatively categorized "
                    "facility_approximate. " + _BULK_RATIONALE
                ),
                rationale_claim_ids=[lat_decision["selected_claim_id"]],
                reviewer=reviewer,
            ),
        )
        decisions += 1
    return decisions


def _set_scope(conn: sqlite3.Connection, incident_id: int, reviewer: str) -> None:
    row = conn.execute(
        "SELECT incident_start_datetime, fatalities_current, scope_rationale, incident_status "
        "FROM incidents WHERE incident_id = ?",
        (incident_id,),
    ).fetchone()
    if row["incident_status"] != "scope_undetermined":
        return
    date, fatalities = row["incident_start_datetime"], row["fatalities_current"]
    if date is None:
        return  # stays scope_undetermined until the date is decided
    if date < "2010-01-01":
        status, reason = "out_of_scope", "pre-2010 incident (MVP scope starts 2010-01-01)"
    elif fatalities == 0:
        status, reason = "out_of_scope", "non-fatal incident (MVP scope is fatal incidents)"
    elif fatalities is None:
        return  # cannot confirm fatal scope yet
    else:
        status, reason = "in_scope", "fatal mining incident in Türkiye within 2010-present"
    conn.execute(
        "UPDATE incidents SET incident_status = ?, scope_rationale = scope_rationale || ' | ' || ? "
        "WHERE incident_id = ?",
        (status, reason, incident_id),
    )
    review.log_review_action(
        conn, reviewer, "set_scope", "incident", incident_id, after_summary=f"{status}: {reason}"
    )
    conn.commit()


def _publish_if_complete(
    conn: sqlite3.Connection, incident_id: int, reviewer: str
) -> str | list[str]:
    """Sign off complete in-scope records; return public id or blocker list."""
    row = conn.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
    blockers: list[str] = []
    if row["incident_status"] != "in_scope":
        blockers.append(f"incident_status={row['incident_status']}")
    for field_name in _PUBLICATION_FIELDS:
        decision = review.get_active_decision(conn, incident_id, field_name)
        if decision is None or decision["decision"] not in ("accept_claim", "manual_override"):
            blockers.append(f"undecided:{field_name}")
    if blockers:
        return blockers
    if not row["public_incident_id"]:
        review.assign_public_incident_id(conn, incident_id, actor=reviewer)
    conn.execute(
        "UPDATE incidents SET verification_status = 'reviewed', "
        "publication_status = 'publishable' WHERE incident_id = ?",
        (incident_id,),
    )
    review.log_review_action(
        conn,
        reviewer,
        "publication_signoff",
        "incident",
        incident_id,
        after_summary="verification_status=reviewed, publication_status=publishable",
        notes="Bulk sign-off per project-owner directive of 2026-07-13 (tier-3 seed).",
    )
    conn.commit()
    return conn.execute(
        "SELECT public_incident_id FROM incidents WHERE incident_id = ?", (incident_id,)
    ).fetchone()[0]
