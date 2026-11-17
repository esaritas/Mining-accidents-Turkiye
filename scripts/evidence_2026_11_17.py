"""Evidence pass of 17 November 2026: the Chamber's journal table, two disputes, injuries.

Role in the evidence flow: source document -> claim -> reviewer decision ->
canonical value. It reuses the machinery of ``scripts/evidence_2026_11_15.py``:
every quote is checked verbatim against the retrieved document before anything
is written, a quote that cannot be found aborts the run, AI-assisted claims are
created ``needs_review`` and reviewed as a logged act, and every value changes
only through ``review.record_decision``. Re-running changes nothing.

The new document is an article in Bilimsel Madencilik Dergisi, the
peer-reviewed journal published by the Chamber of Mining Engineers (TMMOB
Maden Mühendisleri Odası): "Geçmişten Günümüze Büyük Maden Kazaları",
Madencilik 54(2), 33-43, June 2015. Its Çizelge 1 lists accidents in Türkiye
by place, year, kind, deaths and operator type. It gives years, not dates, and
cites no source per row, so it is treated as the Chamber's compilation (tier
2), stated as such in every rationale.

What it does:

1. Nine published tolls the table states with the same figure move from the
   list article (tier 3) to the journal (tier 2).
2. Sorgun 1995: the table gives 37, the register publishes 38, and a local
   report on the 30th anniversary gives 38 with a breakdown (45 trapped, 7
   rescued injured). The register keeps 38, now cited to that report, puts
   the 37 on file and marks the toll disputed. Nothing here decides between
   them.
3. Aşkale 2003: already disputed (reports of 7, 8 and 9). The table's 8 goes
   on file and the disputed status is cited to both figures.
4. Injuries: 77 injured rescued at Kozlu 1992 (the journal, citing a TTK
   engineers' paper) and 20 injured at Dursunbey 2010 (the Chamber's
   statement at the time).

Decisions are taken under the owner's delegation of 2026-11-15 and carry the
same reviewer string, so they can be told from decisions the owner took
directly (open question 44).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence_2026_11_15 as ev  # noqa: E402
from mining_accidents import review  # noqa: E402
from mining_accidents.database import get_connection  # noqa: E402
from mining_accidents.models import ClaimDecision  # noqa: E402

JOURNAL_DATE = "2015-06"

NEW_DOCUMENTS: dict[str, dict[str, object]] = {
    "journal": {
        "organization": "TMMOB Maden Mühendisleri Odası (Bilimsel Madencilik Dergisi)",
        "title": "Geçmişten Günümüze Büyük Maden Kazaları, Madencilik 54(2), 33-43",
        "document_type": "journal_article",
        "url": "https://dergipark.org.tr/tr/download/article-file/374472",
        "publication_date": "2015-06-01",
        "tier": 2,
        "raw": "data/raw/academic/dergipark_374472",
        "kind": "pdf",
    },
    "sorgun_news": {
        "organization": "Yozgat Hakimiyet",
        "title": "Yozgat'ta 26 Mart 1995'in Kara Günü: 30 Yıl Sonra Bile Silinmedi",
        "document_type": "news_article",
        "url": (
            "https://www.yozgathakimiyet.com.tr/"
            "yozgatta-26-mart-1995in-kara-gunu-30-yil-sonra-bile-silinmedi"
        ),
        "publication_date": None,
        "tier": 3,
        "raw": "data/raw/news/yozgat_hakimiyet_sorgun",
        "kind": "html",
    },
}

TABLE = "Çizelge 1. Ülkemizde Meydana Gelen Kazalar (yer, yıl, kazanın şekli, ölü sayısı)"

#: (public id, row quoted from Çizelge 1, toll). The row gives a year, and each
#: register record is the only one in that province and year.
SAME_FIGURE: tuple[tuple[str, str, str], ...] = (
    ("TR-MINE-1983-0003", "Yeni Çeltek 1983 Grizu 5 Kamu", "5"),
    ("TR-MINE-1987-0001", "Kozlu 1987 Göçük 8 Kamu", "8"),
    ("TR-MINE-1990-0001", "Amasra 1990 Grizu 5 Kamu", "5"),
    ("TR-MINE-2003-0001", "Ermenek 2003 Grizu 10 Taşeron", "10"),
    ("TR-MINE-2004-0001", "Bayat 2004 Grizu 3 Özel", "3"),
    ("TR-MINE-2004-0002", "Küre 2004 Yangın 19 Taşeron", "19"),
    ("TR-MINE-2005-0001", "Gediz 2005 Grizu 18 Kamu", "18"),
    ("TR-MINE-2006-0001", "Dursunbey 2006 Grizu 17 Özel", "17"),
    ("TR-MINE-2009-0001", "M. Kemalpaşa 2009 Grizu 19 Özel", "19"),
)

SORGUN = "TR-MINE-1995-0001"
SORGUN_38 = (
    "45 madenciden yalnızca 7’si yaralı olarak kurtarılabilmiş, 38 madenci ise hayatını kaybetmişti"
)
SORGUN_37 = "Sorgun 1995 Grizu 37 Özel"

ASKALE = "TR-MINE-2003-0002"
ASKALE_8 = "Aşkale 2003 Grizu 8 Taşeron"

INJURIES: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "TR-MINE-1992-0001",
        "journal",
        "sırasında ocaklardan 77 yaralı işçi",
        "77",
        "1992-03",
    ),
    (
        "TR-MINE-2010-0004",
        "dursunbey_2010",
        "13 kişi hayatını kaybetmiş, 6‘ sı ağır, 20 işçi de yaralanmıştır",
        "20",
        "2010-02-23",
    ),
)


def _status_dispute(run: ev.Pass, incident_id: int, claim_ids: list[int], why: str) -> None:
    """Mark a toll disputed, citing every figure on file. Idempotent."""
    active = review.get_active_decision(run.conn, incident_id, "casualty_status")
    if active is not None and active["manual_value"] == "disputed":
        cited = set(review_ids(active["rationale_claim_ids"]))
        if set(claim_ids) <= cited:
            return
    review.record_decision(
        run.conn,
        ClaimDecision(
            incident_id=incident_id,
            field_name="casualty_status",
            decision="manual_override",
            manual_value="disputed",
            rationale=f"{why} {ev.DELEGATION}",
            rationale_claim_ids=claim_ids,
            reviewer=run.reviewer,
            supersedes_decision_id=int(active["decision_id"]) if active else None,
        ),
    )
    run.counts["decisions"] += 1


def review_ids(raw: str | None) -> list[int]:
    import json

    return [int(x) for x in json.loads(raw or "[]")]


def _current_toll_claim(run: ev.Pass, incident_id: int) -> int:
    active = review.get_active_decision(run.conn, incident_id, "fatalities_current")
    if active is None or active["selected_claim_id"] is None:
        sys.exit(f"aborted: incident {incident_id} has no selected toll claim")
    return int(active["selected_claim_id"])


def step_same_figure(run: ev.Pass) -> None:
    for public_id, row, value in SAME_FIGURE:
        incident_id = run.incident(public_id)
        published = run.conn.execute(
            "SELECT fatalities_current FROM incidents WHERE incident_id = ?", (incident_id,)
        ).fetchone()[0]
        if str(published) != value:
            sys.exit(f"aborted: {public_id} publishes {published}, the table says {value}")
        claim_id = run.claim("journal", incident_id, "fatalities_current", value, row, "casualty")
        run.decide(
            incident_id,
            "fatalities_current",
            claim_id,
            f"{value}, the same figure, as stated in the Chamber of Mining Engineers' journal "
            f"(tier 2), {TABLE}, in place of the list article (tier 3). The table gives the "
            "year, not the date, and cites no source for the row.",
            observed_as_of=JOURNAL_DATE,
        )


def step_sorgun(run: ev.Pass) -> None:
    incident_id = run.incident(SORGUN)
    c38 = run.claim("sorgun_news", incident_id, "fatalities_current", "38", SORGUN_38, "casualty")
    c37 = run.claim("journal", incident_id, "fatalities_current", "37", SORGUN_37, "casualty")
    run.decide(
        incident_id,
        "fatalities_current",
        c38,
        "38 kept, now cited to a local report that gives the figure with its breakdown "
        "(45 trapped, 7 rescued injured). The Chamber of Mining Engineers' journal table "
        f"({TABLE}) gives 37 and is on file as a claim that was not selected. No record "
        "from the time has been read, so the toll is also marked disputed.",
    )
    _status_dispute(
        run,
        incident_id,
        [c38, c37],
        "Sources give 38 (local report on the 30th anniversary, and the list article) and "
        "37 (the Chamber of Mining Engineers' journal, 2015). Both stay on file; the "
        "register publishes 38 until a record from the time settles it.",
    )


def step_askale(run: ev.Pass) -> None:
    incident_id = run.incident(ASKALE)
    c7 = _current_toll_claim(run, incident_id)
    c8 = run.claim("journal", incident_id, "fatalities_current", "8", ASKALE_8, "casualty")
    _status_dispute(
        run,
        incident_id,
        [c7, c8],
        "Already disputed (reports of 7, 8 and 9 dead, review of 2026-07-25). The Chamber "
        f"of Mining Engineers' journal ({TABLE}) gives 8 and is now on file beside the "
        "published 7.",
    )


def step_injuries(run: ev.Pass) -> None:
    for public_id, key, quote, value, observed in INJURIES:
        incident_id = run.incident(public_id)
        claim_id = run.claim(key, incident_id, "injuries_current", value, quote, "casualty")
        spec = ev.DOCUMENTS[key]
        run.decide(
            incident_id,
            "injuries_current",
            claim_id,
            f"{value} injured, as stated by {spec['organization']}, {spec['title']}. A count "
            "of people injured that the source reports, not a final figure.",
            observed_as_of=observed,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db-path", default="database/mining_accidents.sqlite")
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    ev.DOCUMENTS.update(NEW_DOCUMENTS)
    conn = get_connection(args.db_path)
    try:
        run = ev.Pass(conn, args.reviewer)
        run.load_documents()
        step_same_figure(run)
        step_sorgun(run)
        step_askale(run)
        step_injuries(run)
        print(run.counts)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
