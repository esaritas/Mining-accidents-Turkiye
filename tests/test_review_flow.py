"""Review flow: conflicting claims block canonical values until a decision;
decisions promote values, log to review_log, and supersede correctly."""

from __future__ import annotations

import sqlite3

import pytest

from conftest import make_claim, make_incident, make_source_document
from mining_accidents import review
from mining_accidents.models import ClaimDecision


@pytest.fixture()
def evidence(conn: sqlite3.Connection) -> dict[str, int]:
    doc = make_source_document(conn)
    incident = make_incident(conn)
    claim_2 = make_claim(conn, doc, incident_id=incident, raw_value="iki", normalized_value="2")
    claim_3 = make_claim(conn, doc, incident_id=incident, raw_value="üç", normalized_value="3")
    return {"doc": doc, "incident": incident, "claim_2": claim_2, "claim_3": claim_3}


def test_conflicting_claims_do_not_touch_canonical_value(
    conn: sqlite3.Connection, evidence: dict[str, int]
) -> None:
    row = conn.execute(
        "SELECT fatalities_current FROM incidents WHERE incident_id = ?",
        (evidence["incident"],),
    ).fetchone()
    assert row["fatalities_current"] is None  # nothing resolved in code


def test_accept_claim_promotes_value_and_logs(
    conn: sqlite3.Connection, evidence: dict[str, int]
) -> None:
    decision_id = review.record_decision(
        conn,
        ClaimDecision(
            incident_id=evidence["incident"],
            field_name="fatalities_current",
            decision="accept_claim",
            selected_claim_id=evidence["claim_3"],
            rationale="TEST: follow-up report supersedes initial figure",
            reviewer="TEST-reviewer",
        ),
    )
    incident = conn.execute(
        "SELECT fatalities_current FROM incidents WHERE incident_id = ?",
        (evidence["incident"],),
    ).fetchone()
    assert incident["fatalities_current"] == 3

    log = conn.execute(
        "SELECT actor, action FROM review_log ORDER BY log_id DESC LIMIT 1"
    ).fetchone()
    assert log["actor"] == "TEST-reviewer"
    assert log["action"] == "claim_decision:accept_claim"

    observations = conn.execute(
        "SELECT fatalities, is_current_canonical FROM casualty_observations WHERE incident_id = ?",
        (evidence["incident"],),
    ).fetchall()
    assert [(o["fatalities"], o["is_current_canonical"]) for o in observations] == [(3, 1)]
    assert decision_id > 0


def test_second_decision_requires_supersession(
    conn: sqlite3.Connection, evidence: dict[str, int]
) -> None:
    first = review.record_decision(
        conn,
        ClaimDecision(
            incident_id=evidence["incident"],
            field_name="fatalities_current",
            decision="accept_claim",
            selected_claim_id=evidence["claim_2"],
            rationale="TEST initial",
            reviewer="TEST-reviewer",
        ),
    )
    with pytest.raises(review.ReviewError, match="supersedes_decision_id"):
        review.record_decision(
            conn,
            ClaimDecision(
                incident_id=evidence["incident"],
                field_name="fatalities_current",
                decision="accept_claim",
                selected_claim_id=evidence["claim_3"],
                rationale="TEST revised",
                reviewer="TEST-reviewer",
            ),
        )
    second = review.record_decision(
        conn,
        ClaimDecision(
            incident_id=evidence["incident"],
            field_name="fatalities_current",
            decision="accept_claim",
            selected_claim_id=evidence["claim_3"],
            rationale="TEST revised",
            reviewer="TEST-reviewer",
            supersedes_decision_id=first,
        ),
    )
    active = review.get_active_decision(conn, evidence["incident"], "fatalities_current")
    assert active["decision_id"] == second
    assert (
        conn.execute(
            "SELECT fatalities_current FROM incidents WHERE incident_id = ?",
            (evidence["incident"],),
        ).fetchone()[0]
        == 3
    )
    # Supersession moved the canonical flag; both observations remain (append-only).
    flags = [
        row["is_current_canonical"]
        for row in conn.execute(
            "SELECT is_current_canonical FROM casualty_observations "
            "WHERE incident_id = ? ORDER BY observation_id",
            (evidence["incident"],),
        )
    ]
    assert flags == [0, 1]


