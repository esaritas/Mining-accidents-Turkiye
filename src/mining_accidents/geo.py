"""Province reference geometry: lookup + point-in-polygon derivation.

Role in the evidence flow: `data/reference/tur_provinces.geo.json` (Natural
Earth 10m admin-1, public domain) is display/reference geometry, never
evidence. `province_of_point` mechanically derives which province contains a
source-stated coordinate — a deterministic computation on claimed values,
recorded as such wherever it is used (never presented as a source assertion
about the province).
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

PROVINCES_GEOJSON = Path("data/reference/tur_provinces.geo.json")


@cache
def _load_provinces() -> list[tuple[str, list[list[list[float]]]]]:
    """[(province_code, [exterior_ring, ...]), ...] — exterior rings only.

    Turkish provinces have no ring-shaped holes belonging to *other*
    provinces at this resolution, so exterior-ring containment is exact for
    this dataset.
    """
    data = json.loads(PROVINCES_GEOJSON.read_text(encoding="utf-8"))
    provinces = []
    for feature in data["features"]:
        geometry = feature["geometry"]
        polygons = (
            [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        )
        rings = [polygon[0] for polygon in polygons]  # exterior rings
        provinces.append((feature["properties"]["code"], rings))
    return provinces


def _ring_contains(ring: list[list[float]], lon: float, lat: float) -> bool:
    """Ray casting; ring is [[lon, lat], ...]."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def province_of_point(latitude: float, longitude: float) -> str | None:
    """Province code containing the WGS84 point, or None if outside Türkiye."""
    for code, rings in _load_provinces():
        for ring in rings:
            if _ring_contains(ring, longitude, latitude):
                return code
    return None
