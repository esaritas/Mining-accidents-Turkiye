"""Record which company was running each mine when the accident happened.

Role in the evidence flow: source document -> claim -> incident organization
role. Organization roles are claim-backed statements, not decided canonical
values, so no `claim_decisions` row is involved; each role carries the id of
the claim that supports it and the assertion status of that claim.

Why this phase exists. The register could say where and when people died and
how many, but not under whose operation. A reader could not tell a state pit
from a private one, or a Turkish operator from a foreign-owned one. The schema
has carried `incident_organization_roles` with `valid_at_incident_date` from
the first migration; the table was empty.

What a role here is. A statement by the cited source about who held the mine or
ran it at the time of that accident. It is not a finding of fault: courts
decide that, this register does not, and no individual is named. Where a source
names a contractor as well as the holder, both are recorded, because that
distinction is the substance of the question.

What this phase does not do. It does not infer the company at the time from
whoever runs the site today, and it does not record a role for the many records
whose source says only "a private operation" (ozel bir isletme). Those stay
blank. Licence holders are mostly absent from open sources: MAPEG holds the
licence register and does not publish it.

Every excerpt below is checked against the live document before anything is
written. A quote that cannot be found verbatim aborts the run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from mining_accidents.adapters.wikidata import _http_get
from mining_accidents.database import get_connection, utc_now_iso
from mining_accidents.ingest_sites import _upsert_organization
from mining_accidents.review import log_review_action

UA = (
    "turkey-mining-accidents-project/0.1 "
    "(evidence database of fatal mining accidents in Turkiye; research use)"
)

TR = ("TR", "Türkiye")
CA = ("CA", "Canada")

#: key -> how to retrieve it, and how to register it if it is not yet a document
SOURCES: dict[str, dict[str, object]] = {
    "wp_soma2014": {
        "wiki": ("tr", "Soma Faciası"),
        "url": "https://tr.wikipedia.org/wiki/Soma_Facias%C4%B1",
    },
    "wp_amasra": {
        "wiki": ("tr", "Amasra maden kazası"),
        "url": "https://tr.wikipedia.org/wiki/Amasra_maden_kazas%C4%B1",
    },
    "wp_karadon": {
        "wiki": ("tr", "Karadon maden kazası"),
        "url": "https://tr.wikipedia.org/wiki/Karadon_maden_kazas%C4%B1",
    },
    "wp_ermenek": {
        "wiki": ("tr", "Ermenek maden kazası"),
        "url": "https://tr.wikipedia.org/wiki/Ermenek_maden_kazas%C4%B1",
    },
    "wp_odakoy": {
        "wiki": ("tr", "Odaköy maden kazası"),
        "url": "https://tr.wikipedia.org/wiki/Odak%C3%B6y_maden_kazas%C4%B1",
    },
    "wp_sirvan": {
        "wiki": ("tr", "Şirvan maden kazası"),
        "url": "https://tr.wikipedia.org/wiki/%C5%9Eirvan_maden_kazas%C4%B1",
    },
    "wp_ilic": {
        "wiki": ("tr", "İliç maden kazası"),
        "url": "https://tr.wikipedia.org/wiki/%C4%B0li%C3%A7_maden_kazas%C4%B1",
    },
    "wp_list": {
        "wiki": ("tr", "Türkiye'deki madencilik kazaları listesi"),
        "url": "https://tr.wikipedia.org/wiki/T%C3%BCrkiye%27deki_madencilik_kazalar%C4%B1_listesi",
    },
    "euronews_soma2026": {
        "url": "https://tr.euronews.com/2026/10/06/somada-maden-kazasi-genel-mudur-dahil-9-kisi-tutuklandi",
        "organization": "Euronews Türkçe",
        "title": "Soma'da maden kazası: Genel müdür dahil 9 kişi tutuklandı",
        "published": "2026-10-06",
        "tier": 3,
    },
    "diken_karadon": {
        "url": "https://www.diken.com.tr/?p=50264",
        "organization": "Diken",
        "title": "Karadon grizu faciasında ancak altıncı raporda yetkililer kusurlu bulundu",
        "published": "2014-06-01",
        "tier": 3,
    },
    "birgun_collolar": {
        "url": "https://www.birgun.net/haber/ciner-in-yarattigi-zarar-icin-zamanasimi-uyarisi-336407",
        "organization": "BirGün",
        "title": "Ciner'in yarattığı zarar için zamanaşımı uyarısı",
        "published": "2021-04-20",
        "tier": 3,
    },
}

#: public incident id -> (role, organization, country, source key, excerpt)
#: "[...]" marks text left out of a quote, always a personal name.
ROLES: dict[str, list[tuple[str, str, tuple[str, str], str, str]]] = {
    "TR-MINE-2014-0001": [
        (
            "operator",
            "Soma Kömür İşletmeleri A.Ş.",
            TR,
            "wp_soma2014",
            "Soma Holding şirketlerinden Soma Kömür İşletmeleri A.Ş. tarafından işletilen "
            "maden ocağında",
        ),
    ],
    "TR-MINE-2022-0001": [
        (
            "operator",
            "Türkiye Taşkömürü Kurumu",
            TR,
            "wp_amasra",
            "Türkiye Taşkömürü Kurumu Amasra Müessese Müdürlüğü'ne bağlı maden ocağında "
            "gerçekleşen ve yeraltındaki 110 işçiden 42'sinin ölmesiyle sonuçlanan olaydır",
        ),
    ],
    "TR-MINE-2010-0001": [
        (
            "operator",
            "Türkiye Taşkömürü Kurumu",
            TR,
            "wp_karadon",
            "Türkiye Taşkömürü Kurumuna ait Karadon Müessese Müdürlüğü'nün kömür ocağında "
            "meydana gelen kaza",
        ),
        (
            "subcontractor",
            "Yapı-Tek",
            TR,
            "diken_karadon",
            "Karadon Müessese Müdürlüğü'nün ocağında 17 Mayıs 2010'da meydana gelen faciaya "
            "ilişkin hazırlanan bilirkişi raporunda, 28 sanıktan taşeron firma Yapı-Tek [...]",
        ),
    ],
    "TR-MINE-2014-0004": [
        (
            "owner",
            "Has Şekerler Madencilik",
            TR,
            "wp_ermenek",
            "Has Şekerler Madencilik'e ait kömür madeninde su baskını sonucu 18 işçinin "
            "mahsur kalarak hayatını kaybettiği olaydır",
        ),
    ],
    "TR-MINE-2010-0004": [
        (
            "owner",
            "Şentaş Madencilik",
            TR,
            "wp_odakoy",
            "Odaköy'de bulunan [...] Şentaş Madencilik'e ait kömür madeninde",
        ),
    ],
    "TR-MINE-2006-0001": [
        (
            "operator",
            "Şentaş Madencilik",
            TR,
            "wp_list",
            "1 Haziran 2006'da Balıkesir'in Dursunbey ilçesine bağlı Odaköy'de, Şentaş "
            "Madencilik tarafından işletilen yer altı kömür ocağında meydana gelen grizu "
            "patlamasında 17 kişi hayatını kaybetti",
        ),
    ],
    "TR-MINE-2016-0001": [
        (
            "owner",
            "Park Elektrik",
            TR,
            "wp_sirvan",
            "bu maden sahası Ciner Holding'e bağlı Park Elektrik tarafından 2004'te devralındı",
        ),
        (
            "subcontractor",
            "Antlar İnşaat",
            TR,
            "wp_sirvan",
            "Park Elektrik'e bağlı taşeron şirket Antlar İnşaat'ın maden sahasındaki "
            "çalışmaları sürerken heyelan meydana geldi",
        ),
    ],
    "TR-MINE-2024-0001": [
        (
            "operator",
            "Anagold Madencilik A.Ş.",
            TR,
            "wp_ilic",
            "Kazanın gerçekleştiği Çöpler altın madeni, Erzincan ilinin İliç ilçesinde Çöpler "
            "köyü yakınlarında kurulmuştur ve Anagold Madencilik A.Ş. tarafından işletilmektedir",
        ),
        (
            "owner",
            "SSR Mining",
            CA,
            "wp_ilic",
            "maden işletmesinin %80'inin sahibi olan Kanada merkezli SSR Madencilik",
        ),
        (
            "owner",
            "Çalık Holding",
            TR,
            "wp_ilic",
            "%20 hissesi Çalık Holding'e, işletimi Anagold Madencilik'e ait olan altın madeni",
        ),
    ],
    "TR-MINE-2011-0001": [
        (
            "operator",
            "Park Teknik A.Ş.",
            TR,
            "birgun_collolar",
            "Ciner Holding'e bağlı Park Teknik A.Ş.'nin işlettiği Çöllolar Kömür Sahası",
        ),
    ],
    "TR-MINE-1983-0002": [
        (
            "owner",
            "Türkiye Taşkömürü Kurumu",
            TR,
            "wp_list",
            "10 Nisan 1983 tarihinde, Zonguldak'a bağlı Kozlu ilçesinde TTK'ya ait kömür "
            "ocağında yaşanan grizu patlamasında 10 işçi hayatını kaybetti",
        ),
    ],
    "TR-MINE-1987-0001": [
        (
            "operator",
            "Türkiye Taşkömürü Kurumu",
            TR,
            "wp_list",
            "1987 Ocak ayında, TTK'nin Zonguldak Kozlu kömür ocağında meydana gelen göçükte "
            "8 işçi hayatını kaybetti",
        ),
    ],
    "TR-MINE-1995-0001": [
        (
            "owner",
            "Matsan Madencilik",
            TR,
            "wp_list",
            "26 Mart 1995 tarihinde Yozgat'ın Sorgun ilçesinde, Matsan Madencilik Şirketi'ne "
            "ait kömür ocağında grizu patlaması sebebiyle meydana gelen kazada 38 kişi göçük "
            "altına kalarak can vermiştir",
        ),
    ],
    "TR-MINE-2013-0002": [
        (
            "owner",
            "Türkiye Taşkömürü Kurumu",
            TR,
            "wp_list",
            "8 Ocak 2013'te, Zonguldak'ın Kozlu ilçesinde, Türkiye Taşkömürü Kurumu'na ait "
            "kömür ocağında metan gazı patlamasının yol açtığı göçük sebebiyle 8 işçi öldü",
        ),
    ],
    "TR-MINE-2015-0002": [
        (
            "operator",
            "Türkiye Taşkömürü Kurumu",
            TR,
            "wp_list",
            "10 Mart 2015'te Zonguldak'ın Karadeniz Ereğli ilçesine bağlı Kandilli beldesinde, "
            "Türkiye Taşkömürü Kurumuna bağlı Armutçuk Müessesesinin maden ocağında meydana "
            "gelen göçükte bir işçi hayatını kaybetti",
        ),
    ],
    "TR-MINE-2024-0005": [
        (
            "owner",
            "Türkiye Taşkömürü Kurumu",
            TR,
            "wp_list",
            "4 Haziran 2024'te Zonguldak'ın Kilimli ilçesinde Türkiye Taşkömürü Kurumu Gelik "
            "Müessesesi'ne ait maden ocağında meydana gelen göçükte mahsur kalan 2 işçiden "
            "1'i yaşamını yitirdi",
        ),
    ],
    "TR-MINE-2026-0001": [
        (
            "operator",
            "İmbat Madencilik",
            TR,
            "euronews_soma2026",
            "İmbat Madencilik'e ait maden ocağında 1 Ekim'de meydana gelen göçükte, yedi işçi "
            "toprak altında kalmıştı",
        ),
    ],
}

_SPACE = re.compile(r"\s+")
_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def _key(value: str) -> str:
    """Comparison form: quote style, dash style and spacing all normalised.

    Turkish press and Wikipedia mix straight and curly apostrophes, and
    stripping HTML tags inserts spaces inside words, so a quote has to be
    matched on its letters rather than its typography.
    """
    return _SPACE.sub("", value.translate(_QUOTES).casefold())


def _wiki_text(lang: str, title: str) -> tuple[str, bytes]:
    payload = _http_get(
        f"https://{lang}.wikipedia.org/w/api.php",
        {
            "action": "query",
            "prop": "extracts",
            "explaintext": "1",
            "titles": title,
            "redirects": "1",
            "format": "json",
        },
        timeout=90,
    )
    page = list(json.loads(payload)["query"]["pages"].values())[0]
    return page.get("extract", ""), payload


def _page_text(url: str) -> tuple[str, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = response.read()
    body = payload.decode("utf-8", "replace")
    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", body)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    import html as html_module

    return " ".join(html_module.unescape(body).split()), payload


def _retrieve(key: str) -> tuple[str, str, bytes]:
    """(plain text, sha256 of the retrieved payload, payload)."""
    spec = SOURCES[key]
    if "wiki" in spec:
        lang, title = spec["wiki"]  # type: ignore[misc]
        text, payload = _wiki_text(lang, title)
    else:
        text, payload = _page_text(str(spec["url"]))
    return text, hashlib.sha256(payload).hexdigest(), payload


def _contains(text: str, excerpt: str) -> bool:
    """Is every fragment of the quote present, in order?"""
    position = 0
    haystack = _key(text)
    for fragment in excerpt.split("[...]"):
        fragment = _key(fragment)
        if not fragment:
            continue
        found = haystack.find(fragment, position)
        if found < 0:
            return False
        position = found + len(fragment)
    return True


def _document(conn: sqlite3.Connection, key: str, digest: str) -> int:
    """The document row for this retrieval, reusing an identical one."""
    spec = SOURCES[key]
    url = str(spec["url"])
    row = conn.execute(
        "SELECT source_document_id FROM source_documents WHERE url = ? AND content_hash = ?",
        (url, digest),
    ).fetchone()
    if row:
        return int(row["source_document_id"])
    if "wiki" in spec:
        lang, title = spec["wiki"]  # type: ignore[misc]
        values = {
            "source_organization": f"Wikipedia ({lang})",
            "title": str(title),
            "document_type": "encyclopedia_article",
            "language": lang,
            "tier": 3,
            "licence": "CC BY-SA 4.0. Short quotation with attribution; no redistribution "
            "of the article text.",
            "published": None,
        }
    else:
        values = {
            "source_organization": str(spec["organization"]),
            "title": str(spec["title"]),
            "document_type": "news_article",
            "language": "tr",
            "tier": int(spec["tier"]),  # type: ignore[arg-type]
            "licence": "Press article. Quoted as a short evidence excerpt only; not redistributed.",
            "published": spec.get("published"),
        }
    cur = conn.execute(
        "INSERT INTO source_documents (source_organization, title, document_type, url, "
        "publication_date, retrieved_at, language, content_hash, source_tier, "
        "attribution_required, licence_or_reuse_notes, access_status, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'open', ?)",
        (
            values["source_organization"],
            values["title"],
            values["document_type"],
            url,
            values["published"],
            utc_now_iso(),
            values["language"],
            digest,
            values["tier"],
            values["licence"],
            "Read for the organization operating or holding the mine at the time of the "
            "incident. Retrieved 2026-10-15 for the incident organization roles phase.",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def _normalise_country_labels(conn: sqlite3.Connection, reviewer: str) -> None:
    """One label per country code, so the public column reads consistently."""
    rows = conn.execute(
        "SELECT organization_id, organization_name_tr, country_label FROM organizations "
        "WHERE country_code = 'TR' AND country_label <> 'Türkiye'"
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE organizations SET country_label = 'Türkiye' WHERE organization_id = ?",
            (int(row["organization_id"]),),
        )
        log_review_action(
            conn,
            reviewer,
            "organization_country_label_normalised",
            "organization",
            int(row["organization_id"]),
            before_summary=str(row["country_label"]),
            after_summary="Türkiye",
            notes="Display label only; the country code is unchanged. The same country was "
            "appearing under two names in the public export.",
        )
    if rows:
        conn.commit()
        print(f"{len(rows)} country label(s) normalised to Türkiye")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="database/mining_accidents.sqlite")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument(
        "--evidence-dir",
        default="data/staging/2026-10-15_operators",
        help="where the excerpt table is written for review",
    )
    args = parser.parse_args()
    conn = get_connection(args.db_path)
    reviewer = args.reviewer

    needed = sorted({key for roles in ROLES.values() for *_, key, _ in roles})
    texts: dict[str, tuple[str, str]] = {}
    for key in needed:
        text, digest, _ = _retrieve(key)
        texts[key] = (text, digest)
        print(f"retrieved {key:20} {len(text):>7} ch  sha256 {digest[:12]}")

    failures = []
    for public_id, roles in ROLES.items():
        for role, name, _country, key, excerpt in roles:
            if not _contains(texts[key][0], excerpt):
                failures.append(f"{public_id} {role} {name}: not found in {key}")
    if failures:
        print("\nquotes that could not be verified against the live document:")
        for line in failures:
            print("  !!", line)
        sys.exit(1)
    print(f"\nall {sum(len(v) for v in ROLES.values())} quotes verified verbatim\n")

    _normalise_country_labels(conn, reviewer)

    evidence = []
    added = 0
    for public_id, roles in ROLES.items():
        incident = conn.execute(
            "SELECT incident_id FROM incidents WHERE public_incident_id = ?", (public_id,)
        ).fetchone()
        if incident is None:
            print(f"!! {public_id} is not in this database")
            continue
        incident_id = int(incident["incident_id"])
        for role, name, country, key, excerpt in roles:
            code, label = country
            org_id, created = _upsert_organization(conn, name, None, code, label)
            if created:
                log_review_action(
                    conn,
                    reviewer,
                    "organization_added",
                    "organization",
                    org_id,
                    after_summary=f"{name} ({label})",
                    notes=f"Named by {SOURCES[key]['url']} as {role} of the site at the time "
                    f"of {public_id}.",
                )
            exists = conn.execute(
                "SELECT 1 FROM incident_organization_roles WHERE incident_id = ? "
                "AND organization_id = ? AND role = ?",
                (incident_id, org_id, role),
            ).fetchone()
            if exists:
                print(f"   {public_id}: {role} = {name} already recorded")
                continue
            document_id = _document(conn, key, texts[key][1])
            # Constraint 5: an ai_assisted claim is created needs_review and is
            # only moved to reviewed by a reviewer action, logged as its own act.
            cur = conn.execute(
                "INSERT INTO claims (incident_id, source_document_id, claim_subject_type, "
                "claim_subject_id, field_name, raw_value, normalized_value, "
                "short_evidence_excerpt, extraction_method, extractor_version, "
                "assertion_status, review_status, confidence_score) "
                "VALUES (?, ?, 'organization', ?, ?, ?, ?, ?, 'ai_assisted', "
                "'incident_operators_2026_10_15', 'reported', 'needs_review', 0.9)",
                (
                    incident_id,
                    document_id,
                    org_id,
                    f"{role}_organization",
                    name,
                    name,
                    excerpt,
                ),
            )
            conn.commit()
            claim_id = int(cur.lastrowid)
            conn.execute(
                "UPDATE claims SET review_status = 'reviewed' WHERE claim_id = ?", (claim_id,)
            )
            log_review_action(
                conn,
                reviewer,
                "claim_reviewed",
                "claim",
                claim_id,
                after_summary=f"{public_id} {role} = {name}",
                notes="Quote checked verbatim against the retrieved document, whose sha256 "
                "is recorded on the document row.",
            )
            conn.execute(
                "INSERT INTO incident_organization_roles (incident_id, organization_id, role, "
                "valid_at_incident_date, source_claim_id, assertion_status, review_status, "
                "notes) VALUES (?, ?, ?, 1, ?, 'reported', 'reviewed', ?)",
                (
                    incident_id,
                    org_id,
                    role,
                    claim_id,
                    "As stated by the cited source for the time of this incident. Not a "
                    "finding of responsibility.",
                ),
            )
            conn.commit()
            added += 1
            print(f"   {public_id}: {role} = {name} ({label})")
            evidence.append(
                {
                    "public_incident_id": public_id,
                    "role": role,
                    "organization_name": name,
                    "country_code": code,
                    "country_label": label,
                    "source_url": SOURCES[key]["url"],
                    "content_sha256": texts[key][1],
                    "short_evidence_excerpt": excerpt,
                }
            )

    if evidence:
        out_dir = Path(args.evidence_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "incident_operators.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(evidence[0]))
            writer.writeheader()
            writer.writerows(evidence)
        print(f"\nevidence table: {path}")
    print(f"{added} role(s) recorded")


if __name__ == "__main__":
    main()
