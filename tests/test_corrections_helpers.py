"""Tests for the building blocks of the audit corrections. Synthetic TEST- data only.

Role in the evidence flow: `corrections.py` applies record-level corrections
under a named reviewer. Its program is tied to particular audited records, so
what is tested here is the part every correction relies on: a value changes
only through a superseding decision that cites a claim, the earlier decision
and claim stay on file, a split record is fully decided before it is
published, and running a correction twice changes nothing.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from conftest import make_publishable_incident
from mining_accidents import corrections, export, review

REVIEWER = "TEST Reviewer"
NOW = "2099-06-01T00:00:00Z"


def test_a_value_changes_only_through_a_superseding_decision(conn: sqlite3.Connection) -> None:
    fixture = make_publishable_incident(conn, "A")
    incident, public_id = fixture["incident"], fixture["public_id"]
    before = review.get_active_decision(conn, incident, "fatalities_current")
    claims_before = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]

    changed = corrections._apply_value_override(
        conn, REVIEWER, public_id, "fatalities_current", "4", None, "TEST corrected toll."
    )
    assert changed is True
    after = review.get_active_decision(conn, incident, "fatalities_current")
    assert after["decision"] == "manual_override" and after["manual_value"] == "4"
    assert after["supersedes_decision_id"] == before["decision_id"]
    assert "TEST corrected toll." in after["rationale"] and after["reviewer"] == REVIEWER
    # The decision is anchored to a claim, and nothing was deleted.
    assert after["rationale_claim_ids"] not in (None, "[]")
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == claims_before
    assert conn.execute("SELECT COUNT(*) FROM claim_decisions").fetchone()[0] >= 4
    assert (
        conn.execute(
            "SELECT fatalities_current FROM incidents WHERE incident_id = ?", (incident,)
        ).fetchone()[0]
        == 4
    )
    # The earlier figure stays in the observation history.
    tolls = [
        r[0]
        for r in conn.execute(
            "SELECT fatalities FROM casualty_observations WHERE incident_id = ? "
            "ORDER BY observation_id",
            (incident,),
        )
    ]
    assert tolls[0] == 3 and tolls[-1] == 4


def test_a_correction_applied_twice_changes_nothing_the_second_time(
    conn: sqlite3.Connection,
) -> None:
    fixture = make_publishable_incident(conn, "A")
    args = (conn, REVIEWER, fixture["public_id"], "fatalities_current", "4", None, "TEST")
    assert corrections._apply_value_override(*args) is True
    decisions = corrections._decision_count(conn, fixture["incident"])
    assert corrections._apply_value_override(*args) is False
    assert corrections._decision_count(conn, fixture["incident"]) == decisions


def test_a_correction_to_an_unknown_record_does_nothing(conn: sqlite3.Connection) -> None:
    make_publishable_incident(conn, "A")
    assert (
        corrections._apply_value_override(
            conn, REVIEWER, "TEST-9999-0001", "fatalities_current", "4", None, "TEST"
        )
        is False
    )


def test_a_retitle_keeps_the_normalised_title_in_step(conn: sqlite3.Connection) -> None:
    fixture = make_publishable_incident(conn, "A")
    corrections._apply_value_override(
        conn, REVIEWER, fixture["public_id"], "canonical_title_tr", "TEST Yeni Başlık", None, "x"
    )
    row = conn.execute(
        "SELECT canonical_title_tr, canonical_title_tr_normalized FROM incidents "
        "WHERE incident_id = ?",
        (fixture["incident"],),
    ).fetchone()
    assert row[0] == "TEST Yeni Başlık" and row[1] == "test yeni baslik"


def test_a_split_record_is_fully_decided_before_it_is_published(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    raw = tmp_path / "TEST-list.wikitext"
    raw.write_text("* TEST madde: TEST yerinde 2 işçi, başka yerde 1 işçi.\n", encoding="utf-8")
    fixture = make_publishable_incident(conn, "A")
    conn.execute("DROP TRIGGER trg_source_documents_no_update")  # test set-up only
    conn.execute(
        "UPDATE source_documents SET local_raw_path = ? WHERE source_document_id = ?",
        (str(raw), fixture["doc"]),
    )
    list_doc = conn.execute(
        "SELECT * FROM source_documents WHERE source_document_id = ?", (fixture["doc"],)
    ).fetchone()

    created = corrections._create_split_record(
        conn,
        REVIEWER,
        list_doc,
        "TEST:split",
        "TEST ayrılan kayıt",
        "2099-05-20T00:00:00+03:00",
        "45",
        2,
        "roof_or_ground_collapse",
        "TEST yerinde 2 işçi",
    )
    conn.commit()
    assert created == 1
    row = conn.execute(
        "SELECT * FROM incidents WHERE canonical_title_tr = 'TEST ayrılan kayıt'"
    ).fetchone()
    assert row["public_incident_id"] == "TR-MINE-2099-0002"
    assert (row["fatalities_current"], row["province_code"]) == (2, "45")
    assert row["publication_status"] == "publishable"
    # Publishable in fact, not only by flag: every critical field has a decision.
    assert export.publication_blockers(conn, row["incident_id"]) == []
    mechanism = conn.execute(
        "SELECT classification_code, source_claim_id FROM incident_classifications "
        "WHERE incident_id = ?",
        (row["incident_id"],),
    ).fetchone()
    assert mechanism[0] == "roof_or_ground_collapse" and mechanism[1] is not None
    manifest = export.build_public_export(conn, tmp_path / "public", reference_time=NOW)
    assert manifest["row_counts"]["incidents"] == 2
