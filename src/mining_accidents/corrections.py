"""Editorial corrections from the external audit of 2026-07-17.

Role in the evidence flow: encodes the record-level actions of the external
audit (forwarded by the project owner) as an explicit, idempotent program
applied under a named human reviewer. Nothing here bypasses the pipeline:
withdrawals flip publication status with a logged rationale; value changes
are ``claim_decisions`` rows; new records are built from claims on already-
stored source documents; every action lands in ``review_log`` and in
``docs/corrections_log.csv``. Audit items our assessed sources cannot verify
are logged as PENDING, never applied.

The module was split in November 2026: the standing tables are in
``corrections_data.py``, the shared building blocks in ``correction_tools.py``
and the reviewed-values pass in ``corrections_review2.py``. Their public names
are imported here, so ``corrections.<name>`` keeps working.
"""

from __future__ import annotations

import sqlite3

from mining_accidents import review
from mining_accidents.correction_tools import (
    _apply_value_override,
    _create_split_record,
    _decision_count,
    _log_rows,
    _retitle_dash_style,
    _supporting_claims,
    _write_log,
)
from mining_accidents.corrections_data import (
    _RATIONALE_PREFIX,
    _REVIEW2_PREFIX,
    CORRECTIONS_LOG,
    FACILITY_DUPLICATES,
    FACILITY_FIXES,
    FACILITY_SUPPRESSIONS,
    PENDING,
    REVIEW2_PENDING,
    REVIEW2_VALUE_OVERRIDES,
    SPLIT_RECORDS,
    WITHDRAWALS,
)
from mining_accidents.corrections_review2 import resolve_audit_reviewed_values
from mining_accidents.models import ClaimDecision

#: What other modules and the tests reach through this module. Listed so the
#: re-exports from the split are not taken for unused imports.
__all__ = [
    "CORRECTIONS_LOG",
    "_apply_value_override",
    "_create_split_record",
    "_decision_count",
    "apply_audit_corrections",
    "reparse_stored_sources",
    "resolve_audit_reviewed_values",
]


def reparse_stored_sources(conn: sqlite3.Connection, reviewer: str) -> dict[str, int]:
    """Re-run the fixed parsers over the already-stored raw documents.

    Fully offline: the list article, the per-incident articles, and the site
    entity documents are all on disk. New claims corroborate or extend; the
    append-only evidence tables guarantee nothing is overwritten.
    """
    from mining_accidents import ingest
    from mining_accidents.adapters.wikidata import WikidataAdapter
    from mining_accidents.adapters.wikidata_sites import WikidataSitesAdapter
    from mining_accidents.ingest_sites import ingest_site_documents

    adapter = WikidataAdapter()
    summary = ingest.IngestSummary()
    list_doc = conn.execute(
        "SELECT source_document_id FROM source_documents WHERE notes LIKE "
        "'%wikipedia_list%' ORDER BY source_document_id DESC LIMIT 1"
    ).fetchone()
    ingest._ingest_list_article(conn, adapter, list_doc["source_document_id"], summary, reviewer)

    # Per-incident articles: re-parse for the widened mechanism extraction.
    article_docs = conn.execute(
        "SELECT source_document_id, notes FROM source_documents "
        "WHERE notes LIKE '%kind=wikipedia_article%'"
    ).fetchall()
    for doc in article_docs:
        qid = next((t[4:] for t in (doc["notes"] or "").split() if t.startswith("qid=")), None)
        incident = conn.execute(
            "SELECT incident_id FROM incidents WHERE scope_rationale LIKE ?",
            (f"%wikidata:{qid}%",),
        ).fetchone()
        if incident is None:
            continue
        for draft in adapter.parse(doc["source_document_id"], conn):
            summary.claims_created += int(
                ingest._insert_claim(
                    conn, incident["incident_id"], doc["source_document_id"], draft
                )
            )
        ingest._decide_incident(conn, incident["incident_id"], reviewer, summary)
    conn.commit()

    sites_adapter = WikidataSitesAdapter()
    site_doc_ids = [
        int(r["source_document_id"])
        for r in conn.execute(
            "SELECT source_document_id FROM source_documents WHERE notes LIKE "
            "'%kind=wikidata_site%' OR notes LIKE '%kind=wikipedia_site_article%'"
        )
    ]
    sites_summary = ingest_site_documents(conn, sites_adapter, site_doc_ids, reviewer)
    return {
        "incidents_created": summary.incidents_created,
        "claims_created": summary.claims_created + sites_summary.claims_created,
        "classifications_created": summary.classifications_created,
        "facilities_refreshed": sites_summary.facilities_updated,
    }


