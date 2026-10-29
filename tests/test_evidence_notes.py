"""Synthetic checks for correction notices and the no-promotion staging boundary."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from conftest import make_claim, make_incident, make_source_document
from mining_accidents import review
from mining_accidents.evidence_notes import load_notes, stage_packet
from mining_accidents.models import ClaimDecision


def packet(path: Path, public_id: str = "TR-MINE-2099-0001", status="needs_review") -> Path:
    documents = [
        {
            "source_organization": "TEST institution",
            "title": "TEST synthetic statement",
            "url": "https://example.test/TEST-evidence",
            "content_hash": "b" * 64,
            "source_tier": 2,
        }
    ]
    claims = [
        {
            "public_incident_id": public_id,
            "source_document_hash": "b" * 64,
            "field_name": "fatalities_current",
            "claim_subject_type": "incident",
            "normalized_value": "3",
            "extraction_method": "ai_assisted",
            "review_status": status,
        }
    ]
    for name, rows in (("source_documents.csv", documents), ("claims.csv", claims)):
        with (path / name).open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return path


def test_staging_is_idempotent_and_cannot_promote(conn, tmp_path):
    make_incident(conn, public_incident_id="TR-MINE-2099-0001", fatalities_current=2)
    location = packet(tmp_path)
    first = stage_packet(conn, location)
    second = stage_packet(conn, location)
    assert first.claims_created == 1
    assert second.claims_created == 0
    assert conn.execute("SELECT review_status FROM claims").fetchone()[0] == "needs_review"
    assert conn.execute("SELECT fatalities_current FROM incidents").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM claim_decisions").fetchone()[0] == 0


@pytest.mark.parametrize("case", ["missing_target", "reviewed_claim"])
def test_invalid_packet_writes_nothing(conn, tmp_path, case):
    if case == "reviewed_claim":
        make_incident(conn, public_incident_id="TR-MINE-2099-0001")
    location = packet(tmp_path, status="reviewed" if case == "reviewed_claim" else "needs_review")
    with pytest.raises(ValueError):
        stage_packet(conn, location)
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0] == 0


def test_public_notices_cannot_claim_human_review(tmp_path):
    path = tmp_path / "notices.json"
    path.write_text(json.dumps([{"id": "TEST-note", "status": "reviewed"}]))
    with pytest.raises(ValueError, match="reviewed decisions"):
        load_notes(path)


def test_manual_override_cannot_bypass_unreviewed_ai_support(conn):
    incident = make_incident(conn, fatalities_current=2)
    source = make_source_document(conn)
    claim = make_claim(
        conn, source, incident, extraction_method="ai_assisted", review_status="needs_review"
    )
    with pytest.raises(review.ReviewError, match="not reviewed"):
        review.record_decision(
            conn,
            ClaimDecision(
                incident_id=incident,
                field_name="fatalities_current",
                decision="manual_override",
                manual_value="3",
                rationale_claim_ids=[claim],
                rationale="TEST attempted bypass",
                reviewer="TEST-reviewer",
            ),
        )
    assert conn.execute("SELECT fatalities_current FROM incidents").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM claim_decisions").fetchone()[0] == 0
