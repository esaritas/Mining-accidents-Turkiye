"""Descriptive public-interest analysis over the register and its aggregates.

Role in the evidence flow: consumes canonical values and aggregate context —
never raw claims — and produces the derived findings the dashboard shows:
the recording undercount, rate context with documented denominators, the
policy timeline, and a naive cost-of-inaction projection. Every method here
is documented in docs/analysis_methods.md with STATUS: PROPOSED; nothing is
a causal claim, nothing is labeled "risk", and the projection is a baseline
continuation, not a prediction of fate.
"""

from __future__ import annotations

import csv
import math
import sqlite3
import statistics
from collections.abc import Sequence
from pathlib import Path

POLICY_EVENTS_CSV = Path("data/vocabularies/policy_events.csv")

GAP_CAVEAT = (
    "Different measures: this register counts deaths in reviewed, published "
    "incidents; İSİG Meclisi counts all miner work deaths from all causes. The "
    "difference is loss not yet represented in this register, not loss that no "
    "public source recorded."
)

PROJECTION_METHOD = (
    "Naive continuation baseline: mean of the most recent complete İSİG "
    "years with a ~90% interval widened to at least Poisson dispersion "
    "(sd = sqrt(max(sample variance, mean))). Not a forecast model; see "
    "docs/analysis_methods.md (STATUS: PROPOSED)."
)


ISIG_INSTITUTION = "İSİG Meclisi (via tr.wikipedia list article)"


def isig_aggregates(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Read the explicitly identified legacy seed series; reject ambiguous years.

    Only full calendar-year death counts with the original unclassified scope
    are eligible. Other institutions, sectors and partial periods must not be
    silently mixed into this series. A future direct-source series needs its
    own explicit editorial selection, not a string-prefix match.
    """
    rows = conn.execute(
        "SELECT period_start, period_end, numerator, reporting_institution, comparability_notes "
        "FROM aggregate_occupational_statistics WHERE unit = 'deaths' "
        "AND reporting_institution = ? AND classification_system IS NULL "
        "AND classification_code IS NULL AND classification_version IS NULL "
        "ORDER BY period_start, aggregate_id",
        (ISIG_INSTITUTION,),
    )
    result = []
    years = set()
    for row in rows:
        start, end = row["period_start"], row["period_end"]
        if not start or not end:
            continue
        year = int(start[:4])
        if start != f"{year}-01-01" or end != f"{year}-12-31":
            continue
        if year in years:
            raise ValueError(f"Multiple selected İSİG observations for {year}; review required")
        years.add(year)
        count = row["numerator"]
        if count is None or count < 0 or not float(count).is_integer():
            raise ValueError(f"Invalid annual death count for {year}")
        result.append(
            {
                "year": year,
                "deaths": int(count),
                "institution": row["reporting_institution"],
                "comparability_notes": row["comparability_notes"],
            }
        )
    return result


def _isig_series(conn: sqlite3.Connection) -> dict[int, int]:
    return {row["year"]: row["deaths"] for row in isig_aggregates(conn)}


def _register_deaths_by_year(conn: sqlite3.Connection) -> dict[int, int]:
    return {
        int(row["year"]): int(row["deaths"])
        for row in conn.execute(
            """
            SELECT substr(incident_start_datetime, 1, 4) AS year,
                   SUM(fatalities_current) AS deaths
            FROM incidents
            WHERE publication_status IN ('publishable', 'published')
              AND incident_start_datetime IS NOT NULL
              AND fatalities_current IS NOT NULL
            GROUP BY year
            """
        )
    }


def coverage_gap(
    conn: sqlite3.Connection,
    *,
    public_incidents: Sequence[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Per-year undercount: İSİG sector totals vs register-recorded deaths.

    Only years present in the İSİG series are compared; the caveat text is
    part of the result and must be displayed with it.
    """
    isig = _isig_series(conn)
    if public_incidents is None:
        register = _register_deaths_by_year(conn)
    else:
        # The dashboard must compare the exact export it displays, even when
        # the working database has newer records or publication blockers.
        register: dict[int, int] = {}
        for incident in public_incidents:
            date = incident.get("incident_start_datetime")
            deaths = incident.get("fatalities_current")
            if date and deaths is not None:
                year = int(str(date)[:4])
                register[year] = register.get(year, 0) + int(deaths)
    years = []
    for year in sorted(isig):
        total = isig[year]
        recorded = register.get(year, 0)
        years.append(
            {
                "year": year,
                "isig_total": total,
                "register_deaths": recorded,
                "gap": max(total - recorded, 0),
                "coverage_pct": round(100.0 * min(recorded, total) / total, 1) if total else None,
            }
        )
    total_isig = sum(y["isig_total"] for y in years)
    total_recorded = sum(min(y["register_deaths"], y["isig_total"]) for y in years)
    return {
        "years": years,
        "total_isig": total_isig,
        "total_recorded": total_recorded,
        "total_gap": max(total_isig - total_recorded, 0),
        "caveat": GAP_CAVEAT,
    }


def projection(
    conn: sqlite3.Connection, basis_years: int = 8, z: float = 1.645
) -> dict[str, object] | None:
    """Cost-of-inaction baseline from the İSİG series (None if too few years).

    STATUS: PROPOSED methodology — see docs/analysis_methods.md and
    docs/open_questions.md #17.
    """
    series = _isig_series(conn)
    if len(series) < 5:
        return None
    years = sorted(series)[-basis_years:]
    values = [series[y] for y in years]
    mean = statistics.fmean(values)
    variance = statistics.variance(values) if len(values) > 1 else mean
    sd = math.sqrt(max(variance, mean))  # never narrower than Poisson dispersion
    return {
        "expected": round(mean),
        "low": max(round(mean - z * sd), 0),
        "high": round(mean + z * sd),
        "basis_years": [years[0], years[-1]],
        "method": PROJECTION_METHOD,
    }


def policy_events(csv_path: str | Path = POLICY_EVENTS_CSV) -> list[dict[str, str]]:
    """Curated, sourced public-record timeline events (descriptive only)."""
    path = Path(csv_path)
    with path.open(encoding="utf-8", newline="") as fh:
        events = list(csv.DictReader(fh))
    required = {"date", "label_tr", "label_en", "kind", "source_url", "notes"}
    if events and required - set(events[0]):
        raise ValueError(f"{path.name}: missing columns {sorted(required)}")
    return sorted(events, key=lambda e: e["date"])


def rate_context(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Deaths-per-100M-tonnes comparison rows (documented denominators only)."""
    return [
        {
            "country": row["classification_code"],
            "year": int(row["period_start"][:4]) if row["period_start"] else None,
            "value": float(row["numerator"]),
            "unit": row["unit"],
            "comparability_notes": row["comparability_notes"],
        }
        for row in conn.execute(
            "SELECT classification_code, period_start, numerator, unit, comparability_notes "
            "FROM aggregate_occupational_statistics "
            "WHERE unit = 'deaths_per_100M_tonnes_coal' "
            "ORDER BY classification_code, period_start"
        )
    ]
