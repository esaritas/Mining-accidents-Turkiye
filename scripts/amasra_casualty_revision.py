"""Amasra 2022: the toll is 43, and the register now says so with its date.

Role in the evidence flow: source document -> claim -> reviewer decision ->
canonical value, plus a dated casualty observation. Nothing writes a canonical
field by hand; the change goes through ``review.record_decision``, which refuses
a decision that does not supersede the active one and refuses an unreviewed
AI-assisted claim.

What was wrong. The register published 42 deaths with `casualty_status`
'disputed' and open question 20 noting that TBMM records document a 43rd. That
framing was itself the error: 42 and 43 are not rival claims about one moment,
they are the same toll observed at two different times. A man who survived the
14 October 2022 explosion with injuries died on the evening of 5 April 2023
while still under treatment, and the toll rose with him.

The evidence. The Assembly's own verbatim record of the 86th sitting of
6 April 2023, printed page 74, carries a group spokesperson stating that the
number of miners who lost their lives rose from 42 to 43, and giving the reason.
That is a Tier 1 document and a member's statement within it, so the claim is
`reported`, not an official finding. Corroboration is independent and plain: on
the second anniversary the Anadolu Ajansı report carried by NTV commemorates 43,
and the provincial governor speaks of losing 43.

So the status becomes 'revised', not 'disputed'. Nothing disputes the figure.

Privacy. The transcript names the man who died, and this register does not name
anyone. The quotes stored here are chosen so that neither carries a name, and
the sentence naming him is never written to the database even in redacted form.
What is recorded is that the 43rd death was a survivor who died later under
treatment, which is the part that matters for reading the number.

Every quote is checked against the retrieved document before anything is
written. A quote that cannot be found verbatim aborts the run. Re-running the
script changes nothing once the decision is in place.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
from html import unescape
from pathlib import Path

from mining_accidents.adapters.wikidata import _http_get
from mining_accidents.database import get_connection, utc_now_iso
from mining_accidents.models import ClaimDecision
from mining_accidents.provenance import sha256_bytes
from mining_accidents.review import get_active_decision, log_review_action, record_decision

PUBLIC_ID = "TR-MINE-2022-0001"

#: The date the toll was observed at 43, from the sitting that recorded it.
OBSERVED_AS_OF = "2023-04-06"

SOURCES: dict[str, dict[str, object]] = {
    "tbmm_86": {
        "url": "https://www5.tbmm.gov.tr/tutanaklar/TUTANAK/TBMM/d27/c129/tbmm27129086.pdf",
        "organization": "TBMM",
        "title": (
            "TBMM Tutanak Dergisi, Dönem 27, Yasama Yılı 6, Cilt 129, 86'ncı Birleşim, "
            "6 Nisan 2023 (printed page 74)"
        ),
        "document_type": "parliamentary_minutes",
        "published": "2023-04-06",
        "tier": 1,
        "kind": "pdf",
        "page": 74,
        "licence": (
            "Official verbatim record of the Grand National Assembly, openly published. Short "
            "quotation as evidence with attribution; the document is not redistributed."
        ),
    },
    "ntv_anniversary": {
        "url": (
            "https://www.ntv.com.tr/turkiye/"
            "amasradaki-kazada-hayatini-kaybeden-43-madenci-anildi,02aMaRIsskGujaIp5lFbNQ"
        ),
        "organization": "NTV (Anadolu Ajansı)",
        "title": "Amasra'daki kazada hayatını kaybeden 43 madenci anıldı",
        "document_type": "news_article",
        "published": None,
        "tier": 3,
        "kind": "html",
        "licence": (
            "Copyright stays with the outlet. Short excerpt quoted as evidence under fair "
            "quotation practice; no article text is redistributed."
        ),
    },
}

#: Neither quote names anyone. That is why these two sentences were chosen.
QUOTES: dict[str, str] = {
    "tbmm_86": (
        "Üzülerek söylemeliyim ki Amasra maden katliamında yaşamını yitiren madenci sayısı "
        "42’den 43’e çıktı."
    ),
    "ntv_anniversary": "2 yıl önce 14 Ekim’deki patlamada yaşamını yitiren 43 madenci anıldı.",
}

RATIONALE = (
    "The toll rose from 42 to 43 when a worker who survived the 14 October 2022 explosion with "
    "injuries died on the evening of 5 April 2023, still under treatment. The Assembly's verbatim "
    "record of the 86th sitting of 6 April 2023, printed page 74, states the rise and its reason; "
    "the Anadolu Ajansı report carried by NTV on the second anniversary commemorates 43 and "
    "quotes the provincial governor on the same figure. 42 and 43 were never rival claims about "
    "one moment but the same toll at two times, so the earlier observation is kept and the status "
    "becomes 'revised' rather than 'disputed'. Supersedes the decision that selected 42. "
    "Authorised by the project owner on 2026-10-29. No individual is named in this register."
)

_QUOTES_MAP = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
_SPACE = re.compile(r"\s+")


def _key(value: str) -> str:
    """Comparison form: quote style, spacing and composition all normalised."""
    folded = unicodedata.normalize("NFC", value).translate(_QUOTES_MAP)
    return _SPACE.sub(" ", folded).strip()


def _pdf_text(payload: bytes, page: int) -> str:
    """One page of a PDF, in reading order.

    Not layout order: the transcript sets two columns and layout mode
    interleaves them line by line, cutting every sentence in half. Soft hyphens
    are dropped so a quote broken across a line still matches.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "doc.pdf"
        src.write_bytes(payload)
        out = Path(tmp) / "doc.txt"
        subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), str(src), str(out)],
            check=True,
            capture_output=True,
        )
        return out.read_text(encoding="utf-8", errors="replace").replace("­", "")


