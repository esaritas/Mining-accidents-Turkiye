"""Building blocks the audit corrections share.

Role in the evidence flow: every value a correction changes goes through a
superseding ``claim_decisions`` row that cites a claim (``_apply_value_override``),
every new record is built from claims and decided field by field before it is
numbered (``_create_split_record``), merges go through ``review.merge_incidents``,
and every action is written to ``docs/corrections_log.csv``. Tested in
``tests/test_corrections_helpers.py``.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from mining_accidents import review
from mining_accidents.corrections_data import (
    _DASH_RETITLE_RATIONALE,
    _RATIONALE_PREFIX,
    _REVIEW2_PREFIX,
    CORRECTIONS_LOG,
)
from mining_accidents.models import ClaimDecision


def _log_rows() -> list[dict[str, str]]:
    if CORRECTIONS_LOG.exists():
        with CORRECTIONS_LOG.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    return []


def _write_log(rows: list[dict[str, str]]) -> None:
    columns = ["entity", "field", "original_value", "corrected_value", "action", "rationale"]
    with CORRECTIONS_LOG.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _retitle_dash_style(conn: sqlite3.Connection, reviewer: str) -> int:
    """Reformat titles containing a long dash; superseding decisions record it.

    Only project-assigned descriptive titles are touched: every dashed title in
    the register was synthesized by the pipeline (list-seeded or split records),
    never taken verbatim from a source, so this is presentation, not evidence.
    """
    from mining_accidents.normalization import normalize_tr

    changed = 0
    rows = conn.execute(
        "SELECT incident_id, canonical_title_tr FROM incidents WHERE canonical_title_tr LIKE '%—%'"
    ).fetchall()
    for row in rows:
        title = row["canonical_title_tr"].replace(" — ", ", ").replace("—", ",")
        supporting = _supporting_claims(conn, row["incident_id"]) or [
            int(r["claim_id"])
            for r in conn.execute(
                "SELECT claim_id FROM claims WHERE incident_id = ? ORDER BY claim_id LIMIT 1",
                (row["incident_id"],),
            )
        ]
        if not supporting:
            continue  # draft without claims; nothing citable to hang a decision on
        active = review.get_active_decision(conn, row["incident_id"], "canonical_title_tr")
        review.record_decision(
            conn,
            ClaimDecision(
                incident_id=row["incident_id"],
                field_name="canonical_title_tr",
                decision="manual_override",
                manual_value=title,
                rationale=_RATIONALE_PREFIX + _DASH_RETITLE_RATIONALE,
                rationale_claim_ids=supporting,
                supersedes_decision_id=active["decision_id"] if active else None,
                reviewer=reviewer,
            ),
        )
        conn.execute(
            "UPDATE incidents SET canonical_title_tr_normalized = ? WHERE incident_id = ?",
            (normalize_tr(title), row["incident_id"]),
        )
        changed += 1
    return changed


def _decision_count(conn: sqlite3.Connection, incident_id: int) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM claim_decisions WHERE incident_id = ?", (incident_id,)
        ).fetchone()[0]
    )


def _merge_title_duplicates(conn: sqlite3.Connection, reviewer: str) -> None:
    """Merge active incidents sharing the same normalized title.

    Article-seeded and list-seeded rows for the same event can both exist
    when the article lacks a parseable date (blocking key needs a date). The
    record with more recorded decisions survives.
    """
    groups: dict[str, list[int]] = {}
    for row in conn.execute(
        "SELECT incident_id, canonical_title_tr_normalized AS t FROM incidents "
        "WHERE publication_status != 'withdrawn' AND canonical_title_tr_normalized "
        "NOT LIKE 'maden kazasi%'"
    ):
        groups.setdefault(row["t"], []).append(int(row["incident_id"]))
    for title, ids in groups.items():
        if len(ids) < 2:
            continue
        ids.sort(key=lambda i: (-_decision_count(conn, i), i))
        surviving, merged = ids[0], ids[1:]
        for duplicate in merged:
            review.merge_incidents(
                conn,
                surviving,
                duplicate,
                _RATIONALE_PREFIX + f"Same event, same title ({title!r}): article-seeded and "
                "list-seeded rows merged; the fuller record survives.",
                reviewer,
            )


def _merge_reparse_duplicates(conn: sqlite3.Connection, reviewer: str) -> None:
    """Merge re-parse duplicates that share a distinctive bullet fragment."""
    for fragment in ("Çöllolar",):
        ids = [
            int(r["incident_id"])
            for r in conn.execute(
                "SELECT DISTINCT incident_id FROM claims WHERE raw_value LIKE ? "
                "AND incident_id IS NOT NULL AND field_name = 'incident_start_datetime' "
                "ORDER BY incident_id",
                (f"%{fragment}%",),
            )
        ]
        survivors = [
            i
            for i in ids
            if conn.execute(
                "SELECT publication_status FROM incidents WHERE incident_id = ?", (i,)
            ).fetchone()["publication_status"]
            != "withdrawn"
        ]
        if len(survivors) > 1:
            surviving, merged = survivors[0], survivors[1:]
            for duplicate in merged:
                review.merge_incidents(
                    conn,
                    surviving,
                    duplicate,
                    _RATIONALE_PREFIX + f"Re-parse duplicate of the same '{fragment}' bullet "
                    "(group key changed when citation markup stripping was added).",
                    reviewer,
                )


def _apply_value_override(
    conn: sqlite3.Connection,
    reviewer: str,
    public_id: str,
    field_name: str,
    value: str,
    fragment_hint: str | None,
    reason: str,
) -> bool:
    """Record a superseding manual_override for one canonical field.

    Idempotent: returns False (no-op) once the canonical column already holds
    the target value. The prior claim is never deleted; a new decision selects
    the corrected value and records why, preserving the conflicting evidence.
    """
    from mining_accidents.normalization import normalize_tr

    row = conn.execute(
        f"SELECT incident_id, {field_name} AS current FROM incidents "  # noqa: S608 (field is a fixed literal)
        "WHERE public_incident_id = ?",
        (public_id,),
    ).fetchone()
    if row is None:
        return False
    if str(row["current"]) == value:
        return False  # already corrected
    incident_id = int(row["incident_id"])

    supporting: list[int] = []
    if fragment_hint is not None:
        hit = conn.execute(
            "SELECT claim_id FROM claims WHERE incident_id = ? AND raw_value LIKE ? "
            "ORDER BY claim_id LIMIT 1",
            (incident_id, f"%{fragment_hint}%"),
        ).fetchone()
        if hit is not None:
            supporting = [int(hit["claim_id"])]
    if not supporting:
        supporting = _supporting_claims(conn, incident_id) or [
            int(r["claim_id"])
            for r in conn.execute(
                "SELECT claim_id FROM claims WHERE incident_id = ? ORDER BY claim_id LIMIT 1",
                (incident_id,),
            )
        ]
    if not supporting:
        return False  # no citable claim to anchor the decision

    active = review.get_active_decision(conn, incident_id, field_name)
    review.record_decision(
        conn,
        ClaimDecision(
            incident_id=incident_id,
            field_name=field_name,
            decision="manual_override",
            manual_value=value,
            rationale=_REVIEW2_PREFIX + reason,
            rationale_claim_ids=supporting,
            supersedes_decision_id=active["decision_id"] if active else None,
            reviewer=reviewer,
        ),
    )
    if field_name == "canonical_title_tr":
        conn.execute(
            "UPDATE incidents SET canonical_title_tr_normalized = ? WHERE incident_id = ?",
            (normalize_tr(value), incident_id),
        )
    return True


def _supporting_claims(conn: sqlite3.Connection, incident_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT claim_id FROM claims WHERE incident_id = ? AND field_name = "
        "'fatalities_current' ORDER BY claim_id LIMIT 2",
        (incident_id,),
    ).fetchall()
    return [int(r["claim_id"]) for r in rows]


def _create_split_record(
    conn: sqlite3.Connection,
    reviewer: str,
    list_doc: sqlite3.Row,
    marker: str,
    title: str,
    date: str,
    province: str,
    deaths: int,
    mechanism: str | None,
    fragment: str,
) -> int:
    """One incident from one half of the conflated bullet, fully decided."""
    from mining_accidents import vocabularies
    from mining_accidents.normalization import normalize_tr

    raw_line = next(
        (
            line.strip()
            for line in Path(list_doc["local_raw_path"]).read_text(encoding="utf-8").splitlines()
            if fragment in line
        ),
        fragment,
    )
    cur = conn.execute(
        "INSERT INTO incidents (canonical_title_tr, canonical_title_tr_normalized, "
        "incident_status, scope_rationale) VALUES (?, ?, 'in_scope', ?)",
        (
            title,
            normalize_tr(title),
            f"Seeded from {marker}: audit split of a conflated list bullet "
            "(two same-day accidents in different provinces). | fatal mining "
            "incident in Türkiye within 2010-present",
        ),
    )
    incident_id = int(cur.lastrowid)
    claim_ids: dict[str, int] = {}
    for field_name, value in (
        ("incident_start_datetime", date),
        ("date_precision", "exact_date"),
        ("province_code", province),
        ("fatalities_current", str(deaths)),
    ):
        c = conn.execute(
            "INSERT INTO claims (incident_id, source_document_id, claim_subject_type, "
            "field_name, raw_value, normalized_value, section_reference, "
            "extraction_method, extractor_version, assertion_status, review_status) "
            "VALUES (?, ?, 'incident', ?, ?, ?, 'Kazalar/2014', 'manual', "
            "'audit-2026-07-17', 'reported', 'reviewed')",
            (incident_id, list_doc["source_document_id"], field_name, raw_line[:160], value),
        )
        claim_ids[field_name] = int(c.lastrowid)
    for field_name in (
        "incident_start_datetime",
        "date_precision",
        "province_code",
        "fatalities_current",
    ):
        review.record_decision(
            conn,
            ClaimDecision(
                incident_id=incident_id,
                field_name=field_name,
                decision="accept_claim",
                selected_claim_id=claim_ids[field_name],
                rationale=_RATIONALE_PREFIX
                + "Value read manually from the specific clause of the conflated "
                "bullet during the audited split.",
                reviewer=reviewer,
            ),
        )
    if mechanism:
        entry = next(
            e for e in vocabularies.load_vocabulary("event_mechanisms") if e.code == mechanism
        )
        c = conn.execute(
            "INSERT INTO claims (incident_id, source_document_id, claim_subject_type, "
            "field_name, raw_value, normalized_value, section_reference, "
            "extraction_method, extractor_version, assertion_status, review_status) "
            "VALUES (?, ?, 'classification', 'event_mechanism', ?, ?, 'Kazalar/2014', "
            "'manual', 'audit-2026-07-17', 'reported', 'reviewed')",
            (incident_id, list_doc["source_document_id"], raw_line[:160], mechanism),
        )
        conn.execute(
            "INSERT INTO incident_classifications (incident_id, classification_system, "
            "classification_code, classification_label_tr, classification_label_en, "
            "assertion_status, source_claim_id, review_status) VALUES "
            "(?, 'project_event_mechanism', ?, ?, ?, 'reported', ?, 'reviewed')",
            (incident_id, mechanism, entry.label_tr, entry.label_en, int(c.lastrowid)),
        )
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
        after_summary="audit split record published",
        notes=_RATIONALE_PREFIX,
    )
    return 1
