"""Wikidata + Wikipedia adapter — first implemented network adapter.

Role in the evidence flow: fetches structured event items about mining
accidents in Türkiye from Wikidata (CC0) and the tr/en Wikipedia articles
they link to (CC BY-SA), stores every response immutably in ``data/raw/``
with sha256 hashes, and turns them into field-level claims. Nothing here
touches canonical values — that remains the decision layer's job.

Assessment (recorded in docs/source_registry.csv, 2026-07-13): both projects
explicitly permit API collection; they are tertiary sources (tier 3), so
values seeded here should later be corroborated against Tier 1-2 sources.

Extraction honesty rules:
  * Wikidata statements and Wikipedia infobox/template fields are mechanical
    extractions (``api`` / ``html_parser``).
  * Values recognized in prose are ``ai_assisted`` claims — they enter the
    mandatory human-review queue and cannot be published unreviewed.
  * Personal names are never extracted; excerpts stay within the word cap.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from mining_accidents import vocabularies
from mining_accidents.adapters.base import ClaimDraft, SourceAdapter, SourceAssessment
from mining_accidents.database import utc_now_iso
from mining_accidents.normalization import normalize_tr
from mining_accidents.provenance import sha256_bytes

USER_AGENT = (
    "turkey-mining-accidents-project/0.1 "
    "(evidence database of mining accidents; open-source research)"
)
SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
DEFAULT_RAW_DIR = Path("data/raw/wikidata")

#: instances of `mining accident` (Q1550225) or subclasses, in Türkiye (Q43)
SPARQL_QUERY = """
SELECT DISTINCT ?item WHERE {
  ?item wdt:P31/wdt:P279* wd:Q1550225 .
  ?item wdt:P17 wd:Q43 .
}
"""

#: Items found via Wikipedia category scans that the SPARQL class query
#: misses (documented discovery, not invention).
EXTRA_QIDS: tuple[str, ...] = ("Q124522721",)  # Çöpler mine disaster (2024)

#: tr.wikipedia navigation template that indexes the mining-accident articles
#: (including historic pre-2010 incidents Wikidata classes miss).
NAVBOX_TITLE = "Şablon:Türkiye'deki maden kazaları ve felaketleri"

#: tr.wikipedia list article with per-incident bullets back to 1983 and the
#: İSİG Meclisi annual miner-death table. Bullets are formulaic one-sentence
#: entries; extraction is pattern-based and requires date AND death-count
#: patterns to co-match within one bullet — partial matches are dropped, not
#: guessed (docs/source_assessment_protocol.md §5 rule 7).
LIST_TITLE = "Türkiye'deki madencilik kazaları listesi"

_TR_MONTHS = {
    name: idx + 1
    for idx, name in enumerate(
        "Ocak Şubat Mart Nisan Mayıs Haziran Temmuz Ağustos Eylül Ekim Kasım Aralık".split()
    )
}
_LIST_DATE = re.compile(r"(\d{1,2})\s+(" + "|".join(_TR_MONTHS) + r")\s+(\d{4})")
_LIST_MONTH = re.compile(r"(" + "|".join(_TR_MONTHS) + r")\s+ayında")
_LIST_DEATHS = re.compile(
    r"(\d+)\s*(?:maden işçisi|işçi|kişi|madenci)"
    r"[^.]{0,70}?(?:yaşamını yitir|hayatını kaybet|öldü|ölmüş|can ver)"
)
_LIST_TITLE_LINK = re.compile(r"^\*\s*\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]\s*:")
_ISIG_ROW = re.compile(r"^\|\s*(\d{4})\s*\n\|\s*(\d+)", re.M)

#: navbox links that are not incident articles.
_NAVBOX_SKIP = re.compile(
    r"^(Dosya|Kategori|Şablon|Portal):|Bölgesi$|listesi$|^Türkiye'de madencilik$"
)

#: Items excluded with reasons — curation decisions, kept visible here.
EXCLUDED_QIDS: dict[str, str] = {
    "Q118344293": "article about international reactions, not an incident",
}

#: Wikidata time precision -> project date_precision
_WD_DATE_PRECISION = {11: "exact_date", 10: "month", 9: "year"}

#: Wikidata P31 classes -> project event mechanism (mechanical mapping of what
#: the source item states; extended only with verified QIDs).
P31_EVENT_MECHANISMS: dict[str, str] = {
    "Q1362483": "gas_explosion",  # gas explosion
    "Q1425553": "fire",  # coal seam fire
    "Q19850480": "tailings_dam_failure",
}

#: Turkish incident-type phrases (infobox `tür=` values and lead wording) ->
#: (event_mechanism, hazard-or-None). "grizu" IS firedamp/methane by
#: definition, so the methane hazard is part of what the source states.
TR_MECHANISM_PHRASES: tuple[tuple[str, str, str | None], ...] = (
    ("grizu", "gas_explosion", "methane"),
    ("toz patlaması", "dust_explosion", "coal_dust"),
    ("su baskını", "flooding_or_inrush", "water_ingress"),
    ("göçük", "roof_or_ground_collapse", None),
    ("gocuk", "roof_or_ground_collapse", None),
    ("heyelan", "landslide_or_slope_failure", None),
    ("toprak kayması", "landslide_or_slope_failure", None),
    ("yangın", "fire", "fire"),
)


#: seconds between requests — adapter conduct rule 3 (conservative rate).
REQUEST_SPACING_S = 2.0
_RETRY_STATUSES = {429, 500, 502, 503}
_last_request_at = 0.0


def _http_get(url: str, params: dict[str, str], timeout: int = 60, max_tries: int = 5) -> bytes:
    """Polite GET: spaced requests, exponential backoff, Retry-After honored."""
    global _last_request_at
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}", headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    delay = 4.0
    for attempt in range(1, max_tries + 1):
        wait = _last_request_at + REQUEST_SPACING_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            _last_request_at = time.monotonic()
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in _RETRY_STATUSES or attempt == max_tries:
                raise
            retry_after = exc.headers.get("Retry-After")
            sleep_for = float(retry_after) if retry_after else delay
            time.sleep(min(sleep_for, 60.0))
            delay *= 2
    raise RuntimeError("unreachable")


def _store_raw(raw_dir: Path, payload: bytes, stem: str) -> tuple[Path, str]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    digest = sha256_bytes(payload)
    path = raw_dir / f"{stem}-{digest[:12]}.json"
    if not path.exists():
        path.write_bytes(payload)
    return path, digest


def _insert_document(conn: sqlite3.Connection, **values: object) -> int:
    existing = conn.execute(
        "SELECT source_document_id FROM source_documents WHERE url = ? AND content_hash = ?",
        (values["url"], values["content_hash"]),
    ).fetchone()
    if existing:
        return int(existing[0])
    cols = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    cur = conn.execute(
        f"INSERT INTO source_documents ({cols}) VALUES ({placeholders})",
        tuple(values.values()),
    )
    return int(cur.lastrowid)


class WikidataAdapter(SourceAdapter):
    source_key = "wikidata"
    adapter_version = "1.0.0"

    def __init__(self, raw_dir: str | Path = DEFAULT_RAW_DIR) -> None:
        self.raw_dir = Path(raw_dir)

    def assess(self) -> SourceAssessment:
        return SourceAssessment(
            source_key="wikidata",
            tier_proposed=3,
            automated_collection_permitted="yes",
            access_notes=(
                "Wikidata content is CC0; Wikipedia text is CC BY-SA 4.0 "
                "(attribution recorded per document). Public APIs explicitly "
                "support programmatic access with a descriptive user agent."
            ),
            coverage_notes=(
                "Tertiary aggregation; covers major incidents only and is "
                "sparse for casualty figures, coordinates, and admin areas. "
                "Values require later corroboration against Tier 1-2 sources."
            ),
            format_risks="Structured JSON (low risk); article prose needs review.",
        )

    # ------------------------------------------------------------------
    # fetch
    # ------------------------------------------------------------------

    def discover_qids(self) -> list[str]:
        payload = _http_get(SPARQL_ENDPOINT, {"query": SPARQL_QUERY, "format": "json"}, timeout=90)
        _store_raw(self.raw_dir, payload, "sparql-discovery")
        bindings = json.loads(payload)["results"]["bindings"]
        qids = {row["item"]["value"].rsplit("/", 1)[-1] for row in bindings}
        qids.update(EXTRA_QIDS)
        qids.update(self._discover_navbox_qids())
        return sorted(q for q in qids if q not in EXCLUDED_QIDS)

    def _discover_navbox_qids(self) -> set[str]:
        """Incident items indexed by the tr.wikipedia navigation template."""
        payload = _http_get(
            "https://tr.wikipedia.org/w/api.php",
            {"action": "parse", "page": NAVBOX_TITLE, "prop": "wikitext", "format": "json"},
        )
        _store_raw(self.raw_dir, payload, "navbox-discovery")
        wikitext = json.loads(payload)["parse"]["wikitext"]["*"]
        titles = [
            link.strip()
            for link in _WIKILINK.findall(wikitext)
            if not _NAVBOX_SKIP.search(link.strip())
        ]
        qids: set[str] = set()
        for start in range(0, len(titles), 50):
            batch = titles[start : start + 50]
            payload = _http_get(
                "https://tr.wikipedia.org/w/api.php",
                {
                    "action": "query",
                    "prop": "pageprops",
                    "ppprop": "wikibase_item",
                    "titles": "|".join(batch),
                    "redirects": "1",
                    "format": "json",
                },
            )
            pages = json.loads(payload).get("query", {}).get("pages", {})
            for page in pages.values():
                qid = page.get("pageprops", {}).get("wikibase_item")
                if qid:
                    qids.add(qid)
        return qids

    def fetch_list_article(self, conn: sqlite3.Connection) -> int:
        """Fetch the tr.wikipedia list article as one source document."""
        payload = _http_get(
            "https://tr.wikipedia.org/w/api.php",
            {"action": "parse", "page": LIST_TITLE, "prop": "wikitext", "format": "json"},
        )
        wikitext = json.loads(payload)["parse"]["wikitext"]["*"]
        raw_path, digest = _store_raw(self.raw_dir, wikitext.encode(), "list-article")
        doc_id = _insert_document(
            conn,
            source_organization="Wikipedia (tr)",
            title=LIST_TITLE,
            document_type="other",
            url="https://tr.wikipedia.org/wiki/" + urllib.parse.quote(LIST_TITLE.replace(" ", "_")),
            retrieved_at=utc_now_iso(),
            language="tr",
            content_hash=digest,
            local_raw_path=str(raw_path),
            licence_or_reuse_notes="CC BY-SA 4.0 (attribution required)",
            attribution_required=1,
            source_tier=3,
            access_status="available",
            notes="kind=wikipedia_list",
        )
        conn.commit()
        return doc_id

    def fetch(self, conn: sqlite3.Connection | None = None) -> list[int]:  # type: ignore[override]
        """Fetch entities + linked articles; insert source_documents rows.

        Returns the created/reused source_document_ids. Idempotent: an
        identical (url, content_hash) pair is never inserted twice.
        """
        if conn is None:
            raise ValueError("fetch() needs an open database connection")
        qids = self.discover_qids()
        payload = _http_get(
            "https://www.wikidata.org/w/api.php",
            {
                "action": "wbgetentities",
                "ids": "|".join(qids),
                "props": "labels|claims|sitelinks",
                "format": "json",
            },
        )
        _, batch_hash = _store_raw(self.raw_dir, payload, "entities")
        entities = json.loads(payload)["entities"]

        document_ids: list[int] = []
        retrieved_at = utc_now_iso()
        for qid in qids:
            entity = entities[qid]
            entity_bytes = json.dumps(entity, ensure_ascii=False, sort_keys=True).encode()
            raw_path, digest = _store_raw(self.raw_dir, entity_bytes, qid)
            label = entity["labels"].get("tr", entity["labels"].get("en", {})).get("value", qid)
            document_ids.append(
                _insert_document(
                    conn,
                    source_organization="Wikidata",
                    title=f"Wikidata item {qid}: {label}",
                    document_type="other",
                    url=f"https://www.wikidata.org/wiki/{qid}",
                    retrieved_at=retrieved_at,
                    language="mul",
                    content_hash=digest,
                    local_raw_path=str(raw_path),
                    licence_or_reuse_notes="CC0 1.0",
                    attribution_required=0,
                    source_tier=3,
                    access_status="available",
                    notes=f"kind=wikidata_entity qid={qid} batch={batch_hash[:12]}",
                )
            )
            for site in ("trwiki", "enwiki"):
                sitelink = entity.get("sitelinks", {}).get(site)
                if not sitelink:
                    continue
                lang = site[:2]
                article = sitelink["title"]
                wikitext_payload = _http_get(
                    f"https://{lang}.wikipedia.org/w/api.php",
                    {
                        "action": "parse",
                        "page": article,
                        "prop": "wikitext",
                        "format": "json",
                    },
                )
                wikitext = json.loads(wikitext_payload)["parse"]["wikitext"]["*"]
                raw_path, digest = _store_raw(self.raw_dir, wikitext.encode(), f"{qid}-{lang}wiki")
                document_ids.append(
                    _insert_document(
                        conn,
                        source_organization=f"Wikipedia ({lang})",
                        title=article,
                        document_type="other",
                        url=f"https://{lang}.wikipedia.org/wiki/"
                        + urllib.parse.quote(article.replace(" ", "_")),
                        retrieved_at=retrieved_at,
                        language=lang,
                        content_hash=digest,
                        local_raw_path=str(raw_path),
                        licence_or_reuse_notes="CC BY-SA 4.0 (attribution required)",
                        attribution_required=1,
                        source_tier=3,
                        access_status="available",
                        notes=f"kind=wikipedia_article qid={qid} lang={lang}",
                    )
                )
        conn.commit()
        return document_ids

    # ------------------------------------------------------------------
    # parse
    # ------------------------------------------------------------------

    def parse(
        self, source_document_id: int, conn: sqlite3.Connection | None = None
    ) -> list[ClaimDraft]:  # type: ignore[override]
        if conn is None:
            raise ValueError("parse() needs an open database connection")
        row = conn.execute(
            "SELECT * FROM source_documents WHERE source_document_id = ?",
            (source_document_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"source document {source_document_id} not found")
        raw = Path(row["local_raw_path"]).read_bytes()
        notes = row["notes"] or ""
        if "kind=wikidata_entity" in notes:
            return _parse_entity(json.loads(raw))
        if "kind=wikipedia_list" in notes:
            return parse_list_article(raw.decode())
        return _parse_article(raw.decode())


# ----------------------------------------------------------------------
# Wikidata entity parsing (mechanical -> extraction_method='api')
# ----------------------------------------------------------------------


def _best_statement(claims: dict, pid: str) -> dict | None:
    statements = [s for s in claims.get(pid, []) if s["mainsnak"].get("datavalue")]
    if not statements:
        return None
    preferred = [s for s in statements if s.get("rank") == "preferred"]
    return (preferred or statements)[0]["mainsnak"]["datavalue"]["value"]


def _parse_entity(entity: dict) -> list[ClaimDraft]:
    claims = entity.get("claims", {})
    qid = entity.get("id", "?")
    drafts: list[ClaimDraft] = []

    def draft(field: str, raw: str, normalized: str) -> ClaimDraft:
        return ClaimDraft(
            field_name=field,
            raw_value=raw,
            normalized_value=normalized,
            extraction_method="api",
            extractor_version=WikidataAdapter.adapter_version,
            assertion_status="reported",
            section_reference=qid,
            review_status="pending",
        )

    for lang, field in (("tr", "canonical_title_tr"), ("en", "canonical_title_en")):
        label = entity.get("labels", {}).get(lang, {}).get("value")
        if label:
            drafts.append(draft(field, label, label))

    time_value = _best_statement(claims, "P585")
    if time_value:
        precision = _WD_DATE_PRECISION.get(time_value.get("precision", 11), "approximate")
        iso_date = time_value["time"].lstrip("+")[:10]
        drafts.append(
            draft("incident_start_datetime", time_value["time"], f"{iso_date}T00:00:00+03:00")
        )
        drafts.append(draft("date_precision", str(time_value.get("precision")), precision))

    deaths = _best_statement(claims, "P1120")
    if deaths:
        drafts.append(draft("fatalities_current", deaths["amount"], deaths["amount"].lstrip("+")))

    coord = _best_statement(claims, "P625")
    if coord:
        drafts.append(draft("latitude", str(coord["latitude"]), f"{coord['latitude']:.6f}"))
        drafts.append(draft("longitude", str(coord["longitude"]), f"{coord['longitude']:.6f}"))

    # Cause axes: P31 classes the item itself declares, mapped mechanically.
    for statement in claims.get("P31", []):
        p31 = statement["mainsnak"].get("datavalue", {}).get("value", {}).get("id")
        mechanism = P31_EVENT_MECHANISMS.get(p31 or "")
        if mechanism:
            classification = draft("event_mechanism", f"P31={p31}", mechanism)
            classification.claim_subject_type = "classification"
            drafts.append(classification)
    return drafts


# ----------------------------------------------------------------------
# Wikipedia wikitext parsing
# ----------------------------------------------------------------------

_INFOBOX_DEATHS = re.compile(
    r"\|\s*(?:ölüsayısı|ölü sayısı|deaths|fatalities)\s*=\s*([0-9][0-9.,]*)", re.IGNORECASE
)
_START_DATE_TPL = re.compile(
    r"\{\{(?:Başlangıç tarihi|start date)[^}]*?\|(\d{4})\|(\d{1,2})\|(\d{1,2})", re.IGNORECASE
)
_KOORDINAT_DMS = re.compile(
    r"\{\{(?:Koordinat|coord)\s*\|(\d+)\|(\d+)\|([\d.]+)\|([NS])\|(\d+)\|(\d+)\|([\d.]+)\|([EW])",
    re.IGNORECASE,
)
_COORD_DECIMAL = re.compile(
    r"\{\{(?:Koordinat|coord)\s*\|(-?\d+\.\d+)\|(-?\d+\.\d+)", re.IGNORECASE
)
_MAP_LATLON = re.compile(
    r"lat_deg\s*=\s*(-?\d+\.\d+).{0,200}?lon_deg\s*=\s*(-?\d+\.\d+)", re.DOTALL
)
_WIKILINK = re.compile(r"\[\[([^\]|#]+)")
#: infobox operating-company fields (tr/en). Mechanical extraction; the
#: ingest layer requires >= 2 independent documents before the role row is
#: marked reviewed (editorial protocol §2 corroboration threshold).
_INFOBOX_OPERATOR = re.compile(
    r"\|\s*(?:[İi]şletmeci|[İi]şleten|operat[oö]r|owner|şirket)\s*=\s*([^\n]+)"
)
#: prose fatality statements — inherently interpretive -> ai_assisted
_PROSE_DEATHS = re.compile(
    r"(\d+)\s*(?:tanesi|işçi(?:nin|den)?|kişi(?:nin)?|madenci(?:nin)?)"
    r"[^.]{0,80}?(?:öl(?:dü|ürken|en)|hayatını kaybet|yaşamını yitir)",
)


def _clean_org_wikitext(value: str) -> str | None:
    """Company name from an infobox value: wikilink display text preferred,
    markup and references stripped; empty/template-only values rejected."""
    value = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", "", value, flags=re.DOTALL)
    value = re.sub(r"\{\{[^}]*\}\}", "", value)
    link = re.match(r"\s*\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", value)
    if link:
        cleaned = (link.group(2) or link.group(1)).strip()
    else:
        cleaned = re.sub(r"[\[\]']", "", value).strip()
    return cleaned[:120] or None


def _province_lookup() -> dict[str, str]:
    entries = vocabularies.load_vocabulary("turkey_admin_areas")
    return {normalize_tr(e.label_tr): e.code for e in entries}


def _parse_article(wikitext: str) -> list[ClaimDraft]:
    drafts: list[ClaimDraft] = []

    def draft(field: str, raw: str, normalized: str, method: str = "html_parser") -> ClaimDraft:
        review = "needs_review" if method == "ai_assisted" else "pending"
        return ClaimDraft(
            field_name=field,
            raw_value=raw,
            normalized_value=normalized,
            extraction_method=method,  # type: ignore[arg-type]
            extractor_version=WikidataAdapter.adapter_version,
            assertion_status="reported",
            section_reference="infobox" if method == "html_parser" else "lead_prose",
            review_status=review,  # type: ignore[arg-type]
        )

    match = _INFOBOX_DEATHS.search(wikitext)
    if match:
        number = match.group(1).replace(".", "").replace(",", "")
        drafts.append(draft("fatalities_current", match.group(0).strip(), number))
    else:
        prose = _PROSE_DEATHS.search(wikitext)
        if prose:
            drafts.append(
                draft(
                    "fatalities_current",
                    prose.group(0)[:120],
                    prose.group(1),
                    method="ai_assisted",
                )
            )

    match = _START_DATE_TPL.search(wikitext)
    if match:
        year, month, day = (int(g) for g in match.groups())
        drafts.append(
            draft(
                "incident_start_datetime",
                match.group(0),
                f"{year:04d}-{month:02d}-{day:02d}T00:00:00+03:00",
            )
        )
        drafts.append(draft("date_precision", match.group(0), "exact_date"))

    coord = _KOORDINAT_DMS.search(wikitext)
    if coord:
        lat = int(coord.group(1)) + int(coord.group(2)) / 60 + float(coord.group(3)) / 3600
        lon = int(coord.group(5)) + int(coord.group(6)) / 60 + float(coord.group(7)) / 3600
        if coord.group(4).upper() == "S":
            lat = -lat
        if coord.group(8).upper() == "W":
            lon = -lon
        drafts.append(draft("latitude", coord.group(0)[:120], f"{lat:.6f}"))
        drafts.append(draft("longitude", coord.group(0)[:120], f"{lon:.6f}"))
    else:
        decimal = _COORD_DECIMAL.search(wikitext) or _MAP_LATLON.search(wikitext)
        if decimal:
            drafts.append(draft("latitude", decimal.group(0)[:120], decimal.group(1)))
            drafts.append(draft("longitude", decimal.group(0)[:120], decimal.group(2)))

    operator = _INFOBOX_OPERATOR.search(wikitext)
    if operator:
        company = _clean_org_wikitext(operator.group(1))
        if company:
            org_draft = draft("operator_organization", operator.group(0)[:160], company)
            org_draft.claim_subject_type = "organization"
            org_draft.notes = {"role": "operator"}
            drafts.append(org_draft)

    # Cause axes: the infobox `tür=` value, else the first type phrase in the
    # lead (text before the first section heading) — deterministic phrase
    # table, first match only.
    type_match = re.search(r"\|\s*tür\s*=\s*([^\n|]+)", wikitext, re.IGNORECASE)
    lead = wikitext.split("==", 1)[0]
    cause_text = type_match.group(1).strip() if type_match else lead
    cause_source = "infobox" if type_match else "lead_prose"
    folded = normalize_tr(cause_text)
    for phrase, mechanism, hazard in TR_MECHANISM_PHRASES:
        if normalize_tr(phrase) in folded:
            mech_draft = draft("event_mechanism", cause_text[:120] or phrase, mechanism)
            mech_draft.claim_subject_type = "classification"
            mech_draft.section_reference = cause_source
            drafts.append(mech_draft)
            if hazard:
                hazard_draft = draft("hazard", cause_text[:120] or phrase, hazard)
                hazard_draft.claim_subject_type = "classification"
                hazard_draft.section_reference = cause_source
                drafts.append(hazard_draft)
            break

    # Province: the most-mentioned province wikilink wins (a single stray
    # mention of another province — hatnotes, comparisons — must not win over
    # the article's actual setting). Ties break to the earliest mention.
    provinces = _province_lookup()
    mentions: dict[str, list[int]] = {}
    first_raw: dict[str, str] = {}
    for order, link in enumerate(_WIKILINK.findall(wikitext)):
        cleaned = re.sub(
            r"(\s+(province|ili?)|\s*\((il|province)\))$", "", link.strip(), flags=re.IGNORECASE
        )
        code = provinces.get(normalize_tr(cleaned))
        if code:
            mentions.setdefault(code, []).append(order)
            first_raw.setdefault(code, f"[[{link}]]")
    if mentions:
        code = min(mentions, key=lambda c: (-len(mentions[c]), mentions[c][0]))
        drafts.append(draft("province_code", first_raw[code], code))

    return drafts


# ----------------------------------------------------------------------
# List-article parsing (tr.wikipedia incident list, 1983 -> present)
# ----------------------------------------------------------------------


def _bullet_date(line: str, section_year: str | None) -> tuple[str, str] | None:
    """(iso_datetime, date_precision) from a bullet, or None."""
    match = _LIST_DATE.search(line)
    if match:
        day, month_name, year = match.groups()
        return (
            f"{int(year):04d}-{_TR_MONTHS[month_name]:02d}-{int(day):02d}T00:00:00+03:00",
            "exact_date",
        )
    match = _LIST_MONTH.search(line)
    if match and section_year:
        return (
            f"{int(section_year):04d}-{_TR_MONTHS[match.group(1)]:02d}-01T00:00:00+03:00",
            "month",
        )
    return None


def _bullet_province(line: str) -> str | None:
    provinces = _province_lookup()
    for token in normalize_tr(line).split():
        code = provinces.get(token)
        if code:
            return code
    return None


def parse_list_article(wikitext: str) -> list[ClaimDraft]:
    """One-sentence incident bullets -> grouped claim drafts.

    Every draft carries ``notes={'group': <key>}`` so the ingest layer can
    reassemble per-incident groups; a bullet qualifies only when BOTH a date
    and a death-count pattern match inside it — otherwise it is dropped
    entirely (never guessed, never fabricated).
    """
    body = wikitext.split("== Kazalar ==", 1)[-1].split("== Ayrıca", 1)[0]
    drafts: list[ClaimDraft] = []
    section_year: str | None = None
    for line in body.splitlines():
        heading = re.match(r"^===\s*(\d{4})", line)
        if heading:
            section_year = heading.group(1)
            continue
        if not line.lstrip().startswith("*"):
            continue
        date = _bullet_date(line, section_year)
        deaths = _LIST_DEATHS.search(line)
        if not date or not deaths:
            continue
        # Ambiguity guard: a death sentence carrying several (non-year)
        # numbers — "46 işçiden 13'ü…", "2 işçi yanarak 66 işçi…" — cannot be
        # resolved mechanically. It becomes an ai_assisted claim (mandatory
        # human review) carrying the last number as the candidate value.
        span_numbers = [
            n for n in re.findall(r"\d+", deaths.group(0)) if not 1900 <= int(n) <= 2099
        ]
        deaths_ambiguous = len(span_numbers) > 1
        deaths_value = span_numbers[-1] if span_numbers else deaths.group(1)
        key = sha256_bytes(line.strip().encode())[:12]
        section = f"Kazalar/{section_year}"

        def draft(
            field: str, raw: str, normalized: str, key: str = key, section: str = section
        ) -> ClaimDraft:
            d = ClaimDraft(
                field_name=field,
                raw_value=raw[:160],
                normalized_value=normalized,
                extraction_method="html_parser",
                extractor_version=WikidataAdapter.adapter_version,
                assertion_status="reported",
                section_reference=section,
                review_status="pending",
            )
            d.notes = {"group": key}
            return d

        drafts.append(draft("incident_start_datetime", line.strip()[:160], date[0]))
        drafts.append(draft("date_precision", date[0], date[1]))
        deaths_draft = draft("fatalities_current", deaths.group(0), deaths_value)
        if deaths_ambiguous:
            deaths_draft.extraction_method = "ai_assisted"
            deaths_draft.review_status = "needs_review"
        drafts.append(deaths_draft)
        province = _bullet_province(line)
        if province:
            drafts.append(draft("province_code", line.strip()[:120], province))
        title = _LIST_TITLE_LINK.match(line.strip())
        if title:
            drafts.append(draft("canonical_title_tr", title.group(0), title.group(1)))
        folded = normalize_tr(line)
        for phrase, mechanism, hazard in TR_MECHANISM_PHRASES:
            if normalize_tr(phrase) in folded:
                mech = draft("event_mechanism", line.strip()[:120], mechanism)
                mech.claim_subject_type = "classification"
                drafts.append(mech)
                if hazard:
                    hz = draft("hazard", line.strip()[:120], hazard)
                    hz.claim_subject_type = "classification"
                    drafts.append(hz)
                break
    return drafts


def parse_isig_table(wikitext: str) -> list[tuple[int, int]]:
    """(year, miner deaths) rows from the İSİG Meclisi annual table."""
    return [(int(y), int(n)) for y, n in _ISIG_ROW.findall(wikitext)]
