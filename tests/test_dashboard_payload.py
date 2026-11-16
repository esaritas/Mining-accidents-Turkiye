"""The dashboard payload built from a synthetic register. TEST- data only.

Role in the evidence flow: the payload is the last step before a reader. It
must carry what the export publishes and nothing the export does not, and the
counts the page prints about decisions must come from the database.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from conftest import make_publishable_incident
from mining_accidents import dashboard, export, restore

NOW = "2099-06-01T00:00:00Z"


@pytest.fixture(autouse=True)
def _fixed_epoch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "4102444800")


def test_payload_carries_the_export_and_the_decision_counts(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    fixture = make_publishable_incident(conn, "A")
    export.build_public_export(conn, tmp_path / "public", reference_time=NOW)
    payload = dashboard.build_payload(conn, tmp_path / "public")

    assert [i["public_incident_id"] for i in payload["incidents"]] == [fixture["public_id"]]
    assert payload["incidents"][0]["province_name"] == "Zonguldak"
    cited = {c["field_name"] for c in payload["citations"][fixture["public_id"]]}
    assert {"incident_start_datetime", "province_code", "fatalities_current"} <= cited
    assert payload["pipeline"]["published_incidents"] == 1
    assert payload["pipeline"]["decisions_total"] >= 3
    assert payload["pipeline"]["decisions_restored"] == 0
    assert payload["pipeline"]["decisions_delegated"] == 0
    # The rates panel was removed from the page; its figures no longer travel.
    assert "rate_context" not in payload
    for key in ("last_attempted", "last_checked", "overdue", "failed_sources"):
        assert key in payload["monitoring"]


def test_restored_and_delegated_decisions_are_counted_apart(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    make_publishable_incident(conn, "A")
    export.build_public_export(conn, tmp_path / "public", reference_time=NOW)
    restore.restore_from_export(
        tmp_path / "restored.sqlite",
        tmp_path / "public",
        reviewer="TEST Reviewer",
        registry_csv=None,
    )
    from mining_accidents.database import get_connection

    restored = get_connection(tmp_path / "restored.sqlite")
    try:
        status = dashboard._pipeline_status(restored)
        assert status["decisions_restored"] == status["decisions_total"] > 0
        restored.execute(
            "INSERT INTO claim_decisions (incident_id, field_name, decision, rationale, "
            "reviewer) VALUES (1, 'settlement', 'defer', 'TEST', 'TEST (delegated to TEST)')"
        )
        assert dashboard._pipeline_status(restored)["decisions_delegated"] == 1
    finally:
        restored.close()


def test_data_js_is_one_assignment_of_sorted_json(conn: sqlite3.Connection, tmp_path: Path) -> None:
    make_publishable_incident(conn, "A")
    export.build_public_export(conn, tmp_path / "public", reference_time=NOW)
    out = dashboard.build_dashboard_data(conn, tmp_path / "public", tmp_path / "data.js")
    text = out.read_text(encoding="utf-8")
    marker = "window.MINING_DATA = "
    body = json.loads(text[text.index(marker) + len(marker) :].rstrip().rstrip(";"))
    assert list(body) == sorted(body)
    assert body["export_timestamp"] == "2100-01-01T00:00:00Z"
