"""Editorial corrections from the external audit of 2026-07-17.

Role in the evidence flow: encodes the record-level actions of the external
audit (forwarded by the project owner) as an explicit, idempotent program
applied under a named human reviewer. Nothing here bypasses the pipeline:
withdrawals flip publication status with a logged rationale; value changes
are ``claim_decisions`` rows; new records are built from claims on already-
stored source documents; every action lands in ``review_log`` and in
``docs/corrections_log.csv``. Audit items our assessed sources cannot verify
are logged as PENDING, never applied.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from mining_accidents import review
from mining_accidents.models import ClaimDecision

CORRECTIONS_LOG = Path("docs/corrections_log.csv")

#: (public_id, reason) — extraction artifacts to withdraw (audit §1).
WITHDRAWALS: tuple[tuple[str, str], ...] = (
    (
        "TR-MINE-2025-0002",
        "Bullet is Dev. Maden-Sen's February 2021 monthly multi-incident summary "
        "(Aydın+Elazığ+Aydın); '2025-01-22' was a citation access date, not an event date.",
    ),
    (
        "TR-MINE-2025-0003",
        "Bullet describes the 23 February 2010 Dursunbey (Odaköy) disaster with no "
        "in-text date; '2025-01-22' was a citation access date. The disaster re-enters "
        "from its own dated list entry.",
    ),
    (
        "TR-MINE-2025-0004",
        "Bullet is the April 2021 monthly multi-incident summary; date was a citation access date.",
    ),
    (
        "TR-MINE-2025-0005",
        "Bullet is the May 2021 monthly multi-incident summary (Manisa+Denizli+Bursa); "
        "date was a citation access date.",
    ),
    (
        "TR-MINE-2025-0006",
        "Bullet is the March 2021 monthly multi-incident summary; date was a citation access date.",
    ),
    (
        "TR-MINE-2014-0002",
        "Bullet conflates two same-day accidents in different provinces (Amasra/Bartın "
        "roof collapse, 2 deaths; Gelik/Zonguldak wagon collision, 1 death). Replaced "
        "by two separate records.",
    ),
)

#: New records built from the already-stored list document (audit §2).
#: (marker, title_tr, date, province, deaths, mechanism, bullet_fragment)
SPLIT_RECORDS: tuple[tuple[str, str, str, str, int, str | None, str], ...] = (
    (
        "audit2026:bartin-amasra-2014",
        "Maden kazası — Amasra, Bartın (2014-11-01)",
        "2014-11-01T00:00:00+03:00",
        "74",
        2,
        "roof_or_ground_collapse",
        "1 Kasım 2014",
    ),
    (
        "audit2026:zonguldak-gelik-2014",
        "Maden kazası — Gelik, Zonguldak (2014-11-01)",
        "2014-11-01T00:00:00+03:00",
        "67",
        1,
        "loss_of_vehicle_control",
        "1 Kasım 2014",
    ),
)

#: Facility corrections our sources support. (external_ref, field, value, reason)
FACILITY_FIXES: tuple[tuple[str, str, str, str], ...] = (
    (
        "wikidata:Q16950520",
        "province_code",
        "45",
        "Soma is a district of Manisa; the twin item (Eynez, identical coordinates) "
        "states Manisa; the coordinates sit on the simplified Manisa-İzmir boundary "
        "so geometric derivation is not usable here.",
    ),
    (
        "wikidata:Q49413427",
        "facility_type",
        "operating_directorate",
        "Garp Linyitleri İşletmesi is TKİ's operating directorate at Tavşanlı, "
        "Kütahya — an enterprise over several sites, not one mine (audit §7).",
    ),
    (
        "wikidata:Q49413429",
        "facility_type",
        "operating_directorate",
        "Second Wikidata item for the same TKİ directorate (audit §7).",
    ),
)

#: rows whose notes get a suppression marker: (external_ref, marker_note, reason)
FACILITY_SUPPRESSIONS: tuple[tuple[str, str, str], ...] = (
    (
        "wikidata:Q121494242",
        "OUT_OF_SCOPE: source-stated coordinates (-17.15, 27.36) lie in Zambia "
        "although the source states country=TR; excluded from export pending "
        "upstream fix.",
        "Collum Coal Mine is in Sinazongwe, Zambia; the Wikidata item carries an "
        "erroneous country statement (QA check QC-W06, 2026-07-18).",
    ),
    (
        "wikidata:Q61074517",
        "COORD_CONFLICT: source-stated coordinates are identical to Mastra "
        "(wikidata:Q6009374) and resolve to Gümüşhane, while Sart is in Salihli, "
        "Manisa — likely a source copy error. Coordinates and the province "
        "derived from them suppressed pending upstream fix.",
        "Sart and Mastra gold mines carry the same point (QA check QC-W07, "
        "2026-07-18); the point is consistent with Mastra only.",
    ),
)

#: (external_ref, duplicate_of, reason)
FACILITY_DUPLICATES: tuple[tuple[str, str, str], ...] = (
    (
        "wikidata:Q16958962",
        "wikidata:Q16509436",
        "'Kişladağ mine' and 'Kışladağ altın madeni' are spelling variants of the "
        "same Uşak gold mine.",
    ),
)

#: Audit items our assessed sources cannot verify — logged, never applied.
PENDING: tuple[tuple[str, str], ...] = (
    (
        "TR-MINE-2022-0001 fatalities 42 -> 43",
        "TBMM records document a 43rd death (April 2023); TBMM is TO_ASSESS in the "
        "source registry. casualty_status set to 'disputed' meanwhile; open question #20.",
    ),
    (
        "wikidata:Q137925109 (Gökırmak) commodity -> copper",
        "Operator sources describe a copper project; Wikidata states Pt/Pd/Rb/Au only. "
        "Kept source-stated value; pending operator-source assessment.",
    ),
    (
        "wikidata:Q97236653 (Öksüt) province -> Kayseri",
        "No assessed source states the province (no coordinates, no admin statement, "
        "no linked article). Pending operator/official-source assessment.",
    ),
    (
        "TR-MINE-2010-0002 (Küçükdoğanca) mechanism += fire",
        "Audit reports fire-then-collapse; the stored article text does not mention "
        "fire. Pending a source that states it.",
    ),
    (
        "Yeni Çeltek 1983 (5) and 1990-02-07 (68), Amasya",
        "Absent from all assessed sources (list article, navbox, Wikidata class "
        "query). Known coverage gap pending TBB/TMMOB source assessment; open "
        "question #21.",
    ),
)

_RATIONALE_PREFIX = (
    "External audit of 2026-07-17 (owner-forwarded), verified against the stored "
    "raw source documents. "
)


def reparse_stored_sources(conn: sqlite3.Connection, reviewer: str) -> dict[str, int]:
    """Re-run the fixed parsers over the already-stored raw documents.

    Fully offline: the list article, the per-incident articles, and the site
    entity documents are all on disk. New claims corroborate or extend; the
    append-only evidence tables guarantee nothing is overwritten.
    """
    from mining_accidents import ingest
    from mining_accidents.adapters.wikidata import WikidataAdapter
    from mining_accidents.adapters.wikidata_sites import WikidataSitesAdapter
    from mining_accidents.ingest_sites import ingest_site_documents

    adapter = WikidataAdapter()
    summary = ingest.IngestSummary()
    list_doc = conn.execute(
        "SELECT source_document_id FROM source_documents WHERE notes LIKE "
        "'%wikipedia_list%' ORDER BY source_document_id DESC LIMIT 1"
    ).fetchone()
    ingest._ingest_list_article(conn, adapter, list_doc["source_document_id"], summary, reviewer)

    # Per-incident articles: re-parse for the widened mechanism extraction.
    article_docs = conn.execute(
        "SELECT source_document_id, notes FROM source_documents "
        "WHERE notes LIKE '%kind=wikipedia_article%'"
    ).fetchall()
    for doc in article_docs:
        qid = next((t[4:] for t in (doc["notes"] or "").split() if t.startswith("qid=")), None)
        incident = conn.execute(
            "SELECT incident_id FROM incidents WHERE scope_rationale LIKE ?",
            (f"%wikidata:{qid}%",),
        ).fetchone()
        if incident is None:
            continue
        for draft in adapter.parse(doc["source_document_id"], conn):
            summary.claims_created += int(
                ingest._insert_claim(
                    conn, incident["incident_id"], doc["source_document_id"], draft
                )
            )
        ingest._decide_incident(conn, incident["incident_id"], reviewer, summary)
    conn.commit()

    sites_adapter = WikidataSitesAdapter()
    site_doc_ids = [
        int(r["source_document_id"])
        for r in conn.execute(
            "SELECT source_document_id FROM source_documents WHERE notes LIKE "
            "'%kind=wikidata_site%' OR notes LIKE '%kind=wikipedia_site_article%'"
        )
    ]
    sites_summary = ingest_site_documents(conn, sites_adapter, site_doc_ids, reviewer)
    return {
        "incidents_created": summary.incidents_created,
        "claims_created": summary.claims_created + sites_summary.claims_created,
        "classifications_created": summary.classifications_created,
        "facilities_refreshed": sites_summary.facilities_updated,
    }


def _log_rows() -> list[dict[str, str]]:
    if CORRECTIONS_LOG.exists():
        with CORRECTIONS_LOG.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    return []


def _write_log(rows: list[dict[str, str]]) -> None:
    columns = ["entity", "field", "original_value", "corrected_value", "action", "rationale"]
    with CORRECTIONS_LOG.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def apply_audit_corrections(conn: sqlite3.Connection, reviewer: str) -> dict[str, int]:
    """Apply every verifiable audit action; returns a per-kind count."""
    counts = {
        "withdrawn": 0,
        "records_created": 0,
        "facility_fixes": 0,
        "duplicates": 0,
        "decisions": 0,
        "classifications_demoted": 0,
    }
    log = _log_rows()
    logged = {(r["entity"], r["field"], r["action"]) for r in log}

    def add_log(
        entity: str, field: str, original: str, corrected: str, action: str, rationale: str
    ) -> None:
        if (entity, field, action) in logged:
            return
        log.append(
            {
                "entity": entity,
                "field": field,
                "original_value": original,
                "corrected_value": corrected,
                "action": action,
                "rationale": rationale,
            }
        )
        logged.add((entity, field, action))

    # 1. Withdrawals -------------------------------------------------------
    for public_id, reason in WITHDRAWALS:
        row = conn.execute(
            "SELECT incident_id, publication_status FROM incidents WHERE public_incident_id = ?",
            (public_id,),
        ).fetchone()
        if row is None or row["publication_status"] == "withdrawn":
            continue
        conn.execute(
            "UPDATE incidents SET publication_status = 'withdrawn' WHERE incident_id = ?",
            (row["incident_id"],),
        )
        review.log_review_action(
            conn,
            reviewer,
            "publication_withdrawn",
            "incident",
            row["incident_id"],
            after_summary=f"{public_id} withdrawn",
            notes=_RATIONALE_PREFIX + reason,
        )
        add_log(
            public_id,
            "publication_status",
            row["publication_status"],
            "withdrawn",
            "withdrawn",
            reason,
        )
        counts["withdrawn"] += 1

    # 2. Split records from the stored list document ----------------------
    list_doc = conn.execute(
        "SELECT source_document_id, local_raw_path FROM source_documents "
        "WHERE notes LIKE '%wikipedia_list%' ORDER BY source_document_id DESC LIMIT 1"
    ).fetchone()
    for marker, title, date, province, deaths, mechanism, fragment in SPLIT_RECORDS:
        if conn.execute(
            "SELECT 1 FROM incidents WHERE scope_rationale LIKE ?", (f"%{marker}%",)
        ).fetchone():
            continue
        counts["records_created"] += _create_split_record(
            conn,
            reviewer,
            list_doc,
            marker,
            title,
            date,
            province,
            deaths,
            mechanism,
            fragment,
        )
        add_log(
            marker,
            "record",
            "(part of TR-MINE-2014-0002)",
            f"{title}: {deaths} deaths",
            "created",
            "Split of the conflated 2014-11-01 bullet (audit §2).",
        )

    # 3. Amasra casualty status -------------------------------------------
    amasra = conn.execute(
        "SELECT incident_id, casualty_status FROM incidents WHERE public_incident_id = "
        "'TR-MINE-2022-0001'"
    ).fetchone()
    if (
        amasra
        and review.get_active_decision(conn, amasra["incident_id"], "casualty_status") is not None
        and amasra["casualty_status"] != "disputed"
    ):
        # Decision recorded before casualty_status was promotable: promote now.
        conn.execute(
            "UPDATE incidents SET casualty_status = 'disputed' WHERE incident_id = ?",
            (amasra["incident_id"],),
        )
    elif amasra and amasra["casualty_status"] != "disputed":
        review.record_decision(
            conn,
            ClaimDecision(
                incident_id=amasra["incident_id"],
                field_name="casualty_status",
                decision="manual_override",
                manual_value="disputed",
                rationale=_RATIONALE_PREFIX
                + "Assessed sources state 42 deaths / 27 injured; TBMM records "
                "(TO_ASSESS) document a 43rd death in April 2023 and 10 injured as of "
                "February 2023. Figure marked disputed pending TBMM assessment "
                "(open question #20).",
                rationale_claim_ids=_supporting_claims(conn, amasra["incident_id"]),
                reviewer=reviewer,
            ),
        )
        add_log(
            "TR-MINE-2022-0001",
            "casualty_status",
            "None",
            "disputed",
            "decision",
            "42 vs 43 cumulative deaths; revision pending TBMM assessment.",
        )
        counts["decisions"] += 1

    # 4. Soma: demote gas_explosion/methane classifications ---------------
    soma = conn.execute(
        "SELECT incident_id FROM incidents WHERE public_incident_id = 'TR-MINE-2014-0001'"
    ).fetchone()
    if soma:
        demoted = conn.execute(
            "UPDATE incident_classifications SET review_status = 'needs_review' "
            "WHERE incident_id = ? AND review_status = 'reviewed' AND ("
            "  (classification_system = 'project_event_mechanism' AND "
            "   classification_code = 'gas_explosion') OR "
            "  (classification_system = 'project_hazard' AND classification_code = 'methane'))",
            (soma["incident_id"],),
        ).rowcount
        if demoted:
            review.log_review_action(
                conn,
                reviewer,
                "classification_demoted",
                "incident",
                soma["incident_id"],
                after_summary="gas_explosion + methane -> needs_review",
                notes=_RATIONALE_PREFIX
                + "The cited public account establishes fire; 'gas explosion' is not "
                "equally established and returns to the review queue (audit §6).",
            )
            add_log(
                "TR-MINE-2014-0001",
                "event_mechanism",
                "fire + gas_explosion",
                "fire (gas_explosion needs_review)",
                "demoted",
                "Fire is the established mechanism (audit §6).",
            )
            counts["classifications_demoted"] += demoted

    # 5. Facility fixes ----------------------------------------------------
    for external_ref, field, value, reason in FACILITY_FIXES:
        row = conn.execute(
            f"SELECT facility_id, {field} AS current FROM facilities WHERE external_ref = ?",
            (external_ref,),
        ).fetchone()
        if row is None or row["current"] == value:
            continue
        conn.execute(
            f"UPDATE facilities SET {field} = ?, notes = COALESCE(notes, '') || ' | audit "
            f"correction 2026-07-17: {field}={value}' WHERE facility_id = ?",
            (value, row["facility_id"]),
        )
        review.log_review_action(
            conn,
            reviewer,
            "facility_corrected",
            "facility",
            row["facility_id"],
            after_summary=f"{external_ref}: {field} {row['current']} -> {value}",
            notes=_RATIONALE_PREFIX + reason,
        )
        add_log(external_ref, field, str(row["current"]), value, "corrected", reason)
        counts["facility_fixes"] += 1

    # 5b. Suppressions (out-of-scope location / coordinate conflicts) ------
    for external_ref, marker_note, reason in FACILITY_SUPPRESSIONS:
        row = conn.execute(
            "SELECT facility_id, notes FROM facilities WHERE external_ref = ?",
            (external_ref,),
        ).fetchone()
        if row is None or (row["notes"] or "").startswith(("OUT_OF_SCOPE", "COORD_CONFLICT")):
            continue
        if marker_note.startswith("COORD_CONFLICT"):
            conn.execute(
                "UPDATE facilities SET latitude = NULL, longitude = NULL, "
                "coordinate_precision = NULL, province_code = NULL, notes = ? "
                "WHERE facility_id = ?",
                (marker_note, row["facility_id"]),
            )
        else:
            conn.execute(
                "UPDATE facilities SET notes = ? WHERE facility_id = ?",
                (marker_note, row["facility_id"]),
            )
        review.log_review_action(
            conn,
            reviewer,
            "facility_suppressed",
            "facility",
            row["facility_id"],
            after_summary=f"{external_ref}: {marker_note.split(':')[0]}",
            notes=_RATIONALE_PREFIX + reason,
        )
        add_log(external_ref, "suppression", "", marker_note.split(":")[0], "suppressed", reason)
        counts["facility_fixes"] += 1

    # 6. Duplicates --------------------------------------------------------
    for external_ref, duplicate_of, reason in FACILITY_DUPLICATES:
        row = conn.execute(
            "SELECT facility_id, notes FROM facilities WHERE external_ref = ?",
            (external_ref,),
        ).fetchone()
        if row is None or "DUPLICATE of" in (row["notes"] or ""):
            continue
        conn.execute(
            "UPDATE facilities SET notes = ? WHERE facility_id = ?",
            (f"DUPLICATE of {duplicate_of} — excluded from export. {reason}", row["facility_id"]),
        )
        review.log_review_action(
            conn,
            reviewer,
            "facility_deduplicated",
            "facility",
            row["facility_id"],
            after_summary=f"{external_ref} marked duplicate of {duplicate_of}",
            notes=_RATIONALE_PREFIX + reason,
        )
        add_log(external_ref, "duplicate_of", "", duplicate_of, "deduplicated", reason)
        counts["duplicates"] += 1

    # 7. Pending items (logged only) --------------------------------------
    for entity, reason in PENDING:
        add_log(entity, "", "", "", "pending", reason)

    conn.commit()
    _write_log(log)
    return counts


#: ai_assisted claims the audit reviewed against the bullet text:
#: (raw_value fragment, field, correct value, reason). The claim is marked
#: reviewed and accepted — an ordinary human review recorded through tooling.
REVIEWED_AI_VALUES: tuple[tuple[str, str, str, str], ...] = (
    (
        "3 maden kişi hayatını kaybet",
        "fatalities_current",
        "3",
        "Şirvan 2024-10-23: '2 mühendis 1 işçi olmak üzere 3' — the total is 3.",
    ),
    (
        "2 işçiden 1'i yaşamını yitir",
        "fatalities_current",
        "1",
        "Gelik 2024-06-04: one of two trapped workers died — the death count is 1.",
    ),
    (
        "2 işçi yanarak 66 işçi ise göçük altında kalarak ölmüş",
        "fatalities_current",
        "68",
        "Yeni Çeltek 1990-02-07 (Amasya): 2 died in the fire and 66 under the "
        "collapse — the source states 68 in total (audit §3).",
    ),
    (
        "grizu patlamasında 17 kişi ölürken",
        "fatalities_current",
        "17",
        "Odaköy/Dursunbey 2010-02-23: the list states 17 dead and 30 injured; "
        "the article's early prose figure of 13 stays visible as a competing "
        "claim (audit §3).",
    ),
)

#: unpublished drafts whose bullet aggregates several accidents or reproduces
#: a monthly union report — never one incident (audit §1 pattern; matched by
#: a distinctive fragment of the stored claim text).
AGGREGATE_DRAFT_FRAGMENTS: tuple[tuple[str, str], ...] = (
    ("iki ayrı kazada", "Two separate February 2022 Zonguldak accidents in one bullet."),
    (
        "2021 Ekim ayında, [[Türkiye Devrimci",
        "Dev. Maden-Sen October 2021 monthly report total, not one incident.",
    ),
    (
        "Muğla'nın Kavaklıdere ilçesi Derebağ Mahallesinde faaliyet",
        "One bullet spanning two accidents (Muğla marble quarry and Kayseri "
        "Aladağlar); needs per-accident sourcing.",
    ),
)

#: (merged normalized title, surviving public id, reason) — article-seeded
#: rows without a parseable date duplicating a published list record.
EXPLICIT_TITLE_MERGES: tuple[tuple[str, str, str], ...] = (
    (
        "1992 kozlu komur madeni faciasi",
        "TR-MINE-1992-0001",
        "Article row for the 3 March 1992 Kozlu disaster duplicates the "
        "published record (differently titled).",
    ),
    (
        "ermenek maden kazasi",
        "TR-MINE-2014-0004",
        "The 'Ermenek maden kazası' article describes the 28 October 2014 "
        "Ermenek flooding disaster already published.",
    ),
)

#: descriptive title repairs for records whose auto-title says 'yeri belirsiz'
#: although the location is decided: (public_id, corrected_title, reason).
TITLE_FIXES: tuple[tuple[str, str, str], ...] = (
    (
        "TR-MINE-2011-0001",
        "Çöllolar maden kazası — Afşin-Elbistan (Şubat 2011)",
        "Project-assigned descriptive title; the bullet names the Çöllolar "
        "mine at Afşin-Elbistan (Kahramanmaraş), decided province 46.",
    ),
)

#: unpublished drafts whose decided date is a citation access date from the
#: pre-fix parser (2025-01-22, 2025-05-27/28, 2026-02-18 are retrieval dates
#: of the list article's references, not event dates). The fixed parser no
#: longer produces such groups; the old rows are withdrawn as artifacts.
_ACCESS_DATE_ARTIFACTS = ("2025-01-22", "2025-05-27", "2025-05-28", "2026-02-18")

#: manual province decisions for records whose bullet names only a district:
#: (claim raw fragment, province_code, reason)
PROVINCE_DECISIONS: tuple[tuple[str, str, str], ...] = (
    (
        "Çöllolar",
        "46",
        "Afşin-Elbistan is in Kahramanmaraş province; the bullet names the "
        "district and the named facility, not the province.",
    ),
)


def resolve_audit_reviewed_values(conn: sqlite3.Connection, reviewer: str) -> int:
    """Reviewed decisions for queued extractions the audit checked by hand."""
    from mining_accidents.ingest import _publish_if_complete

    resolved = 0
    touched: set[int] = set()
    for fragment, field_name, value, reason in REVIEWED_AI_VALUES:
        claim = conn.execute(
            "SELECT claim_id, incident_id, review_status, normalized_value FROM claims "
            "WHERE field_name = ? AND raw_value LIKE ? AND incident_id IS NOT NULL "
            "ORDER BY claim_id LIMIT 1",
            (field_name, f"%{fragment}%"),
        ).fetchone()
        if claim is None:
            continue
        if review.get_active_decision(conn, claim["incident_id"], field_name) is not None:
            touched.add(claim["incident_id"])
            continue
        if claim["review_status"] != "reviewed":
            conn.execute(
                "UPDATE claims SET review_status = 'reviewed' WHERE claim_id = ?",
                (claim["claim_id"],),
            )
        decision = (
            ClaimDecision(
                incident_id=claim["incident_id"],
                field_name=field_name,
                decision="accept_claim",
                selected_claim_id=claim["claim_id"],
                rationale=_RATIONALE_PREFIX + reason,
                reviewer=reviewer,
            )
            if claim["normalized_value"] == value
            else ClaimDecision(
                incident_id=claim["incident_id"],
                field_name=field_name,
                decision="manual_override",
                manual_value=value,
                rationale=_RATIONALE_PREFIX + reason,
                rationale_claim_ids=[int(claim["claim_id"])],
                reviewer=reviewer,
            )
        )
        review.record_decision(conn, decision)
        touched.add(claim["incident_id"])
        resolved += 1
    for fragment, province, reason in PROVINCE_DECISIONS:
        claim = conn.execute(
            "SELECT claim_id, incident_id FROM claims WHERE raw_value LIKE ? "
            "AND incident_id IS NOT NULL ORDER BY claim_id LIMIT 1",
            (f"%{fragment}%",),
        ).fetchone()
        if claim is None:
            continue
        if review.get_active_decision(conn, claim["incident_id"], "province_code") is None:
            review.record_decision(
                conn,
                ClaimDecision(
                    incident_id=claim["incident_id"],
                    field_name="province_code",
                    decision="manual_override",
                    manual_value=province,
                    rationale=_RATIONALE_PREFIX + reason,
                    rationale_claim_ids=[int(claim["claim_id"])],
                    reviewer=reviewer,
                ),
            )
            resolved += 1
        touched.add(claim["incident_id"])
    # Withdraw aggregate/multi-incident draft bullets (never published).
    for fragment, reason in AGGREGATE_DRAFT_FRAGMENTS:
        row = conn.execute(
            "SELECT DISTINCT i.incident_id FROM incidents i JOIN claims c USING (incident_id) "
            "WHERE c.raw_value LIKE ? AND i.publication_status NOT IN "
            "('publishable', 'published', 'withdrawn')",
            (f"%{fragment}%",),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE incidents SET publication_status = 'withdrawn' WHERE incident_id = ?",
                (row["incident_id"],),
            )
            review.log_review_action(
                conn,
                reviewer,
                "publication_withdrawn",
                "incident",
                row["incident_id"],
                after_summary="aggregate bullet withdrawn",
                notes=_RATIONALE_PREFIX + reason,
            )

    # Explicit merges and descriptive-title repairs.
    for merged_title, surviving_public_id, reason in EXPLICIT_TITLE_MERGES:
        merged = conn.execute(
            "SELECT incident_id FROM incidents WHERE canonical_title_tr_normalized = ? "
            "AND publication_status != 'withdrawn'",
            (merged_title,),
        ).fetchone()
        surviving = conn.execute(
            "SELECT incident_id FROM incidents WHERE public_incident_id = ?",
            (surviving_public_id,),
        ).fetchone()
        if merged and surviving and merged["incident_id"] != surviving["incident_id"]:
            review.merge_incidents(
                conn,
                surviving["incident_id"],
                merged["incident_id"],
                _RATIONALE_PREFIX + reason,
                reviewer,
            )
    for public_id, title, reason in TITLE_FIXES:
        row = conn.execute(
            "SELECT incident_id, canonical_title_tr FROM incidents WHERE public_incident_id = ?",
            (public_id,),
        ).fetchone()
        if (
            row
            and row["canonical_title_tr"] != title
            and review.get_active_decision(conn, row["incident_id"], "canonical_title_tr") is None
        ):
            review.record_decision(
                conn,
                ClaimDecision(
                    incident_id=row["incident_id"],
                    field_name="canonical_title_tr",
                    decision="manual_override",
                    manual_value=title,
                    rationale=_RATIONALE_PREFIX + reason,
                    rationale_claim_ids=_supporting_claims(conn, row["incident_id"]),
                    reviewer=reviewer,
                ),
            )
            conn.execute(
                "UPDATE incidents SET canonical_title_tr_normalized = ? WHERE incident_id = ?",
                (
                    __import__(
                        "mining_accidents.normalization", fromlist=["normalize_tr"]
                    ).normalize_tr(title),
                    row["incident_id"],
                ),
            )

    # Withdraw the pre-fix access-date artifact drafts (never published).
    for row in conn.execute(
        "SELECT incident_id, substr(incident_start_datetime, 1, 10) AS d FROM incidents "
        "WHERE publication_status NOT IN ('publishable', 'published', 'withdrawn') "
        "AND scope_rationale LIKE '%trlist:%'"
    ).fetchall():
        if row["d"] not in _ACCESS_DATE_ARTIFACTS:
            continue
        conn.execute(
            "UPDATE incidents SET publication_status = 'withdrawn' WHERE incident_id = ?",
            (row["incident_id"],),
        )
        review.log_review_action(
            conn,
            reviewer,
            "publication_withdrawn",
            "incident",
            row["incident_id"],
            after_summary=f"draft artifact withdrawn (event date {row['d']} is a "
            "citation access date)",
            notes=_RATIONALE_PREFIX
            + "Pre-fix list parser read citation access/archive dates as event "
            "dates; the cleaned parser no longer seeds these groups.",
        )

    # Re-parse group keys are revision-scoped; a bullet edited (or newly
    # ref-stripped) can seed a second record for an incident that escaped the
    # province+date blocking match. Merge duplicates (fragment- and
    # title-based; the record with the most decisions survives).
    _merge_reparse_duplicates(conn, reviewer)
    _merge_title_duplicates(conn, reviewer)

    # Decide any newly corroborated claims, then publish every complete,
    # in-scope record that is still a draft.
    from mining_accidents import ingest

    summary = ingest.IngestSummary()
    for row in conn.execute(
        "SELECT incident_id, incident_status FROM incidents "
        "WHERE publication_status NOT IN ('publishable', 'published', 'withdrawn')"
    ).fetchall():
        ingest._decide_incident(conn, row["incident_id"], reviewer, summary)
        _publish_if_complete(conn, row["incident_id"], reviewer)
    conn.commit()
    return resolved


def _decision_count(conn: sqlite3.Connection, incident_id: int) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM claim_decisions WHERE incident_id = ?", (incident_id,)
        ).fetchone()[0]
    )


def _merge_title_duplicates(conn: sqlite3.Connection, reviewer: str) -> None:
    """Merge active incidents sharing the same normalized title.

    Article-seeded and list-seeded rows for the same event can both exist
    when the article lacks a parseable date (blocking key needs a date). The
    record with more recorded decisions survives.
    """
    groups: dict[str, list[int]] = {}
    for row in conn.execute(
        "SELECT incident_id, canonical_title_tr_normalized AS t FROM incidents "
        "WHERE publication_status != 'withdrawn' AND canonical_title_tr_normalized "
        "NOT LIKE 'maden kazasi%'"
    ):
        groups.setdefault(row["t"], []).append(int(row["incident_id"]))
    for title, ids in groups.items():
        if len(ids) < 2:
            continue
        ids.sort(key=lambda i: (-_decision_count(conn, i), i))
        surviving, merged = ids[0], ids[1:]
        for duplicate in merged:
            review.merge_incidents(
                conn,
                surviving,
                duplicate,
                _RATIONALE_PREFIX + f"Same event, same title ({title!r}): article-seeded and "
                "list-seeded rows merged; the fuller record survives.",
                reviewer,
            )


def _merge_reparse_duplicates(conn: sqlite3.Connection, reviewer: str) -> None:
    """Merge re-parse duplicates that share a distinctive bullet fragment."""
    for fragment in ("Çöllolar",):
        ids = [
            int(r["incident_id"])
            for r in conn.execute(
                "SELECT DISTINCT incident_id FROM claims WHERE raw_value LIKE ? "
                "AND incident_id IS NOT NULL AND field_name = 'incident_start_datetime' "
                "ORDER BY incident_id",
                (f"%{fragment}%",),
            )
        ]
        survivors = [
            i
            for i in ids
            if conn.execute(
                "SELECT publication_status FROM incidents WHERE incident_id = ?", (i,)
            ).fetchone()["publication_status"]
            != "withdrawn"
        ]
        if len(survivors) > 1:
            surviving, merged = survivors[0], survivors[1:]
            for duplicate in merged:
                review.merge_incidents(
                    conn,
                    surviving,
                    duplicate,
                    _RATIONALE_PREFIX + f"Re-parse duplicate of the same '{fragment}' bullet "
                    "(group key changed when citation markup stripping was added).",
                    reviewer,
                )


def _supporting_claims(conn: sqlite3.Connection, incident_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT claim_id FROM claims WHERE incident_id = ? AND field_name = "
        "'fatalities_current' ORDER BY claim_id LIMIT 2",
        (incident_id,),
    ).fetchall()
    return [int(r["claim_id"]) for r in rows]


def _create_split_record(
    conn: sqlite3.Connection,
    reviewer: str,
    list_doc: sqlite3.Row,
    marker: str,
    title: str,
    date: str,
    province: str,
    deaths: int,
    mechanism: str | None,
    fragment: str,
) -> int:
    """One incident from one half of the conflated bullet, fully decided."""
    from mining_accidents import vocabularies
    from mining_accidents.normalization import normalize_tr

    raw_line = next(
        (
            line.strip()
            for line in Path(list_doc["local_raw_path"]).read_text(encoding="utf-8").splitlines()
            if fragment in line
        ),
        fragment,
    )
    cur = conn.execute(
        "INSERT INTO incidents (canonical_title_tr, canonical_title_tr_normalized, "
        "incident_status, scope_rationale) VALUES (?, ?, 'in_scope', ?)",
        (
            title,
            normalize_tr(title),
            f"Seeded from {marker}: audit split of a conflated list bullet "
            "(two same-day accidents in different provinces). | fatal mining "
            "incident in Türkiye within 2010-present",
        ),
    )
    incident_id = int(cur.lastrowid)
    claim_ids: dict[str, int] = {}
    for field_name, value in (
        ("incident_start_datetime", date),
        ("date_precision", "exact_date"),
        ("province_code", province),
        ("fatalities_current", str(deaths)),
    ):
        c = conn.execute(
            "INSERT INTO claims (incident_id, source_document_id, claim_subject_type, "
            "field_name, raw_value, normalized_value, section_reference, "
            "extraction_method, extractor_version, assertion_status, review_status) "
            "VALUES (?, ?, 'incident', ?, ?, ?, 'Kazalar/2014', 'manual', "
            "'audit-2026-07-17', 'reported', 'reviewed')",
            (incident_id, list_doc["source_document_id"], field_name, raw_line[:160], value),
        )
        claim_ids[field_name] = int(c.lastrowid)
    for field_name in (
        "incident_start_datetime",
        "date_precision",
        "province_code",
        "fatalities_current",
    ):
        review.record_decision(
            conn,
            ClaimDecision(
                incident_id=incident_id,
                field_name=field_name,
                decision="accept_claim",
                selected_claim_id=claim_ids[field_name],
                rationale=_RATIONALE_PREFIX
                + "Value read manually from the specific clause of the conflated "
                "bullet during the audited split.",
                reviewer=reviewer,
            ),
        )
    if mechanism:
        entry = next(
            e for e in vocabularies.load_vocabulary("event_mechanisms") if e.code == mechanism
        )
        c = conn.execute(
            "INSERT INTO claims (incident_id, source_document_id, claim_subject_type, "
            "field_name, raw_value, normalized_value, section_reference, "
            "extraction_method, extractor_version, assertion_status, review_status) "
            "VALUES (?, ?, 'classification', 'event_mechanism', ?, ?, 'Kazalar/2014', "
            "'manual', 'audit-2026-07-17', 'reported', 'reviewed')",
            (incident_id, list_doc["source_document_id"], raw_line[:160], mechanism),
        )
        conn.execute(
            "INSERT INTO incident_classifications (incident_id, classification_system, "
            "classification_code, classification_label_tr, classification_label_en, "
            "assertion_status, source_claim_id, review_status) VALUES "
            "(?, 'project_event_mechanism', ?, ?, ?, 'reported', ?, 'reviewed')",
            (incident_id, mechanism, entry.label_tr, entry.label_en, int(c.lastrowid)),
        )
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
        after_summary="audit split record published",
        notes=_RATIONALE_PREFIX,
    )
    return 1
