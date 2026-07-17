"""Seed ingestion: adapter output -> incidents + claims (+ optional decisions).

Role in the evidence flow: turns adapter fetch/parse results into linked
evidence rows, and — only when a human reviewer identity is supplied — records
bulk *accept* decisions under a documented, deterministic source-priority
rule. Unreviewed ``ai_assisted`` claims are never selected; incomplete
records stay unpublished. Everything is auditable in ``claim_decisions`` and
``review_log``, and every decision can later be superseded per the conflict
resolution protocol.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from mining_accidents import review, validators, vocabularies
from mining_accidents.adapters.base import ClaimDraft
from mining_accidents.adapters.wikidata import WikidataAdapter, parse_isig_table
from mining_accidents.database import utc_now_iso
from mining_accidents.models import ClaimDecision, IngestionRun
from mining_accidents.normalization import normalize_tr
from mining_accidents.provenance import record_ingestion_run

#: field -> decision order. Wikipedia infobox values (html_parser) are the
#: current-revision figures and win over the structured item; ai_assisted is
#: never auto-selected (hard constraint 5).
_METHOD_PRIORITY = {"html_parser": 0, "api": 1}

_DECIDED_FIELDS = (
    "canonical_title_tr",
    "canonical_title_en",
    "incident_start_datetime",
    "date_precision",
    "province_code",
    "fatalities_current",
    "injuries_current",
    "latitude",
    "longitude",
)
_PUBLICATION_FIELDS = ("incident_start_datetime", "province_code", "fatalities_current")

_BULK_RATIONALE = (
    "Bulk-accepted from tier-3 seed sources (priority: Wikipedia infobox > "
    "Wikidata item) per project-owner directive of 2026-07-13. Single-pass "
    "seeding; value awaits corroboration against Tier 1-2 sources and may be "
    "superseded per docs/conflict_resolution_protocol.md."
)


#: classification claim field -> classification_system (+ backing vocabulary)
_CLASSIFICATION_SYSTEMS = {
    "hazard": ("project_hazard", "hazards"),
    "event_mechanism": ("project_event_mechanism", "event_mechanisms"),
    "mode_of_harm": ("project_mode_of_harm", "modes_of_harm"),
    "contributing_condition": ("project_contributing_condition", "contributing_conditions"),
}


@dataclass
class IngestSummary:
    run_id: int | None = None
    documents: int = 0
    incidents_created: int = 0
    claims_created: int = 0
    decisions_recorded: int = 0
    classifications_created: int = 0
    organization_roles_created: int = 0
    published: list[str] = field(default_factory=list)
    unpublished: dict[str, list[str]] = field(default_factory=dict)
    claims_needing_review: int = 0


def _insert_claim(
    conn: sqlite3.Connection, incident_id: int, source_document_id: int, draft: ClaimDraft
) -> bool:
    """Insert one claim; returns False when an identical claim already exists."""
    existing = conn.execute(
        "SELECT 1 FROM claims WHERE incident_id = ? AND source_document_id = ? "
        "AND field_name = ? AND normalized_value IS ?",
        (incident_id, source_document_id, draft.field_name, draft.normalized_value),
    ).fetchone()
    if existing:
        return False
    conn.execute(
        """
        INSERT INTO claims (
            incident_id, source_document_id, claim_subject_type, claim_subject_id,
            field_name, raw_value, normalized_value, unit, page_number,
            section_reference, short_evidence_excerpt, extraction_method,
            extractor_version, assertion_status, confidence_score, review_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            incident_id,
            source_document_id,
            draft.claim_subject_type,
            draft.claim_subject_id,
            draft.field_name,
            draft.raw_value,
            draft.normalized_value,
            draft.unit,
            draft.page_number,
            draft.section_reference,
            draft.short_evidence_excerpt,
            draft.extraction_method,
            draft.extractor_version,
            draft.assertion_status,
            draft.confidence_score,
            draft.review_status,
        ),
    )
    return True


def _find_or_create_incident(
    conn: sqlite3.Connection, qid: str, title_tr: str | None, title_en: str | None
) -> tuple[int, bool]:
    marker = f"wikidata:{qid}"
    row = conn.execute(
        "SELECT incident_id FROM incidents WHERE scope_rationale LIKE ?", (f"%{marker}%",)
    ).fetchone()
    if row:
        return int(row["incident_id"]), False
    title = title_tr or title_en or qid
    cur = conn.execute(
        "INSERT INTO incidents (canonical_title_tr, canonical_title_en, "
        "canonical_title_tr_normalized, incident_status, scope_rationale) "
        "VALUES (?, ?, ?, 'scope_undetermined', ?)",
        (
            title_tr or title,
            title_en,
            normalize_tr(title),
            f"Seeded from {marker}; scope set after date/fatality decisions.",
        ),
    )
    return int(cur.lastrowid), True


