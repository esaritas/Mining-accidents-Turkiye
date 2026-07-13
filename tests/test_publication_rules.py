"""The seven-rule publication threshold (docs/editorial_and_legal_protocol.md §5)."""

from __future__ import annotations

import sqlite3

from conftest import make_incident, make_publishable_incident
from mining_accidents import review
from mining_accidents.export import publication_blockers
from mining_accidents.models import ClaimDecision


def test_fully_decided_record_is_eligible(conn: sqlite3.Connection) -> None:
    fixture = make_publishable_incident(conn)
    assert publication_blockers(conn, fixture["incident"]) == []


def test_unreviewed_identity_blocks(conn: sqlite3.Connection) -> None:
    fixture = make_publishable_incident(conn)
    conn.execute(
        "UPDATE incidents SET verification_status = 'in_review' WHERE incident_id = ?",
        (fixture["incident"],),
    )
    blockers = publication_blockers(conn, fixture["incident"])
    assert any("verification_status" in b for b in blockers)


def test_missing_editorial_signoff_blocks(conn: sqlite3.Connection) -> None:
    fixture = make_publishable_incident(conn)
    conn.execute(
        "UPDATE incidents SET publication_status = 'internal' WHERE incident_id = ?",
        (fixture["incident"],),
    )
    blockers = publication_blockers(conn, fixture["incident"])
    assert any("editorial sign-off" in b for b in blockers)


def test_missing_critical_decision_blocks(conn: sqlite3.Connection) -> None:
    bare = make_incident(conn, publication_status="publishable", verification_status="reviewed")
    blockers = publication_blockers(conn, bare)
    assert any("incident_start_datetime" in b for b in blockers)
    assert any("province_code" in b for b in blockers)
    assert any("fatalities_current" in b for b in blockers)


def test_defer_on_critical_field_blocks_unless_disclosed(conn: sqlite3.Connection) -> None:
    fixture = make_publishable_incident(conn)
    active = review.get_active_decision(conn, fixture["incident"], "fatalities_current")
    review.record_decision(
        conn,
        ClaimDecision(
            incident_id=fixture["incident"],
            field_name="fatalities_current",
            decision="defer",
            rationale="TEST: conflicting synthetic sources",
            reviewer="TEST-reviewer",
            supersedes_decision_id=active["decision_id"],
        ),
    )
    blockers = publication_blockers(conn, fixture["incident"], disclose_conflicts=False)
    assert any("deferred decision" in b for b in blockers)
    # Rule 6, second branch: the conflict may instead be exported as disclosed.
    assert publication_blockers(conn, fixture["incident"], disclose_conflicts=True) == []


def test_coordinates_without_precision_block(conn: sqlite3.Connection) -> None:
    fixture = make_publishable_incident(conn)
    conn.execute(
        "UPDATE incidents SET latitude = 41.0, longitude = 31.8 WHERE incident_id = ?",
        (fixture["incident"],),
    )
    blockers = publication_blockers(conn, fixture["incident"])
    assert any("coordinate_precision" in b for b in blockers)
    conn.execute(
        "UPDATE incidents SET coordinate_precision = 'settlement' WHERE incident_id = ?",
        (fixture["incident"],),
    )
    assert publication_blockers(conn, fixture["incident"]) == []
