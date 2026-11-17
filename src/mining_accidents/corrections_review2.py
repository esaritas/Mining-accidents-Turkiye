"""Reviewed values from the audit of July 2026.

Role in the evidence flow: queued AI-assisted extractions the audit checked by
hand are marked reviewed and accepted through recorded decisions; drafts that
aggregate several accidents or carry a citation access date as an event date
are withdrawn; duplicates are merged through the review module. Called by
``mining-accidents apply-audit`` after ``corrections.apply_audit_corrections``.
"""

from __future__ import annotations

import sqlite3

from mining_accidents import review
from mining_accidents.correction_tools import (
    _merge_reparse_duplicates,
    _merge_title_duplicates,
    _supporting_claims,
)
from mining_accidents.corrections_data import (
    _ACCESS_DATE_ARTIFACTS,
    _RATIONALE_PREFIX,
    AGGREGATE_DRAFT_FRAGMENTS,
    EXPLICIT_TITLE_MERGES,
    PROVINCE_DECISIONS,
    REVIEWED_AI_VALUES,
    TITLE_FIXES,
)
from mining_accidents.models import ClaimDecision


def resolve_audit_reviewed_values(conn: sqlite3.Connection, reviewer: str) -> int:
    """Reviewed decisions for queued extractions the audit checked by hand."""
    from mining_accidents.ingest import _publish_if_complete

    resolved = 0
    touched: set[int] = set()
    for fragment, field_name, value, reason in REVIEWED_AI_VALUES:
        claim = conn.execute(
            "SELECT claim_id, incident_id, review_status, normalized_value FROM claims "
            "WHERE field_name = ? AND raw_value LIKE ? AND incident_id IS NOT NULL "
            "ORDER BY claim_id LIMIT 1",
            (field_name, f"%{fragment}%"),
        ).fetchone()
        if claim is None:
            continue
        if review.get_active_decision(conn, claim["incident_id"], field_name) is not None:
            touched.add(claim["incident_id"])
            continue
        if claim["review_status"] != "reviewed":
            conn.execute(
                "UPDATE claims SET review_status = 'reviewed' WHERE claim_id = ?",
                (claim["claim_id"],),
            )
        decision = (
            ClaimDecision(
                incident_id=claim["incident_id"],
                field_name=field_name,
                decision="accept_claim",
                selected_claim_id=claim["claim_id"],
                rationale=_RATIONALE_PREFIX + reason,
                reviewer=reviewer,
            )
            if claim["normalized_value"] == value
            else ClaimDecision(
                incident_id=claim["incident_id"],
                field_name=field_name,
                decision="manual_override",
                manual_value=value,
                rationale=_RATIONALE_PREFIX + reason,
                rationale_claim_ids=[int(claim["claim_id"])],
                reviewer=reviewer,
            )
        )
        review.record_decision(conn, decision)
        touched.add(claim["incident_id"])
        resolved += 1
    for fragment, province, reason in PROVINCE_DECISIONS:
        claim = conn.execute(
            "SELECT claim_id, incident_id FROM claims WHERE raw_value LIKE ? "
            "AND incident_id IS NOT NULL ORDER BY claim_id LIMIT 1",
            (f"%{fragment}%",),
        ).fetchone()
        if claim is None:
            continue
        if review.get_active_decision(conn, claim["incident_id"], "province_code") is None:
            review.record_decision(
                conn,
                ClaimDecision(
                    incident_id=claim["incident_id"],
                    field_name="province_code",
                    decision="manual_override",
                    manual_value=province,
                    rationale=_RATIONALE_PREFIX + reason,
                    rationale_claim_ids=[int(claim["claim_id"])],
                    reviewer=reviewer,
                ),
            )
            resolved += 1
        touched.add(claim["incident_id"])
    # Withdraw aggregate/multi-incident draft bullets (never published).
    for fragment, reason in AGGREGATE_DRAFT_FRAGMENTS:
        row = conn.execute(
            "SELECT DISTINCT i.incident_id FROM incidents i JOIN claims c USING (incident_id) "
            "WHERE c.raw_value LIKE ? AND i.publication_status NOT IN "
            "('publishable', 'published', 'withdrawn')",
            (f"%{fragment}%",),
        ).fetchone()
        if row:
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
                after_summary="aggregate bullet withdrawn",
                notes=_RATIONALE_PREFIX + reason,
            )

    # Explicit merges and descriptive-title repairs.
    for merged_title, surviving_public_id, reason in EXPLICIT_TITLE_MERGES:
        merged = conn.execute(
            "SELECT incident_id FROM incidents WHERE canonical_title_tr_normalized = ? "
            "AND publication_status != 'withdrawn'",
            (merged_title,),
        ).fetchone()
        surviving = conn.execute(
            "SELECT incident_id FROM incidents WHERE public_incident_id = ?",
            (surviving_public_id,),
        ).fetchone()
        if merged and surviving and merged["incident_id"] != surviving["incident_id"]:
            review.merge_incidents(
                conn,
                surviving["incident_id"],
                merged["incident_id"],
                _RATIONALE_PREFIX + reason,
                reviewer,
            )
    for public_id, title, reason in TITLE_FIXES:
        row = conn.execute(
            "SELECT incident_id, canonical_title_tr FROM incidents WHERE public_incident_id = ?",
            (public_id,),
        ).fetchone()
        if (
            row
            and row["canonical_title_tr"] != title
            and review.get_active_decision(conn, row["incident_id"], "canonical_title_tr") is None
        ):
            review.record_decision(
                conn,
                ClaimDecision(
                    incident_id=row["incident_id"],
                    field_name="canonical_title_tr",
                    decision="manual_override",
                    manual_value=title,
                    rationale=_RATIONALE_PREFIX + reason,
                    rationale_claim_ids=_supporting_claims(conn, row["incident_id"]),
                    reviewer=reviewer,
                ),
            )
            conn.execute(
                "UPDATE incidents SET canonical_title_tr_normalized = ? WHERE incident_id = ?",
                (
                    __import__(
                        "mining_accidents.normalization", fromlist=["normalize_tr"]
                    ).normalize_tr(title),
                    row["incident_id"],
                ),
            )

    # Withdraw the pre-fix access-date artifact drafts (never published).
    for row in conn.execute(
        "SELECT incident_id, substr(incident_start_datetime, 1, 10) AS d FROM incidents "
        "WHERE publication_status NOT IN ('publishable', 'published', 'withdrawn') "
        "AND scope_rationale LIKE '%trlist:%'"
    ).fetchall():
        if row["d"] not in _ACCESS_DATE_ARTIFACTS:
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
            after_summary=f"draft artifact withdrawn (event date {row['d']} is a "
            "citation access date)",
            notes=_RATIONALE_PREFIX
            + "Pre-fix list parser read citation access/archive dates as event "
            "dates; the cleaned parser no longer seeds these groups.",
        )

    # Re-parse group keys are revision-scoped; a bullet edited (or newly
    # ref-stripped) can seed a second record for an incident that escaped the
    # province+date blocking match. Merge duplicates (fragment- and
    # title-based; the record with the most decisions survives).
    _merge_reparse_duplicates(conn, reviewer)
    _merge_title_duplicates(conn, reviewer)

    # Decide any newly corroborated claims, then publish every complete,
    # in-scope record that is still a draft.
    from mining_accidents import ingest

    summary = ingest.IngestSummary()
    for row in conn.execute(
        "SELECT incident_id, incident_status FROM incidents "
        "WHERE publication_status NOT IN ('publishable', 'published', 'withdrawn')"
    ).fetchall():
        ingest._decide_incident(conn, row["incident_id"], reviewer, summary)
        _publish_if_complete(conn, row["incident_id"], reviewer)
    conn.commit()
    return resolved
