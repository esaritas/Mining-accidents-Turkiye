"""Correct two company records and fill the missing home countries.

Role in the evidence flow: corrections to organization rows, each logged.
Canonical facility values are untouched; this only fixes who the company is
and where it is from.

Two errors from the first enrichment pass:

* Çayeli's owner field reads "Cengiz İnşaat, part of Cengiz Holding<br>
  Previously [[First Quantum Minerals]]". The name kept the markup, and the
  home country was read from the link in it, which names the *previous*
  owner, a Canadian company. Çayeli's owner is recorded as Cengiz İnşaat, a
  Turkish company, and the former owner is left out rather than guessed at.
* Amasra ended up with two organizations for one body: "Türkiye Taşkömürü
  Kurumu" from the structured source and "Turkish Hard Coal Enterprises" from
  the article. The roles are re-pointed at the Turkish name and the duplicate
  removed.

Countries are then filled from each company's own Wikidata item, reached
through its Wikipedia article. A company that cannot be resolved keeps a blank
country rather than a guessed one.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.parse

from mining_accidents.adapters.wikidata import _http_get
from mining_accidents.database import get_connection
from mining_accidents.review import log_review_action

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

#: Company name as recorded -> the article to read its home country from.
#: Only companies whose article title differs from the recorded name need one.
COUNTRY_LOOKUP = {
    "Koza İpek Holding": "Koza İpek Holding",
    "Eldorado Gold": "Eldorado Gold",
    "European Nickel": "European Nickel",
    "Cengiz İnşaat": "Cengiz Holding",
    "TKİ": "Turkish Coal Enterprises",
    "Anagold Inc": "",  # a JV; its own country is not stated in an assessed source
    "POMZA EXPORT": "",  # Turkish firm, no article found
    "Suat Bilgin": "",
}


def _country_of(title: str) -> tuple[str, str, str] | None:
    if not title:
        return None
    raw = _http_get(
        "https://en.wikipedia.org/w/api.php",
        {
            "action": "query",
            "prop": "pageprops",
            "titles": title,
            "redirects": "1",
            "format": "json",
        },
    )
    page = list(json.loads(raw)["query"]["pages"].values())[0]
    item = page.get("pageprops", {}).get("wikibase_item")
    if not item:
        return None
    # A company item often states no country directly; its headquarters or
    # country of origin answers the same question.
    query = (
        "SELECT ?code ?label WHERE { VALUES ?p { wdt:P17 wdt:P495 } "
        "{ wd:" + item + " ?p ?c . } UNION { wd:" + item + " wdt:P159/wdt:P17 ?c . } "
        "OPTIONAL { ?c wdt:P297 ?code . } "
        'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". ?c rdfs:label ?label. } }'
        " LIMIT 1"
    )
    rows = json.loads(_http_get(WIKIDATA_SPARQL, {"query": query, "format": "json"}))["results"][
        "bindings"
    ]
    if not rows:
        return None
    url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
    return (
        rows[0].get("code", {}).get("value", ""),
        rows[0].get("label", {}).get("value", ""),
        url,
    )


def _fix_cengiz(conn: sqlite3.Connection, reviewer: str) -> None:
    row = conn.execute(
        "SELECT organization_id, organization_name_tr, country_label FROM organizations "
        "WHERE organization_name_tr LIKE 'Cengiz%'"
    ).fetchone()
    if row is None or row["organization_name_tr"] == "Cengiz İnşaat":
        return
    conn.execute(
        "UPDATE organizations SET organization_name_tr = 'Cengiz İnşaat', "
        "organization_name_normalized = 'cengiz insaat', country_code = NULL, "
        "country_label = NULL WHERE organization_id = ?",
        (row["organization_id"],),
    )
    log_review_action(
        conn,
        reviewer,
        "organization_corrected",
        "organization",
        int(row["organization_id"]),
        before_summary=f"{row['organization_name_tr']} / {row['country_label']}",
        after_summary="Cengiz İnşaat / country to be resolved",
        notes="The recorded name kept the infobox markup and the home country had been read "
        "from the link to the previous owner, First Quantum Minerals, a Canadian company. "
        "Çayeli's owner is Cengiz İnşaat; the former owner is not recorded here.",
    )
    conn.commit()
    print("Çayeli: owner corrected to Cengiz İnşaat, country cleared")


def _merge_ttk(conn: sqlite3.Connection, reviewer: str) -> None:
    keep = conn.execute(
        "SELECT organization_id FROM organizations WHERE organization_name_tr = "
        "'Türkiye Taşkömürü Kurumu'"
    ).fetchone()
    dupe = conn.execute(
        "SELECT organization_id FROM organizations WHERE organization_name_tr = "
        "'Turkish Hard Coal Enterprises'"
    ).fetchone()
    if not keep or not dupe:
        return
    keep_id, dupe_id = int(keep["organization_id"]), int(dupe["organization_id"])
    moved = conn.execute(
        "UPDATE facility_organization_roles SET organization_id = ? WHERE organization_id = ? "
        "AND NOT EXISTS (SELECT 1 FROM facility_organization_roles x WHERE x.facility_id = "
        "facility_organization_roles.facility_id AND x.organization_id = ? AND x.role = "
        "facility_organization_roles.role)",
        (keep_id, dupe_id, keep_id),
    ).rowcount
    conn.execute("DELETE FROM facility_organization_roles WHERE organization_id = ?", (dupe_id,))
    conn.execute("DELETE FROM organizations WHERE organization_id = ?", (dupe_id,))
    log_review_action(
        conn,
        reviewer,
        "organization_merged",
        "organization",
        keep_id,
        before_summary="Turkish Hard Coal Enterprises",
        after_summary="Türkiye Taşkömürü Kurumu",
        notes="One body under two names: the English name came from the article, the Turkish "
        "from the structured source. The Turkish name is kept.",
    )
    conn.commit()
    print(f"TTK: duplicate organization merged ({moved} role(s) re-pointed)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="database/mining_accidents.sqlite")
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    conn = get_connection(args.db_path)
    reviewer = args.reviewer

    _fix_cengiz(conn, reviewer)
    _merge_ttk(conn, reviewer)

    rows = conn.execute(
        "SELECT organization_id, organization_name_tr FROM organizations "
        "WHERE (country_code IS NULL OR country_code = '') AND organization_id IN "
        "(SELECT organization_id FROM facility_organization_roles)"
    ).fetchall()
    for row in rows:
        name = row["organization_name_tr"]
        title = COUNTRY_LOOKUP.get(name, name)
        if title == "":
            print(f"{name}: no article to resolve a country from; left blank")
            continue
        found = _country_of(title)
        if not found:
            print(f"{name}: country not resolved; left blank")
            continue
        code, label, url = found
        conn.execute(
            "UPDATE organizations SET country_code = ?, country_label = ? "
            "WHERE organization_id = ?",
            (code or None, label or None, int(row["organization_id"])),
        )
        log_review_action(
            conn,
            reviewer,
            "organization_country_set",
            "organization",
            int(row["organization_id"]),
            after_summary=f"{code} {label}",
            notes=f"Home country from the company's own record, via {url}",
        )
        conn.commit()
        print(f"{name}: {code} {label}")


if __name__ == "__main__":
    main()
