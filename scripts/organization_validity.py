"""Stop the register naming a company that did not exist yet.

Role in the evidence flow: source document -> claim -> reviewer act on the
`valid_at_incident_date` flag of an organization role. No canonical incident
value changes here, so no `claim_decisions` row is involved.

What was wrong. Both 1983 records named Türkiye Taşkömürü Kurumu and flagged
the role as valid at the incident date. TTK did not exist on either date. Its
own legal page records that Ereğli Kömürleri İşletme Müessesesi (EKİ), a
müessese under Türkiye Kömür İşletmeleri (TKİ), was abolished by law 2929 of
19 October 1983 and TTK formed in its place, gathering the Armutçuk, Kozlu,
Üzülmez, Karadon and Amasra establishments; its history page dates the founding
decree to 10 October 1983. The Armutçuk accident was 7 March 1983 and the
Kozlu-İhsaniye accident 10 or 11 April 1983, both months earlier.

What this does. It marks those two roles as not valid at the incident date,
citing TTK's own pages, and leaves the rows in place: TTK does run those pits,
which is a true present-day association and worth keeping, just not a statement
about who was running them on the day.

What this deliberately does not do. It does not record EKİ as the operator.
TTK's page establishes that EKİ held the Armutçuk establishment until October
1983, which makes EKİ the likely operator, but no assessed source says so of
that day. The inference is filed as a claim that stays `needs_review` for a
reviewer to settle (open question 39), because guessing an operator is the
error this script exists to undo.

It also adds, without deciding anything:
  * the TTK chronology's date for Kozlu-İhsaniye, 11 April, against the 10 April
    the register publishes from the Wikipedia list. Both claims stand and no
    decision selects between them. The same TTK page is internally inconsistent
    on other dates, so being official does not make it right (open question 40).
  * a corroborating toll and an event mechanism for Armutçuk, which the page
    states as a gas and dust explosion that killed 103.

Every quote is checked against the live document before anything is written. A
quote that cannot be found verbatim aborts the run. Re-running adds only what
is missing, so this file is the standing table of what TTK's pages support.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import unicodedata
from html import unescape
from pathlib import Path

from mining_accidents.adapters.wikidata import _http_get
from mining_accidents.database import get_connection
from mining_accidents.provenance import sha256_bytes
from mining_accidents.review import log_review_action

SOURCES: dict[str, dict[str, str]] = {
    "ttk_yasal": {
        "url": "https://www.taskomuru.gov.tr/ttk/yasal-duzenleme/",
        "title": "Türkiye Taşkömürü Kurumu — Yasal Düzenleme",
        "document_type": "institutional_legal_history",
    },
    "ttk_tarihce": {
        "url": "https://www.taskomuru.gov.tr/ttk/tarihce/",
        "title": "Türkiye Taşkömürü Kurumu — Tarihçe",
        "document_type": "institutional_history",
    },
}

#: What each quote is used for. Checked verbatim before anything is written.
QUOTES: dict[str, str] = {
    "eki_abolished": (
        "1983 tarih ve 2929 sayılı kanunla kaldırılarak yerine Armutçuk, Kozlu, "
        "Üzülmez, Karadon ve Amasra Taşkömürü İşletme Müesseselerini bünyesinde "
        "toplayan (TTK) Türkiye Taşkömürü Kurumu oluşturulmuştur."
    ),
    "ttk_founded": (
        "96 sayılı KHK ile Türkiye Taşkömürü Kurumu Genel Müdürlüğü kuruldu (10 Ekim)."
    ),
    "armutcuk": "Armutçuk Ocağında, gaz ve toz patlaması oldu, 103 kişi öldü (7 Mart).",
    "kozlu": "Kozlu-İhsaniye Ocağında patlama oldu, 10 kişi öldü (11 Nisan).",
}
QUOTE_SOURCE = {
    "eki_abolished": "ttk_yasal",
    "ttk_founded": "ttk_tarihce",
    "armutcuk": "ttk_tarihce",
    "kozlu": "ttk_tarihce",
}

#: The roles to correct: (public id, organization name fragment, role).
CORRECTIONS: tuple[tuple[str, str, str], ...] = (
    ("TR-MINE-1983-0001", "Türkiye Taşkömürü Kurumu", "operator"),
    ("TR-MINE-1983-0002", "Türkiye Taşkömürü Kurumu", "owner"),
)

_QUOTES_MAP = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
_SPACE = re.compile(r"\s+")


def _key(value: str) -> str:
    """Comparison form: quote style, spacing and composition all normalised."""
    folded = unicodedata.normalize("NFC", value).translate(_QUOTES_MAP)
    return _SPACE.sub(" ", folded).strip()


def _plain_text(raw: bytes) -> str:
    markup = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw.decode("utf-8", "replace"))
    return _SPACE.sub(" ", unescape(re.sub(r"(?s)<[^>]+>", " ", markup)))


def _fetch(raw_dir: Path) -> dict[str, tuple[str, str]]:
    """Retrieve each page once; return {key: (text, sha256)}."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, tuple[str, str]] = {}
    for key, spec in SOURCES.items():
        payload = _http_get(spec["url"], {}, accept="text/html")
        digest = sha256_bytes(payload)
        path = raw_dir / f"{key}-{digest[:12]}.html"
        if not path.exists():
            path.write_bytes(payload)
        out[key] = (_plain_text(payload), digest)
        print(f"   retrieved {spec['url']} ({len(payload)} bytes, sha256 {digest[:12]})")
    return out