def _qid_of(notes: str | None) -> str | None:
    for token in (notes or "").split():
        if token.startswith("qid="):
            return token[4:]
    return None


def ingest_wikidata(
    conn: sqlite3.Connection,
    reviewer: str | None = None,
    publish: bool = True,
    raw_dir: str | None = None,
) -> IngestSummary:
    """Fetch, link, and (optionally) bulk-decide the Wikidata/Wikipedia seed.

    Without ``reviewer``, only evidence rows are created — no decisions, no
    publication. With ``reviewer``, deterministic bulk accepts are recorded in
    that human identity's name.
    """
    started_at = utc_now_iso()
    adapter = WikidataAdapter(raw_dir) if raw_dir else WikidataAdapter()
    summary = IngestSummary()

    document_ids = adapter.fetch(conn)
    summary.documents = len(set(document_ids))

    docs_by_qid: dict[str, list[sqlite3.Row]] = {}
    for doc_id in dict.fromkeys(document_ids):
        row = conn.execute(
            "SELECT * FROM source_documents WHERE source_document_id = ?", (doc_id,)
        ).fetchone()
        qid = _qid_of(row["notes"])
        if qid:
            docs_by_qid.setdefault(qid, []).append(row)

    incident_ids: dict[str, int] = {}
    list_doc_id = adapter.fetch_list_article(conn)
    for qid, docs in sorted(docs_by_qid.items()):
        drafts_by_doc = {
            doc["source_document_id"]: adapter.parse(doc["source_document_id"], conn)
            for doc in docs
        }
        titles = {
            draft.field_name: draft.normalized_value
            for drafts in drafts_by_doc.values()
            for draft in drafts
            if draft.field_name.startswith("canonical_title")
        }
        incident_id, created = _find_or_create_incident(
            conn, qid, titles.get("canonical_title_tr"), titles.get("canonical_title_en")
        )
        incident_ids[qid] = incident_id
        summary.incidents_created += int(created)
        for doc_id, drafts in drafts_by_doc.items():
            for draft in drafts:
                summary.claims_created += int(_insert_claim(conn, incident_id, doc_id, draft))
        conn.commit()
        # Decide immediately so canonical date/province exist before the list
        # pass runs its duplicate blocking-key matches against them.
        if reviewer:
            _decide_incident(conn, incident_id, reviewer, summary)

    incident_ids.update(_ingest_list_article(conn, adapter, list_doc_id, summary, reviewer))
    _ingest_isig_aggregates(conn, list_doc_id, summary)
    _ingest_rate_context(conn, list_doc_id)

    if reviewer and publish:
        for key, incident_id in sorted(incident_ids.items()):
            public_id_or_blockers = _publish_if_complete(conn, incident_id, reviewer)
            if isinstance(public_id_or_blockers, str):
                summary.published.append(public_id_or_blockers)
            else:
                summary.unpublished[key] = public_id_or_blockers

    summary.claims_needing_review = conn.execute(
        "SELECT COUNT(*) FROM claims WHERE review_status = 'needs_review'"
    ).fetchone()[0]
    summary.run_id = record_ingestion_run(
        conn,
        IngestionRun(
            run_type="adapter",
            adapter_name=adapter.source_key,
            adapter_version=adapter.adapter_version,
            started_at=started_at,
            input_reference="wikidata SPARQL + wbgetentities + wikipedia parse API",
            records_created=summary.claims_created + summary.incidents_created,
            records_skipped=0,
            status="completed",
            notes=f"reviewer={reviewer or 'none'} publish={publish}",
        ),
    )
    return summary


def _decide_incident(
    conn: sqlite3.Connection, incident_id: int, reviewer: str, summary: IngestSummary
) -> None:
    """Bulk decisions + cause rows + scope for one incident (idempotent)."""
    summary.decisions_recorded += _bulk_decide(conn, incident_id, reviewer)
    summary.classifications_created += _apply_classifications(conn, incident_id, reviewer)
    summary.organization_roles_created += _apply_organization_roles(conn, incident_id, reviewer)
    _set_scope(conn, incident_id, reviewer)


