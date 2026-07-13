"""Duplicate-candidate detection and name matching.

Role in the evidence flow: flags *candidate* duplicate incidents for human
review using the blocking key from docs/research_protocol.md §12 (same
province + incident date within a window + fuzzy facility/title match).
Nothing here merges anything — merges are human decisions recorded in
``incident_merge_log``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher

from mining_accidents.normalization import normalize_tr

DEFAULT_DATE_WINDOW_DAYS = 3
DEFAULT_SIMILARITY_THRESHOLD = 0.75


@dataclass(frozen=True)
class DuplicateCandidate:
    incident_id_a: int
    incident_id_b: int
    province_code: str
    date_difference_days: float
    name_similarity: float


def name_similarity(a: str, b: str) -> float:
    """Similarity of two names after Turkish normalization (0.0-1.0)."""
    na, nb = normalize_tr(a), normalize_tr(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _comparison_name(row: sqlite3.Row) -> str | None:
    """Best available name for fuzzy comparison: facility name, else title."""
    return row["facility_name_tr"] or row["canonical_title_tr"]


def find_duplicate_candidates(
    conn: sqlite3.Connection,
    date_window_days: int = DEFAULT_DATE_WINDOW_DAYS,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[DuplicateCandidate]:
    """Pairs of incidents matching the duplicate blocking key.

    Blocking key: same province_code, incident start dates within
    ±date_window_days, and facility/title similarity >= threshold.
    """
    pairs = conn.execute(
        """
        SELECT a.incident_id AS id_a,
               b.incident_id AS id_b,
               a.province_code AS province_code,
               ABS(julianday(a.incident_start_datetime) - julianday(b.incident_start_datetime))
                   AS day_diff,
               a.canonical_title_tr AS title_a,
               b.canonical_title_tr AS title_b,
               fa.facility_name_tr AS facility_a,
               fb.facility_name_tr AS facility_b
        FROM incidents a
        JOIN incidents b
            ON a.incident_id < b.incident_id
            AND a.province_code = b.province_code
        LEFT JOIN facilities fa ON fa.facility_id = a.facility_id
        LEFT JOIN facilities fb ON fb.facility_id = b.facility_id
        WHERE a.province_code IS NOT NULL
            AND a.incident_start_datetime IS NOT NULL
            AND b.incident_start_datetime IS NOT NULL
            AND day_diff <= ?
        """,
        (date_window_days,),
    ).fetchall()

    candidates: list[DuplicateCandidate] = []
    for row in pairs:
        name_a = row["facility_a"] or row["title_a"]
        name_b = row["facility_b"] or row["title_b"]
        if not name_a or not name_b:
            continue
        similarity = name_similarity(name_a, name_b)
        if similarity >= similarity_threshold:
            candidates.append(
                DuplicateCandidate(
                    incident_id_a=row["id_a"],
                    incident_id_b=row["id_b"],
                    province_code=row["province_code"],
                    date_difference_days=row["day_diff"],
                    name_similarity=round(similarity, 4),
                )
            )
    return sorted(candidates, key=lambda c: (c.incident_id_a, c.incident_id_b))