def _verify(texts: dict[str, tuple[str, str]]) -> None:
    """Every quote must appear verbatim, or nothing is written."""
    missing = [
        name
        for name, quote in QUOTES.items()
        if _key(quote) not in _key(texts[QUOTE_SOURCE[name]][0])
    ]
    if missing:
        for name in missing:
            print(f"   NOT FOUND in {SOURCES[QUOTE_SOURCE[name]]['url']}: {QUOTES[name]!r}")
        sys.exit("aborted: a quote could not be verified against the retrieved document")
    print(f"   all {len(QUOTES)} quotes verified verbatim")


def _document(conn: sqlite3.Connection, key: str, digest: str, raw_path: str) -> int:
    spec = SOURCES[key]
    row = conn.execute(
        "SELECT source_document_id FROM source_documents WHERE url = ? AND content_hash = ?",
        (spec["url"], digest),
    ).fetchone()
    if row:
        return int(row["source_document_id"])
    cur = conn.execute(
        "INSERT INTO source_documents (source_organization, title, document_type, url, "
        "retrieved_at, language, content_hash, local_raw_path, licence_or_reuse_notes, "
        "attribution_required, source_tier, access_status, notes) "
        "VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'), 'tr', ?, ?, ?, 1, 1, "
        "'open', ?)",
        (
            "Türkiye Taşkömürü Kurumu",
            spec["title"],
            spec["document_type"],
            spec["url"],
            digest,
            raw_path,
            "No reuse statement is published on the site. Short quotation as evidence with "
            "attribution; no page is redistributed.",
            "kind=ttk_institutional_record",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def _incident(conn: sqlite3.Connection, public_id: str) -> int:
    row = conn.execute(
        "SELECT incident_id FROM incidents WHERE public_incident_id = ?", (public_id,)
    ).fetchone()
    if row is None:
        sys.exit(f"aborted: {public_id} is not in this database")
    return int(row["incident_id"])


def _claim(
    conn: sqlite3.Connection,
    *,
    incident_id: int | None,
    document_id: int,
    subject_type: str,
    subject_id: int | None,
    field_name: str,
    value: str,
    excerpt: str,
    assertion: str = "reported",
) -> int | None:
    """Insert one claim at `needs_review`; None when an identical one exists.

    Constraint 5: these are ai_assisted readings of prose, so they are created
    `needs_review` and only a reviewer act can move them on. Nothing here
    promotes one, because every value this script adds is either a conflict or
    an inference for a human to settle.
    """
    exists = conn.execute(
        "SELECT claim_id FROM claims WHERE source_document_id = ? AND field_name = ? "
        "AND IFNULL(incident_id, -1) = IFNULL(?, -1) AND IFNULL(normalized_value, '') = ?",
        (document_id, field_name, incident_id, value),
    ).fetchone()
    if exists:
        return None
    cur = conn.execute(
        "INSERT INTO claims (incident_id, source_document_id, claim_subject_type, "
        "claim_subject_id, field_name, raw_value, normalized_value, short_evidence_excerpt, "
        "extraction_method, extractor_version, assertion_status, review_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ai_assisted', 'organization_validity', ?, "
        "'needs_review')",
        (
            incident_id,
            document_id,
            subject_type,
            subject_id,
            field_name,
            excerpt,
            value,
            excerpt,
            assertion,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="database/mining_accidents.sqlite")
    parser.add_argument("--reviewer", required=True, help="Human authorising the correction.")
    parser.add_argument("--raw-dir", default="data/raw/ttk")
    args = parser.parse_args()

    print("1. retrieving TTK's own pages")
    texts = _fetch(Path(args.raw_dir))
    print("2. verifying quotes")
    _verify(texts)

    conn = get_connection(args.db_path)
    try:
        docs = {
            key: _document(
                conn,
                key,
                digest,
                str(Path(args.raw_dir) / f"{key}-{digest[:12]}.html"),
            )
            for key, (_, digest) in texts.items()
        }
        print("3. recording what the pages state")
        ttk = conn.execute(
            "SELECT organization_id FROM organizations WHERE organization_name_tr = ?",
            ("Türkiye Taşkömürü Kurumu",),
        ).fetchone()
        if ttk is None:
            sys.exit("aborted: Türkiye Taşkömürü Kurumu is not in this database")
        ttk_id = int(ttk["organization_id"])

        added = 0
        for field, value, quote, doc_key in (
            ("organization_valid_from", "1983-10-10", QUOTES["ttk_founded"], "ttk_tarihce"),
            (
                "predecessor_organization",
                "Ereğli Kömürleri İşletme Müessesesi (EKİ)",
                QUOTES["eki_abolished"],
                "ttk_yasal",
            ),
        ):
            if _claim(
                conn,
                incident_id=None,
                document_id=docs[doc_key],
                subject_type="organization",
                subject_id=ttk_id,
                field_name=field,
                value=value,
                excerpt=quote,
            ):
                added += 1
                print(f"   claim: TTK {field} = {value}")

        armutcuk = _incident(conn, "TR-MINE-1983-0001")
        kozlu = _incident(conn, "TR-MINE-1983-0002")
        for incident_id, field, value, quote in (
            (armutcuk, "fatalities_current", "103", QUOTES["armutcuk"]),
            (armutcuk, "event_mechanism", "gas_or_dust_explosion", QUOTES["armutcuk"]),
            (kozlu, "incident_start_datetime", "1983-04-11T00:00:00+03:00", QUOTES["kozlu"]),
            (kozlu, "fatalities_current", "10", QUOTES["kozlu"]),
        ):
            if _claim(
                conn,
                incident_id=incident_id,
                document_id=docs["ttk_tarihce"],
                subject_type="incident",
                subject_id=None,
                field_name=field,
                value=value,
                excerpt=quote,
            ):
                added += 1
                print(f"   claim: incident {incident_id} {field} = {value}")

        # The inference this script refuses to act on, filed for a reviewer.
        if _claim(
            conn,
            incident_id=armutcuk,
            document_id=docs["ttk_yasal"],
            subject_type="organization",
            subject_id=None,
            field_name="operator_organization_candidate",
            value="Ereğli Kömürleri İşletme Müessesesi (EKİ)",
            excerpt=QUOTES["eki_abolished"],
            assertion="unknown",
        ):
            added += 1
            print("   claim: Armutçuk operator candidate = EKİ (inference, awaiting review)")

        print("4. correcting the validity flags")
        fixed = 0
        for public_id, org_name, role in CORRECTIONS:
            row = conn.execute(
                "SELECT r.incident_organization_role_id AS rid, r.valid_at_incident_date AS v "
                "FROM incident_organization_roles r "
                "JOIN incidents i ON i.incident_id = r.incident_id "
                "JOIN organizations o ON o.organization_id = r.organization_id "
                "WHERE i.public_incident_id = ? AND o.organization_name_tr = ? AND r.role = ?",
                (public_id, org_name, role),
            ).fetchone()
            if row is None:
                print(f"   {public_id}: no {role} role for {org_name}, nothing to correct")
                continue
            if row["v"] == 0:
                print(f"   {public_id}: {role} already marked not valid at the incident date")
                continue
            conn.execute(
                "UPDATE incident_organization_roles SET valid_at_incident_date = 0, "
                "notes = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                "WHERE incident_organization_role_id = ?",
                (
                    "TTK did not exist on the date of this incident: its own pages date the "
                    "founding decree to 10 October 1983 and record EKİ, under TKİ, as what it "
                    "replaced by law 2929 of 19 October 1983. The association with the pit is "
                    "kept because TTK does run it, but it is not a statement about who was "
                    "running it on the day. No operator is recorded for that day, because no "
                    "assessed source names one.",
                    row["rid"],
                ),
            )
            conn.commit()
            log_review_action(
                conn,
                args.reviewer,
                "organization_role_validity_corrected",
                "incident_organization_role",
                int(row["rid"]),
                before_summary=f"{public_id} {role} {org_name} valid_at_incident_date=1",
                after_summary=f"{public_id} {role} {org_name} valid_at_incident_date=0",
                notes="TTK postdates the incident. Quotes checked verbatim against the "
                "retrieved TTK pages, whose sha256 is recorded on the document rows.",
            )
            fixed += 1
            print(f"   {public_id}: {role} {org_name} marked not valid at the incident date")

        print(f"\n{added} claim(s) added, {fixed} role flag(s) corrected.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
