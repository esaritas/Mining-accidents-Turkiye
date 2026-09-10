"""Presentation checks do not promote claims or change canonical facts."""

import json
import shutil
from pathlib import Path

import pytest

from mining_accidents.research import annual_context, has_facility_location, verify_public_export


def test_parallel_series_preserve_absence_and_do_not_subtract():
    rows = annual_context(
        [{"incident_start_datetime": "2099-01-01", "fatalities_current": 5}],
        [{"year": 2098, "deaths": 8}, {"year": 2099, "deaths": 3}],
    )
    assert rows == [
        {"year": 2098, "register_deaths": None, "sector_deaths": 8},
        {"year": 2099, "register_deaths": 5, "sector_deaths": 3},
    ]


def test_duplicate_context_year_rejected():
    with pytest.raises(ValueError, match="Ambiguous"):
        annual_context([], [{"year": 2099, "deaths": 1}] * 2)


@pytest.mark.parametrize("precision", [None, "province_centroid", "district_approximate"])
def test_coarse_coordinates_are_not_facility_points(precision):
    assert not has_facility_location(
        {"coordinate_precision": precision, "latitude": 39, "longitude": 32}
    )


def test_legacy_manifest_still_checks_json_parity(tmp_path):
    public = Path(__file__).resolve().parents[1] / "data" / "public"
    shutil.copytree(public, tmp_path / "public")
    verify_public_export(tmp_path / "public")
    path = tmp_path / "public" / "incidents.json"
    rows = json.loads(path.read_text())
    rows[0]["fatalities_current"] += 1
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError, match="disagree|checksum mismatch"):
        verify_public_export(tmp_path / "public")
