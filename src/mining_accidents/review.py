"""Reviewer decisions, canonical promotion, and supersession.

Role in the evidence flow: this module is the ONLY writer of canonical
incident values. A human decision (``claim_decisions`` row) is recorded and
the decided value is copied into ``incidents`` by code — never by hand-editing
and never automatically from claims. Conflicting claims are untouched; they
coexist permanently.
"""

from __future__ import annotations

import json
import sqlite3

from mining_accidents.database import utc_now_iso
from mining_accidents.models import ClaimDecision

#: incident columns a decision may set. Anything else is not a canonical
#: incident field and must be decided on its own table.
CANONICAL_INCIDENT_FIELDS = frozenset(
    {
        "canonical_title_tr",
        "canonical_title_en",
        "incident_start_datetime",
        "incident_end_datetime",
        "date_precision",
        "province_code",
        "district_code",
        "settlement",
        "latitude",
        "longitude",
        "coordinate_precision",
        "location_uncertainty_m",
        "fatalities_current",
        "injuries_current",
        "missing_current",
    }
)
_INT_FIELDS = frozenset({"fatalities_current", "injuries_current", "missing_current"})
_FLOAT_FIELDS = frozenset({"latitude", "longitude", "location_uncertainty_m"})
_CASUALTY_FIELDS = _INT_FIELDS


class ReviewError(RuntimeError):
    """Raised when a decision violates the review-flow rules."""


def log_review_action(
    conn: sqlite3.Connection,
    actor: str,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    before_summary: str | None = None,
    after_summary: str | None = None,
    notes: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO review_log (actor, action, entity_type, entity_id, before_summary, "
        "after_summary, occurred_at, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            actor,
            action,
            entity_type,
            entity_id,
            before_summary,
            after_summary,
            utc_now_iso(),
            notes,
        ),
    )


def get_active_decision(
    conn: sqlite3.Connection, incident_id: int, field_name: str
) -> sqlite3.Row | None:
    """The one decision for (incident, field) not superseded by another."""
    rows = conn.execute(
        """
        SELECT d.* FROM claim_decisions d
        WHERE d.incident_id = ? AND d.field_name = ?
          AND NOT EXISTS (
              SELECT 1 FROM claim_decisions s WHERE s.supersedes_decision_id = d.decision_id
          )
        ORDER BY d.decision_id
        """,
        (incident_id, field_name),
    ).fetchall()
    if len(rows) > 1:
        raise ReviewError(
            f"Integrity violation: {len(rows)} active decisions for incident "
            f"{incident_id} field {field_name!r}"
        )
    return rows[0] if rows else None


