"""Tests for the seed ingest's decision rules. Synthetic TEST- data only.

Role in the evidence flow: `ingest.py` is where a rule, authorised once by a
reviewer, selects among claims for a whole batch. Most published values were
first chosen this way, so the rule is tested directly: which claim it picks,
what it refuses to pick, what it will not publish, and that running it twice
changes nothing. No network: the adapters are not called.
"""

from __future__ import annotations

import sqlite3

from conftest import make_claim, make_incident, make_source_document
from mining_accidents import ingest, review
from mining_accidents.adapters.base import ClaimDraft

REVIEWER = "TEST Reviewer"


def _incident_with(conn: sqlite3.Connection, claims: list[dict]) -> tuple[int, dict[str, int]]:
    doc_a = make_source_document(conn, url="file:///dev/null/TEST-a", content_hash="a" * 64)
    doc_b = make_source_document(conn, url="file:///dev/null/TEST-b", content_hash="b" * 64)
    incident = make_incident(conn, incident_status="scope_undetermined", scope_rationale="TEST")
    ids = {}
    for spec in claims:
        doc = doc_b if spec.pop("doc", "a") == "b" else doc_a
        key = spec.pop("key")
        ids[key] = make_claim(conn, doc, incident_id=incident, **spec)
    return incident, ids


def _selected(conn: sqlite3.Connection, incident: int, field: str) -> int:
    return review.get_active_decision(conn, incident, field)["selected_claim_id"]


def test_the_rule_prefers_the_article_over_the_structured_item(conn: sqlite3.Connection) -> None:
    incident, ids = _incident_with(
        conn,
        [
            {"key": "item", "field_name": "fatalities_current", "normalized_value": "3",
             "extraction_method": "api"},
            {"key": "article", "doc": "b", "field_name": "fatalities_current",
             "normalized_value": "4", "extraction_method": "html_parser"},
        ],
    )  # fmt: skip
    assert ingest._bulk_decide(conn, incident, REVIEWER) == 1
    assert _selected(conn, incident, "fatalities_current") == ids["article"]
    decision = review.get_active_decision(conn, incident, "fatalities_current")
    # The conflict is recorded in the rationale, never settled silently.
    assert "2 distinct values were present" in decision["rationale"]
    assert decision["reviewer"] == REVIEWER
    # Both claims are still on file.
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 2


def test_the_rule_never_selects_an_unreviewed_ai_assisted_claim(
    conn: sqlite3.Connection,
) -> None:
    incident, ids = _incident_with(
        conn,
        [
            {"key": "ai", "field_name": "fatalities_current", "normalized_value": "9",
             "extraction_method": "ai_assisted", "review_status": "needs_review"},
        ],
    )  # fmt: skip
    assert ingest._bulk_decide(conn, incident, REVIEWER) == 0
    assert review.get_active_decision(conn, incident, "fatalities_current") is None
    # Reviewed as a human act, the same claim becomes selectable.
    conn.execute("UPDATE claims SET review_status = 'reviewed' WHERE claim_id = ?", (ids["ai"],))
    conn.commit()
    assert ingest._bulk_decide(conn, incident, REVIEWER) == 1
    assert _selected(conn, incident, "fatalities_current") == ids["ai"]


def test_running_the_rule_twice_decides_nothing_new(conn: sqlite3.Connection) -> None:
    incident, _ = _incident_with(
        conn,
        [
            {"key": "d", "field_name": "incident_start_datetime",
             "normalized_value": "2099-05-10T00:00:00+03:00", "extraction_method": "api"},
            {"key": "p", "field_name": "province_code", "normalized_value": "67",
             "extraction_method": "api"},
        ],
    )  # fmt: skip
    assert ingest._bulk_decide(conn, incident, REVIEWER) == 2
    assert ingest._bulk_decide(conn, incident, REVIEWER) == 0
    assert conn.execute("SELECT COUNT(*) FROM claim_decisions").fetchone()[0] == 2