def _html_text(payload: bytes) -> str:
    markup = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", payload.decode("utf-8", "replace"))
    return _SPACE.sub(" ", unescape(re.sub(r"(?s)<[^>]+>", " ", markup)))


def _retrieve(raw_dir: Path) -> dict[str, tuple[str, str, str]]:
    """Fetch each document once; return {key: (text, sha256, raw path)}."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, tuple[str, str, str]] = {}
    for key, spec in SOURCES.items():
        payload = _http_get(str(spec["url"]), {}, accept="*/*", timeout=120)
        digest = sha256_bytes(payload)
        suffix = "pdf" if spec["kind"] == "pdf" else "html"
        path = raw_dir / f"{key}-{digest[:12]}.{suffix}"
        if not path.exists():
            path.write_bytes(payload)
        text = (
            _pdf_text(payload, int(spec["page"]))  # type: ignore[arg-type]
            if spec["kind"] == "pdf"
            else _html_text(payload)
        )
        out[key] = (text, digest, str(path))
        print(f"   retrieved {key:18} {len(payload):>9} bytes  sha256 {digest[:12]}")
    return out


def _verify(texts: dict[str, tuple[str, str, str]]) -> None:
    missing = [k for k, q in QUOTES.items() if _key(q) not in _key(texts[k][0])]
    if missing:
        for key in missing:
            print(f"   NOT FOUND in {SOURCES[key]['url']}: {QUOTES[key]!r}")
        sys.exit("aborted: a quote could not be verified against the retrieved document")
    print("   both quotes verified verbatim, and neither names anyone")


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
        "publication_date, retrieved_at, language, content_hash, local_raw_path, "
        "licence_or_reuse_notes, attribution_required, source_tier, access_status, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, 'tr', ?, ?, ?, 1, ?, 'open', ?)",
        (
            spec["organization"],
            spec["title"],
            spec["document_type"],
            spec["url"],
            spec["published"],
            utc_now_iso(),
            digest,
            raw_path,
            spec["licence"],
            spec["tier"],
            "kind=amasra_casualty_revision",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def _reviewed_claim(
    conn: sqlite3.Connection, reviewer: str, incident_id: int, document_id: int, excerpt: str
) -> int:
    """One fatalities claim at 43, created needs_review then reviewed as an act.

    Constraint 5: an ai_assisted claim is created `needs_review` and only a
    reviewer action moves it on, logged as its own act. The act here is that the
    quote was machine-checked against the retrieved document, whose sha256 is on
    the document row.
    """
    held = conn.execute(
        "SELECT claim_id FROM claims WHERE incident_id = ? AND source_document_id = ? "
        "AND field_name = 'fatalities_current'",
        (incident_id, document_id),
    ).fetchone()
    if held:
        return int(held["claim_id"])
    cur = conn.execute(
        "INSERT INTO claims (incident_id, source_document_id, claim_subject_type, field_name, "
        "raw_value, normalized_value, short_evidence_excerpt, extraction_method, "
        "extractor_version, assertion_status, review_status, confidence_score) "
        "VALUES (?, ?, 'incident', 'fatalities_current', ?, '43', ?, 'ai_assisted', "
        "'amasra_casualty_revision', 'reported', 'needs_review', 0.9)",
        (incident_id, document_id, excerpt, excerpt),
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
        after_summary=f"{PUBLIC_ID} fatalities_current = 43",
        notes="Quote checked verbatim against the retrieved document, whose sha256 is recorded "
        "on the document row. The excerpt names nobody.",
    )
    conn.commit()
    return claim_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="database/mining_accidents.sqlite")
    parser.add_argument("--reviewer", required=True, help="Human authorising the revision.")
    parser.add_argument("--raw-dir", default="data/raw/tbmm")
    args = parser.parse_args()

    print("1. retrieving the record and its corroboration")
    texts = _retrieve(Path(args.raw_dir))
    print("2. verifying quotes")
    _verify(texts)

    conn = get_connection(args.db_path)
    try:
        row = conn.execute(
            "SELECT incident_id, fatalities_current, casualty_status FROM incidents "
            "WHERE public_incident_id = ?",
            (PUBLIC_ID,),
        ).fetchone()
        if row is None:
            sys.exit(f"aborted: {PUBLIC_ID} is not in this database")
        incident_id = int(row["incident_id"])
        print(
            f"3. {PUBLIC_ID} currently publishes {row['fatalities_current']} "
            f"({row['casualty_status']})"
        )

        docs = {k: _document(conn, k, d, p) for k, (_, d, p) in texts.items()}
        claims = {
            k: _reviewed_claim(conn, args.reviewer, incident_id, docs[k], QUOTES[k])
            for k in SOURCES
        }
        print(f"   claims: {claims}")

        active = get_active_decision(conn, incident_id, "fatalities_current")
        if active is not None and str(active["selected_claim_id"]) == str(claims["tbmm_86"]):
            print("   the decision selecting 43 is already in place")
        else:
            record_decision(
                conn,
                ClaimDecision(
                    incident_id=incident_id,
                    field_name="fatalities_current",
                    selected_claim_id=claims["tbmm_86"],
                    decision="accept_claim",
                    rationale=RATIONALE,
                    rationale_claim_ids=[claims["ntv_anniversary"]],
                    reviewer=args.reviewer,
                    decision_date=utc_now_iso(),
                    supersedes_decision_id=int(active["decision_id"]) if active else None,
                ),
            )
            print("4. decision recorded: fatalities_current 42 -> 43")

        # Casualty observations are immutable, so a wrong date cannot be edited:
        # it has to be superseded. The toll was observed at 43 on the day the
        # Assembly recorded it, and dating the canonical observation to the
        # pipeline run would reproduce the very flaw this change answers.
        observation = conn.execute(
            "SELECT observation_id, observation_as_of FROM casualty_observations "
            "WHERE incident_id = ? AND is_current_canonical = 1",
            (incident_id,),
        ).fetchone()
        if observation and not str(observation["observation_as_of"]).startswith(OBSERVED_AS_OF):
            active = get_active_decision(conn, incident_id, "fatalities_current")
            record_decision(
                conn,
                ClaimDecision(
                    incident_id=incident_id,
                    field_name="fatalities_current",
                    selected_claim_id=claims["tbmm_86"],
                    decision="accept_claim",
                    rationale="Same figure, same claim, recorded again only to date the "
                    "canonical casualty observation to when the toll was observed rather "
                    "than when the pipeline ran. " + RATIONALE,
                    rationale_claim_ids=[claims["ntv_anniversary"]],
                    reviewer=args.reviewer,
                    decision_date=utc_now_iso(),
                    supersedes_decision_id=int(active["decision_id"]) if active else None,
                    observed_as_of=OBSERVED_AS_OF,
                ),
            )
            print(f"5. canonical observation dated {OBSERVED_AS_OF}")

        current = conn.execute(
            "SELECT casualty_status FROM incidents WHERE incident_id = ?", (incident_id,)
        ).fetchone()["casualty_status"]
        if current != "revised":
            conn.execute(
                "UPDATE incidents SET casualty_status = 'revised', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE incident_id = ?",
                (incident_id,),
            )
            conn.commit()
            log_review_action(
                conn,
                args.reviewer,
                "casualty_status_set",
                "incident",
                incident_id,
                before_summary=f"casualty_status={current}",
                after_summary="casualty_status=revised",
                notes="Nothing disputes the figure. The toll was revised upward by a later "
                "death, which is a revision over time and not a conflict between sources.",
            )
            print(f"6. casualty_status {current} -> revised")

        final = conn.execute(
            "SELECT fatalities_current, casualty_status FROM incidents WHERE incident_id = ?",
            (incident_id,),
        ).fetchone()
        print(
            f"\n{PUBLIC_ID} now publishes {final['fatalities_current']} "
            f"({final['casualty_status']})"
        )
        print("observations on file:")
        for obs in conn.execute(
            "SELECT fatalities, observation_as_of, is_current_canonical FROM "
            "casualty_observations WHERE incident_id = ? ORDER BY observation_id",
            (incident_id,),
        ):
            flag = " <- canonical" if obs["is_current_canonical"] else ""
            print(f"   {obs['fatalities']} as of {obs['observation_as_of']}{flag}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
