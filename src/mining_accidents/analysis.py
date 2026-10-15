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
import json
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


HAZARD_MATRIX_METHOD = (
    "Both axes are counts of what this register has documented, not "
    "probabilities and not a safety assessment of any site or company. "
    "Severity bands are the deaths recorded in a single incident. A record "
    "appears in every mechanism row its sources document, so rows sum to more "
    "than the number of records. An empty cell means nothing of that kind is "
    "documented here. STATUS: PROPOSED — see docs/analysis_methods.md and "
    "docs/open_questions.md #29."
)

#: Single-incident death bands. The edges are the natural breaks in the record
#: (a single death; a small group; a whole shift; a national disaster), not a
#: severity scale borrowed from elsewhere.
SEVERITY_BANDS: tuple[dict[str, object], ...] = (
    {"key": "1", "low": 1, "high": 1, "label_tr": "1 ölüm", "label_en": "1 death"},
    {"key": "2-9", "low": 2, "high": 9, "label_tr": "2-9 ölüm", "label_en": "2-9 deaths"},
    {"key": "10-49", "low": 10, "high": 49, "label_tr": "10-49 ölüm", "label_en": "10-49 deaths"},
    {"key": "50+", "low": 50, "high": None, "label_tr": "50+ ölüm", "label_en": "50+ deaths"},
)

UNCODED = "not_yet_coded"
MECHANISM_SYSTEM = "project_event_mechanism"


def _band_index(deaths: int) -> int | None:
    for index, band in enumerate(SEVERITY_BANDS):
        low, high = band["low"], band["high"]
        if deaths >= int(low) and (high is None or deaths <= int(high)):
            return index
    return None


def hazard_matrix(public_dir: str | Path = Path("data/public")) -> dict[str, object]:
    """What kind of event is documented, how deadly it was, and where.

    Reads the public export only, so the matrix can be rebuilt by anyone from
    the published files. Two views:

    * ``mechanisms`` — event mechanism against the deaths in a single record.
      This is the shape of a risk matrix (how often against how severe), but
      both axes are documented counts, so it describes a record, not a risk.
    * ``provinces`` — what is documented in each province, beside the number of
      sites the register currently documents there. Provinces holding
      documented sites and no record of their own are counted separately,
      because that is a gap in this register and not a statement about safety.
    """
    public_dir = Path(public_dir)
    incidents = json.loads((public_dir / "incidents.json").read_text(encoding="utf-8"))

    mechanisms: dict[str, dict[str, str]] = {}
    by_incident: dict[str, set[str]] = {}
    classifications = public_dir / "incident_classifications.csv"
    if classifications.exists():
        with classifications.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row["classification_system"] != MECHANISM_SYSTEM:
                    continue
                code = row["classification_code"]
                mechanisms.setdefault(
                    code,
                    {
                        "label_tr": row["classification_label_tr"],
                        "label_en": row["classification_label_en"],
                    },
                )
                by_incident.setdefault(row["public_incident_id"], set()).add(code)

    site_counts: dict[str, int] = {}
    facilities = public_dir / "facilities.csv"
    if facilities.exists():
        with facilities.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row["province_code"]:
                    site_counts[row["province_code"]] = site_counts.get(row["province_code"], 0) + 1

    rows: dict[str, dict[str, object]] = {}
    provinces: dict[str, dict[str, object]] = {}
    for incident in incidents:
        public_id = incident["public_incident_id"]
        deaths = int(incident.get("fatalities_current") or 0)
        year = int(str(incident.get("incident_start_datetime") or "0")[:4]) or None
        codes = sorted(by_incident.get(public_id) or {UNCODED})
        band = _band_index(deaths)
        for code in codes:
            row = rows.setdefault(
                code,
                {
                    "code": code,
                    "label_tr": mechanisms.get(code, {}).get("label_tr", "henüz kodlanmadı"),
                    "label_en": mechanisms.get(code, {}).get("label_en", "not yet coded"),
                    "cells": [0] * len(SEVERITY_BANDS),
                    "records": 0,
                    "deaths": 0,
                    "worst": 0,
                    "years": [],
                },
            )
            row["records"] = int(row["records"]) + 1
            row["deaths"] = int(row["deaths"]) + deaths
            row["worst"] = max(int(row["worst"]), deaths)
            if band is not None:
                row["cells"][band] += 1  # type: ignore[index]
            if year:
                row["years"].append(year)  # type: ignore[attr-defined]
        code_key = incident.get("province_code") or ""
        province = provinces.setdefault(
            code_key,
            {
                "province_code": code_key,
                "records": 0,
                "deaths": 0,
                "latest_year": None,
                "mechanisms": {},
                "documented_sites": site_counts.get(code_key, 0),
            },
        )
        province["records"] = int(province["records"]) + 1
        province["deaths"] = int(province["deaths"]) + deaths
        if year and (province["latest_year"] is None or year > int(province["latest_year"])):
            province["latest_year"] = year
        for code in codes:
            counts: dict[str, int] = province["mechanisms"]  # type: ignore[assignment]
            counts[code] = counts.get(code, 0) + 1

    total_deaths = sum(int(i.get("fatalities_current") or 0) for i in incidents)
    # Heaviest documented toll first, with the uncoded bucket always last: it
    # is a gap in the coding, not a kind of event, and should not sit among the
    # mechanisms as though it were one.
    ordered = sorted(
        rows.values(),
        key=lambda r: (r["code"] == UNCODED, -int(r["deaths"]), -int(r["records"])),
    )
    for row in ordered:
        years = sorted(row.pop("years"))  # type: ignore[arg-type]
        row["first_year"] = years[0] if years else None
        row["latest_year"] = years[-1] if years else None
        row["share_of_deaths"] = (
            round(100.0 * int(row["deaths"]) / total_deaths, 1) if total_deaths else None
        )

    sites_without_record = {
        code: count for code, count in site_counts.items() if code not in provinces
    }
    return {
        "bands": [dict(band) for band in SEVERITY_BANDS],
        "mechanisms": ordered,
        "provinces": sorted(
            provinces.values(), key=lambda p: (-int(p["deaths"]), -int(p["records"]))
        ),
        "mechanism_order": [row["code"] for row in ordered],
        "sites_outside_recorded_provinces": {
            "sites": sum(sites_without_record.values()),
            "provinces": len(sites_without_record),
        },
        "totals": {
            "records": len(incidents),
            "deaths": total_deaths,
            "records_with_a_mechanism": sum(
                1 for i in incidents if i["public_incident_id"] in by_incident
            ),
            "documented_sites": sum(site_counts.values()),
        },
        "method": HAZARD_MATRIX_METHOD,
    }
