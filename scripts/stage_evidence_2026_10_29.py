"""Stage the sourced correction packet; never promote it to canonical data."""

from __future__ import annotations

import argparse
from pathlib import Path

from mining_accidents.database import get_connection
from mining_accidents.evidence_notes import stage_packet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, required=True)
    args = parser.parse_args()
    if not args.db_path.is_file():
        parser.error(
            "An existing working database is required; no empty replacement will be created"
        )
    conn = get_connection(args.db_path)
    try:
        result = stage_packet(conn, Path("data/staging/evidence_2026_10_29"))
        print(result)
        print("Candidate claims remain needs_review. Canonical data and decisions are unchanged.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
