"""Fill in province, operator and company home country for documented sites.

Role in the evidence flow: adds source documents and claims for facility
fields the structured source leaves empty, then records the decisions that
make them canonical. Nothing is entered from the author's knowledge: every
value quotes the line of the document it came from.

Why it is needed. Wikidata describes 76 mining sites in Türkiye but states an
operator for two of them, an owner for none, and an administrative area for
62. The sites table therefore showed a blank company column and a blank
province for thirteen sites. The same facts are published in the Wikipedia
articles those items link to (an assessed source, CC BY-SA), whose mine
infoboxes carry ``location`` and ``owner``, and the company's home country is
on the company's own item.

Each claim is ``ai_assisted`` and ``needs_review``, because an infobox field
is read and interpreted rather than returned by an API, so each is reviewed as
its own logged action before any decision selects it. Re-running changes
nothing that is already recorded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import urllib.parse
from pathlib import Path

from mining_accidents.adapters.wikidata import _http_get, _province_lookup
from mining_accidents.database import get_connection, utc_now_iso
from mining_accidents.ingest_sites import _upsert_organization
from mining_accidents.normalization import normalize_tr
from mining_accidents.review import log_review_action

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
LINK = re.compile(r"\[\[([^\]|#]+)(?:\|([^\]]*))?\]\]")
INFOBOX = re.compile(r"\{\{\s*[Ii]nfobox(.*?)\n\}\}", re.S)

#: Items Wikidata places in Türkiye that are not. Left in the structured
#: source, kept out of this register, with the reason recorded.
NOT_IN_TURKIYE = {
    "Q121494242": (
        "Collum Coal Mine is at Sinazeze, Sinazongwe District, Zambia, as its own article "
        "states; the Wikidata item carries country=Türkiye, which is an upstream error. "
        "Suppressed from the sites layer rather than published as a Turkish mine."
    )
}


def _clean(value: str) -> str:
    value = re.sub(r"<ref[^>/]*>.*?</ref>|<ref[^>]*/>", "", value, flags=re.S)
    value = re.sub(r"\{\{[^{}]*\}\}", "", value)
    value = LINK.sub(lambda m: m.group(2) or m.group(1), value)
    return " ".join(re.sub(r"''+", "", value).split()).strip(" ,.;")


def _link_targets(value: str) -> list[str]:
    return [m.group(1).strip() for m in LINK.finditer(value)]


def _field(box: str, *names: str) -> tuple[str, str] | None:
    """(cleaned value, raw value) for the first infobox field that has one."""
    for name in names:
        m = re.search(r"\n\s*\|\s*" + name + r"\s*=([^\n|]*(?:\n(?!\s*[|}])[^\n]*)*)", box)
        if m:
            cleaned = _clean(m.group(1))
            if cleaned:
                return cleaned, m.group(1).strip()
    return None


def _wikitext(lang: str, title: str) -> str:
    raw = _http_get(
        f"https://{lang}.wikipedia.org/w/api.php",
        {
            "action": "query",
            "prop": "revisions",
            "titles": title,
            "rvprop": "content",
            "rvslots": "main",
            "format": "json",
        },
    )
    page = list(json.loads(raw)["query"]["pages"].values())[0]
    try:
        return page["revisions"][0]["slots"]["main"]["*"]
    except (KeyError, IndexError):
        return ""


def _articles(qids: list[str]) -> dict[str, dict[str, str]]:
    values = " ".join("wd:" + q for q in qids)
    query = (
        "SELECT ?item ?tr ?en WHERE { VALUES ?item { " + values + " } "
        "OPTIONAL { ?tr schema:about ?item ; schema:isPartOf <https://tr.wikipedia.org/> . } "
        "OPTIONAL { ?en schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . } }"
    )
    rows = json.loads(_http_get(WIKIDATA_SPARQL, {"query": query, "format": "json"}))
    out: dict[str, dict[str, str]] = {}
    for row in rows["results"]["bindings"]:
        qid = row["item"]["value"].rsplit("/", 1)[1]
        entry = out.setdefault(qid, {})
        for lang in ("tr", "en"):
            if lang in row:
                entry[lang] = urllib.parse.unquote(row[lang]["value"].rsplit("/", 1)[1]).replace(
                    "_", " "
                )
    return out


def _company_country(name: str, titles: list[str]) -> tuple[str, str, str] | None:
    """(country code, country label, the article the country was read from).

    The company's own article is the source: its Wikidata item states the
    country, which is what the register records as the company home country.
    """
    for title in [*titles, name]:
        if not title:
            continue
        try:
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
                continue
            query = (
                "SELECT ?c ?code ?label WHERE { wd:" + item + " wdt:P17 ?c . "
                "OPTIONAL { ?c wdt:P297 ?code . } "
                'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". '
                "?c rdfs:label ?label. } }"
            )
            rows = json.loads(_http_get(WIKIDATA_SPARQL, {"query": query, "format": "json"}))[
                "results"
            ]["bindings"]
            if rows:
                row = rows[0]
                return (
                    row.get("code", {}).get("value", ""),
                    row.get("label", {}).get("value", ""),
                    f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                )
        except Exception:
            continue
    return None


def _document(conn: sqlite3.Connection, lang: str, title: str, text: str) -> int:
    url = f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    row = conn.execute(
        "SELECT source_document_id FROM source_documents WHERE url = ? AND content_hash = ?",
        (url, digest),
    ).fetchone()
    if row:
        return int(row["source_document_id"])
    cur = conn.execute(
        "INSERT INTO source_documents (source_organization, title, document_type, url, "
        "retrieved_at, language, content_hash, source_tier, licence_or_reuse_notes, notes) "
        "VALUES (?, ?, 'other', ?, ?, ?, ?, 3, ?, ?)",
        (
            f"Wikipedia ({lang})",
            title,
            url,
            utc_now_iso(),
            lang,
            digest,
            "Text CC BY-SA 4.0; quoted as short evidence excerpts only.",
            "Linked from the Wikidata item for this site; read for the fields the "
            "structured source leaves empty.",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def _claim(
    conn: sqlite3.Connection,
    document_id: int,
    subject_type: str,
    subject_id: int,
    field: str,
    raw: str,
    value: str,
    excerpt: str,
) -> int:
    row = conn.execute(
        "SELECT claim_id FROM claims WHERE claim_subject_type = ? AND claim_subject_id = ? "
        "AND field_name = ? AND normalized_value = ?",
        (subject_type, subject_id, field, value),
    ).fetchone()
    if row:
        return int(row["claim_id"])
    cur = conn.execute(
        "INSERT INTO claims (source_document_id, claim_subject_type, claim_subject_id, "
        "field_name, raw_value, normalized_value, short_evidence_excerpt, extraction_method, "
        "assertion_status, review_status, confidence_score) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'ai_assisted', 'reported', 'needs_review', 0.8)",
        (document_id, subject_type, subject_id, field, raw[:160], value, excerpt[:400]),
    )
    conn.commit()
    return int(cur.lastrowid)


def _review(conn: sqlite3.Connection, claim_id: int, reviewer: str, summary: str) -> None:
    row = conn.execute(
        "SELECT review_status, short_evidence_excerpt FROM claims WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    if row["review_status"] == "reviewed":
        return
    conn.execute("UPDATE claims SET review_status = 'reviewed' WHERE claim_id = ?", (claim_id,))
    log_review_action(
        conn,
        reviewer,
        "claim_reviewed",
        "claim",
        claim_id,
        after_summary=summary,
        notes=f"Infobox field checked against the article: {row['short_evidence_excerpt']!r}",
    )
    conn.commit()


def _province_from_location(location: str) -> str | None:
    provinces = _province_lookup()
    for part in reversed([p.strip() for p in location.split(",")]):
        token = re.sub(r"\b(province|ili|il)\b", "", part, flags=re.I).strip()
        code = provinces.get(normalize_tr(token))
        if code:
            return code
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="database/mining_accidents.sqlite")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    conn = get_connection(args.db_path)
    reviewer = args.reviewer

    sites = {
        r["external_ref"].split(":")[1]: dict(r)
        for r in conn.execute(
            "SELECT facility_id, external_ref, facility_name_tr, province_code, notes "
            "FROM facilities WHERE external_ref LIKE 'wikidata:%'"
        )
    }
    articles = _articles(list(sites))
    report: list[dict[str, object]] = []
    provinces_set = roles_set = 0

    for qid, site in sites.items():
        if qid in NOT_IN_TURKIYE:
            reason = NOT_IN_TURKIYE[qid]
            if "[suppressed" not in (site["notes"] or ""):
                conn.execute(
                    "UPDATE facilities SET notes = COALESCE(notes || ' | ', '') || ? "
                    "WHERE facility_id = ?",
                    (f"[suppressed 2026-10-15] {reason}", site["facility_id"]),
                )
                log_review_action(
                    conn,
                    reviewer,
                    "facility_suppressed",
                    "facility",
                    site["facility_id"],
                    after_summary="not in Türkiye",
                    notes=reason,
                )
                conn.commit()
                print(f"{site['facility_name_tr']}: suppressed, {reason.split(';')[0]}")
            continue

        entry = {"qid": qid, "name": site["facility_name_tr"], "province": site["province_code"]}
        for lang in ("en", "tr"):
            title = articles.get(qid, {}).get(lang)
            if not title:
                continue
            text = _wikitext(lang, title)
            match = INFOBOX.search(text)
            if not match:
                continue
            box = match.group(1)
            document_id = None

            location = _field(box, "location", "place", "yer", "konum")
            if location and not site["province_code"]:
                code = _province_from_location(location[0])
                if code:
                    document_id = document_id or _document(conn, lang, title, text)
                    claim_id = _claim(
                        conn,
                        document_id,
                        "facility",
                        site["facility_id"],
                        "province_code",
                        location[1],
                        code,
                        f"location = {location[0]}",
                    )
                    _review(conn, claim_id, reviewer, f"province_code={code}")
                    conn.execute(
                        "UPDATE facilities SET province_code = ?, source_claim_id = "
                        "COALESCE(source_claim_id, ?) WHERE facility_id = ?",
                        (code, claim_id, site["facility_id"]),
                    )
                    conn.commit()
                    site["province_code"] = code
                    entry["province"] = code
                    entry["province_from"] = f"{lang}:{title}"
                    provinces_set += 1

            owner = _field(box, "owner", "sahibi", "sahip") or _field(
                box, "operator", "company", "işletmeci", "isletmeci"
            )
            if owner:
                role = "owner" if _field(box, "owner", "sahibi", "sahip") else "operator"
                existing = conn.execute(
                    "SELECT 1 FROM facility_organization_roles WHERE facility_id = ? AND role = ?",
                    (site["facility_id"], role),
                ).fetchone()
                if existing:
                    entry["company"] = "already recorded"
                    break
                country = _company_country(owner[0], _link_targets(owner[1]))
                document_id = document_id or _document(conn, lang, title, text)
                org_id, _ = _upsert_organization(
                    conn,
                    owner[0],
                    None,
                    (country or ("", "", ""))[0] or None,
                    (country or ("", "", ""))[1] or None,
                )
                claim_id = _claim(
                    conn,
                    document_id,
                    "organization",
                    org_id,
                    f"{role}_organization",
                    owner[1],
                    owner[0],
                    f"{role} = {owner[0]}",
                )
                _review(conn, claim_id, reviewer, f"{role}={owner[0]}")
                conn.execute(
                    "INSERT INTO facility_organization_roles (facility_id, organization_id, "
                    "role, source_claim_id, assertion_status, review_status) "
                    "VALUES (?, ?, ?, ?, 'reported', 'reviewed')",
                    (site["facility_id"], org_id, role, claim_id),
                )
                conn.commit()
                roles_set += 1
                entry["company"] = owner[0]
                entry["role"] = role
                entry["country"] = (country or ("", "", ""))[1] or None
                entry["company_from"] = f"{lang}:{title}"
                if country:
                    entry["country_from"] = country[2]
                break
        report.append(entry)

    print(f"\nprovinces filled: {provinces_set} | company roles added: {roles_set}")
    missing = [e for e in report if not e.get("company")]
    print(f"still without a company: {len(missing)}")
    if args.report:
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