def _bulk_decide(conn: sqlite3.Connection, incident_id: int, reviewer: str) -> int:
    decisions = 0
    for field_name in _DECIDED_FIELDS:
        if review.get_active_decision(conn, incident_id, field_name) is not None:
            continue
        candidates = conn.execute(
            """
            SELECT claim_id, extraction_method, normalized_value FROM claims
            WHERE incident_id = ? AND field_name = ?
              AND NOT (extraction_method IN ('ai_assisted', 'ocr_assisted')
                       AND review_status != 'reviewed')
            ORDER BY claim_id
            """,
            (incident_id, field_name),
        ).fetchall()
        if not candidates:
            continue
        chosen = min(
            candidates,
            key=lambda c: (_METHOD_PRIORITY.get(c["extraction_method"], 9), c["claim_id"]),
        )
        distinct_values = {c["normalized_value"] for c in candidates}
        rationale = _BULK_RATIONALE
        if len(distinct_values) > 1:
            rationale += f" NOTE: {len(distinct_values)} distinct values were present."
        review.record_decision(
            conn,
            ClaimDecision(
                incident_id=incident_id,
                field_name=field_name,
                decision="accept_claim",
                selected_claim_id=chosen["claim_id"],
                rationale=rationale,
                reviewer=reviewer,
            ),
        )
        decisions += 1

    # Coordinates decided -> precision must be stated (publication rule 5).
    incident = conn.execute(
        "SELECT latitude, longitude, coordinate_precision FROM incidents WHERE incident_id = ?",
        (incident_id,),
    ).fetchone()
    if (
        incident["latitude"] is not None
        and incident["coordinate_precision"] is None
        and review.get_active_decision(conn, incident_id, "coordinate_precision") is None
    ):
        lat_decision = review.get_active_decision(conn, incident_id, "latitude")
        review.record_decision(
            conn,
            ClaimDecision(
                incident_id=incident_id,
                field_name="coordinate_precision",
                decision="manual_override",
                manual_value="facility_approximate",
                rationale=(
                    "Seed coordinates locate the facility/settlement, not a "
                    "verified exact point; conservatively categorized "
                    "facility_approximate. " + _BULK_RATIONALE
                ),
                rationale_claim_ids=[lat_decision["selected_claim_id"]],
                reviewer=reviewer,
            ),
        )
        decisions += 1
    return decisions


def _find_matching_incident(
    conn: sqlite3.Connection, province_code: str | None, iso_datetime: str | None
) -> int | None:
    """Blocking-key match (province + date ±3 days) against existing incidents,
    so a list bullet about an already-seeded incident becomes corroborating
    evidence instead of a duplicate record."""
    if not province_code or not iso_datetime:
        return None
    row = conn.execute(
        """
        SELECT incident_id FROM incidents
        WHERE province_code = ? AND incident_start_datetime IS NOT NULL
          AND ABS(julianday(incident_start_datetime) - julianday(?)) <= 3
        ORDER BY incident_id LIMIT 1
        """,
        (province_code, iso_datetime),
    ).fetchone()
    return int(row["incident_id"]) if row else None


def _ingest_list_article(
    conn: sqlite3.Connection,
    adapter: WikidataAdapter,
    list_doc_id: int,
    summary: IngestSummary,
    reviewer: str | None = None,
) -> dict[str, int]:
    """Per-bullet incident groups from the tr.wikipedia list article."""
    provinces = {e.code: e.label_tr for e in vocabularies.load_vocabulary("turkey_admin_areas")}
    groups: dict[str, list[ClaimDraft]] = defaultdict(list)
    for draft in adapter.parse(list_doc_id, conn):
        groups[draft.notes["group"]].append(draft)

    incident_ids: dict[str, int] = {}
    for key, drafts in sorted(groups.items()):
        fields = {
            d.field_name: d.normalized_value for d in drafts if d.claim_subject_type == "incident"
        }
        date = fields.get("incident_start_datetime")
        province = fields.get("province_code")
        marker = f"trlist:{key}"
        existing = conn.execute(
            "SELECT incident_id FROM incidents WHERE scope_rationale LIKE ?", (f"%{marker}%",)
        ).fetchone()
        if existing:
            incident_id = int(existing["incident_id"])
        else:
            matched = _find_matching_incident(conn, province, date)
            if matched is not None:
                incident_id = matched  # corroborating claims for a known incident
            else:
                title = fields.get("canonical_title_tr") or (
                    f"Maden kazası — {provinces.get(province or '', 'yeri belirsiz')}"
                    f" ({(date or '')[:10]})"
                )
                cur = conn.execute(
                    "INSERT INTO incidents (canonical_title_tr, canonical_title_tr_normalized, "
                    "incident_status, scope_rationale) VALUES (?, ?, 'scope_undetermined', ?)",
                    (
                        title,
                        normalize_tr(title),
                        f"Seeded from {marker} (tr.wikipedia incident list); descriptive "
                        "title is project-assigned; scope set after decisions.",
                    ),
                )
                incident_id = int(cur.lastrowid)
                summary.incidents_created += 1
        incident_ids[marker] = incident_id
        for draft in drafts:
            summary.claims_created += int(_insert_claim(conn, incident_id, list_doc_id, draft))
        conn.commit()
        # Decide now so the next bullet's blocking-key match sees this one.
        if reviewer:
            _decide_incident(conn, incident_id, reviewer, summary)
    return incident_ids