def test_an_existing_decision_is_left_alone(conn: sqlite3.Connection) -> None:
    incident, ids = _incident_with(
        conn,
        [
            {"key": "first", "field_name": "fatalities_current", "normalized_value": "3",
             "extraction_method": "api"},
        ],
    )  # fmt: skip
    ingest._bulk_decide(conn, incident, REVIEWER)
    doc = make_source_document(conn, url="file:///dev/null/TEST-late", content_hash="c" * 64)
    make_claim(conn, doc, incident_id=incident, field_name="fatalities_current",
               normalized_value="5", extraction_method="html_parser")  # fmt: skip
    # A later, higher-priority claim does not overturn a recorded decision.
    assert ingest._bulk_decide(conn, incident, REVIEWER) == 0
    assert _selected(conn, incident, "fatalities_current") == ids["first"]


def test_scope_follows_the_decided_toll_and_date(conn: sqlite3.Connection) -> None:
    incident, _ = _incident_with(
        conn,
        [
            {"key": "d", "field_name": "incident_start_datetime",
             "normalized_value": "2099-05-10T00:00:00+03:00", "extraction_method": "api"},
            {"key": "f", "field_name": "fatalities_current", "normalized_value": "0",
             "extraction_method": "api"},
        ],
    )  # fmt: skip
    ingest._set_scope(conn, incident, REVIEWER)  # nothing decided yet
    status = "SELECT incident_status FROM incidents WHERE incident_id = ?"
    assert conn.execute(status, (incident,)).fetchone()[0] == "scope_undetermined"
    ingest._bulk_decide(conn, incident, REVIEWER)
    ingest._set_scope(conn, incident, REVIEWER)
    # A non-fatal event is out of scope, with the reason kept.
    row = conn.execute(
        "SELECT incident_status, scope_rationale FROM incidents WHERE incident_id = ?",
        (incident,),
    ).fetchone()
    assert row["incident_status"] == "out_of_scope"
    assert "non-fatal" in row["scope_rationale"]


def test_a_record_missing_a_critical_decision_is_not_published(
    conn: sqlite3.Connection,
) -> None:
    incident, _ = _incident_with(
        conn,
        [
            {"key": "d", "field_name": "incident_start_datetime",
             "normalized_value": "2099-05-10T00:00:00+03:00", "extraction_method": "api"},
            {"key": "f", "field_name": "fatalities_current", "normalized_value": "2",
             "extraction_method": "api"},
        ],
    )  # fmt: skip
    ingest._bulk_decide(conn, incident, REVIEWER)
    ingest._set_scope(conn, incident, REVIEWER)
    blockers = ingest._publish_if_complete(conn, incident, REVIEWER)
    assert blockers == ["undecided:province_code"]
    row = conn.execute(
        "SELECT public_incident_id, publication_status FROM incidents WHERE incident_id = ?",
        (incident,),
    ).fetchone()
    assert row["public_incident_id"] is None and row["publication_status"] == "draft"


def test_a_complete_record_is_signed_off_and_numbered_once(conn: sqlite3.Connection) -> None:
    incident, _ = _incident_with(
        conn,
        [
            {"key": "d", "field_name": "incident_start_datetime",
             "normalized_value": "2099-05-10T00:00:00+03:00", "extraction_method": "api"},
            {"key": "p", "field_name": "province_code", "normalized_value": "67",
             "extraction_method": "api"},
            {"key": "f", "field_name": "fatalities_current", "normalized_value": "2",
             "extraction_method": "api"},
        ],
    )  # fmt: skip
    ingest._bulk_decide(conn, incident, REVIEWER)
    ingest._set_scope(conn, incident, REVIEWER)
    public_id = ingest._publish_if_complete(conn, incident, REVIEWER)
    assert public_id == "TR-MINE-2099-0001"
    assert ingest._publish_if_complete(conn, incident, REVIEWER) == public_id
    actions = [r[0] for r in conn.execute("SELECT action FROM review_log ORDER BY log_id")]
    assert actions.count("assign_public_incident_id") == 1
    assert "publication_signoff" in actions


