"""Duplicate-candidate detection (flags for human review; never auto-merges)."""

from __future__ import annotations

import sqlite3

from conftest import make_incident
from mining_accidents.entity_resolution import find_duplicate_candidates, name_similarity


def test_name_similarity_handles_turkish_variants() -> None:
    assert name_similarity("TEST Kömür İşletmesi", "TEST KOMUR ISLETMESI") == 1.0
    assert name_similarity("TEST A", "") == 0.0


def test_duplicate_candidates_same_province_close_dates(conn: sqlite3.Connection) -> None:
    a = make_incident(
        conn,
        canonical_title_tr="TEST Ocak-1 göçük olayı",
        province_code="67",
        incident_start_datetime="2099-05-10T00:00:00+03:00",
    )
    b = make_incident(
        conn,
        canonical_title_tr="TEST Ocak-1 gocuk olayi",  # spelling variant of the same fiction
        province_code="67",
        incident_start_datetime="2099-05-12T00:00:00+03:00",
    )
    candidates = find_duplicate_candidates(conn)
    assert [(c.incident_id_a, c.incident_id_b) for c in candidates] == [(a, b)]
    assert candidates[0].name_similarity >= 0.75


def test_no_candidates_across_provinces(conn: sqlite3.Connection) -> None:
    make_incident(
        conn,
        canonical_title_tr="TEST aynı başlık",
        province_code="67",
        incident_start_datetime="2099-05-10T00:00:00+03:00",
    )
    make_incident(
        conn,
        canonical_title_tr="TEST aynı başlık",
        province_code="35",
        incident_start_datetime="2099-05-10T00:00:00+03:00",
    )
    assert find_duplicate_candidates(conn) == []


def test_no_candidates_outside_date_window(conn: sqlite3.Connection) -> None:
    make_incident(
        conn,
        canonical_title_tr="TEST aynı başlık",
        province_code="67",
        incident_start_datetime="2099-05-10T00:00:00+03:00",
    )
    make_incident(
        conn,
        canonical_title_tr="TEST aynı başlık",
        province_code="67",
        incident_start_datetime="2099-05-20T00:00:00+03:00",
    )
    assert find_duplicate_candidates(conn) == []


def test_dissimilar_names_not_flagged(conn: sqlite3.Connection) -> None:
    make_incident(
        conn,
        canonical_title_tr="TEST tamamen farklı bir başlık",
        province_code="67",
        incident_start_datetime="2099-05-10T00:00:00+03:00",
    )
    make_incident(
        conn,
        canonical_title_tr="TEST bambaşka kelimeler burada",
        province_code="67",
        incident_start_datetime="2099-05-11T00:00:00+03:00",
    )
    assert find_duplicate_candidates(conn) == []
