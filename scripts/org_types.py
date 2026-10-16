"""Fill the organization type for the companies named in incident roles.

Role in the evidence flow: an attribute of the organization row, set by a
reviewer and logged with the wording that supports it. The public export
carries `organization_type` and it read `unknown` for every organization,
which hid the one distinction readers most need: a state enterprise and a
private contractor are not the same kind of operator.

Each value below is supported either by the quoted wording of the source
already cited for that role (sirket, firma, A.S., taseron firma) or, for the
state coal corporation, by its own encyclopedia record. Nothing is inferred
from the shape of a name alone: an organization no source describes keeps
`unknown`.
"""

from __future__ import annotations

import argparse

from mining_accidents.database import get_connection
from mining_accidents.review import log_review_action

TTK_SOURCE = "https://tr.wikipedia.org/wiki/T%C3%BCrkiye_Ta%C5%9Fk%C3%B6m%C3%BCr%C3%BC_Kurumu"

#: organization -> (type, the wording that supports it)
TYPES: dict[str, tuple[str, str]] = {
    "Türkiye Taşkömürü Kurumu": (
        "state_enterprise",
        'Established in public law, not incorporated privately: "Türkiye Taşkömürü Kurumu, '
        '1983 yılında 96 sayılı kanun hükmünde kararname (KHK) ile kuruldu." '
        f"({TTK_SOURCE})",
    ),
    "Soma Kömür İşletmeleri A.Ş.": (
        "private_company",
        'A joint-stock company of a private group: "Soma Holding şirketlerinden Soma Kömür '
        'İşletmeleri A.Ş."',
    ),
    "Matsan Madencilik": (
        "private_company",
        "Described as a company by the cited source: \"Matsan Madencilik Şirketi'ne ait kömür "
        'ocağında".',
    ),
    "Şentaş Madencilik": (
        "private_company",
        "Registered as a joint-stock company: \"Şen Madencilik Sanayi ve Ticaret A.Ş'nin "
        '(Şentaş Madencilik)".',
    ),
    "Has Şekerler Madencilik": (
        "private_company",
        'Described as a company by the cited source: "Has Şekerler Madencilik Şirketi".',
    ),
    "Yapı-Tek": (
        "private_company",
        'Described as a subcontracting firm: "taşeron firma Yapı-Tek".',
    ),
    "Antlar İnşaat": (
        "private_company",
        "Described as a subcontracting company: \"Park Elektrik'e bağlı taşeron şirket Antlar "
        'İnşaat".',
    ),
    "Park Teknik A.Ş.": (
        "private_company",
        'A joint-stock company of a private group: "Ciner Holding\'e bağlı Park Teknik A.Ş.".',
    ),
    "Park Elektrik": (
        "private_company",
        'Part of a private group and publicly listed: "Ciner Holding\'e bağlı Park Elektrik"; '
        '"halka açık bir şirket olan Park Elektrik".',
    ),
    "Anagold Madencilik A.Ş.": (
        "private_company",
        'A joint-stock company held by two private shareholders: "Anagold Madencilik A.Ş. '
        'tarafından işletilmektedir".',
    ),
    "SSR Mining": (
        "private_company",
        "A listed company: \"Kanada merkezli SSR Madencilik'in Toronto ve New York "
        'borsalarında işlem gören hisseleri".',
    ),
    "Çalık Holding": (
        "private_company",
        'A private holding company: "Çalık Holding\'in yan kuruluşu Lidya Madencilik A.Ş.".',
    ),
    "STFA Tünel İnşaatı": (
        "private_company",
        "A contractor extracting on another company's behalf: \"Etibank A.Ş adına maden "
        'çıkartan STFA Tünel İnşaatı".',
    ),
    "Bükköy Madencilik": (
        "private_company",
        'Named as the company owning the pit: "Bükköy Madencilik\'e ait kömür ocağında".',
    ),
    "Kömür İşletmeleri A.Ş. (KİAŞ)": (
        "private_company",
        "A joint-stock company: \"Kömür İşletmeleri AŞ'ye (KİAŞ) ait Gediz Linyit "
        'İşletmesi ocağı".',
    ),
    "Eti Bakır": (
        "private_company",
        'Held by a private group: "Cengiz Holdinge ait Eti Bakır maden sahası".',
    ),
    "HemGrup A.Ş.": (
        "private_company",
        "A joint-stock company, named in a trade union's statement about the site.",
    ),
    "İmbat Madencilik": (
        "private_company",
        'Described as a mining company by the cited source: "maden şirketinin genel müdürü".',
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="database/mining_accidents.sqlite")
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    conn = get_connection(args.db_path)

    for name, (org_type, support) in TYPES.items():
        row = conn.execute(
            "SELECT organization_id, organization_type FROM organizations "
            "WHERE organization_name_tr = ?",
            (name,),
        ).fetchone()
        if row is None:
            print(f"!! {name} is not in this database")
            continue
        if row["organization_type"] == org_type:
            continue
        conn.execute(
            "UPDATE organizations SET organization_type = ? WHERE organization_id = ?",
            (org_type, int(row["organization_id"])),
        )
        log_review_action(
            conn,
            args.reviewer,
            "organization_type_set",
            "organization",
            int(row["organization_id"]),
            before_summary=str(row["organization_type"]),
            after_summary=org_type,
            notes=support,
        )
        conn.commit()
        print(f"{name}: {org_type}")


if __name__ == "__main__":
    main()
