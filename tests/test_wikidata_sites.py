"""Sites adapter parsing + ingest (synthetic TEST- payloads only, no network)."""

from __future__ import annotations

import json
import sqlite3

from mining_accidents.adapters.wikidata_sites import (
    WikidataSitesAdapter,
    map_commodity,
    map_facility_type,
    parse_site_entity,
)
from mining_accidents.ingest_sites import ingest_site_documents


def _statement(pid: str, qid: str) -> dict:
    return {"mainsnak": {"datavalue": {"value": {"id": qid}}}}


def _synthetic_entity() -> dict:
    return {
        "id": "Q99999901",
        "labels": {"tr": {"value": "TEST Linyit Ocağı"}},
        "claims": {
            "P31": [_statement("P31", "Q99999801")],
            "P1056": [_statement("P1056", "Q99999701")],
            "P131": [_statement("P131", "Q99999601")],
            "P137": [_statement("P137", "Q99999501")],
            "P625": [{"mainsnak": {"datavalue": {"value": {"latitude": 39.1, "longitude": 27.6}}}}],
        },
    }


_REFERENCES = {
    "Q99999801": {"label": "open-pit mine", "p131": [], "p17": [], "p297": None},
    "Q99999701": {"label": "lignite", "p131": [], "p17": [], "p297": None},
    "Q99999601": {"label": "Soma", "p131": ["Q99999602"], "p17": [], "p297": None},
    "Q99999602": {"label": "Manisa Province", "p131": [], "p17": [], "p297": None},
    "Q99999501": {
        "label": "TEST Madencilik A.Ş.",
        "p131": [],
        "p17": ["Q99999401"],
        "p297": None,
    },
    "Q99999401": {"label": "Türkiye", "p131": [], "p17": [], "p297": "TR"},
}


def test_parse_site_entity_extracts_all_fields() -> None:
    drafts = parse_site_entity(_synthetic_entity(), _REFERENCES)
    fields = {d.field_name: d for d in drafts}

    assert fields["facility_name_tr"].normalized_value == "TEST Linyit Ocağı"
    assert fields["facility_type"].normalized_value == "mine_openpit"
    assert fields["commodity_code"].normalized_value == "lignite"
    assert fields["commodity_code"].notes["commodity_label"] == "lignite"
    assert fields["latitude"].normalized_value == "39.100000"
    # district (Soma) resolves to its parent province (Manisa, TR-45)
    assert fields["province_code"].normalized_value == "45"
    assert fields["operational_status"].normalized_value == "unknown"

    org = fields["operator_organization"]
    assert org.claim_subject_type == "organization"
    assert org.normalized_value == "TEST Madencilik A.Ş."
    assert org.notes["country_code"] == "TR"
    assert org.notes["role"] == "operator"
    assert all(d.extraction_method == "api" for d in drafts)


def test_closure_statement_maps_to_closed_status() -> None:
    entity = _synthetic_entity()
    entity["claims"]["P3999"] = [{"mainsnak": {}}]
    fields = {d.field_name: d for d in parse_site_entity(entity, _REFERENCES)}
    assert fields["operational_status"].normalized_value == "closed"


def test_unlabeled_entity_is_not_registered() -> None:
    assert parse_site_entity({"id": "Q1", "labels": {}, "claims": {}}, {}) == []


def test_type_and_commodity_mapping_edges() -> None:
    assert map_facility_type(["underground mine"]) == "mine_underground"
    assert map_facility_type(["colliery"]) == "mine_unspecified"
    assert map_facility_type(["quarry"]) == "quarry"
    assert map_facility_type(["power station"]) == "unknown"
    assert map_commodity("Chromite") == ("chromium", "Chromite")
    assert map_commodity("uranium") == ("other", "uranium")  # never guessed
    assert map_commodity(None) == (None, None)


def _insert_site_document(conn: sqlite3.Connection, tmp_path, entity: dict) -> int:
    raw = tmp_path / f"{entity['id']}.json"
    raw.write_text(json.dumps(entity), encoding="utf-8")
    cur = conn.execute(
        "INSERT INTO source_documents (source_organization, title, document_type, url, "
        "retrieved_at, content_hash, local_raw_path, source_tier, access_status, notes) "
        "VALUES ('Wikidata', ?, 'other', ?, '2099-01-01T00:00:00Z', ?, ?, 3, 'available', ?)",
        (
            f"TEST item {entity['id']}",
            f"https://www.wikidata.org/wiki/{entity['id']}",
            f"TEST-hash-{entity['id']}",
            str(raw),
            f"kind=wikidata_site qid={entity['id']}",
        ),
    )
    return int(cur.lastrowid)


def test_ingest_site_documents_registers_facility(conn, tmp_path) -> None:
    adapter = WikidataSitesAdapter(raw_dir=tmp_path)
    adapter._references = _REFERENCES
    doc_id = _insert_site_document(conn, tmp_path, _synthetic_entity())

    summary = ingest_site_documents(conn, adapter, [doc_id], reviewer="TEST Reviewer")
    assert summary.facilities_created == 1
    assert summary.organizations_created == 1
    assert summary.roles_created == 1

    facility = conn.execute("SELECT * FROM facilities").fetchone()
    assert facility["external_ref"] == "wikidata:Q99999901"
    assert facility["facility_type"] == "mine_openpit"
    assert facility["commodity_code"] == "lignite"
    assert facility["province_code"] == "45"
    assert facility["coordinate_precision"] == "facility_approximate"
    assert facility["source_claim_id"] is not None

    org = conn.execute("SELECT * FROM organizations").fetchone()
    assert org["country_code"] == "TR"
    role = conn.execute("SELECT * FROM facility_organization_roles").fetchone()
    assert role["role"] == "operator"
    assert role["assertion_status"] == "reported"
    assert role["review_status"] == "reviewed"
    signoff = conn.execute(
        "SELECT * FROM review_log WHERE action = 'facility_registered'"
    ).fetchone()
    assert signoff["actor"] == "TEST Reviewer"

    # Idempotent re-run: nothing duplicated.
    again = ingest_site_documents(conn, adapter, [doc_id], reviewer="TEST Reviewer")
    assert again.facilities_created == 0
    assert again.claims_created == 0
    assert again.roles_created == 0
    assert conn.execute("SELECT COUNT(*) FROM facilities").fetchone()[0] == 1


def test_ingest_without_reviewer_keeps_roles_pending(conn, tmp_path) -> None:
    adapter = WikidataSitesAdapter(raw_dir=tmp_path)
    adapter._references = _REFERENCES
    doc_id = _insert_site_document(conn, tmp_path, _synthetic_entity())
    ingest_site_documents(conn, adapter, [doc_id], reviewer=None)
    role = conn.execute("SELECT review_status FROM facility_organization_roles").fetchone()
    assert role["review_status"] == "pending"
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM review_log WHERE action='facility_registered'"
        ).fetchone()[0]
        == 0
    )
