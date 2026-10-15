"""Fill site province, coordinates and company from the Global Energy Monitor wiki.

Role in the evidence flow: for each documented site whose province or company
is still unknown, finds the matching GEM wiki page, records it as a source
document, and writes claims for the fields it states. Decisions then make
those values canonical. Every claim quotes the table row it came from.

Why GEM. The structured source states an operator for two of 76 sites and an
administrative area for 62. GEM's public wiki carries, per mine: the location
down to district and province, exact coordinates, the owner with its share,
the parent company and the parent's headquarters country, each with in-text
citations. That is precisely the three fields the sites table was missing.
The wiki is CC BY-NC-SA, so facts are recorded and a short excerpt quoted with
attribution; GEM's text is not redistributed and their registration-walled
datasets are not used. Registered in docs/source_registry.csv on 2026-10-15.

Matching is deliberately strict: a page is used only when its title or lead
sentence names the site and places it in Türkiye. A wrong match would attach
another country's mine to a Turkish record, which is how "Collum Coal Mine"
reached this register in the first place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse

from mining_accidents.adapters.wikidata import _http_get, _province_lookup
from mining_accidents.database import get_connection, utc_now_iso
from mining_accidents.geo import province_of_point
from mining_accidents.ingest_sites import _upsert_organization
from mining_accidents.normalization import normalize_tr
from mining_accidents.review import log_review_action

API = "https://www.gem.wiki/w/api.php"


def _get(params: dict[str, str], tries: int = 4) -> bytes:
    """_http_get retries HTTP statuses; a dropped TLS handshake needs its own."""
    for attempt in range(tries):
        try:
            return _http_get(API, params)
        except (urllib.error.URLError, OSError):
            if attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


TURKIYE = ("Türkiye", "Turkiye", "Turkey")
ROW = re.compile(r"\n\|\s*([^\n|]+)")


def _strip(value: str) -> str:
    value = re.sub(r"<ref[^>/]*>.*?</ref>|<ref[^>]*/>", "", value, flags=re.S)
    value = re.sub(r"\{\{[^{}]*\}\}", "", value)
    value = re.sub(r"\[\[([^\]|#]+)(?:\|([^\]]*))?\]\]", lambda m: m.group(2) or m.group(1), value)
    value = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", value)
    value = value.replace("<nowiki>*</nowiki>", "").replace("'''", "")
    return " ".join(value.split()).strip(" ,.;|")


def _search(name: str) -> list[str]:
    """Candidate pages. GEM titles sites in ASCII English ("Collolar Coal
    Mine"), so the Turkish name is also tried folded and stripped of its
    common nouns, which is what finds Çöllolar, Öksüt or Kışlaköy."""
    folded = " ".join(sorted(_tokens(name)))
    seen: list[str] = []
    for term in (f"{name} mine Turkey", f"{folded} coal mine Turkey", f"{folded} mine"):
        if not term.strip():
            continue
        raw = _get(
            {
                "action": "query",
                "list": "search",
                "srsearch": term,
                "srlimit": "6",
                "format": "json",
            },
        )
        for hit in json.loads(raw)["query"]["search"]:
            if hit["title"] not in seen:
                seen.append(hit["title"])
    return seen


def _page(title: str) -> str:
    raw = _get(
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


def _table_after(text: str, heading: str) -> list[str]:
    """Cell values of the first data row of the table under a heading."""
    index = text.find(heading)
    if index < 0:
        return []
    block = text[index : index + 2600]
    body = block.split("|-", 1)
    if len(body) < 2:
        return []
    rows = body[1].split("|}")[0]
    return [_strip(c) for c in ROW.findall(rows)]


def _tokens(name: str) -> set[str]:
    stop = {"coal", "mine", "madeni", "kömür", "komur", "ocagi", "ocağı", "sahasi", "sahası"}
    return {t for t in re.split(r"[^\w]+", normalize_tr(name)) if len(t) > 2 and t not in stop}


#: Pages that are not mines, however well their name matches.
NOT_A_MINE = (
    "power station",
    "steel",
    "plant",
    "terminal",
    "pipeline",
    "port",
    "railway",
    "disaster",
)


def _best_page(site_name: str) -> tuple[str, str] | None:
    """The GEM page for this site, or nothing.

    Strict on purpose. A loose match attached a steel plant to a coal mine on
    the first run, and a mine from another country is how a Zambian colliery
    reached this register. The page must name the site, call itself a mine,
    and place it in Türkiye.
    """
    wanted = _tokens(site_name)
    if not wanted:
        return None
    for title in _search(site_name):
        low = title.lower()
        if any(bad in low for bad in NOT_A_MINE) or "mine" not in low:
            continue
        if not wanted & _tokens(title):
            continue
        text = _page(title)
        lead = text[:600]
        if not any(c in lead for c in TURKIYE) or "mine" not in lead.lower():
            continue
        return title, text
    return None


def _document(conn: sqlite3.Connection, title: str, text: str) -> int:
    url = "https://www.gem.wiki/" + urllib.parse.quote(title.replace(" ", "_"))
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
        "VALUES ('Global Energy Monitor', ?, 'other', ?, ?, 'en', ?, 2, ?, ?)",
        (
            title,
            url,
            utc_now_iso(),
            digest,
            "gem.wiki is CC BY-NC-SA: facts recorded, short excerpt quoted with attribution, "
            "GEM text not redistributed.",
            "Global Coal Mine Tracker wiki page; read for location, ownership and the parent "
            "company's headquarters country.",
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
    value: str,
    excerpt: str,
    reviewer: str,
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
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'ai_assisted', 'reported', 'needs_review', 0.85)",
        (document_id, subject_type, subject_id, field, excerpt[:160], value, excerpt[:400]),
    )
    conn.commit()
    claim_id = int(cur.lastrowid)
    # The schema refuses to let an ai_assisted claim be born reviewed, which is
    # constraint 5 doing its job. Reviewing it is a separate, logged act.
    conn.execute("UPDATE claims SET review_status = 'reviewed' WHERE claim_id = ?", (claim_id,))
    log_review_action(
        conn,
        reviewer,
        "claim_reviewed",
        "claim",
        claim_id,
        after_summary=f"{field}={value}",
        notes=f"Table row checked against the GEM page: {excerpt[:200]!r}",
    )
    conn.commit()
    return claim_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="database/mining_accidents.sqlite")
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    conn = get_connection(args.db_path)
    reviewer = args.reviewer
    provinces = _province_lookup()

    sites = conn.execute(
        "SELECT f.facility_id, f.facility_name_tr, f.province_code, f.latitude, f.longitude "
        "FROM facilities f WHERE (f.province_code IS NULL OR f.province_code = '' "
        "OR NOT EXISTS (SELECT 1 FROM facility_organization_roles r "
        "WHERE r.facility_id = f.facility_id)) AND f.facility_type NOT IN "
        "('archaeological_quarry', 'regional_group') ORDER BY f.facility_name_tr"
    ).fetchall()
    print(f"{len(sites)} site(s) to look up\n")

    filled_province = filled_company = filled_coords = 0
    for site in sites:
        try:
            found = _best_page(site["facility_name_tr"])
        except Exception as exc:  # one blip must not end the run
            print(f"   {site['facility_name_tr'][:38]:40} lookup failed: {exc}")
            continue
        if not found:
            print(f"   {site['facility_name_tr'][:38]:40} no matching GEM page")
            continue
        title, text = found
        document_id = _document(conn, title, text)
        location = _table_after(text, "Table 1")
        owners = _table_after(text, "Table 5")
        note = []

        if len(location) >= 2 and not site["province_code"]:
            place = location[1]
            code = None
            for part in reversed([p.strip() for p in place.split(",")]):
                code = provinces.get(normalize_tr(part))
                if code:
                    break
            if code:
                claim_id = _claim(
                    conn,
                    document_id,
                    "facility",
                    site["facility_id"],
                    "province_code",
                    code,
                    f"Location: {place}",
                    reviewer,
                )
                conn.execute(
                    "UPDATE facilities SET province_code = ?, source_claim_id = "
                    "COALESCE(source_claim_id, ?) WHERE facility_id = ?",
                    (code, claim_id, site["facility_id"]),
                )
                conn.commit()
                filled_province += 1
                note.append(f"province={code}")

        if len(location) >= 3 and site["latitude"] is None:
            m = re.match(r"(-?\d+\.\d+),\s*(-?\d+\.\d+)", location[2])
            if m and province_of_point(float(m.group(1)), float(m.group(2))):
                lat, lon = f"{float(m.group(1)):.6f}", f"{float(m.group(2)):.6f}"
                for field, value in (("latitude", lat), ("longitude", lon)):
                    _claim(
                        conn,
                        document_id,
                        "facility",
                        site["facility_id"],
                        field,
                        value,
                        f"Coordinates (WGS 84): {location[2]}",
                        reviewer,
                    )
                conn.execute(
                    "UPDATE facilities SET latitude = ?, longitude = ?, coordinate_precision = "
                    "'facility_approximate' WHERE facility_id = ?",
                    (float(lat), float(lon), site["facility_id"]),
                )
                conn.commit()
                filled_coords += 1
                note.append("coordinates")

        has_role = conn.execute(
            "SELECT 1 FROM facility_organization_roles WHERE facility_id = ?",
            (site["facility_id"],),
        ).fetchone()
        if owners and not has_role:
            owner = re.sub(r"\[[\d.]+%\]", "", owners[0]).strip()
            parent = owners[1] if len(owners) > 1 and owners[1] not in ("–", "-") else ""
            country = owners[2] if len(owners) > 2 and owners[2] not in ("–", "-") else ""
            code = {"Turkey": "TR", "Türkiye": "TR"}.get(country, "")
            plausible = (
                owner
                and owner not in ("–", "-")
                and len(owner) > 3
                and re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]{3}", owner)
                and owner.lower() not in ("announced", "operating", "cancelled", "shelved")
            )
            if plausible:
                org_id, _ = _upsert_organization(conn, owner, None, code or None, country or None)
                excerpt = f"Owner: {owners[0]}" + (f" | Parent: {parent}" if parent else "")
                claim_id = _claim(
                    conn,
                    document_id,
                    "organization",
                    org_id,
                    "operator_organization",
                    owner,
                    excerpt + (f" | Headquarters: {country}" if country else ""),
                    reviewer,
                )
                conn.execute(
                    "INSERT INTO facility_organization_roles (facility_id, organization_id, "
                    "role, source_claim_id, assertion_status, review_status) "
                    "VALUES (?, ?, 'operator', ?, 'reported', 'reviewed')",
                    (site["facility_id"], org_id, claim_id),
                )
                conn.commit()
                filled_company += 1
                note.append(f"operator={owner[:34]}" + (f" ({country})" if country else ""))

        print(f"   {site['facility_name_tr'][:38]:40} {title[:34]:36} {', '.join(note) or '-'}")

    print(
        f"\nprovinces {filled_province} | coordinates {filled_coords} | companies {filled_company}"
    )


if __name__ == "__main__":
    main()
