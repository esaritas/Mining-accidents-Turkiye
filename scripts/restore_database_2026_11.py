"""Rebuild the working database lost on 2026-11-11 from the committed export.

Role in the evidence flow: a one-off recovery, kept as the record of exactly
how the database that now exists was made. It restores what the export of
2026-10-29 published (commit 46154be) and nothing else; see
docs/database_recovery.md for what that does and does not bring back.

    python3 scripts/restore_database_2026_11.py --reviewer "<name>"

The reviewer is the person authorising the restoration. Every restored
decision is recorded under that name, as the original decisions were.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mining_accidents import restore

EXPORT_COMMIT = "46154be"

#: Withdrawn without a merge, so absent from merged_id_redirects.csv. The
#: reason is the one recorded in docs/corrections_log.csv.
WITHDRAWN = {
    "TR-MINE-2014-0002": (
        "The list entry joined two accidents of 1 November 2014 in different provinces "
        "(Amasra, Bartın: two deaths; Gelik, Zonguldak: one death). Replaced by two "
        "separate records."
    ),
}

#: The published citation named the member of parliament who gave the speech.
#: The register names no individual anywhere, so the restored title drops it.
TITLE_REDACTIONS = {
    "Genel Kurul konuşması (Özcan Ulupınar) — 3 Mart 1992 Kozlu faciası": (
        "TBMM Genel Kurul konuşması, 3 Mart 1992 Kozlu faciası"
    ),
}

#: The Amasra toll became 43 when the Assembly's record of 6 April 2023 stated
#: it. Every other figure is dated to the export, the last date it is known
#: to have been the register's figure.
OBSERVED_AS_OF = {"TR-MINE-2022-0001": "2023-04-06"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--db-path", default="database/mining_accidents.sqlite")
    parser.add_argument("--keep-titles", action="store_true", help="No title redaction.")
    args = parser.parse_args()
    summary = restore.restore_from_export(
        args.db_path,
        Path("data/public"),
        reviewer=args.reviewer,
        export_label=f"commit {EXPORT_COMMIT}",
        export_url_base=(
            f"https://github.com/esaritas/Mining-accidents-Turkiye/blob/{EXPORT_COMMIT}"
        ),
        payload_path="dashboard/data.js",
        withdrawn=WITHDRAWN,
        title_redactions={} if args.keep_titles else TITLE_REDACTIONS,
        observed_as_of=OBSERVED_AS_OF,
        archive_index="data/archive/index.json",
    )
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
