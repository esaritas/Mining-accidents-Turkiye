"""Wikidata active-sites adapter — mining/quarrying site registry seed.

Role in the evidence flow: fetches mine and quarry *items* (not accidents)
located in Türkiye from Wikidata (CC0), stores every response immutably in
``data/raw/``, and turns them into facility-subject claims: name, type,
commodity, location, operating/owning organization and that organization's
home country. Facilities are a **context registry**, not incident evidence —
values are written with their ``source_claim_id`` and a review-log sign-off
(the incident ``claim_decisions`` table stays incident-scoped by design; see
docs/data_dictionary.md).

Coverage honesty: Wikidata documents only a fraction of licensed operations
in Türkiye. The dashboard and export must label this layer "open structured
sources only — not a complete register". Fuller registers (Global Energy
Monitor tracker, MAPEG licence data) are registered TO_ASSESS in
docs/source_registry.csv.

Extraction honesty: everything here is a mechanical ``api`` extraction of
statements the source item itself makes. No prose, no inference; class and
commodity labels are mapped through explicit tables and anything unmapped
lands in ``other``/``unknown`` rather than being guessed.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.parse
from pathlib import Path

from mining_accidents.adapters.base import ClaimDraft, SourceAdapter, SourceAssessment
from mining_accidents.adapters.wikidata import (
    SPARQL_ENDPOINT,
    _http_get,
    _insert_document,
    _province_lookup,
    _store_raw,
)
from mining_accidents.database import utc_now_iso
from mining_accidents.normalization import normalize_tr

DEFAULT_RAW_DIR = Path("data/raw/wikidata_sites")

#: instances of `mine` (Q820477) or subclasses, in Türkiye (Q43).
SPARQL_QUERY = """
SELECT DISTINCT ?item WHERE {
  ?item wdt:P31/wdt:P279* wd:Q820477 .
  ?item wdt:P17 wd:Q43 .
}
"""

#: P31 class *label* fragments (en + tr, lowercased with normalize_tr) ->
#: facility_types.csv code. Order matters: the first matching fragment wins;
#: unmapped classes are skipped (never guessed).
CLASS_LABEL_FACILITY_TYPES: tuple[tuple[str, str], ...] = (
    ("underground mine", "mine_underground"),
    ("yeraltı", "mine_underground"),
    ("yeralti", "mine_underground"),
    ("open-pit", "mine_openpit"),
    ("open pit", "mine_openpit"),
    ("opencast", "mine_openpit"),
    ("strip mine", "mine_openpit"),
    ("açık ocak", "mine_openpit"),
    ("açık işletme", "mine_openpit"),
    ("quarry", "quarry"),
    ("taş ocağı", "quarry"),
    ("tailings", "tailings_facility"),
    ("atık barajı", "tailings_facility"),
    ("processing plant", "processing_plant"),
    ("smelter", "processing_plant"),
    ("izabe", "processing_plant"),
    ("mine", "mine_unspecified"),
    ("mining", "mine_unspecified"),
    ("colliery", "mine_unspecified"),
    ("maden", "mine_unspecified"),
    ("ocağı", "mine_unspecified"),
)

#: P1056 (product/material produced) label (en + tr, lowercased) ->
#: commodities.csv code. Unmapped labels become `other` with the source label
#: passed through.
COMMODITY_LABELS: dict[str, str] = {
    "coal": "coal",
    "hard coal": "coal",
    "bituminous coal": "coal",
    "anthracite": "coal",
    "kömür": "coal",
    "taşkömürü": "coal",
    "taş kömürü": "coal",
    "antrasit": "coal",
    "lignite": "lignite",
    "brown coal": "lignite",
    "linyit": "lignite",
    "chromium": "chromium",
    "chromite": "chromium",
    "krom": "chromium",
    "kromit": "chromium",
    "iron": "iron",
    "iron ore": "iron",
    "demir": "iron",
    "demir cevheri": "iron",
    "copper": "copper",
    "copper ore": "copper",
    "bakır": "copper",
    "gold": "gold",
    "altın": "gold",
    "silver": "silver",
    "gümüş": "silver",
    "zinc": "zinc",
    "çinko": "zinc",
    "lead": "lead",
    "kurşun": "lead",
    "phosphate": "phosphate",
    "phosphorite": "phosphate",
    "phosphate rock": "phosphate",
    "fosfat": "phosphate",
    "boron": "boron",
    "borax": "boron",
    "bor": "boron",
    "boraks": "boron",
    "marble": "marble",
    "mermer": "marble",
}


def _entity_label(entity_or_ref: dict, prefer: tuple[str, ...] = ("tr", "en")) -> str | None:
    labels = entity_or_ref.get("labels", {})
    for lang in prefer:
        value = labels.get(lang, {}).get("value")
        if value:
            return value
    return None


def _statement_qids(claims: dict, pid: str) -> list[str]:
    qids = []
    for statement in claims.get(pid, []):
        value = statement.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("id"):
            qids.append(value["id"])
    return qids


def _best_coordinate(claims: dict) -> tuple[float, float] | None:
    for statement in claims.get("P625", []):
        value = statement.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and "latitude" in value:
            return float(value["latitude"]), float(value["longitude"])
    return None


def map_facility_type(class_labels: list[str]) -> str:
    """First matching class-label fragment wins; nothing matched -> unknown."""
    for label in class_labels:
        folded = normalize_tr(label)
        for fragment, code in CLASS_LABEL_FACILITY_TYPES:
            if normalize_tr(fragment) in folded:
                return code
    return "unknown"


def map_commodity(label: str | None) -> tuple[str | None, str | None]:
    """(commodity_code, commodity_label) — unmapped labels become `other`."""
    if not label:
        return None, None
    folded = {normalize_tr(k): v for k, v in COMMODITY_LABELS.items()}
    return folded.get(normalize_tr(label), "other"), label


def parse_site_entity(entity: dict, references: dict[str, dict]) -> list[ClaimDraft]:
    """Mechanical facility-subject claims from one Wikidata site entity.

    ``references`` maps referenced QIDs (classes, commodities, admin areas,
    organizations, countries) to ``{"label", "p131", "p17", "p297"}`` built
    from a separate wbgetentities batch — all still statements the source
    makes, resolved to labels.
    """
    claims = entity.get("claims", {})
    qid = entity.get("id", "?")
    drafts: list[ClaimDraft] = []

    def draft(field: str, raw: str, normalized: str, **notes: str) -> ClaimDraft:
        d = ClaimDraft(
            field_name=field,
            raw_value=raw[:160],
            normalized_value=normalized,
            claim_subject_type="facility",
            extraction_method="api",
            extractor_version=WikidataSitesAdapter.adapter_version,
            assertion_status="reported",
            section_reference=qid,
            review_status="pending",
        )
        d.notes = dict(notes)
        return d

    label = _entity_label(entity)
    if not label:
        return []  # a site we cannot even name is not registered
    drafts.append(draft("facility_name_tr", label, label))

    class_qids = _statement_qids(claims, "P31")
    class_labels: list[str] = []
    for class_qid in class_qids:
        ref = references.get(class_qid, {})
        class_labels.extend(lb for lb in (ref.get("label_en"), ref.get("label")) if lb)
    drafts.append(
        draft(
            "facility_type",
            "P31=" + ",".join(class_qids) if class_qids else "P31 absent",
            map_facility_type(class_labels),
        )
    )

    commodity_qids = _statement_qids(claims, "P1056")
    if commodity_qids:
        ref = references.get(commodity_qids[0], {})
        # Try the English label, then the Turkish one; keep whichever maps.
        code, label_out = None, None
        for candidate in (ref.get("label_en"), ref.get("label")):
            code, label_out = map_commodity(candidate)
            if code and code != "other":
                break
        if code:
            drafts.append(
                draft(
                    "commodity_code",
                    f"P1056={commodity_qids[0]} ({label_out})",
                    code,
                    commodity_label=label_out or "",
                )
            )

    coordinate = _best_coordinate(claims)
    if coordinate:
        drafts.append(draft("latitude", f"P625={coordinate[0]}", f"{coordinate[0]:.6f}"))
        drafts.append(draft("longitude", f"P625={coordinate[1]}", f"{coordinate[1]:.6f}"))

    province_code = _resolve_province(claims, references)
    if province_code:
        drafts.append(draft("province_code", "P131", province_code))

    # Closure statements are the only status the source can assert
    # mechanically; anything else stays `unknown` (never claimed "operating").
    closed = bool(claims.get("P3999")) or bool(claims.get("P576"))
    drafts.append(
        draft(
            "operational_status",
            "P3999/P576 present" if closed else "no closure statement",
            "closed" if closed else "unknown",
        )
    )

    for pid, role in (("P137", "operator"), ("P127", "owner")):
        for org_qid in _statement_qids(claims, pid):
            ref = references.get(org_qid, {})
            org_label = ref.get("label")
            if not org_label:
                continue
            country_qid = (ref.get("p17") or [None])[0]
            country = references.get(country_qid or "", {})
            org_draft = draft(
                f"{role}_organization",
                f"{pid}={org_qid}",
                org_label,
                org_qid=org_qid,
                role=role,
                country_code=country.get("p297") or "",
                country_label=country.get("label") or "",
            )
            org_draft.claim_subject_type = "organization"
            drafts.append(org_draft)
    return drafts


def _resolve_province(claims: dict, references: dict[str, dict]) -> str | None:
    """P131 admin chain -> province code (two levels: district -> province)."""
    provinces = _province_lookup()
    for admin_qid in _statement_qids(claims, "P131"):
        ref = references.get(admin_qid, {})
        label = ref.get("label")
        if label:
            code = provinces.get(normalize_tr(_strip_admin_suffix(label)))
            if code:
                return code
        for parent_qid in ref.get("p131", []):
            parent = references.get(parent_qid, {})
            if parent.get("label"):
                code = provinces.get(normalize_tr(_strip_admin_suffix(parent["label"])))
                if code:
                    return code
    return None


def _strip_admin_suffix(label: str) -> str:
    import re

    return re.sub(
        r"(\s+(province|ili?)|\s*\((il|province)\))$", "", label.strip(), flags=re.IGNORECASE
    )


class WikidataSitesAdapter(SourceAdapter):
    source_key = "wikidata_sites"
    adapter_version = "1.0.0"

    def __init__(self, raw_dir: str | Path = DEFAULT_RAW_DIR) -> None:
        self.raw_dir = Path(raw_dir)
        self._references: dict[str, dict] = {}

    def assess(self) -> SourceAssessment:
        return SourceAssessment(
            source_key="wikidata_sites",
            tier_proposed=3,
            automated_collection_permitted="yes",
            access_notes="Wikidata content is CC0; API collection explicitly permitted.",
            coverage_notes=(
                "Documents only mines notable enough for Wikidata — a fraction "
                "of licensed operations in Türkiye. Operator/owner statements "
                "are sparse. Fuller registers (GEM tracker, MAPEG) are "
                "TO_ASSESS in docs/source_registry.csv."
            ),
            format_risks="Structured JSON (low risk).",
        )

    def discover_qids(self) -> list[str]:
        payload = _http_get(SPARQL_ENDPOINT, {"query": SPARQL_QUERY, "format": "json"}, timeout=90)
        _store_raw(self.raw_dir, payload, "sparql-sites-discovery")
        bindings = json.loads(payload)["results"]["bindings"]
        return sorted({row["item"]["value"].rsplit("/", 1)[-1] for row in bindings})

    def _fetch_entities(self, qids: list[str], stem: str) -> dict[str, dict]:
        entities: dict[str, dict] = {}
        for start in range(0, len(qids), 50):
            batch = qids[start : start + 50]
            payload = _http_get(
                "https://www.wikidata.org/w/api.php",
                {
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "props": "labels|claims",
                    "format": "json",
                },
            )
            _store_raw(self.raw_dir, payload, f"{stem}-{start // 50}")
            for qid, entity in json.loads(payload).get("entities", {}).items():
                if "missing" not in entity:
                    entities[qid] = entity
        return entities

    def _build_references(self, site_entities: dict[str, dict]) -> dict[str, dict]:
        """Resolve referenced QIDs (classes, commodities, admin, orgs) to
        labels + the follow-up statements parsing needs (org P17, admin P131,
        country P297). Two fetch levels, stored like every raw response."""
        level1: set[str] = set()
        for entity in site_entities.values():
            claims = entity.get("claims", {})
            for pid in ("P31", "P1056", "P131", "P137", "P127"):
                level1.update(_statement_qids(claims, pid))
        fetched = self._fetch_entities(sorted(level1), "site-refs-l1")

        level2: set[str] = set()
        for entity in fetched.values():
            claims = entity.get("claims", {})
            level2.update(_statement_qids(claims, "P131"))  # admin parents
            level2.update(_statement_qids(claims, "P17"))  # org home countries
        level2 -= set(fetched)
        if level2:
            fetched.update(self._fetch_entities(sorted(level2), "site-refs-l2"))

        references: dict[str, dict] = {}
        for qid, entity in fetched.items():
            claims = entity.get("claims", {})
            iso_codes = [
                s.get("mainsnak", {}).get("datavalue", {}).get("value")
                for s in claims.get("P297", [])
            ]
            references[qid] = {
                "label": _entity_label(entity),
                "label_en": _entity_label(entity, prefer=("en",)),
                "p131": _statement_qids(claims, "P131"),
                "p17": _statement_qids(claims, "P17"),
                "p297": next((c for c in iso_codes if isinstance(c, str)), None),
            }
        references_bytes = json.dumps(references, ensure_ascii=False, sort_keys=True).encode()
        _store_raw(self.raw_dir, references_bytes, "site-references")
        return references

    def fetch(self, conn: sqlite3.Connection | None = None) -> list[int]:  # type: ignore[override]
        """Fetch site entities; insert one source_documents row per site."""
        if conn is None:
            raise ValueError("fetch() needs an open database connection")
        qids = self.discover_qids()
        entities = self._fetch_entities(qids, "site-entities")
        self._references = self._build_references(entities)

        document_ids: list[int] = []
        retrieved_at = utc_now_iso()
        for qid in sorted(entities):
            entity = entities[qid]
            entity_bytes = json.dumps(entity, ensure_ascii=False, sort_keys=True).encode()
            raw_path, digest = _store_raw(self.raw_dir, entity_bytes, qid)
            label = _entity_label(entity) or qid
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
                    notes=f"kind=wikidata_site qid={qid}",
                )
            )
        conn.commit()
        return document_ids

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
        entity = json.loads(Path(row["local_raw_path"]).read_bytes())
        return parse_site_entity(entity, self._load_references())

    def _load_references(self) -> dict[str, dict]:
        if not self._references:
            candidates = sorted(
                self.raw_dir.glob("site-references-*.json"), key=lambda p: p.stat().st_mtime
            )
            if candidates:
                self._references = json.loads(candidates[-1].read_text(encoding="utf-8"))
        return self._references

    def site_url(self, qid: str) -> str:
        return "https://www.wikidata.org/wiki/" + urllib.parse.quote(qid)
