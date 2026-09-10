"""Research presentation integrity for an already published evidence snapshot.

Role in the evidence flow: verifies public files and enriches presentation
metadata; never creates source claims, reviewer decisions, or canonical facts.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

POINT_PRECISIONS = {"exact_verified", "facility_approximate"}


def has_facility_location(record: dict[str, object]) -> bool:
    return (
        record.get("coordinate_precision") in POINT_PRECISIONS
        and record.get("latitude") is not None
        and record.get("longitude") is not None
    )


def annual_context(
    incidents: list[dict[str, object]], aggregates: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Parallel series only: their difference is not a count of missing people."""
    register: dict[int, int] = {}
    for incident in incidents:
        if incident.get("incident_start_datetime"):
            year = int(str(incident["incident_start_datetime"])[:4])
            register[year] = register.get(year, 0) + int(incident.get("fatalities_current") or 0)
    sector = {}
    for row in aggregates:
        year = int(row["year"])
        if year in sector:
            raise ValueError(f"Ambiguous aggregate series: multiple observations for {year}")
        sector[year] = row["deaths"]
    return [
        {"year": year, "register_deaths": register.get(year), "sector_deaths": sector.get(year)}
        for year in sorted(register.keys() | sector.keys())
    ]


def verify_public_export(public_dir: Path) -> dict[str, object]:
    """Check declared hashes plus CSV/JSON parity (legacy manifests omit JSON)."""
    manifest = json.loads((public_dir / "export_manifest.json").read_text(encoding="utf-8"))
    hashes = manifest["file_sha256"]
    for required in (
        "incidents.csv",
        "sources.csv",
        "incident_classifications.csv",
        "facilities.csv",
    ):
        if required not in hashes:
            raise ValueError(f"Missing manifest checksum: {required}")
    for name, expected in hashes.items():
        if Path(name).name != name:
            raise ValueError(f"Invalid export filename: {name}")
        if hashlib.sha256((public_dir / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Public export checksum mismatch: {name}")
    incidents = json.loads((public_dir / "incidents.json").read_text(encoding="utf-8"))
    with (public_dir / "incidents.csv").open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        columns = reader.fieldnames
        rows = list(reader)
    expected_rows = [
        {key: "" if row.get(key) is None else str(row[key]) for key in columns} for row in incidents
    ]
    if rows != expected_rows or len(rows) != manifest["row_counts"]["incidents"]:
        raise ValueError("Public incidents CSV, JSON, or manifest count disagree")
    ids = [row["public_incident_id"] for row in incidents]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate public incident IDs")
    return manifest


def refresh_snapshot(public_dir: Path, data_js: Path) -> Path:
    """Refresh presentation from verified public files; retain saved context only.

    The aggregate/pipeline snapshot cannot be regenerated without the working
    database. Its timestamp is retained and no new evidence review is implied.
    """
    from mining_accidents.artifact import _payload_from_js
    from mining_accidents.dashboard import HEADER, _citations, _classifications, _sites

    manifest = verify_public_export(public_dir)
    payload = _payload_from_js(data_js)
    if payload["export_timestamp"] != manifest["export_timestamp"]:
        raise ValueError(
            "Context snapshot and public export timestamps differ; rebuild from database"
        )
    payload["incidents"] = json.loads((public_dir / "incidents.json").read_text(encoding="utf-8"))
    payload["citations"] = _citations(public_dir)
    payload["classifications"] = _classifications(public_dir)
    payload["sites"] = _sites(public_dir)
    for row in [*payload["incidents"], *payload["sites"]]:
        row["province_name"] = payload["province_names"].get(row.get("province_code") or "", "")
    ids = {row["public_incident_id"] for row in payload["incidents"]}
    if (payload["citations"].keys() | payload["classifications"].keys()) - ids:
        raise ValueError("Evidence references an incident outside the public export")
    payload["annual_context"] = annual_context(payload["incidents"], payload["aggregates"])
    payload.pop("coverage_gap", None)
    payload["pipeline"]["published_incidents"] = len(payload["incidents"])
    data_js.write_text(
        HEADER
        + "window.MINING_DATA = "
        + json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + ";\n",
        encoding="utf-8",
    )
    return data_js