def apply_audit_corrections(conn: sqlite3.Connection, reviewer: str) -> dict[str, int]:
    """Apply every verifiable audit action; returns a per-kind count."""
    counts = {
        "withdrawn": 0,
        "records_created": 0,
        "facility_fixes": 0,
        "duplicates": 0,
        "decisions": 0,
        "classifications_demoted": 0,
    }
    log = _log_rows()
    logged = {(r["entity"], r["field"], r["action"]) for r in log}

    def add_log(
        entity: str, field: str, original: str, corrected: str, action: str, rationale: str
    ) -> None:
        if (entity, field, action) in logged:
            return
        log.append(
            {
                "entity": entity,
                "field": field,
                "original_value": original,
                "corrected_value": corrected,
                "action": action,
                "rationale": rationale,
            }
        )
        logged.add((entity, field, action))

    # 1. Withdrawals -------------------------------------------------------
    for public_id, reason in WITHDRAWALS:
        row = conn.execute(
            "SELECT incident_id, publication_status FROM incidents WHERE public_incident_id = ?",
            (public_id,),
        ).fetchone()
        if row is None or row["publication_status"] == "withdrawn":
            continue
        conn.execute(
            "UPDATE incidents SET publication_status = 'withdrawn' WHERE incident_id = ?",
            (row["incident_id"],),
        )
        review.log_review_action(
            conn,
            reviewer,
            "publication_withdrawn",
            "incident",
            row["incident_id"],
            after_summary=f"{public_id} withdrawn",
            notes=_RATIONALE_PREFIX + reason,
        )
        add_log(
            public_id,
            "publication_status",
            row["publication_status"],
            "withdrawn",
            "withdrawn",
            reason,
        )
        counts["withdrawn"] += 1

    # 2. Split records from the stored list document ----------------------
    list_doc = conn.execute(
        "SELECT source_document_id, local_raw_path FROM source_documents "
        "WHERE notes LIKE '%wikipedia_list%' ORDER BY source_document_id DESC LIMIT 1"
    ).fetchone()
    for marker, title, date, province, deaths, mechanism, fragment in SPLIT_RECORDS:
        if conn.execute(
            "SELECT 1 FROM incidents WHERE scope_rationale LIKE ?", (f"%{marker}%",)
        ).fetchone():
            continue
        counts["records_created"] += _create_split_record(
            conn,
            reviewer,
            list_doc,
            marker,
            title,
            date,
            province,
            deaths,
            mechanism,
            fragment,
        )
        add_log(
            marker,
            "record",
            "(part of TR-MINE-2014-0002)",
            f"{title}: {deaths} deaths",
            "created",
            "Split of the conflated 2014-11-01 bullet (audit §2).",
        )

    # 3. Amasra casualty status -------------------------------------------
    amasra = conn.execute(
        "SELECT incident_id, casualty_status FROM incidents WHERE public_incident_id = "
        "'TR-MINE-2022-0001'"
    ).fetchone()
    if (
        amasra
        and review.get_active_decision(conn, amasra["incident_id"], "casualty_status") is not None
        and amasra["casualty_status"] != "disputed"
    ):
        # Decision recorded before casualty_status was promotable: promote now.
        conn.execute(
            "UPDATE incidents SET casualty_status = 'disputed' WHERE incident_id = ?",
            (amasra["incident_id"],),
        )
    elif amasra and amasra["casualty_status"] != "disputed":
        review.record_decision(
            conn,
            ClaimDecision(
                incident_id=amasra["incident_id"],
                field_name="casualty_status",
                decision="manual_override",
                manual_value="disputed",
                rationale=_RATIONALE_PREFIX
                + "Assessed sources state 42 deaths / 27 injured; TBMM records "
                "(TO_ASSESS) document a 43rd death in April 2023 and 10 injured as of "
                "February 2023. Figure marked disputed pending TBMM assessment "
                "(open question #20).",
                rationale_claim_ids=_supporting_claims(conn, amasra["incident_id"]),
                reviewer=reviewer,
            ),
        )
        add_log(
            "TR-MINE-2022-0001",
            "casualty_status",
            "None",
            "disputed",
            "decision",
            "42 vs 43 cumulative deaths; revision pending TBMM assessment.",
        )
        counts["decisions"] += 1

    # 4. Soma: demote gas_explosion/methane classifications ---------------
    soma = conn.execute(
        "SELECT incident_id FROM incidents WHERE public_incident_id = 'TR-MINE-2014-0001'"
    ).fetchone()
    if soma:
        demoted = conn.execute(
            "UPDATE incident_classifications SET review_status = 'needs_review' "
            "WHERE incident_id = ? AND review_status = 'reviewed' AND ("
            "  (classification_system = 'project_event_mechanism' AND "
            "   classification_code = 'gas_explosion') OR "
            "  (classification_system = 'project_hazard' AND classification_code = 'methane'))",
            (soma["incident_id"],),
        ).rowcount
        if demoted:
            review.log_review_action(
                conn,
                reviewer,
                "classification_demoted",
                "incident",
                soma["incident_id"],
                after_summary="gas_explosion + methane -> needs_review",
                notes=_RATIONALE_PREFIX
                + "The cited public account establishes fire; 'gas explosion' is not "
                "equally established and returns to the review queue (audit §6).",
            )
            add_log(
                "TR-MINE-2014-0001",
                "event_mechanism",
                "fire + gas_explosion",
                "fire (gas_explosion needs_review)",
                "demoted",
                "Fire is the established mechanism (audit §6).",
            )
            counts["classifications_demoted"] += demoted

    # 5. Facility fixes ----------------------------------------------------
    for external_ref, field, value, reason in FACILITY_FIXES:
        row = conn.execute(
            f"SELECT facility_id, {field} AS current FROM facilities WHERE external_ref = ?",
            (external_ref,),
        ).fetchone()
        if row is None or row["current"] == value:
            continue
        conn.execute(
            f"UPDATE facilities SET {field} = ?, notes = COALESCE(notes, '') || ' | audit "
            f"correction 2026-07-17: {field}={value}' WHERE facility_id = ?",
            (value, row["facility_id"]),
        )
        review.log_review_action(
            conn,
            reviewer,
            "facility_corrected",
            "facility",
            row["facility_id"],
            after_summary=f"{external_ref}: {field} {row['current']} -> {value}",
            notes=_RATIONALE_PREFIX + reason,
        )
        add_log(external_ref, field, str(row["current"]), value, "corrected", reason)
        counts["facility_fixes"] += 1

    # 5b. Suppressions (out-of-scope location / coordinate conflicts) ------
    for external_ref, marker_note, reason in FACILITY_SUPPRESSIONS:
        row = conn.execute(
            "SELECT facility_id, notes FROM facilities WHERE external_ref = ?",
            (external_ref,),
        ).fetchone()
        if row is None or (row["notes"] or "").startswith(("OUT_OF_SCOPE", "COORD_CONFLICT")):
            continue
        if marker_note.startswith("COORD_CONFLICT"):
            conn.execute(
                "UPDATE facilities SET latitude = NULL, longitude = NULL, "
                "coordinate_precision = NULL, province_code = NULL, notes = ? "
                "WHERE facility_id = ?",
                (marker_note, row["facility_id"]),
            )
        else:
            conn.execute(
                "UPDATE facilities SET notes = ? WHERE facility_id = ?",
                (marker_note, row["facility_id"]),
            )
        review.log_review_action(
            conn,
            reviewer,
            "facility_suppressed",
            "facility",
            row["facility_id"],
            after_summary=f"{external_ref}: {marker_note.split(':')[0]}",
            notes=_RATIONALE_PREFIX + reason,
        )
        add_log(external_ref, "suppression", "", marker_note.split(":")[0], "suppressed", reason)
        counts["facility_fixes"] += 1

    # 6. Duplicates --------------------------------------------------------
    for external_ref, duplicate_of, reason in FACILITY_DUPLICATES:
        row = conn.execute(
            "SELECT facility_id, notes FROM facilities WHERE external_ref = ?",
            (external_ref,),
        ).fetchone()
        if row is None or "DUPLICATE of" in (row["notes"] or ""):
            continue
        conn.execute(
            "UPDATE facilities SET notes = ? WHERE facility_id = ?",
            (f"DUPLICATE of {duplicate_of} — excluded from export. {reason}", row["facility_id"]),
        )
        review.log_review_action(
            conn,
            reviewer,
            "facility_deduplicated",
            "facility",
            row["facility_id"],
            after_summary=f"{external_ref} marked duplicate of {duplicate_of}",
            notes=_RATIONALE_PREFIX + reason,
        )
        add_log(external_ref, "duplicate_of", "", duplicate_of, "deduplicated", reason)
        counts["duplicates"] += 1

    # 7. Pending items (logged only) --------------------------------------
    for entity, reason in PENDING:
        add_log(entity, "", "", "", "pending", reason)

    # 8. 2026-07-25 review: canonical corrections our sources confirm ------
    for public_id, field_name, value, hint, reason in REVIEW2_VALUE_OVERRIDES:
        if _apply_value_override(conn, reviewer, public_id, field_name, value, hint, reason):
            add_log(
                public_id,
                field_name,
                "",
                value,
                "corrected",
                _REVIEW2_PREFIX + reason,
            )
            counts["decisions"] += 1
    for entity, reason in REVIEW2_PENDING:
        add_log(entity, "", "", "", "pending", reason)

    # 9. Style: no long dashes in project-assigned descriptive titles -----
    retitled = _retitle_dash_style(conn, reviewer)
    if retitled:
        add_log(
            "incidents",
            "canonical_title_tr",
            "descriptive titles containing a long dash",
            "same titles with a comma instead",
            "style_retitle",
            "Owner directive (2026-07-24): no long dashes in display text. "
            "The titles are project-assigned descriptive labels; no factual change.",
        )
        counts["decisions"] += retitled

    conn.commit()
    _write_log(log)
    return counts
