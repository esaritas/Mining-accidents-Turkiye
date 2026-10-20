"""Give every site a commodity code, in one language per reader.

Role in the evidence flow: a correction to facility attributes, logged. The
claims that carried these values are append-only and untouched.

Two defects from the quality audit of 2026-10-20 (B4):

* Eleven sites carried a specific commodity in the free-text label while the
  code said `other`: bauxite, cobalt ore, gold ore, manganese, nickel,
  palladium, phosphates, rock salt, silver ore. Gold was therefore split
  between the `gold` code and an `other` row labelled "gold ore", and
  phosphate between `phosphate` and `other`.
* Labels arrived in whichever language the source wrote them, so the same
  commodity appeared as `coal` on 19 sites and `kömür` on four, `copper` on
  four and `bakır` on two. The export published both spellings, and the page
  fell back to the stored label whenever a code was missing, which put English
  words in the Turkish page and Turkish words in the English one.

The fix is to code what the source said and let the vocabulary carry the
words: the page renders a commodity from its code, so each reader sees one
language. Six codes are added to the vocabulary for commodities Türkiye mines
that it did not yet cover.
"""

from __future__ import annotations

import argparse

from mining_accidents.database import get_connection
from mining_accidents.review import log_review_action
from mining_accidents.vocabularies import load_vocabulary

#: free-text label as harvested -> vocabulary code
LABEL_TO_CODE: dict[str, str] = {
    "bauxite": "bauxite",
    "cobalt ore": "cobalt",
    "gold ore": "gold",
    "manganese ores": "manganese",
    "nickel ore": "nickel",
    "palladium": "platinum_group",
    "phosphates": "phosphate",
    "rock salt": "salt",
    "silver ore": "silver",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="database/mining_accidents.sqlite")
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    conn = get_connection(args.db_path)
    labels = {entry.code: entry for entry in load_vocabulary("commodities")}

    recoded = relabelled = 0
    for row in conn.execute(
        "SELECT facility_id, facility_name_tr, commodity_code, commodity_label FROM facilities "
        "WHERE commodity_label IS NOT NULL AND commodity_label <> ''"
    ).fetchall():
        label = str(row["commodity_label"]).strip()
        code = str(row["commodity_code"] or "")
        target = LABEL_TO_CODE.get(label.casefold(), code)
        if target and target not in labels:
            print(f"!! {target} is not in the commodities vocabulary")
            continue
        new_label = labels[target].label_tr if target in labels else label
        if target == code and new_label == label:
            continue
        conn.execute(
            "UPDATE facilities SET commodity_code = ?, commodity_label = ? WHERE facility_id = ?",
            (target or None, new_label, int(row["facility_id"])),
        )
        log_review_action(
            conn,
            args.reviewer,
            "facility_commodity_recoded" if target != code else "facility_commodity_relabelled",
            "facility",
            int(row["facility_id"]),
            before_summary=f"{code or '-'} / {label}",
            after_summary=f"{target or '-'} / {new_label}",
            notes="Commodity coded against the project vocabulary so the page can render it "
            "in the reader's language; the source's own wording stays on the claim.",
        )
        if target != code:
            recoded += 1
        else:
            relabelled += 1
    conn.commit()
    print(f"{recoded} site(s) recoded, {relabelled} label(s) normalised")

    remaining = conn.execute(
        "SELECT COUNT(*) FROM facilities WHERE commodity_code = 'other'"
    ).fetchone()[0]
    print(f"{remaining} site(s) still coded 'other'")


if __name__ == "__main__":
    main()
