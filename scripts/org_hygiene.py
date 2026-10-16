"""Two corrections to the organizations table, each logged.

Role in the evidence flow: corrections to organization rows. No canonical
incident value changes; the claims that named these organizations stay as
they were written, because claims are append-only.

* A named private individual was standing in the owner column of one site,
  harvested from a source that wrote a person's name where a company would
  normally be. This register publishes no personal data, and an individual
  named beside a mining accident reads as an attribution of responsibility,
  which is not what this project does. The site keeps its claim and loses
  the owner row, so it reads "not stated" like every other site whose
  operator no open source names.
* Çöpler's operator appeared twice: "Anagold Inc" from the structured site
  source and "Anagold Madencilik A.Ş." from the incident article. One body,
  two spellings. The Turkish legal name is kept.
* Etibank likewise appeared as "Etibank" on sixteen historic site records and
  as "Etibank A.Ş." on the Küre 2004 incident. The short form is kept, because
  it is the one the site layer already uses.
"""

from __future__ import annotations

import argparse

from mining_accidents.database import get_connection
from mining_accidents.review import log_review_action


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="database/mining_accidents.sqlite")
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    conn = get_connection(args.db_path)
    reviewer = args.reviewer

    person = conn.execute(
        "SELECT organization_id FROM organizations WHERE organization_name_tr = 'Suat Bilgin'"
    ).fetchone()
    if person:
        org_id = int(person["organization_id"])
        removed = conn.execute(
            "DELETE FROM facility_organization_roles WHERE organization_id = ?", (org_id,)
        ).rowcount
        conn.execute("DELETE FROM organizations WHERE organization_id = ?", (org_id,))
        log_review_action(
            conn,
            reviewer,
            "organization_withdrawn",
            "organization",
            org_id,
            before_summary="a named private individual recorded as a site owner",
            after_summary="withdrawn; the site now reads not stated",
            notes="This register publishes no personal data. The harvest read a person's "
            f"name out of a source's owner field. {removed} site role row(s) removed. The "
            "claim itself is append-only and remains, unpublished.",
        )
        conn.commit()
        print(f"withdrew a personal name from the organizations table ({removed} role row)")

    _merge(conn, args.reviewer, "Anagold Madencilik A.Ş.", "Anagold Inc")
    _merge(conn, args.reviewer, "Etibank", "Etibank A.Ş.")


def _merge(conn, reviewer: str, keep_name: str, dupe_name: str) -> None:
    """Fold one spelling of a company into another, keeping every role."""
    keep = conn.execute(
        "SELECT organization_id FROM organizations WHERE organization_name_tr = ?",
        (keep_name,),
    ).fetchone()
    dupe = conn.execute(
        "SELECT organization_id FROM organizations WHERE organization_name_tr = ?",
        (dupe_name,),
    ).fetchone()
    if keep and dupe:
        keep_id, dupe_id = int(keep["organization_id"]), int(dupe["organization_id"])
        moved = conn.execute(
            "UPDATE facility_organization_roles SET organization_id = ? WHERE organization_id = ? "
            "AND NOT EXISTS (SELECT 1 FROM facility_organization_roles x WHERE x.facility_id = "
            "facility_organization_roles.facility_id AND x.organization_id = ? AND x.role = "
            "facility_organization_roles.role)",
            (keep_id, dupe_id, keep_id),
        ).rowcount
        moved += conn.execute(
            "UPDATE incident_organization_roles SET organization_id = ? WHERE organization_id = ? "
            "AND NOT EXISTS (SELECT 1 FROM incident_organization_roles x WHERE x.incident_id = "
            "incident_organization_roles.incident_id AND x.organization_id = ? AND x.role = "
            "incident_organization_roles.role)",
            (keep_id, dupe_id, keep_id),
        ).rowcount
        conn.execute(
            "DELETE FROM facility_organization_roles WHERE organization_id = ?", (dupe_id,)
        )
        conn.execute(
            "DELETE FROM incident_organization_roles WHERE organization_id = ?", (dupe_id,)
        )
        conn.execute("DELETE FROM organizations WHERE organization_id = ?", (dupe_id,))
        log_review_action(
            conn,
            reviewer,
            "organization_merged",
            "organization",
            keep_id,
            before_summary=dupe_name,
            after_summary=keep_name,
            notes="One company under two spellings, from two sources. The name already used "
            f"across the register is kept; {moved} role row(s) re-pointed.",
        )
        conn.commit()
        print(f"merged {dupe_name} into {keep_name} ({moved} role row(s) re-pointed)")


if __name__ == "__main__":
    main()