def _ingest_isig_aggregates(
    conn: sqlite3.Connection, list_doc_id: int, summary: IngestSummary
) -> None:
    """İSİG Meclisi annual miner-death totals -> aggregate context table.

    Aggregate context only: sector-wide work deaths from all causes, NOT
    comparable to the per-incident register (rule: raw counts are never
    labeled 'risk'; comparability_notes ship with every row)."""
    from pathlib import Path

    row = conn.execute(
        "SELECT local_raw_path FROM source_documents WHERE source_document_id = ?",
        (list_doc_id,),
    ).fetchone()
    wikitext = Path(row["local_raw_path"]).read_text(encoding="utf-8")
    for year, deaths in parse_isig_table(wikitext):
        exists = conn.execute(
            "SELECT 1 FROM aggregate_occupational_statistics "
            "WHERE reporting_institution = ? AND period_start = ?",
            ("İSİG Meclisi (via tr.wikipedia list article)", f"{year}-01-01"),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO aggregate_occupational_statistics (reporting_institution, "
            "period_start, period_end, numerator, unit, source_document_id, "
            "comparability_notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "İSİG Meclisi (via tr.wikipedia list article)",
                f"{year}-01-01",
                f"{year}-12-31",
                float(deaths),
                "deaths",
                list_doc_id,
                "Sector-wide miner work deaths, all causes, per İSİG annual reports "
                "as transcribed by the Wikipedia list. NOT comparable to the "
                "per-incident register (which covers listed accidents only) and "
                "never a rate: no exposure denominator.",
            ),
        )
    conn.commit()


#: (country, year-or-None, regex) — the per-100M-tonnes figures the list
#: article's lead cites (with references). Mechanical extraction; a row is
#: created only when its pattern matches the retrieved text.
_RATE_PATTERNS: tuple[tuple[str, int | None, str], ...] = (
    ("TR", 2000, r"2000 yılında 100 milyon ton başına (\d+)"),
    ("TR", 2008, r"Türkiye['’]de bu sayı (\d+) olarak kaydedilmiş"),
    ("CN", 2008, r"Çin\]{0,2}['’]de,? 2008 yılında 100 milyon ton başına düşen ölüm sayısı (\d+)"),
    ("CN", 2013, r"2013 yılında (\d+)['’][a-zçğıöşü]* düşmüştür"),
    ("US", None, r"100 milyon ton üretim başına (\d+) ile (\d+) kişi"),
)