def test_a_classification_needs_a_known_code_and_keeps_its_claim(
    conn: sqlite3.Connection,
) -> None:
    incident, ids = _incident_with(
        conn,
        [
            {"key": "known", "claim_subject_type": "classification",
             "field_name": "event_mechanism", "normalized_value": "fire",
             "extraction_method": "html_parser"},
            {"key": "invented", "claim_subject_type": "classification",
             "field_name": "event_mechanism", "normalized_value": "TEST_not_a_code",
             "extraction_method": "html_parser"},
            {"key": "ai", "claim_subject_type": "classification", "field_name": "hazard",
             "normalized_value": "methane", "extraction_method": "ai_assisted",
             "review_status": "needs_review"},
        ],
    )  # fmt: skip
    assert ingest._apply_classifications(conn, incident, REVIEWER) == 1
    rows = conn.execute(
        "SELECT classification_code, source_claim_id, review_status FROM incident_classifications"
    ).fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [("fire", ids["known"], "reviewed")]
    assert ingest._apply_classifications(conn, incident, REVIEWER) == 0


def test_an_operator_is_published_only_when_two_documents_name_it(
    conn: sqlite3.Connection,
) -> None:
    incident, _ = _incident_with(
        conn,
        [
            {"key": "one", "claim_subject_type": "organization",
             "field_name": "operator_organization", "normalized_value": "TEST Madencilik A.Ş."},
        ],
    )  # fmt: skip
    assert ingest._apply_organization_roles(conn, incident, REVIEWER) == 1
    status = "SELECT review_status FROM incident_organization_roles"
    assert conn.execute(status).fetchone()[0] == "pending"

    second = make_source_document(conn, url="file:///dev/null/TEST-2", content_hash="d" * 64)
    make_claim(
        conn,
        second,
        incident_id=incident,
        claim_subject_type="organization",
        field_name="operator_organization",
        normalized_value="TEST Madencilik A.Ş.",
    )
    assert ingest._apply_organization_roles(conn, incident, REVIEWER) == 0
    assert conn.execute(status).fetchone()[0] == "reviewed"
    assert conn.execute("SELECT COUNT(*) FROM incident_organization_roles").fetchone()[0] == 1


def test_a_list_entry_about_a_held_incident_becomes_evidence_not_a_duplicate(
    conn: sqlite3.Connection,
) -> None:
    held = make_incident(
        conn, province_code="67", incident_start_datetime="2099-05-10T00:00:00+03:00"
    )
    match = ingest._find_matching_incident
    assert match(conn, "67", "2099-05-12T00:00:00+03:00") == held
    assert match(conn, "67", "2099-05-20T00:00:00+03:00") is None
    assert match(conn, "45", "2099-05-10T00:00:00+03:00") is None
    assert match(conn, None, "2099-05-10T00:00:00+03:00") is None


def test_an_identical_claim_is_not_inserted_twice(conn: sqlite3.Connection) -> None:
    doc = make_source_document(conn)
    incident = make_incident(conn)
    draft = ClaimDraft(field_name="province_code", raw_value="TEST ili", normalized_value="67",
                       extraction_method="api", assertion_status="reported")  # fmt: skip
    assert ingest._insert_claim(conn, incident, doc, draft) is True
    assert ingest._insert_claim(conn, incident, doc, draft) is False
    assert ingest._qid_of("TEST note qid=Q1 other") == "Q1"
    assert ingest._qid_of(None) is None


def test_an_incident_is_found_again_by_its_source_item(conn: sqlite3.Connection) -> None:
    first, created = ingest._find_or_create_incident(conn, "Q1", "TEST olay", None)
    again, created_again = ingest._find_or_create_incident(conn, "Q1", "TEST başka ad", None)
    assert (created, created_again) == (True, False) and first == again