def _claim_row(conn: sqlite3.Connection, claim_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
    if row is None:
        raise ReviewError(f"Claim {claim_id} does not exist")
    return row


def _coerce(field_name: str, value: str | None) -> object:
    if value is None:
        return None
    if field_name in _INT_FIELDS:
        return int(value)
    if field_name in _FLOAT_FIELDS:
        return float(value)
    return value


def _guard_decision(conn: sqlite3.Connection, decision: ClaimDecision) -> None:
    incident = conn.execute(
        "SELECT incident_id FROM incidents WHERE incident_id = ?", (decision.incident_id,)
    ).fetchone()
    if incident is None:
        raise ReviewError(f"Incident {decision.incident_id} does not exist")

    active = get_active_decision(conn, decision.incident_id, decision.field_name)
    if active is not None and decision.supersedes_decision_id != active["decision_id"]:
        raise ReviewError(
            f"An active decision ({active['decision_id']}) exists for this field; "
            "a new decision must set supersedes_decision_id to it"
        )
    if decision.supersedes_decision_id is not None:
        if active is None or active["decision_id"] != decision.supersedes_decision_id:
            raise ReviewError(
                f"supersedes_decision_id={decision.supersedes_decision_id} is not the "
                "active decision for this field"
            )

    referenced = list(decision.rationale_claim_ids)
    if decision.selected_claim_id is not None:
        referenced.append(decision.selected_claim_id)
    for claim_id in referenced:
        claim = _claim_row(conn, claim_id)
        if claim["incident_id"] is not None and claim["incident_id"] != decision.incident_id:
            raise ReviewError(f"Claim {claim_id} is linked to a different incident")

    if decision.selected_claim_id is not None:
        claim = _claim_row(conn, decision.selected_claim_id)
        # Hard constraint 5: unreviewed AI/OCR output can never become canonical.
        if (
            claim["extraction_method"] in ("ai_assisted", "ocr_assisted")
            and claim["review_status"] != "reviewed"
        ):
            raise ReviewError(
                f"Claim {decision.selected_claim_id} is {claim['extraction_method']} and not "
                "reviewed; it cannot be selected as canonical"
            )


def _promote(conn: sqlite3.Connection, decision: ClaimDecision, decision_id: int) -> str | None:
    """Copy the decided value into incidents (application code, never by hand)."""
    if decision.field_name not in CANONICAL_INCIDENT_FIELDS:
        return None
    if decision.decision == "accept_claim":
        claim = _claim_row(conn, decision.selected_claim_id)  # type: ignore[arg-type]
        value = (
            claim["normalized_value"]
            if claim["normalized_value"] is not None
            else claim["raw_value"]
        )
        source_claim_id: int | None = decision.selected_claim_id
    elif decision.decision == "manual_override":
        value = decision.manual_value
        source_claim_id = decision.rationale_claim_ids[0]
    elif decision.decision == "reject_field":
        value = None
        source_claim_id = None
    else:  # defer — nothing is promoted
        return None

    coerced = _coerce(decision.field_name, value)
    conn.execute(
        f"UPDATE incidents SET {decision.field_name} = ? WHERE incident_id = ?",
        (coerced, decision.incident_id),
    )
    if decision.field_name in ("latitude", "longitude") and source_claim_id is not None:
        conn.execute(
            "UPDATE incidents SET location_source_claim_id = ? WHERE incident_id = ?",
            (source_claim_id, decision.incident_id),
        )
    if decision.field_name in _CASUALTY_FIELDS and decision.decision != "reject_field":
        _append_canonical_observation(conn, decision, source_claim_id)
    return None if coerced is None else str(coerced)


def _append_canonical_observation(
    conn: sqlite3.Connection, decision: ClaimDecision, source_claim_id: int | None
) -> None:
    """Casualty figures never overwrite: append a new observation and move the
    single is_current_canonical flag to it (research_protocol.md §11)."""
    conn.execute(
        "UPDATE casualty_observations SET is_current_canonical = 0 "
        "WHERE incident_id = ? AND is_current_canonical = 1",
        (decision.incident_id,),
    )
    row = conn.execute(
        "SELECT fatalities_current, injuries_current, missing_current FROM incidents "
        "WHERE incident_id = ?",
        (decision.incident_id,),
    ).fetchone()
    conn.execute(
        "INSERT INTO casualty_observations (incident_id, fatalities, injuries, missing, "
        "observation_as_of, source_claim_id, is_current_canonical, review_status, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, 'reviewed', ?)",
        (
            decision.incident_id,
            row["fatalities_current"],
            row["injuries_current"],
            row["missing_current"],
            utc_now_iso(),
            source_claim_id,
            f"set via claim decision on {decision.field_name}",
        ),
    )


def record_decision(conn: sqlite3.Connection, decision: ClaimDecision) -> int:
    """Record a reviewer decision, promote the canonical value, log the action.

    Enforces: one active decision per (incident, field); supersession chains;
    manual_override needs rationale + supporting claims (model-validated);
    unreviewed AI/OCR claims are never selectable.
    """
    _guard_decision(conn, decision)
    before = get_active_decision(conn, decision.incident_id, decision.field_name)
    cur = conn.execute(
        """
        INSERT INTO claim_decisions (
            incident_id, field_name, selected_claim_id, decision, manual_value,
            rationale, rationale_claim_ids, reviewer, decision_date, supersedes_decision_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision.incident_id,
            decision.field_name,
            decision.selected_claim_id,
            decision.decision,
            decision.manual_value,
            decision.rationale,
            json.dumps(decision.rationale_claim_ids),
            decision.reviewer,
            decision.decision_date or utc_now_iso(),
            decision.supersedes_decision_id,
        ),
    )
    decision_id = int(cur.lastrowid)
    promoted = _promote(conn, decision, decision_id)
    log_review_action(
        conn,
        actor=decision.reviewer,
        action=f"claim_decision:{decision.decision}",
        entity_type="incident",
        entity_id=decision.incident_id,
        before_summary=(
            f"active decision {before['decision_id']} ({before['decision']})"
            if before
            else "no active decision"
        ),
        after_summary=(
            f"decision {decision_id} ({decision.decision}) on {decision.field_name}"
            + (f" -> {promoted!r}" if promoted is not None else "")
        ),
    )
    conn.commit()
    return decision_id


def assign_public_incident_id(conn: sqlite3.Connection, incident_id: int, actor: str) -> str:
    """Assign TR-MINE-YYYY-NNNN once; never reused, preserved through merges."""
    row = conn.execute(
        "SELECT public_incident_id, incident_start_datetime FROM incidents WHERE incident_id = ?",
        (incident_id,),
    ).fetchone()
    if row is None:
        raise ReviewError(f"Incident {incident_id} does not exist")
    if row["public_incident_id"]:
        raise ReviewError(f"Incident {incident_id} already has a public id — ids are never reused")
    if not row["incident_start_datetime"]:
        raise ReviewError("Cannot assign a public id before the incident start date is decided")
    year = row["incident_start_datetime"][:4]
    prefix = f"TR-MINE-{year}-"
    used = [
        r[0]
        for r in conn.execute(
            "SELECT public_incident_id FROM incidents WHERE public_incident_id LIKE ? "
            "UNION SELECT merged_public_incident_id FROM incident_merge_log "
            "WHERE merged_public_incident_id LIKE ?",
            (prefix + "%", prefix + "%"),
        )
    ]
    next_seq = max((int(u.rsplit("-", 1)[1]) for u in used), default=0) + 1
    public_id = f"{prefix}{next_seq:04d}"
    conn.execute(
        "UPDATE incidents SET public_incident_id = ? WHERE incident_id = ?",
        (public_id, incident_id),
    )
    log_review_action(
        conn,
        actor=actor,
        action="assign_public_incident_id",
        entity_type="incident",
        entity_id=incident_id,
        after_summary=public_id,
    )
    conn.commit()
    return public_id


def merge_incidents(
    conn: sqlite3.Connection,
    surviving_incident_id: int,
    merged_incident_id: int,
    reason: str,
    reviewer: str,
) -> int:
    """Record a reviewed merge. The merged record is withdrawn, never deleted;
    its public id remains resolvable as a redirect in exports."""
    merged = conn.execute(
        "SELECT public_incident_id FROM incidents WHERE incident_id = ?",
        (merged_incident_id,),
    ).fetchone()
    if merged is None:
        raise ReviewError(f"Incident {merged_incident_id} does not exist")
    cur = conn.execute(
        "INSERT INTO incident_merge_log (surviving_incident_id, merged_incident_id, "
        "merged_public_incident_id, reason, reviewer, merged_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            surviving_incident_id,
            merged_incident_id,
            merged["public_incident_id"],
            reason,
            reviewer,
            utc_now_iso(),
        ),
    )
    conn.execute(
        "UPDATE incidents SET publication_status = 'withdrawn' WHERE incident_id = ?",
        (merged_incident_id,),
    )
    log_review_action(
        conn,
        actor=reviewer,
        action="merge_incidents",
        entity_type="incident",
        entity_id=surviving_incident_id,
        before_summary=f"separate incidents {surviving_incident_id}, {merged_incident_id}",
        after_summary=f"incident {merged_incident_id} merged into {surviving_incident_id}",
        notes=reason,
    )
    conn.commit()
    return int(cur.lastrowid)