def _ingest_rate_context(conn: sqlite3.Connection, list_doc_id: int) -> int:
    """Deaths-per-100M-tonnes figures (documented denominator) -> aggregates.

    Rule respected: rates only where the source states the exposure
    denominator (here: per 100 million tonnes of coal produced); every row
    carries comparability notes and the citing document."""
    import re
    from pathlib import Path

    row = conn.execute(
        "SELECT local_raw_path FROM source_documents WHERE source_document_id = ?",
        (list_doc_id,),
    ).fetchone()
    lead = Path(row["local_raw_path"]).read_text(encoding="utf-8").split("== Kazalar ==", 1)[0]
    created = 0
    for country, year, pattern in _RATE_PATTERNS:
        match = re.search(pattern, lead)
        if not match:
            continue
        values = [(None, match.group(1))]
        if match.lastindex and match.lastindex > 1:  # a range, e.g. US 1-6
            values = [("range_low", match.group(1)), ("range_high", match.group(2))]
        for version, value in values:
            period = f"{year}-01-01" if year else None
            exists = conn.execute(
                "SELECT 1 FROM aggregate_occupational_statistics WHERE unit = ? "
                "AND classification_code = ? AND period_start IS ? "
                "AND classification_version IS ?",
                ("deaths_per_100M_tonnes_coal", country, period, version),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                "INSERT INTO aggregate_occupational_statistics (reporting_institution, "
                "period_start, period_end, classification_system, classification_code, "
                "classification_version, numerator, denominator, unit, source_document_id, "
                "comparability_notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "Press figures via tr.wikipedia list article (cited therein)",
                    period,
                    f"{year}-12-31" if year else None,
                    "country",
                    country,
                    version,
                    float(value),
                    100_000_000.0,
                    "deaths_per_100M_tonnes_coal",
                    list_doc_id,
                    "Coal-mining deaths per 100 million tonnes produced, as cited by "
                    "press sources referenced in the Wikipedia list article"
                    + ("; year unspecified in source" if year is None else "")
                    + ". Methodologies differ across countries; indicative comparison "
                    "only, pending TÜİK/TKİ-based series (see docs/open_questions.md #18).",
                ),
            )
            created += 1
    conn.commit()
    return created


def _apply_classifications(conn: sqlite3.Connection, incident_id: int, reviewer: str) -> int:
    """Materialize classification claims into incident_classifications rows.

    Only mechanical extractions (or human-reviewed AI claims) qualify; codes
    are validated against the backing vocabulary; every row keeps its
    source_claim_id (cause_coding_protocol.md §2 — an event mechanism is not a
    root cause and not a statement of legal responsibility).
    """
    created = 0
    claims = conn.execute(
        """
        SELECT claim_id, field_name, normalized_value, assertion_status FROM claims
        WHERE incident_id = ? AND claim_subject_type = 'classification'
          AND NOT (extraction_method IN ('ai_assisted', 'ocr_assisted')
                   AND review_status != 'reviewed')
        ORDER BY claim_id
        """,
        (incident_id,),
    ).fetchall()
    for claim in claims:
        mapping = _CLASSIFICATION_SYSTEMS.get(claim["field_name"])
        if mapping is None or not claim["normalized_value"]:
            continue
        system, vocab_name = mapping
        code = claim["normalized_value"]
        try:
            validators.validate_classification_code(system, code)
        except validators.ValidationError:
            continue  # unknown code: leave as claim only, never invent a row
        exists = conn.execute(
            "SELECT 1 FROM incident_classifications WHERE incident_id = ? "
            "AND classification_system = ? AND classification_code = ?",
            (incident_id, system, code),
        ).fetchone()
        if exists:
            continue
        entry = next(e for e in vocabularies.load_vocabulary(vocab_name) if e.code == code)
        conn.execute(
            "INSERT INTO incident_classifications (incident_id, classification_system, "
            "classification_code, classification_label_tr, classification_label_en, "
            "assertion_status, source_claim_id, review_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                incident_id,
                system,
                code,
                entry.label_tr,
                entry.label_en,
                claim["assertion_status"],
                claim["claim_id"],
                "reviewed",
            ),
        )
        review.log_review_action(
            conn,
            reviewer,
            "classification_added",
            "incident",
            incident_id,
            after_summary=f"{system}={code} (claim {claim['claim_id']})",
            notes=_BULK_RATIONALE,
        )
        created += 1
    conn.commit()
    return created


