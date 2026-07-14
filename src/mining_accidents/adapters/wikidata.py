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

#: Items excluded with reasons — curation decisions, kept visible here.
EXCLUDED_QIDS: dict[str, str] = {
    "Q118344293": "article about international reactions, not an incident",
}

#: Wikidata time precision -> project date_precision
_WD_DATE_PRECISION = {11: "exact_date", 10: "month", 9: "year"}


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
        return sorted(q for q in qids if q not in EXCLUDED_QIDS)

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
        if "kind=wikidata_entity" in (row["notes"] or ""):
            return _parse_entity(json.loads(raw))
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
#: prose fatality statements — inherently interpretive -> ai_assisted
_PROSE_DEATHS = re.compile(
    r"(\d+)\s*(?:tanesi|işçi(?:nin|den)?|kişi(?:nin)?|madenci(?:nin)?)"
    r"[^.]{0,80}?(?:öl(?:dü|ürken|en)|hayatını kaybet|yaşamını yitir)",
)


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