def test_unreviewed_ai_claim_cannot_become_canonical(
    conn: sqlite3.Connection, evidence: dict[str, int]
) -> None:
    ai_claim = make_claim(
        conn,
        evidence["doc"],
        incident_id=evidence["incident"],
        field_name="province_code",
        raw_value="TEST ili",
        normalized_value="35",
        extraction_method="ai_assisted",
        review_status="needs_review",
    )
    with pytest.raises(review.ReviewError, match="cannot be selected"):
        review.record_decision(
            conn,
            ClaimDecision(
                incident_id=evidence["incident"],
                field_name="province_code",
                decision="accept_claim",
                selected_claim_id=ai_claim,
                rationale="TEST",
                reviewer="TEST-reviewer",
            ),
        )
    # After human review of the claim, selection is allowed.
    conn.execute("UPDATE claims SET review_status = 'reviewed' WHERE claim_id = ?", (ai_claim,))
    review.record_decision(
        conn,
        ClaimDecision(
            incident_id=evidence["incident"],
            field_name="province_code",
            decision="accept_claim",
            selected_claim_id=ai_claim,
            rationale="TEST: verified against raw document",
            reviewer="TEST-reviewer",
        ),
    )
    assert (
        conn.execute(
            "SELECT province_code FROM incidents WHERE incident_id = ?",
            (evidence["incident"],),
        ).fetchone()[0]
        == "35"
    )


def test_manual_override_promotes_manual_value(
    conn: sqlite3.Connection, evidence: dict[str, int]
) -> None:
    review.record_decision(
        conn,
        ClaimDecision(
            incident_id=evidence["incident"],
            field_name="settlement",
            decision="manual_override",
            manual_value="TEST Yerleşimi",
            rationale="TEST: harmonized spelling across sources",
            rationale_claim_ids=[evidence["claim_2"]],
            reviewer="TEST-reviewer",
        ),
    )
    assert (
        conn.execute(
            "SELECT settlement FROM incidents WHERE incident_id = ?", (evidence["incident"],)
        ).fetchone()[0]
        == "TEST Yerleşimi"
    )


def test_defer_promotes_nothing(conn: sqlite3.Connection, evidence: dict[str, int]) -> None:
    review.record_decision(
        conn,
        ClaimDecision(
            incident_id=evidence["incident"],
            field_name="fatalities_current",
            decision="defer",
            rationale="TEST: sources conflict; awaiting official report",
            reviewer="TEST-reviewer",
        ),
    )
    assert (
        conn.execute(
            "SELECT fatalities_current FROM incidents WHERE incident_id = ?",
            (evidence["incident"],),
        ).fetchone()[0]
        is None
    )


def test_public_id_assignment_and_merge_redirect(
    conn: sqlite3.Connection, evidence: dict[str, int]
) -> None:
    incident = evidence["incident"]
    conn.execute(
        "UPDATE incidents SET incident_start_datetime = '2099-05-10T00:00:00+03:00' "
        "WHERE incident_id = ?",
        (incident,),
    )
    public_id = review.assign_public_incident_id(conn, incident, actor="TEST-reviewer")
    assert public_id == "TR-MINE-2099-0001"
    with pytest.raises(review.ReviewError, match="never reused"):
        review.assign_public_incident_id(conn, incident, actor="TEST-reviewer")

    other = make_incident(conn, incident_start_datetime="2099-06-01T00:00:00+03:00")
    other_id = review.assign_public_incident_id(conn, other, actor="TEST-reviewer")
    assert other_id == "TR-MINE-2099-0002"

    review.merge_incidents(conn, incident, other, reason="TEST duplicate", reviewer="TEST-reviewer")
    redirect = conn.execute(
        "SELECT merged_public_incident_id, surviving_incident_id FROM incident_merge_log"
    ).fetchone()
    assert redirect["merged_public_incident_id"] == "TR-MINE-2099-0002"
    assert (
        conn.execute(
            "SELECT publication_status FROM incidents WHERE incident_id = ?", (other,)
        ).fetchone()[0]
        == "withdrawn"
    )
    # The sequence remains burned even after the merge.
    third = make_incident(conn, incident_start_datetime="2099-07-01T00:00:00+03:00")
    assert review.assign_public_incident_id(conn, third, "TEST-reviewer") == "TR-MINE-2099-0003"
