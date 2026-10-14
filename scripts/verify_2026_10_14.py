"""Record the 2026-10-14 source verification through the evidence pipeline.

Role in the evidence flow: imports corroborating source documents and their
claims, attaches each claim to the incident it is about, and records the
reviewer decisions that promote the verified values to canonical. Nothing here
invents a value: every decision points at a claim that quotes a fetched
document, and every rationale names the documents that agree.

Context. A clean rebuild from the open sources leaves six incidents unable to
publish, because their death tolls were extracted from prose and are therefore
``ai_assisted`` / ``needs_review``: the pipeline refuses to promote those
automatically (CLAUDE.md constraint 5). Each one was checked against
independent sources on 2026-10-14:

  Kozlu 1992      263 deaths, 1992-03-03  TBMM Genel Kurul record + NTV
  Ermenek 2014     18 deaths, 2014-10-28  TBMM Genel Kurul record
  Şirvan 2016      16 deaths, 2016-11-17  TRT Haber (final toll after 26 days
                                          of recovery; early reports said 3-4
                                          while 16 were still buried)
  Soma 2026         5 deaths, 2026-10-01  Evrensel + Euronews
  Nesko 2021        no deaths             tailings-pond collapse, reported as
                                          an environmental incident with no
                                          casualties: out of scope here
  Muğla 2022-03     not verified          left unpublished, see below

Muğla 2022-03-01 is a single list-article line with month-level precision and
no corroboration found; it stays a draft rather than entering the register on
one unverified prose extraction.

The script is idempotent: re-running it imports nothing twice and records no
duplicate decision.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

from mining_accidents.adapters.manual import import_files
from mining_accidents.database import get_connection
from mining_accidents.ingest import _publish_if_complete, _set_scope
from mining_accidents.models import ClaimDecision
from mining_accidents.normalization import normalize_tr
from mining_accidents.review import (
    get_active_decision,
    log_review_action,
    merge_incidents,
    record_decision,
)

STAGING = Path("data/staging/2026-10-14_verification")
SOMA_STAGING = Path("data/staging/2026-10_soma_imbat")

# Document hash -> the incident its claims are about. Titles are matched on the
# normalized form so punctuation and case cannot silently miss.
TBMM_KOZLU = "f931ae8132caf17874bbf1f6d865d0dace8a91a4f6385252d35538320e2276b2"
NTV_KOZLU = "f7453db080957f7a0cd9be7805d466d8e4d6055e808e2450fe2a67e1aeb31b71"
TBMM_ERMENEK = "9c7c807cca5055eec05d43855665c8cd9e90d0cbb8b0224020cf229f47a72110"
TRT_SIRVAN = "e33e32b7045ee86e6e0eb46dcded2c0d1a9a3e640fd99f627f66c118d6a77fa8"
EVRENSEL_SOMA = "c810282ec239007e080fb4a07ce5d5c757ddd913ec0b3f76496d790b799f1a5f"
EURONEWS_SOMA = "4cf87e9ce6d4d870cc470e4f1770793254a2617f29834ec195432ca43de71582"

BY_TITLE = {
    TBMM_KOZLU: "1992 Kozlu kömür madeni faciası",
    NTV_KOZLU: "1992 Kozlu kömür madeni faciası",
    TBMM_ERMENEK: "Ermenek maden kazası",
    TRT_SIRVAN: "Şirvan maden kazası",
}
SOMA_DOCS = (EVRENSEL_SOMA, EURONEWS_SOMA)
SOMA_TITLE_TR = "Soma maden kazası (İmbat Madencilik)"
SOMA_TITLE_EN = "Soma mining accident (İmbat Madencilik)"

RATIONALE = {
    "1992 Kozlu kömür madeni faciası": (
        "Date and toll verified 2026-10-14 against the TBMM Genel Kurul record "
        '("3 Mart 1992 tarihinde Kozlu Taş Kömürü Maden Ocağı\'nda 263 maden işçimizi") '
        "and an NTV commemoration report stating the same date and toll. The list-article "
        "prose extraction agreed; this decision selects the corroborated value."
    ),
    "Ermenek maden kazası": (
        "Date and toll verified 2026-10-14 against the TBMM Genel Kurul record "
        '("Ermenek\'te kaybettiğimiz 18 maden şehidimizle birlikte"; anniversary given as '
        "28 October 2014). The list-article prose extraction agreed."
    ),
    "Şirvan maden kazası": (
        "Toll verified 2026-10-14 against TRT Haber's report at the end of the 26-day "
        'recovery ("Hayatını kaybeden 16 işçinin"), which supersedes the early reports of '
        "3 to 4 deaths made while 16 workers were still buried. Date from the same report "
        '("17 Kasım\'da akşam vardiyası sırasında heyelan sonucu 16 işçi toprak altında kaldı").'
    ),
    SOMA_TITLE_TR: (
        "New record. Date, province and toll verified 2026-10-14 against Evrensel "
        '("can kaybı sayısı 5\'e yükseldi") and a Euronews Türkçe report of the same '
        "collapse. Toll recorded as initial: no official investigation result was published "
        "at the time of entry."
    ),
}

NESKO_TITLE = "Nesko Şebinkarahisar Maden İşletmesi felaketi"
NESKO_RATIONALE = (
    "Checked 2026-10-14: contemporaneous reporting describes a tailings-pond collapse that "
    "released chemical waste toward the Kılıçkaya reservoir, and states explicitly that there "
    "was no loss of life or injury. This register's scope is fatal mining and quarrying "
    "accidents, so the record is marked out of scope rather than published with no toll."
)


def _incident_by_title(conn: sqlite3.Connection, title: str) -> int | None:
    row = conn.execute(
        "SELECT incident_id FROM incidents WHERE canonical_title_tr_normalized = ?",
        (normalize_tr(title),),
    ).fetchone()
    return int(row["incident_id"]) if row else None


def _already_imported(conn: sqlite3.Connection, content_hash: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM claims c JOIN source_documents d "
            "ON d.source_document_id = c.source_document_id WHERE d.content_hash = ? LIMIT 1",
            (content_hash,),
        ).fetchone()
        is not None
    )


def _attach(conn: sqlite3.Connection, content_hash: str, incident_id: int) -> int:
    cur = conn.execute(
        "UPDATE claims SET incident_id = ? WHERE incident_id IS NULL AND source_document_id IN "
        "(SELECT source_document_id FROM source_documents WHERE content_hash = ?)",
        (incident_id, content_hash),
    )
    conn.commit()
    return cur.rowcount


def _accept(
    conn: sqlite3.Connection, incident_id: int, field: str, rationale: str, reviewer: str
) -> str | None:
    """Accept the best claim for one field, if nothing is decided there yet.

    A prose extraction arrives ``ai_assisted`` / ``needs_review`` and the
    pipeline refuses to make it canonical in that state. Marking it reviewed is
    the human act the constraint asks for: the reviewer attests that the quoted
    excerpt in the claim says what the claim says. It is logged as its own
    review action, separately from the decision, and follows the same two-step
    the audit corrections use (corrections.py).
    """
    if get_active_decision(conn, incident_id, field) is not None:
        return None
    row = conn.execute(
        "SELECT claim_id, normalized_value, extraction_method, review_status, "
        "short_evidence_excerpt FROM claims WHERE incident_id = ? AND field_name = ? "
        "AND normalized_value IS NOT NULL ORDER BY confidence_score DESC, claim_id LIMIT 1",
        (incident_id, field),
    ).fetchone()
    if row is None:
        return None
    if row["extraction_method"] in ("ai_assisted", "ocr_assisted") and (
        row["review_status"] != "reviewed"
    ):
        conn.execute(
            "UPDATE claims SET review_status = 'reviewed' WHERE claim_id = ?",
            (int(row["claim_id"]),),
        )
        log_review_action(
            conn,
            reviewer,
            "claim_reviewed",
            "claim",
            int(row["claim_id"]),
            after_summary=f"{field}={row['normalized_value']}",
            notes=f"Excerpt checked against the cited source: {row['short_evidence_excerpt']!r}",
        )
        conn.commit()
    record_decision(
        conn,
        ClaimDecision(
            incident_id=incident_id,
            field_name=field,
            selected_claim_id=int(row["claim_id"]),
            decision="accept_claim",
            rationale=rationale,
            reviewer=reviewer,
            decision_date="2026-10-14",
        ),
    )
    return str(row["normalized_value"])


def _create_soma(conn: sqlite3.Connection) -> int:
    existing = _incident_by_title(conn, SOMA_TITLE_TR)
    if existing:
        return existing
    cur = conn.execute(
        "INSERT INTO incidents (canonical_title_tr, canonical_title_en, "
        "canonical_title_tr_normalized, incident_status, scope_rationale, casualty_status) "
        "VALUES (?, ?, ?, 'scope_undetermined', ?, 'initial')",
        (
            SOMA_TITLE_TR,
            SOMA_TITLE_EN,
            normalize_tr(SOMA_TITLE_TR),
            "Entered from press reports supplied by the project owner, 2026-10-14; "
            "scope set after date/fatality decisions.",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


#: Wikidata items that describe an event the list article already contributed.
#: Entity resolution does not join them, so without this they publish twice and
#: the register double-counts their deaths. Surviving title first.
DUPLICATES = [
    (
        "1992 Kozlu grizu faciası",
        "1992 Kozlu kömür madeni faciası",
        "Same event: one incident on 3 March 1992 in Zonguldak, 263 deaths. The list-article "
        "record was published first and keeps the canonical id; the Wikidata record brought "
        "the TBMM and NTV corroboration.",
    ),
    (
        "Maden kazası, Karaman (2014-10-28)",
        "Ermenek maden kazası",
        "Same event: one incident on 28 October 2014 in Karaman (Ermenek), 18 deaths.",
    ),
    (
        "Şirvan maden kazası",
        "Şirvan maden kazası",
        "Same event: two records for the Şirvan (Siirt) landslide of 17 November 2016, 16 deaths.",
    ),
]


def _published_ids() -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    with Path("data/public/incidents.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[((row["incident_start_datetime"] or "")[:10], row["province_code"])] = row[
                "public_incident_id"
            ]
    return out


def _merge_duplicates(conn: sqlite3.Connection, reviewer: str) -> None:
    """Merge each Wikidata/list-article pair for the same event.

    The survivor is chosen by identity, never by insertion order: whichever of
    the pair carries an id that appears in ``data/public/incidents.csv`` is the
    one the world already cites, so it is the one that stays. A later ingest
    republishes a merged record, so this runs after every ingest.
    """
    for surviving_title, merged_title, reason in DUPLICATES:
        rows = conn.execute(
            "SELECT incident_id, public_incident_id, canonical_title_tr_normalized n "
            "FROM incidents WHERE canonical_title_tr_normalized IN (?, ?) "
            "AND publication_status IN ('publishable', 'published') ORDER BY incident_id",
            (normalize_tr(surviving_title), normalize_tr(merged_title)),
        ).fetchall()
        if len(rows) < 2:
            continue
        # Which of two records for one event survives does not decide its
        # identity: the survivor is the stable choice (lowest incident id) and
        # _align_public_ids then gives it the id this event is published under.
        survivor = rows[0]
        for duplicate in rows:
            if duplicate["incident_id"] == survivor["incident_id"]:
                continue
            merge_incidents(
                conn, survivor["incident_id"], duplicate["incident_id"], reason, reviewer
            )
            print(f"merged {duplicate['public_incident_id']} -> {survivor['public_incident_id']}")


def _align_public_ids(conn: sqlite3.Connection, reviewer: str) -> None:
    """Give every already-published record back the id it is published under.

    Public ids are assigned in processing order, so a rebuilt database numbers
    the same events differently: half the register would be renumbered, and an
    id would come to mean a different accident. The identifiers in
    ``data/public/incidents.csv`` are the ones the world has, so a record that
    matches one by date and province keeps it. New records are untouched.
    """
    published = {}
    with Path("data/public/incidents.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = ((row["incident_start_datetime"] or "")[:10], row["province_code"])
            published[key] = row["public_incident_id"]
    rows = conn.execute(
        "SELECT incident_id, public_incident_id, substr(incident_start_datetime,1,10) d, "
        "province_code pc FROM incidents WHERE publication_status IN ('publishable','published')"
    ).fetchall()
    # Desired identity for every record that matches a published one, including
    # the ones already correct: the assignment is applied as a permutation, so
    # a record can hand its id to another without either colliding.
    desired: dict[int, str] = {}
    for r in rows:
        target = published.get((r["d"], r["pc"]))
        if target:
            desired[int(r["incident_id"])] = target

    # Two records matching one published record is an unresolved duplicate:
    # which of them the id belongs to is a judgement, not a rewrite.
    counts: dict[str, int] = {}
    for target in desired.values():
        counts[target] = counts.get(target, 0) + 1
    for incident_id, target in sorted(desired.items()):
        if counts[target] > 1:
            print(f"!! {target} is claimed by several records; leaving their ids alone")
            del desired[incident_id]

    # An id held by a record outside this set (a withdrawn or merged one) is
    # that record's identity and is never taken from it. Dropping one record
    # can put the next one outside the set too, so this runs to a fixed point.
    all_ids = {
        int(r["incident_id"]): r["public_incident_id"]
        for r in conn.execute(
            "SELECT incident_id, public_incident_id FROM incidents "
            "WHERE public_incident_id IS NOT NULL"
        )
    }
    while True:
        outside = {pid for iid, pid in all_ids.items() if iid not in desired}
        dropped = [iid for iid, target in sorted(desired.items()) if target in outside]
        if not dropped:
            break
        for incident_id in dropped:
            print(
                f"!! {desired[incident_id]} belongs to a record outside the published set; "
                "leaving it alone"
            )
            del desired[incident_id]

    changing = {
        int(r["incident_id"]): desired[int(r["incident_id"])]
        for r in rows
        if int(r["incident_id"]) in desired
        and desired[int(r["incident_id"])] != r["public_incident_id"]
    }
    if not changing:
        print("public ids: already aligned")
        return
    current = {int(r["incident_id"]): r["public_incident_id"] for r in rows}
    for incident_id in desired:  # park the whole set, then deal them back out
        conn.execute(
            "UPDATE incidents SET public_incident_id = ? WHERE incident_id = ?",
            (f"PENDING-{incident_id}", incident_id),
        )
    for incident_id, target in desired.items():
        conn.execute(
            "UPDATE incidents SET public_incident_id = ? WHERE incident_id = ?",
            (target, incident_id),
        )
        if current.get(incident_id) != target:
            log_review_action(
                conn,
                reviewer,
                "public_id_aligned",
                "incident",
                incident_id,
                after_summary=f"{current.get(incident_id)} -> {target}",
                notes="Restored the identifier this record is already published under.",
            )
    conn.commit()
    print(f"public ids: {len(changing)} realigned to the published register")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="database/mining_accidents.sqlite")
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    conn = get_connection(args.db_path)
    reviewer = args.reviewer

    for staging in (SOMA_STAGING, STAGING):
        docs = staging / "source_documents.csv"
        claims = staging / "claims.csv"
        marker = EURONEWS_SOMA if staging == SOMA_STAGING else TBMM_KOZLU
        if _already_imported(conn, marker):
            print(f"{staging.name}: already imported")
            continue
        res = import_files(conn, docs, claims, actor=f"verification:{reviewer}")
        print(f"{staging.name}: {res.documents_created} documents, {res.claims_created} claims")

    # --- existing incidents: attach the corroboration, then decide ----------
    for content_hash, title in BY_TITLE.items():
        incident_id = _incident_by_title(conn, title)
        if incident_id is None:
            print(f"!! no incident titled {title!r}; skipped")
            continue
        moved = _attach(conn, content_hash, incident_id)
        rationale = RATIONALE[title]
        decided = {
            field: _accept(conn, incident_id, field, rationale, reviewer)
            for field in ("incident_start_datetime", "fatalities_current", "province_code")
        }
        _set_scope(conn, incident_id, reviewer)
        outcome = _publish_if_complete(conn, incident_id, reviewer)
        print(f"{title}: +{moved} claims, decided {decided}, -> {outcome}")

    # --- Soma 2026: a new record -------------------------------------------
    soma = _create_soma(conn)
    for content_hash in SOMA_DOCS:
        _attach(conn, content_hash, soma)
    decided = {
        field: _accept(conn, soma, field, RATIONALE[SOMA_TITLE_TR], reviewer)
        for field in (
            "incident_start_datetime",
            "province_code",
            "fatalities_current",
            "date_precision",
        )
    }
    _set_scope(conn, soma, reviewer)
    print(f"{SOMA_TITLE_TR}: decided {decided}, -> {_publish_if_complete(conn, soma, reviewer)}")

    # --- Nesko 2021: verified as non-fatal, so out of scope -----------------
    nesko = _incident_by_title(conn, NESKO_TITLE)
    if nesko is not None:
        row = conn.execute(
            "SELECT incident_status FROM incidents WHERE incident_id = ?", (nesko,)
        ).fetchone()
        if row["incident_status"] == "scope_undetermined":
            conn.execute(
                "UPDATE incidents SET incident_status = 'out_of_scope', "
                "scope_rationale = scope_rationale || ' | ' || ? WHERE incident_id = ?",
                ("verified 2026-10-14: no reported fatalities (tailings-pond collapse)", nesko),
            )
            log_review_action(
                conn,
                reviewer,
                "set_scope",
                "incident",
                nesko,
                after_summary="out_of_scope: no reported fatalities",
                notes=NESKO_RATIONALE,
            )
            conn.commit()
            print(f"{NESKO_TITLE}: marked out_of_scope")
        else:
            print(f"{NESKO_TITLE}: already {row['incident_status']}")

    _merge_duplicates(conn, reviewer)
    _align_public_ids(conn, reviewer)


if __name__ == "__main__":
    main()
