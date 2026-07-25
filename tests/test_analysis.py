"""Analysis-layer math on synthetic (TEST-) data only."""

from __future__ import annotations

import sqlite3

from conftest import make_publishable_incident
from mining_accidents import analysis


def _add_isig_year(conn: sqlite3.Connection, year: int, deaths: int) -> None:
    conn.execute(
        "INSERT INTO aggregate_occupational_statistics (reporting_institution, period_start, "
        "period_end, numerator, unit, comparability_notes) VALUES (?, ?, ?, ?, 'deaths', 'TEST')",
        ("TEST kurum", f"{year}-01-01", f"{year}-12-31", float(deaths)),
    )


def test_coverage_gap_math(conn: sqlite3.Connection) -> None:
    make_publishable_incident(conn)  # 3 deaths in 2099
    for year, deaths in ((2098, 50), (2099, 40)):
        _add_isig_year(conn, year, deaths)
    gap = analysis.coverage_gap(conn)
    by_year = {y["year"]: y for y in gap["years"]}
    assert by_year[2098] == {
        "year": 2098,
        "isig_total": 50,
        "register_deaths": 0,
        "gap": 50,
        "coverage_pct": 0.0,
    }
    assert by_year[2099]["register_deaths"] == 3
    assert by_year[2099]["gap"] == 37
    assert by_year[2099]["coverage_pct"] == 7.5
    assert gap["total_isig"] == 90 and gap["total_gap"] == 87
    # The caveat must frame the difference as under-representation in this
    # register, not as deaths absent from all public records (2026-07-25 review).
    assert "not yet represented in this register" in gap["caveat"]
    assert "never" not in gap["caveat"]


def test_coverage_gap_never_negative(conn: sqlite3.Connection) -> None:
    make_publishable_incident(conn)  # 3 deaths in 2099
    _add_isig_year(conn, 2099, 1)  # register exceeds the aggregate
    gap = analysis.coverage_gap(conn)
    year = gap["years"][0]
    assert year["gap"] == 0
    assert year["coverage_pct"] == 100.0


def test_projection_requires_enough_years(conn: sqlite3.Connection) -> None:
    for year in (2095, 2096):
        _add_isig_year(conn, year, 70)
    assert analysis.projection(conn) is None


def test_projection_interval_never_narrower_than_poisson(conn: sqlite3.Connection) -> None:
    # A constant series has zero sample variance; the interval must still
    # carry at least Poisson dispersion around the mean.
    for year in range(2090, 2098):
        _add_isig_year(conn, year, 64)
    result = analysis.projection(conn)
    assert result["expected"] == 64
    assert result["low"] < 64 < result["high"]
    assert result["high"] - result["expected"] >= 13  # ~1.645 * sqrt(64)
    assert result["basis_years"] == [2090, 2097]
    assert "PROPOSED" in result["method"]


def test_projection_is_deterministic(conn: sqlite3.Connection) -> None:
    for year, deaths in enumerate((81, 93, 386, 67, 73, 93, 66, 63), start=2090):
        _add_isig_year(conn, year, deaths)
    assert analysis.projection(conn) == analysis.projection(conn)


def test_policy_events_load_sorted() -> None:
    events = analysis.policy_events()
    assert len(events) >= 5
    dates = [e["date"] for e in events]
    assert dates == sorted(dates)
    kinds = {e["kind"] for e in events}
    assert kinds <= {"disaster", "law", "treaty"}
    assert all(e["source_url"] for e in events)


def test_rate_context_reads_only_denominated_rows(conn: sqlite3.Connection) -> None:
    _add_isig_year(conn, 2099, 70)  # unit='deaths' — must not appear
    conn.execute(
        "INSERT INTO aggregate_occupational_statistics (reporting_institution, period_start, "
        "classification_system, classification_code, numerator, denominator, unit, "
        "comparability_notes) VALUES ('TEST kurum', '2098-01-01', 'country', 'TR', 700.0, "
        "100000000.0, 'deaths_per_100M_tonnes_coal', 'TEST note')"
    )
    rows = analysis.rate_context(conn)
    assert rows == [
        {
            "country": "TR",
            "year": 2098,
            "value": 700.0,
            "unit": "deaths_per_100M_tonnes_coal",
            "comparability_notes": "TEST note",
        }
    ]
