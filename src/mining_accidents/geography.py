"""Geography rules: WGS84 coordinates, precision semantics, sanity bounds.

Role in the evidence flow: every published coordinate carries a precision
category and a source claim; this module supplies the shared rules —
including the Turkey bounding-box *heuristic* (a sanity flag, never a border
test or auto-reject) and the pin-rendering contract for the future dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoundingBox:
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float

    def contains(self, latitude: float, longitude: float) -> bool:
        return (
            self.lat_min <= latitude <= self.lat_max and self.lon_min <= longitude <= self.lon_max
        )


#: Heuristic sanity box for Türkiye (config/project.yml mirrors these values).
#: Values outside are FLAGGED for review, never auto-rejected.
TURKEY_BBOX = BoundingBox(lat_min=35.5, lat_max=42.5, lon_min=25.5, lon_max=45.0)

#: Precision categories from best to worst (coordinate_precisions.csv).
PRECISION_ORDER: tuple[str, ...] = (
    "exact_verified",
    "facility_approximate",
    "settlement",
    "district_centroid",
    "province_centroid",
    "unknown",
)

#: Worst precision that may ever be rendered as an exact map pin
#: (dashboard/README.md contract).
_EXACT_PIN_PRECISIONS = frozenset({"exact_verified", "facility_approximate"})


def in_turkey_bbox(latitude: float, longitude: float, bbox: BoundingBox = TURKEY_BBOX) -> bool:
    """True if the point is inside the heuristic sanity box."""
    return bbox.contains(latitude, longitude)


def may_render_exact_pin(coordinate_precision: str | None) -> bool:
    """Dashboard contract: worse than facility_approximate is never an exact pin."""
    return coordinate_precision in _EXACT_PIN_PRECISIONS


def precision_rank(coordinate_precision: str) -> int:
    """Lower is better. Unknown categories rank worst."""
    try:
        return PRECISION_ORDER.index(coordinate_precision)
    except ValueError:
        return len(PRECISION_ORDER)


def check_coordinates(
    latitude: float | None,
    longitude: float | None,
    coordinate_precision: str | None,
    bbox: BoundingBox = TURKEY_BBOX,
) -> list[str]:
    """Return human-readable flags (empty list = no concerns). Never rejects."""
    flags: list[str] = []
    if latitude is None and longitude is None:
        return flags
    if (latitude is None) != (longitude is None):
        flags.append("coordinate pair is incomplete (one of latitude/longitude missing)")
        return flags
    assert latitude is not None and longitude is not None
    if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
        flags.append("coordinates outside valid WGS84 range")
        return flags
    if not bbox.contains(latitude, longitude):
        flags.append(
            "coordinates outside Turkey sanity bounding box "
            "(heuristic flag, not a border test — review, do not auto-reject)"
        )
    if coordinate_precision is None:
        flags.append("coordinates present but coordinate_precision missing")
    elif coordinate_precision not in PRECISION_ORDER:
        flags.append(f"unknown coordinate_precision category: {coordinate_precision!r}")
    return flags
