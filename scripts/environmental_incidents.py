"""Record documented environmental harm from mining, through the same pipeline.

Role in the evidence flow: source document -> claim -> reviewer decision ->
canonical value, and source document -> claim -> environmental effect. Nothing
is written to a canonical field except through ``review.record_decision``.

Scope, set by the project owner on 2026-10-20 and written up as STATUS:
PROPOSED in docs/environmental_scope_protocol.md. The register had documented
fatal accidents only and said so nowhere: İliç 2024 was held because nine
people died, while the cyanide heap-leach failure that killed them was
recorded as an event mechanism and nothing else, and the Şebinkarahisar
tailings-dam collapse of 2021 was marked out of scope for having no deaths.

What goes in. An incident at a mining or processing site where a source
documents material leaving containment, or reaching ground, water or air
outside the site. What stays out, for now and deliberately: fines,
prosecutions, licence cancellations as sanctions, and anything a source frames
as fault. This register documents what happened, not who should answer for it.

What is deliberately not here. The Ayvalık waste-heap collapse of December
2021 is well reported but no source found states its date, and a date is a
publication-critical field. It waits for one rather than being guessed.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from pathlib import Path

from mining_accidents.database import get_connection, utc_now_iso
from mining_accidents.models import ClaimDecision
from mining_accidents.review import (
    assign_public_incident_id,
    get_active_decision,
    log_review_action,
    record_decision,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from incident_operators import _contains, _page_text, _wiki_text  # noqa: E402

SOURCES: dict[str, dict[str, object]] = {
    "diken_sebinkarahisar": {
        "url": "https://www.diken.com.tr/?p=1042329",
        "organization": "Diken",
        "title": "Çöken barajdan 4 bin 500 ton kimyasal atık yayılmış",
        "published": "2021-11-30",
        "tier": 3,
        "kind": "html",
    },
    "diken_kelkit": {
        "url": "https://www.diken.com.tr/?p=1037971",
        "organization": "Diken",
        "title": "Çevre felaketine davetiye: Atık barajı çöktü, Kelkit Çayı tehdit altında",
        "published": "2021-11-22",
        "tier": 3,
        "kind": "html",
    },
    "medyascope_ilic2022": {
        "url": "https://medyascope.tv/2022/09/24/bakanliga-ilic-itirazi-bakanlik-siyanur-sizintisi-miktari-konusunda-bile-sirketin-beyanini-esas-aliyor-sizan-siyanur-20-degil-210-metrekup/",
        "organization": "Medyascope",
        "title": "Bakanlığa İliç itirazı: sızan siyanür 20 değil 210 metreküp",
        "published": "2022-09-24",
        "tier": 3,
        "kind": "html",
    },
    "wp_ilic": {
        "wiki": ("tr", "İliç maden kazası"),
        "url": "https://tr.wikipedia.org/wiki/%C4%B0li%C3%A7_maden_kazas%C4%B1",
        "organization": "Wikipedia (tr)",
        "title": "İliç maden kazası",
        "published": None,
        "tier": 3,
        "kind": "wiki",
    },
}

#: Each record: the incident itself, what it did, and who was running the site.
#: `existing_incident_id` reuses a row already carrying decided values.
RECORDS: tuple[dict[str, object], ...] = (
    {
        "key": "sebinkarahisar_2021",
        "existing_incident_id": 2,
        "title_tr": "Nesko Şebinkarahisar atık barajı çökmesi",
        "title_en": "Nesko Şebinkarahisar tailings dam failure",
        "datetime": "2021-11-18T00:00:00+03:00",
        "province": "28",
        "related": None,
        "source": "diken_sebinkarahisar",
        "mechanism": ("tailings_dam_failure", "atık barajı çökmesi", "tailings dam failure"),
        "operator": ("Nesko Madencilik A.Ş.", "private_company"),
        "operator_excerpt": "Yedikardeş köyü sınırlarındaki NESKO Madencilik A.Ş.'ye ait "
        "kurşun, çinko, bakır ocağı ve zenginleştirme tesisinin ikinci atık barajındaki iç "
        "set, 18 Kasım'da yıkılmıştı",
        "effects": (
            {
                "type": "containment_failure",
                "qualitative": "İkinci atık barajının iç seti",
                "qualitative_en": "Inner embankment of the second tailings dam",
                "status": "reported",
                "source": "diken_sebinkarahisar",
                "excerpt": "ikinci atık barajındaki iç set, 18 Kasım'da yıkılmıştı",
            },
            {
                "type": "released_material",
                "value": 4500.0,
                "unit": "tonne",
                "qualitative": "Kimyasal atık (kurşun, çinko, bakır zenginleştirme tesisi)",
                "qualitative_en": "Chemical waste from a lead, zinc and copper concentrator",
                "status": "reported",
                "source": "diken_sebinkarahisar",
                "excerpt": "4 bin 500 tondan fazla kimyasal atığın çevreye yayıldığı belirlendi",
            },
            {
                "type": "receiving_environment",
                "qualitative": "Darabul Deresi ve Kılıçkaya Barajı",
                "qualitative_en": "Darabul Deresi stream and the Kılıçkaya reservoir",
                "status": "reported",
                "source": "diken_sebinkarahisar",
                "excerpt": "atıklar, Darabul Deresi ile taşınarak Kılıçkaya Barajı'na ulaştı",
            },
            {
                "type": "receiving_environment",
                "qualitative": "Kelkit Çayı ve ovası (tehdit altında olduğu bildirildi)",
                "qualitative_en": "The Kelkit Çayı river and its plain, reported as threatened",
                # The source reports a threat, not an arrival, and the page used
                # to print it under "Reached" like every other receptor.
                "effect_status": "threatened",
                "status": "alleged",
                "source": "diken_kelkit",
                "excerpt": "Kılıçkaya Barajı'nın bağlı olduğu Kelkit Çayı ve ovasını tehdit "
                "ettiğini belirterek",
            },
        ),
    },
    {
        "key": "ilic_2022",
        "title_tr": "Çöpler Altın Madeni siyanür sızıntısı (2022)",
        "title_en": "Çöpler gold mine cyanide leak (2022)",
        "datetime": "2022-06-21T00:00:00+03:00",
        "province": "24",
        "related": None,
        "source": "medyascope_ilic2022",
        "mechanism": ("chemical_release", "kimyasal sızıntı", "chemical release"),
        "operator": ("Anagold Madencilik A.Ş.", None),
        "operator_excerpt": 'Anagold Madencilik şirketinin ileri sürdüğü "20 metreküp '
        'siyanürlü solüsyon sızdı" açıklamasını',
        "effects": (
            {
                "type": "released_material",
                "value": 20.0,
                "unit": "m3",
                "qualitative": "Siyanürlü solüsyon (şirket beyanı)",
                "qualitative_en": "Cyanide solution, as the operator stated it",
                "status": "reported",
                "source": "medyascope_ilic2022",
                "excerpt": "Şirket yaptığı ilk açıklamada, 20 metreküplük siyanür çözeltisinin "
                "toprağa karıştığını açıklamıştı",
            },
            {
                "type": "released_material",
                "value": 210.0,
                "unit": "m3",
                "qualitative": "Siyanürlü bileşik (bilirkişi raporuna atfen)",
                "qualitative_en": "Cyanide compound, per a court-appointed expert report",
                "status": "technical_finding",
                "source": "medyascope_ilic2022",
                "excerpt": "Bilirkişi raporuna göre, sızan siyanürlü bileşiğin gerçek miktarı "
                "şirketin beyan ettiği gibi 20 metreküp değil, 210 metreküp",
                "notes": "The quantity is in dispute. Both figures are recorded, each with "
                "the status its source carries; this register does not pick between them.",
            },
            {
                "type": "receiving_environment",
                "qualitative": "Toprak; maden Fırat Nehri kıyısında kurulu",
                "qualitative_en": "Ground; the mine stands on the bank of the Euphrates",
                "status": "reported",
                "source": "medyascope_ilic2022",
                "excerpt": "Erzincan'ın İliç ilçesinde, Fırat Nehri kıyısına kurulu Çöpler "
                "Altın Madeni'nde 21 Haziran 2022'de siyanür sızıntısı meydana gelmiş",
            },
            {
                "type": "production_suspension",
                "qualitative": "Bakanlık madenin faaliyetlerini durdurdu",
                "qualitative_en": "The ministry halted operations at the mine",
                "status": "official_finding",
                "source": "medyascope_ilic2022",
                "excerpt": "Çevre, Şehircilik ve İklim Değişikliği Bakanlığı madenin "
                "faaliyetlerini durdurmuştu",
            },
        ),
    },
    {
        "key": "ilic_2024",
        "title_tr": "Çöpler Altın Madeni yığın liç alanı çökmesi (2024)",
        "title_en": "Çöpler gold mine heap leach collapse (2024)",
        "datetime": "2024-02-13T00:00:00+03:00",
        "province": "24",
        "related": "TR-MINE-2024-0001",
        "source": "wp_ilic",
        "mechanism": ("heap_leach_failure", "yığın liç yapısının çökmesi", "heap leach failure"),
        "operator": ("Anagold Madencilik A.Ş.", None),
        "operator_excerpt": "Çöpler altın madeni, Erzincan ilinin İliç ilçesinde Çöpler köyü "
        "yakınlarında kurulmuştur ve Anagold Madencilik A.Ş. tarafından işletilmektedir",
        "effects": (
            {
                "type": "containment_failure",
                "qualitative": "Yığın liç alanı",
                "qualitative_en": "The heap leach pad",
                "status": "reported",
                "source": "wp_ilic",
                "excerpt": "yığın liç alanındaki çökme sonrası acil durum planının devreye "
                "sokulduğu",
            },
            {
                "type": "receiving_environment",
                "qualitative": "Sabırlı Deresi",
                "qualitative_en": "Sabırlı Deresi stream",
                "status": "reported",
                "source": "wp_ilic",
                "excerpt": "liç işleminin yapıldığı bölgedeki toprağın, civar bölgede bulunan "
                "Sabırlı Deresi'ne akmasından dolayı",
            },
            {
                "type": "production_suspension",
                "qualitative": "Çevre izin ve lisans belgeleri iptal edildi, üretim durduruldu",
                "qualitative_en": "Environmental permits and licences cancelled; "
                "production stopped",
                "status": "official_finding",
                "source": "wp_ilic",
                "excerpt": "Anagold Madencilik'in bu maden için almış olduğu çevre izin ve "
                "lisans belgelerini iptal etti ve firmanın tüm üretimi durduruldu",
            },
        ),
    },
)


def _retrieve(key: str) -> tuple[str, str]:
    spec = SOURCES[key]
    if spec["kind"] == "wiki":
        lang, title = spec["wiki"]  # type: ignore[misc]
        text, payload = _wiki_text(lang, title)
    else:
        text, payload = _page_text(str(spec["url"]))
    return text, hashlib.sha256(payload).hexdigest()


def _document(conn: sqlite3.Connection, key: str, digest: str) -> int:
    spec = SOURCES[key]
    url = str(spec["url"])
    row = conn.execute(
        "SELECT source_document_id FROM source_documents WHERE url = ? AND content_hash = ?",
        (url, digest),
    ).fetchone()
    if row:
        return int(row["source_document_id"])
    licence = (
        "CC BY-SA 4.0. Short quotation with attribution; no redistribution of the article text."
        if spec["kind"] == "wiki"
        else "Press article. Quoted as a short evidence excerpt only; not redistributed."
    )
    cur = conn.execute(
        "INSERT INTO source_documents (source_organization, title, document_type, url, "
        "publication_date, retrieved_at, language, content_hash, source_tier, "
        "attribution_required, licence_or_reuse_notes, access_status, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, 'tr', ?, ?, 1, ?, 'open', ?)",
        (
            spec["organization"],
            spec["title"],
            "encyclopedia_article" if spec["kind"] == "wiki" else "news_article",
            url,
            spec["published"],
            utc_now_iso(),
            digest,
            spec["tier"],
            licence,
            "Read for environmental harm documented at a mining site.",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def _reviewed_claim(
    conn: sqlite3.Connection, reviewer: str, incident_id: int, document_id: int, **values
) -> int:
    cur = conn.execute(
        "INSERT INTO claims (incident_id, source_document_id, claim_subject_type, field_name, "
        "raw_value, normalized_value, unit, short_evidence_excerpt, extraction_method, "
        "extractor_version, assertion_status, review_status, confidence_score) "
        "VALUES (?, ?, 'incident', ?, ?, ?, ?, ?, 'ai_assisted', 'environmental_incidents', "
        "?, 'needs_review', 0.9)",
        (
            incident_id,
            document_id,
            values["field_name"],
            values["raw_value"],
            values["normalized_value"],
            values.get("unit"),
            values["excerpt"],
            values.get("assertion_status", "reported"),
        ),
    )
    conn.commit()
    claim_id = int(cur.lastrowid)
    conn.execute("UPDATE claims SET review_status = 'reviewed' WHERE claim_id = ?", (claim_id,))
    log_review_action(
        conn,
        reviewer,
        "claim_reviewed",
        "claim",
        claim_id,
        after_summary=f"{values['field_name']} = {values['normalized_value']}",
        notes="Quote checked verbatim against the retrieved document, whose sha256 is "
        "recorded on the document row.",
    )
    conn.commit()
    return claim_id


def _apply_effect_statuses(conn: sqlite3.Connection, reviewer: str) -> int:
    """Set effect_status on rows already held, from the table in this file.

    Touches one column and writes no claim, no decision and no new row. The
    values come from what each cited source states, which is why a receptor a
    source only reports as threatened stops being shown as one the material
    reached.
    """
    changed = 0
    for record in RECORDS:
        row = conn.execute(
            "SELECT incident_id FROM incidents WHERE canonical_title_tr = ?",
            (record["title_tr"],),
        ).fetchone()
        if row is None:
            print(f"   {record['key']}: not in this database, skipped")
            continue
        for effect in record["effects"]:  # type: ignore[union-attr]
            status = str(effect.get("effect_status", "reported"))
            held = conn.execute(
                "SELECT environmental_effect_id AS eid, effect_status FROM "
                "environmental_effects WHERE incident_id = ? AND effect_type = ? "
                "AND IFNULL(qualitative_value,'') = ?",
                (int(row["incident_id"]), effect["type"], effect.get("qualitative") or ""),
            ).fetchone()
            if held is None or held["effect_status"] == status:
                continue
            conn.execute(
                "UPDATE environmental_effects SET effect_status = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                "WHERE environmental_effect_id = ?",
                (status, held["eid"]),
            )
            conn.commit()
            log_review_action(
                conn,
                reviewer,
                "environmental_effect_status_set",
                "environmental_effect",
                int(held["eid"]),
                before_summary=f"effect_status={held['effect_status']}",
                after_summary=f"effect_status={status}",
                notes="Set from what the cited source states, so a threatened receptor is "
                "no longer displayed as one the material reached.",
            )
            changed += 1
            print(f"   {record['key']}: {effect['type']} -> {status}")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="database/mining_accidents.sqlite")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--statuses-only",
        action="store_true",
        help="Bring effect_status into line with the table above without retrieving "
        "anything. For a correction to a column on rows whose quotes were already "
        "verified and whose document hashes are on file, where re-retrieval is either "
        "unnecessary or impossible: Medyascope began refusing this project's requests "
        "with HTTP 403 (checked 2026-10-29) and no local copy of its pages was kept, "
        "so the Çöpler 2022 record cannot be re-verified from source at all "
        "(open question 42).",
    )
    args = parser.parse_args()
    conn = get_connection(args.db_path)
    reviewer = args.reviewer

    if args.statuses_only:
        print("statuses only: nothing retrieved, nothing verified, no new row written.\n")
        changed = _apply_effect_statuses(conn, reviewer)
        print(f"\n{changed} effect status(es) brought into line.")
        conn.close()
        return

    needed = {str(r["source"]) for r in RECORDS}
    needed |= {str(e["source"]) for r in RECORDS for e in r["effects"]}  # type: ignore[union-attr]
    texts = {}
    for key in sorted(needed):
        text, digest = _retrieve(key)
        texts[key] = (text, digest)
        print(f"retrieved {key:22} {len(text):>7} ch  sha256 {digest[:12]}")

    failures = []
    for record in RECORDS:
        if not _contains(texts[str(record["source"])][0], str(record["operator_excerpt"])):
            failures.append(f"{record['key']}: operator quote not found")
        for effect in record["effects"]:  # type: ignore[union-attr]
            if not _contains(texts[str(effect["source"])][0], str(effect["excerpt"])):
                failures.append(f"{record['key']}/{effect['type']}: quote not found")
    if failures:
        print("\nquotes that could not be verified:")
        for line in failures:
            print("  !!", line)
        sys.exit(1)
    total = sum(1 + len(r["effects"]) for r in RECORDS)  # type: ignore[arg-type]
    print(f"\nall {total} quotes verified verbatim\n")
    if args.dry_run:
        return

    for record in RECORDS:
        key = str(record["source"])
        document_id = _document(conn, key, texts[key][1])
        incident_id = record.get("existing_incident_id")

        if incident_id is None:
            existing = conn.execute(
                "SELECT incident_id FROM incidents WHERE canonical_title_tr = ? "
                "AND incident_kind = 'environmental'",
                (record["title_tr"],),
            ).fetchone()
            if existing:
                incident_id = int(existing["incident_id"])
            else:
                cur = conn.execute(
                    "INSERT INTO incidents (canonical_title_tr, canonical_title_en, "
                    "canonical_title_tr_normalized, incident_kind, incident_status, "
                    "scope_rationale, publication_status, verification_status) "
                    "VALUES (?, ?, ?, 'environmental', 'in_scope', ?, 'draft', 'unverified')",
                    (
                        record["title_tr"],
                        record["title_en"],
                        str(record["title_tr"]).casefold(),
                        "Environmental harm at a mining site; scope extension of 2026-10-20 "
                        "(docs/environmental_scope_protocol.md, STATUS: PROPOSED).",
                    ),
                )
                conn.commit()
                incident_id = int(cur.lastrowid)
        incident_id = int(incident_id)
        print(f"{record['key']}: incident {incident_id}")

        conn.execute(
            "UPDATE incidents SET incident_kind = 'environmental', incident_status = 'in_scope' "
            "WHERE incident_id = ?",
            (incident_id,),
        )

        # date and province are the publication-critical pair for this kind
        for field, value in (
            ("incident_start_datetime", record["datetime"]),
            ("date_precision", "exact_date"),
            ("province_code", record["province"]),
        ):
            active = get_active_decision(conn, incident_id, field)
            current = conn.execute(
                f"SELECT {field} AS v FROM incidents WHERE incident_id = ?", (incident_id,)
            ).fetchone()["v"]
            if active is not None and current == value:
                continue
            claim_id = _reviewed_claim(
                conn,
                reviewer,
                incident_id,
                document_id,
                field_name=field,
                raw_value=str(value),
                normalized_value=value,
                excerpt=record["operator_excerpt"],
            )
            record_decision(
                conn,
                ClaimDecision(
                    incident_id=incident_id,
                    field_name=field,
                    selected_claim_id=claim_id,
                    decision="accept_claim",
                    rationale=f"Environmental record. {field} as stated by the cited source.",
                    rationale_claim_ids=[claim_id],
                    reviewer=reviewer,
                    decision_date=utc_now_iso(),
                    supersedes_decision_id=int(active["decision_id"]) if active else None,
                ),
            )
            print(f"   decision: {field} = {value}")

        for field, value in (
            ("canonical_title_tr", record["title_tr"]),
            ("canonical_title_en", record["title_en"]),
        ):
            current = conn.execute(
                f"SELECT {field} AS v FROM incidents WHERE incident_id = ?", (incident_id,)
            ).fetchone()["v"]
            if current == value:
                continue
            active = get_active_decision(conn, incident_id, field)
            claim_id = _reviewed_claim(
                conn,
                reviewer,
                incident_id,
                document_id,
                field_name=field,
                raw_value=str(value),
                normalized_value=value,
                excerpt=record["operator_excerpt"],
            )
            record_decision(
                conn,
                ClaimDecision(
                    incident_id=incident_id,
                    field_name=field,
                    decision="manual_override",
                    manual_value=str(value),
                    rationale="Descriptive title assigned by the project for an environmental "
                    "record, naming the site and what failed.",
                    rationale_claim_ids=[claim_id],
                    reviewer=reviewer,
                    decision_date=utc_now_iso(),
                    supersedes_decision_id=int(active["decision_id"]) if active else None,
                ),
            )
            print(f"   decision: {field}")

        if record["related"]:
            related = conn.execute(
                "SELECT incident_id FROM incidents WHERE public_incident_id = ?",
                (record["related"],),
            ).fetchone()
            if related:
                conn.execute(
                    "UPDATE incidents SET related_incident_id = ? WHERE incident_id = ?",
                    (int(related["incident_id"]), incident_id),
                )
                print(f"   linked to {record['related']}")

        code, label_tr, label_en = record["mechanism"]  # type: ignore[misc]
        if not conn.execute(
            "SELECT 1 FROM incident_classifications WHERE incident_id = ? "
            "AND classification_system = 'project_environmental_mechanism'",
            (incident_id,),
        ).fetchone():
            claim_id = _reviewed_claim(
                conn,
                reviewer,
                incident_id,
                document_id,
                field_name="environmental_mechanism",
                raw_value=code,
                normalized_value=code,
                excerpt=record["effects"][0]["excerpt"],  # type: ignore[index]
            )
            conn.execute(
                "INSERT INTO incident_classifications (incident_id, classification_system, "
                "classification_code, classification_label_tr, classification_label_en, "
                "assertion_status, source_claim_id, review_status) "
                "VALUES (?, 'project_environmental_mechanism', ?, ?, ?, 'reported', ?, "
                "'reviewed')",
                (incident_id, code, label_tr, label_en, claim_id),
            )
            conn.commit()
            print(f"   mechanism: {code}")

        name, org_type = record["operator"]  # type: ignore[misc]
        org = conn.execute(
            "SELECT organization_id FROM organizations WHERE organization_name_tr = ?", (name,)
        ).fetchone()
        if org is None:
            cur = conn.execute(
                "INSERT INTO organizations (organization_name_tr, organization_name_normalized, "
                "organization_type, country_code, country_label) "
                "VALUES (?, ?, ?, 'TR', 'Türkiye')",
                (name, str(name).casefold(), org_type or "unknown"),
            )
            conn.commit()
            org_id = int(cur.lastrowid)
            log_review_action(
                conn,
                reviewer,
                "organization_added",
                "organization",
                org_id,
                after_summary=f"{name} (Türkiye)",
                notes=f"Named by {SOURCES[key]['url']} as operating the site.",
            )
        else:
            org_id = int(org["organization_id"])
        if not conn.execute(
            "SELECT 1 FROM incident_organization_roles WHERE incident_id = ? "
            "AND organization_id = ? AND role = 'operator'",
            (incident_id, org_id),
        ).fetchone():
            claim_id = _reviewed_claim(
                conn,
                reviewer,
                incident_id,
                document_id,
                field_name="operator_organization",
                raw_value=name,
                normalized_value=name,
                excerpt=record["operator_excerpt"],
            )
            conn.execute(
                "INSERT INTO incident_organization_roles (incident_id, organization_id, role, "
                "valid_at_incident_date, source_claim_id, assertion_status, review_status, "
                "notes) VALUES (?, ?, 'operator', 1, ?, 'reported', 'reviewed', ?)",
                (
                    incident_id,
                    org_id,
                    claim_id,
                    "As stated by the cited source for the time of this incident. Not a finding "
                    "of responsibility.",
                ),
            )
            conn.commit()
            print(f"   operator: {name}")

        for effect in record["effects"]:  # type: ignore[union-attr]
            held = conn.execute(
                "SELECT environmental_effect_id AS eid, effect_status FROM environmental_effects "
                "WHERE incident_id = ? AND effect_type = ? AND IFNULL(qualitative_value,'') = ?",
                (incident_id, effect["type"], effect.get("qualitative") or ""),
            ).fetchone()
            status = str(effect.get("effect_status", "reported"))
            if held:
                if held["effect_status"] != status:
                    conn.execute(
                        "UPDATE environmental_effects SET effect_status = ?, "
                        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                        "WHERE environmental_effect_id = ?",
                        (status, held["eid"]),
                    )
                    conn.commit()
                    log_review_action(
                        conn,
                        reviewer,
                        "environmental_effect_status_set",
                        "environmental_effect",
                        int(held["eid"]),
                        before_summary=f"effect_status={held['effect_status']}",
                        after_summary=f"effect_status={status}",
                        notes="Set from what the cited source states, so a threatened "
                        "receptor is no longer displayed as one the material reached.",
                    )
                    print(f"   effect: {effect['type']} status -> {status}")
                continue
            ekey = str(effect["source"])
            effect_document = _document(conn, ekey, texts[ekey][1])
            claim_id = _reviewed_claim(
                conn,
                reviewer,
                incident_id,
                effect_document,
                field_name=f"environmental_effect:{effect['type']}",
                raw_value=str(effect.get("value") or effect.get("qualitative") or ""),
                normalized_value=str(effect.get("value") or effect.get("qualitative") or ""),
                unit=effect.get("unit"),
                excerpt=effect["excerpt"],
                assertion_status=effect.get("status", "reported"),
            )
            conn.execute(
                "INSERT INTO environmental_effects (incident_id, effect_type, measure_value, "
                "measure_unit, qualitative_value, source_claim_id, assertion_status, "
                "review_status, notes, qualitative_value_en, effect_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'reviewed', ?, ?, ?)",
                (
                    incident_id,
                    effect["type"],
                    effect.get("value"),
                    effect.get("unit"),
                    effect.get("qualitative"),
                    claim_id,
                    effect.get("status", "reported"),
                    effect.get("notes"),
                    effect.get("qualitative_en"),
                    status,
                ),
            )
            conn.commit()
            measure = f"{effect.get('value')} {effect.get('unit')}" if effect.get("value") else ""
            print(f"   effect: {effect['type']} {measure} [{effect.get('status', 'reported')}]")

        conn.execute(
            "UPDATE incidents SET verification_status = 'reviewed', "
            "publication_status = 'publishable' WHERE incident_id = ?",
            (incident_id,),
        )
        conn.commit()
        row = conn.execute(
            "SELECT public_incident_id FROM incidents WHERE incident_id = ?", (incident_id,)
        ).fetchone()
        if not row["public_incident_id"]:
            public_id = assign_public_incident_id(conn, incident_id, reviewer)
            conn.commit()
            print(f"   public id: {public_id}")
        else:
            print(f"   public id: {row['public_incident_id']}")
    print("\ndone")


if __name__ == "__main__":
    main()
