"""Apply three reviewed date corrections, each through the decision machinery.

Role in the evidence flow: source document -> claim -> reviewer decision ->
canonical value. Nothing here writes a canonical field directly; every change
goes through ``review.record_decision``, which refuses a decision that does not
supersede the active one and refuses an unreviewed AI-assisted claim.

The three corrections, raised as open questions 32 and 33 and approved by the
project owner on 2026-10-16:

* **TR-MINE-2024-0004 (Şirvan, Siirt)** carried 23 October 2024 from the list
  article. Contemporary reporting places that accident, with the same toll and
  the same make-up of the dead, at Eti Bakır's Madenköy site on 23 November
  2023. The public identifier keeps its 2024 stem: identifiers are stable and
  already cited, and the year in one is an artefact of assignment order, not a
  claim about the event (open question 24).
* **TR-MINE-2005-0001 (Gediz, Kütahya)** carried April 2005 at month
  precision. Evrensel's court report gives 21 April 2005.
* **TR-MINE-2004-0001 (Bayat, Çorum)** carried August 2004 at month precision.
  The Chamber of Mining Engineers' own bulletin gives 9 August 2004.

Each title carries its date in the text, so the title moves with the date, as a
manual override citing the same claim.

Every excerpt is checked against the retrieved document before anything is
written, for PDFs as well as web pages. A quote that cannot be found verbatim
aborts the run.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from mining_accidents.database import get_connection, utc_now_iso
from mining_accidents.models import ClaimDecision
from mining_accidents.review import get_active_decision, log_review_action, record_decision

sys.path.insert(0, str(Path(__file__).resolve().parent))
from incident_operators import UA, _contains, _page_text  # noqa: E402

#: Documents these corrections rest on. A key already in source_documents is
#: reused by url; a new one is retrieved, hashed and registered here.
SOURCES: dict[str, dict[str, object]] = {
    "evrensel_sirvan2023": {
        "url": "https://www.evrensel.net/haber/504128/cengizin-madeninde-tesvikli-cinayet-siirtte-maden-ocaginda-gocuk-meydana-geldi-3-isci-hayatini-kaybetti",
        "organization": "Evrensel",
        "title": "Siirt'te maden ocağında göçük meydana geldi, 3 işçi hayatını kaybetti",
        "published": "2023-11-23",
        "tier": 3,
        "kind": "html",
    },
    "evrensel_gediz": {
        "url": "https://www.evrensel.net/haber/170084/madenci-aileleri-adalet-istiyor",
        "organization": "Evrensel",
        "title": "Madenci aileleri adalet istiyor",
        "published": "2006-02-10",
        "tier": 3,
        "kind": "html",
    },
    "mmo_corum2004": {
        "url": "https://api.maden.org.tr/uploads/portal/resimler/ekler/34e6bfcd358e25a_ek.pdf",
        "organization": "TMMOB Maden Mühendisleri Odası",
        "title": "Çorum'un Bayat ilçesi Karakaya köyü'nde grizu patlaması "
        "(Madencilik Bülteni, Eylül 2004)",
        "published": "2004-09-01",
        "tier": 2,
        "kind": "pdf",
    },
}

#: incident public id -> the correction to apply
CORRECTIONS: tuple[dict[str, object], ...] = (
    {
        "public_id": "TR-MINE-2024-0004",
        "source": "evrensel_sirvan2023",
        "datetime": "2023-11-23T00:00:00+03:00",
        "precision": "exact_date",
        "title": "Maden kazası, Siirt (2023-11-23)",
        "excerpt": "Siirt Valisi Kemal Kızılkaya, yaptığı açıklamada, maden ocağında 01.25 "
        "sularında göçük meydana geldiğini söyledi",
        "rationale": "The register carried 23 October 2024, taken from the Turkish Wikipedia "
        "list of mining accidents. The cited report, published 23 November 2023, describes "
        "the same accident: Şirvan in Siirt, a collapse at Eti Bakır's Madenköy copper site, "
        "three dead of whom two were engineers, two injured. Evrensel (15:08), sol haber "
        "(07:05) and Sözcü all published it on 23 November 2023, and the governor timed the "
        "collapse at about 01.25 that morning. Place, toll, the make-up of the dead and the "
        "day of the month all match the register's record, so this is one accident whose "
        "date was carried over wrongly. Precision stays exact_date rather than being "
        "sharpened to the reported time. The public identifier is unchanged: identifiers are "
        "stable and already cited (open question 24).",
    },
    {
        "public_id": "TR-MINE-2005-0001",
        "source": "evrensel_gediz",
        "datetime": "2005-04-21T00:00:00+03:00",
        "precision": "exact_date",
        "title": "Maden kazası, Kütahya (2005-04-21)",
        "excerpt": "Gediz Linyit İşletmesi'nin 7 Numaralı ocağında, 21 Nisan 2005'te meydana "
        "gelen grizu patlamasında, 1'i maden mühendisi 18 kişi hayatını kaybetmiş",
        "rationale": "The register carried April 2005 at month precision, because the list "
        "article gives only the month. The cited court report names the day, the pit and the "
        "toll already in the register (18 dead, one of them a mining engineer), so the month "
        "placeholder is replaced by the stated date and the precision raised to exact_date. "
        "No value is in conflict; this sharpens an imprecise one.",
    },
    {
        "public_id": "TR-MINE-2004-0001",
        "source": "mmo_corum2004",
        "datetime": "2004-08-09T00:00:00+03:00",
        "precision": "exact_date",
        "title": "Maden kazası, Çorum (2004-08-09)",
        "excerpt": "Çorum'un Bayat İlçesi Karakaya Köyü'nde faaliyet gösteren özel bir "
        "şirkete ait kömür ocağında, 9 Ağustos 2004 tarihinde meydana gelen grizu patlaması "
        "sonucu 3 işçi yaşamını yitirmiş",
        "rationale": "The register carried August 2004 at month precision from the list "
        "article. The Chamber of Mining Engineers' own bulletin, a Tier 2 source, names the "
        "day, the village and the toll already in the register (three dead), so the month "
        "placeholder is replaced by the stated date and the precision raised to exact_date. "
        "The bulletin names no company, so no organization role follows from it.",
    },
)


def _pdf_text(url: str) -> tuple[str, bytes]:
    """Retrieved bytes plus their text, so a quote can be checked against a PDF."""
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()
    with tempfile.TemporaryDirectory() as workdir:
        source = Path(workdir) / "doc.pdf"
        source.write_bytes(payload)
        target = Path(workdir) / "doc.txt"
        # No -layout: this bulletin sets two columns, and the layout mode
        # interleaves them line by line, cutting every sentence in half.
        subprocess.run(["pdftotext", str(source), str(target)], check=True, capture_output=True)
        text = target.read_text(encoding="utf-8", errors="replace")
        return text.replace("\u00ad", ""), payload  # drop soft hyphens from wrapped words


def _retrieve(key: str) -> tuple[str, str]:
    spec = SOURCES[key]
    if spec["kind"] == "pdf":
        text, payload = _pdf_text(str(spec["url"]))
        return text, hashlib.sha256(payload).hexdigest()
    text, payload = _page_text(str(spec["url"]))
    return text, hashlib.sha256(payload).hexdigest()


def _document(conn, key: str, digest: str) -> int:
    spec = SOURCES[key]
    url = str(spec["url"])
    row = conn.execute(
        "SELECT source_document_id FROM source_documents WHERE url = ? AND content_hash = ?",
        (url, digest),
    ).fetchone()
    if row:
        return int(row["source_document_id"])
    licence = (
        "Chamber publication, quoted as a short evidence excerpt only; not redistributed."
        if spec["tier"] == 2
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
            "bulletin" if spec["kind"] == "pdf" else "news_article",
            url,
            spec["published"],
            utc_now_iso(),
            digest,
            spec["tier"],
            licence,
            "Read for the date of the incident it reports.",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def _reviewed_claim(conn, reviewer: str, incident_id: int, document_id: int, **values) -> int:
    """An ai_assisted claim, created needs_review and reviewed as its own act."""
    cur = conn.execute(
        "INSERT INTO claims (incident_id, source_document_id, claim_subject_type, field_name, "
        "raw_value, normalized_value, short_evidence_excerpt, extraction_method, "
        "extractor_version, assertion_status, review_status, confidence_score) "
        "VALUES (?, ?, 'incident', ?, ?, ?, ?, 'ai_assisted', 'date_corrections', "
        "'reported', 'needs_review', 0.9)",
        (
            incident_id,
            document_id,
            values["field_name"],
            values["raw_value"],
            values["normalized_value"],
            values["excerpt"],
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="database/mining_accidents.sqlite")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    conn = get_connection(args.db_path)
    reviewer = args.reviewer

    texts: dict[str, tuple[str, str]] = {}
    for key in sorted({str(c["source"]) for c in CORRECTIONS}):
        text, digest = _retrieve(key)
        texts[key] = (text, digest)
        print(f"retrieved {key:22} {len(text):>7} ch  sha256 {digest[:12]}")

    failures = [
        f"{c['public_id']}: quote not found in {c['source']}"
        for c in CORRECTIONS
        if not _contains(texts[str(c["source"])][0], str(c["excerpt"]))
    ]
    if failures:
        print("\nquotes that could not be verified:")
        for line in failures:
            print("  !!", line)
        sys.exit(1)
    print(f"\nall {len(CORRECTIONS)} quotes verified verbatim\n")
    if args.dry_run:
        return

    for correction in CORRECTIONS:
        public_id = str(correction["public_id"])
        row = conn.execute(
            "SELECT incident_id, incident_start_datetime, date_precision, canonical_title_tr "
            "FROM incidents WHERE public_incident_id = ?",
            (public_id,),
        ).fetchone()
        if row is None:
            print(f"!! {public_id} is not in this database")
            continue
        incident_id = int(row["incident_id"])
        key = str(correction["source"])
        document_id = _document(conn, key, texts[key][1])
        print(
            f"{public_id}: {row['incident_start_datetime'][:10]} -> {correction['datetime'][:10]}"
        )

        date_claim = _reviewed_claim(
            conn,
            reviewer,
            incident_id,
            document_id,
            field_name="incident_start_datetime",
            raw_value=str(correction["datetime"])[:10],
            normalized_value=correction["datetime"],
            excerpt=correction["excerpt"],
        )
        precision_claim = _reviewed_claim(
            conn,
            reviewer,
            incident_id,
            document_id,
            field_name="date_precision",
            raw_value=correction["precision"],
            normalized_value=correction["precision"],
            excerpt=correction["excerpt"],
        )

        for field, claim_id in (
            ("incident_start_datetime", date_claim),
            ("date_precision", precision_claim),
        ):
            active = get_active_decision(conn, incident_id, field)
            if active is not None and str(active["selected_claim_id"]) == str(claim_id):
                continue
            record_decision(
                conn,
                ClaimDecision(
                    incident_id=incident_id,
                    field_name=field,
                    selected_claim_id=claim_id,
                    decision="accept_claim",
                    rationale=str(correction["rationale"]),
                    rationale_claim_ids=[date_claim],
                    reviewer=reviewer,
                    decision_date=utc_now_iso(),
                    supersedes_decision_id=int(active["decision_id"]) if active else None,
                ),
            )
            print(f"   decision recorded: {field}")

        if row["canonical_title_tr"] != correction["title"]:
            active = get_active_decision(conn, incident_id, "canonical_title_tr")
            record_decision(
                conn,
                ClaimDecision(
                    incident_id=incident_id,
                    field_name="canonical_title_tr",
                    decision="manual_override",
                    manual_value=str(correction["title"]),
                    rationale="The generated title carries the date in its text, so it moves "
                    "with the corrected date. " + str(correction["rationale"]),
                    rationale_claim_ids=[date_claim],
                    reviewer=reviewer,
                    decision_date=utc_now_iso(),
                    supersedes_decision_id=int(active["decision_id"]) if active else None,
                ),
            )
            print(f"   title: {row['canonical_title_tr']} -> {correction['title']}")
    conn.commit()
    print("\ndone")


if __name__ == "__main__":
    main()