def _apply_organization_roles(conn: sqlite3.Connection, incident_id: int, reviewer: str) -> int:
    """Operator claims -> incident_organization_roles rows.

    Corroboration threshold (editorial protocol §2): the role row is marked
    ``reviewed`` — and therefore exportable — only when >= 2 distinct source
    documents assert the same normalized company for this incident. A single
    assertion stays ``pending`` (recorded, never published). Assertion status
    is always ``reported``: an operator role is who ran the site, never a
    statement of legal responsibility.
    """
    from mining_accidents.ingest_sites import _upsert_organization

    claims = conn.execute(
        """
        SELECT claim_id, source_document_id, normalized_value FROM claims
        WHERE incident_id = ? AND claim_subject_type = 'organization'
          AND field_name = 'operator_organization' AND normalized_value IS NOT NULL
        ORDER BY claim_id
        """,
        (incident_id,),
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for claim in claims:
        groups.setdefault(normalize_tr(claim["normalized_value"]), []).append(claim)

    created = 0
    for _, group in sorted(groups.items()):
        corroborated = len({c["source_document_id"] for c in group}) >= 2
        status = "reviewed" if corroborated else "pending"
        org_id, _ = _upsert_organization(conn, group[0]["normalized_value"], None, None, None)
        existing = conn.execute(
            "SELECT incident_organization_role_id, review_status FROM "
            "incident_organization_roles WHERE incident_id = ? AND organization_id = ? "
            "AND role = 'operator'",
            (incident_id, org_id),
        ).fetchone()
        if existing:
            if corroborated and existing["review_status"] == "pending":
                conn.execute(
                    "UPDATE incident_organization_roles SET review_status = 'reviewed' "
                    "WHERE incident_organization_role_id = ?",
                    (existing["incident_organization_role_id"],),
                )
                review.log_review_action(
                    conn,
                    reviewer,
                    "organization_role_corroborated",
                    "incident",
                    incident_id,
                    after_summary=f"operator={group[0]['normalized_value']} (>=2 sources)",
                )
            continue
        conn.execute(
            "INSERT INTO incident_organization_roles (incident_id, organization_id, role, "
            "source_claim_id, assertion_status, review_status) VALUES (?, ?, 'operator', ?, "
            "'reported', ?)",
            (incident_id, org_id, group[0]["claim_id"], status),
        )
        if corroborated:
            review.log_review_action(
                conn,
                reviewer,
                "organization_role_added",
                "incident",
                incident_id,
                after_summary=f"operator={group[0]['normalized_value']} "
                f"({len(group)} claims, corroborated)",
                notes=_BULK_RATIONALE,
            )
        created += 1
    conn.commit()
    return created


def _set_scope(conn: sqlite3.Connection, incident_id: int, reviewer: str) -> None:
    row = conn.execute(
        "SELECT incident_start_datetime, fatalities_current, scope_rationale, incident_status "
        "FROM incidents WHERE incident_id = ?",
        (incident_id,),
    ).fetchone()
    if row["incident_status"] != "scope_undetermined":
        return
    date, fatalities = row["incident_start_datetime"], row["fatalities_current"]
    if date is None:
        return  # stays scope_undetermined until the date is decided
    if fatalities == 0:
        status, reason = "out_of_scope", "non-fatal incident (scope is fatal incidents)"
    elif fatalities is None:
        return  # cannot confirm fatal scope yet
    elif date < "2010-01-01":
        # Historic extension per project owner directive (2026-07-14): the
        # schema always accommodated pre-2010; they are now collected too.
        status, reason = "in_scope", "fatal mining incident (historic, pre-2010 extension)"
    else:
        status, reason = "in_scope", "fatal mining incident in Türkiye within 2010-present"
    conn.execute(
        "UPDATE incidents SET incident_status = ?, scope_rationale = scope_rationale || ' | ' || ? "
        "WHERE incident_id = ?",
        (status, reason, incident_id),
    )
    review.log_review_action(
        conn, reviewer, "set_scope", "incident", incident_id, after_summary=f"{status}: {reason}"
    )
    conn.commit()


def _publish_if_complete(
    conn: sqlite3.Connection, incident_id: int, reviewer: str
) -> str | list[str]:
    """Sign off complete in-scope records; return public id or blocker list."""
    row = conn.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
    blockers: list[str] = []
    if row["incident_status"] != "in_scope":
        blockers.append(f"incident_status={row['incident_status']}")
    for field_name in _PUBLICATION_FIELDS:
        decision = review.get_active_decision(conn, incident_id, field_name)
        if decision is None or decision["decision"] not in ("accept_claim", "manual_override"):
            blockers.append(f"undecided:{field_name}")
    if blockers:
        return blockers
    if not row["public_incident_id"]:
        review.assign_public_incident_id(conn, incident_id, actor=reviewer)
    conn.execute(
        "UPDATE incidents SET verification_status = 'reviewed', "
        "publication_status = 'publishable' WHERE incident_id = ?",
        (incident_id,),
    )
    review.log_review_action(
        conn,
        reviewer,
        "publication_signoff",
        "incident",
        incident_id,
        after_summary="verification_status=reviewed, publication_status=publishable",
        notes="Bulk sign-off per project-owner directive of 2026-07-13 (tier-3 seed).",
    )
    conn.commit()
    return conn.execute(
        "SELECT public_incident_id FROM incidents WHERE incident_id = ?", (incident_id,)
    ).fetchone()[0]
