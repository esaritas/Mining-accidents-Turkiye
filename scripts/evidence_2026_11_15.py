"""Evidence pass of 15 November 2026: stronger sources, settled conflicts, new records.

Role in the evidence flow: source document -> claim -> reviewer decision ->
canonical value. Nothing here writes a canonical field by hand. Every value
goes through ``review.record_decision``, every quote is checked verbatim
against the retrieved document before anything is written, and a quote that
cannot be found aborts the run. The script is re-runnable: a claim, decision,
record or classification that already exists is left alone.

What it does, in order:

1. Moves the death tolls of eleven published records from a tertiary source to
   an official or chamber source that states the same figure (TTK's own
   chronology; the Chamber of Mining Engineers' 2010-2020 accident report and
   three of its statements).
2. Settles what those documents settle: Dursunbey 2010 was 13 on the day and
   17 in the chamber's later report, a toll revised over time and not a
   dispute; Yeni Çeltek 1990 is 68; Amasra 2014 is 2; Soma 2026 has two
   injured and a reported collapse; Afşin-Elbistan 2011 was two slope failures
   on 6 and 10 February.
3. Adds nine records the chamber report lists and the register lacked
   (2010 to 2020), and nine records for February, April and May 2021 from the
   list article's own entries, each split out as a separate accident.
4. Gives every death-toll citation to the list article its supporting passage,
   read from the archived revision.
5. Replaces generated titles that printed a machine date, and adds English
   titles where there were none.

Who decides. The owner delegated these decisions on 2026-11-15. The reviewer
recorded on each one says so, so a delegated decision can always be told from
one the owner took directly (docs/open_questions.md #44).

Privacy. No quote stored here names anyone. Passages are cut to the words that
carry the figure, and a passage that might contain a name is not stored.
"""

from __future__ import annotations

import argparse
import glob
import re
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
from html import unescape
from pathlib import Path

from mining_accidents import review, validators, vocabularies
from mining_accidents.adapters import wikidata as wd
from mining_accidents.database import get_connection, utc_now_iso
from mining_accidents.models import ClaimDecision
from mining_accidents.normalization import normalize_tr
from mining_accidents.provenance import sha256_bytes

DELEGATION = (
    "Decided under the owner's delegation of 2026-11-15; the evidence was checked "
    "verbatim against the retrieved document."
)

DOCUMENTS: dict[str, dict[str, object]] = {
    "report": {
        "organization": "TMMOB Maden Mühendisleri Odası",
        "title": "Madencilikte Yaşanan İş Kazaları Raporu (2010-2020)",
        "document_type": "report",
        "url": "https://api.maden.org.tr/uploads/portal/resimler/ekler/f4e5d6912a_2079309069_ek.pdf",
        "publication_date": "2021-03-01",
        "tier": 2,
        "raw": "data/raw/tmmob/is_kazalari_raporu_2010_2020",
        "kind": "pdf",
    },
    "dursunbey_2010": {
        "organization": "TMMOB Maden Mühendisleri Odası",
        "title": "Kazaların kader olarak gösterilmesine son verilsin",
        "document_type": "chamber_statement",
        "url": "https://www.maden.org.tr/icerik/kazalarin-kader-olarak-gosterilmesine-son-verilsin-4064",
        "publication_date": None,
        "tier": 2,
        "raw": "data/raw/tmmob/kader",
        "kind": "html",
    },
    "yeni_celtek": {
        "organization": "TMMOB Maden Mühendisleri Odası",
        "title": "7 Şubat 1990 Yeni Çeltek Faciası",
        "document_type": "chamber_statement",
        "url": "https://www.maden.org.tr/icerik/7-subat-1990-yeni-celtek-faciasi-12471",
        "publication_date": "2023-02-07",
        "tier": 2,
        "raw": "data/raw/tmmob/yeni_celtek",
        "kind": "html",
    },
    "sirvan_2016": {
        "organization": "TMMOB Maden Mühendisleri Odası",
        "title": "Yine taşeron yine maden faciası",
        "document_type": "chamber_statement",
        "url": "https://www.maden.org.tr/icerik/yine-taseron-yine-maden-faciasi-9547",
        "publication_date": None,
        "tier": 2,
        "raw": "data/raw/tmmob/taseron",
        "kind": "html",
    },
    "soma_2026": {
        "organization": "TMMOB Maden Mühendisleri Odası",
        "title": "Yaşadığımız çağda madenlerde yaşanan göçükler kabul edilemez",
        "document_type": "chamber_statement",
        "url": (
            "https://www.maden.org.tr/calismalar/basin-aciklamalari/detay/"
            "yasadigimiz-cagda-madenlerde-yasanan-gocukler-kabul-edilemez-soma-da-meydana-"
            "gelen-gocukte-5-maden-emekcisi-hayatini-kaybetmis-2-isci-yaralanmistir-202610021438"
        ),
        "publication_date": "2026-10-02",
        "tier": 2,
        "raw": "data/raw/tmmob/soma_2026",
        "kind": "html",
    },
    "amasra_2014": {
        "organization": "Bartın.info",
        "title": "Amasra'da Maden Ocağında Göçük: 2 Ölü 1 Yaralı",
        "document_type": "news_article",
        "url": "https://www.bartin.info/amasrada-maden-ocaginda-gocuk-2-olu-1-yarali",
        "publication_date": "2014-11-01",
        "tier": 3,
        "raw": "data/raw/news/bartin_info_2014",
        "kind": "html",
    },
}

REPORT_DATE = "2021-03-01"

#: Published records whose toll an official or chamber document states.
#: (public id, document, quote, value, observed_as_of)
TOLL_SUPPORT: tuple[tuple[str, str, str, str, str | None], ...] = (
    (
        "TR-MINE-1990-0002",
        "yeni_celtek",
        "yaşamını yitiren 68 madenciyi saygıyla anıyoruz",
        "68",
        "2023-02-07",
    ),
    (
        "TR-MINE-2010-0004",
        "dursunbey_2010",
        "1'i maden mühendisi, 13 kişi hayatını kaybetmiş",
        "13",
        "2010-02-23",
    ),
    (
        "TR-MINE-2010-0004",
        "report",
        "da olmak üzere 17 maden emekçisi hayatını kaybetmiştir",
        "17",
        REPORT_DATE,
    ),
    (
        "TR-MINE-2010-0001",
        "report",
        "30 maden emekçisi grizu patlaması nedeniyle hayatını kaybetmiştir",
        "30",
        REPORT_DATE,
    ),
    (
        "TR-MINE-2010-0002",
        "report",
        "yangın ve oluşan göçük nedeniyle 3 maden emekçisi hayatını kaybetmiştir",
        "3",
        REPORT_DATE,
    ),
    (
        "TR-MINE-2011-0001",
        "report",
        "mühendisi olmak üzere toplamda 11 maden emekçisi yaşamını yitirmiştir",
        "11",
        REPORT_DATE,
    ),
    (
        "TR-MINE-2013-0002",
        "report",
        "ani metan degajı sebebiyle 8 maden emekçisi hayatını kaybetmiştir",
        "8",
        REPORT_DATE,
    ),
    (
        "TR-MINE-2014-0001",
        "report",
        "maden mühendisi meslektaşımız olmak üzere 301 maden",
        "301",
        REPORT_DATE,
    ),
    (
        "TR-MINE-2016-0001",
        "report",
        "meydana gelen heyelanda 16 maden emekçisi hayatını kaybetmiştir",
        "16",
        REPORT_DATE,
    ),
    ("TR-MINE-2014-0012", "amasra_2014", "İKİNCİ İŞÇİNİN DE CESEDİ ÇIKARILDI", "2", "2014-11-01"),
    (
        "TR-MINE-2026-0001",
        "soma_2026",
        "meydana gelen göçükte 5 işçi hayatını kaybetmiş ve 2 işçi yaralanmıştır",
        "5",
        "2026-10-02",
    ),
)

#: Further decisions on published records. (public id, document, field, value, quote)
FIELD_DECISIONS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "TR-MINE-2026-0001",
        "soma_2026",
        "injuries_current",
        "2",
        "meydana gelen göçükte 5 işçi hayatını kaybetmiş ve 2 işçi yaralanmıştır",
    ),
    (
        "TR-MINE-2011-0001",
        "report",
        "incident_start_datetime",
        "2011-02-06T00:00:00+03:00",
        "6 Şubat 2011 Afşin-Elbistan",
    ),
    ("TR-MINE-2011-0001", "report", "date_precision", "exact_date", "6 Şubat 2011 Afşin-Elbistan"),
    (
        "TR-MINE-2011-0001",
        "report",
        "incident_end_datetime",
        "2011-02-10T00:00:00+03:00",
        "Kısa süre 10 Şubat 2011 arayla meydana gelen bu iki şev kaymasında",
    ),
    (
        "TR-MINE-2010-0004",
        "report",
        "casualty_status",
        "revised",
        "da olmak üzere 17 maden emekçisi hayatını kaybetmiştir",
    ),
)

#: Mechanisms a chamber document reports. (public id, document, system field, code, quote)
CLASSIFICATIONS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "TR-MINE-2010-0002",
        "report",
        "event_mechanism",
        "fire",
        "yangın ve oluşan göçük nedeniyle 3 maden emekçisi hayatını kaybetmiştir",
    ),
    (
        "TR-MINE-2016-0001",
        "sirvan_2016",
        "event_mechanism",
        "landslide_or_slope_failure",
        "17 Kasım 2016 tarihinde saat 20:30 sıralarında şev kayması nedeniyle",
    ),
    (
        "TR-MINE-2026-0001",
        "soma_2026",
        "event_mechanism",
        "roof_or_ground_collapse",
        "meydana gelen göçükte 5 işçi hayatını kaybetmiş ve 2 işçi yaralanmıştır",
    ),
)

#: Records the register lacked. Each: key, document, date, precision, province,
#: deaths, place for the title, date quote, toll quote, classifications.
NEW_RECORDS: tuple[dict[str, object], ...] = (
    {
        "doc": "report",
        "date": "2010-12-22",
        "province": "22",
        "deaths": 1,
        "place": "Uzunköprü, Edirne",
        "quotes": (
            "22 Aralık 2010 Uzunköprü",
            "göçük sonucu 1 meslektaşımız hayatını kaybetmiştir",
        ),
        "codes": (("event_mechanism", "roof_or_ground_collapse"),),
    },
    {
        "doc": "report",
        "date": "2012-09-14",
        "province": "45",
        "deaths": 1,
        "place": "Soma, Manisa",
        "quotes": ("14 Eylül 2012 Soma - MANİSA", "1 meslektaşımız hayatını kaybetmiş"),
        "codes": (),
    },
    {
        "doc": "report",
        "date": "2015-05-17",
        "province": "15",
        "deaths": 2,
        "place": "Yeşilova, Burdur",
        "quotes": (
            "17 Mayıs 2015 Yeşilova-BURDUR",
            "gaz zehirlenmesi sonucu 2 maden emekçisi hayatını kaybetti",
        ),
        "codes": (),
    },
    {
        "doc": "report",
        "date": "2017-05-17",
        "province": "07",
        "deaths": 2,
        "place": "Kemer, Antalya",
        "quotes": (
            "17 Mayıs 2017 Kemer - ANTALYA",
            "parlaması sonucu 2 maden emekçisi hayatını kaybetmiştir",
        ),
        "codes": (("hazard", "methane"),),
    },
    {
        "doc": "report",
        "date": "2017-05-31",
        "province": "67",
        "deaths": 2,
        "place": "Kilimli, Zonguldak",
        "quotes": ("31 Mayıs 2017 Kilimli- ZONGULDAK", "cu 2 maden emekçisi öldü"),
        "codes": (("event_mechanism", "roof_or_ground_collapse"),),
    },
    {
        "doc": "report",
        "date": "2017-10-17",
        "province": "73",
        "deaths": 7,
        "place": "Şırnak",
        "quotes": ("17 Ekim 2017 Şırnak", "heyelanda 7 maden emekçisi hayatını kaybetmiştir"),
        "codes": (("event_mechanism", "landslide_or_slope_failure"),),
    },
    {
        "doc": "report",
        "date": "2019-02-18",
        "province": "48",
        "deaths": 3,
        "place": "Milas, Muğla",
        "quotes": (
            "18 Şubat 2019 Milas – MUĞLA",
            "kayması sonucu 3 maden emekçisi hayatını kaybetmiştir",
        ),
        "codes": (("event_mechanism", "landslide_or_slope_failure"),),
    },
    {
        "doc": "report",
        "date": "2019-05-01",
        "province": "37",
        "deaths": 2,
        "place": "Ağlı, Kastamonu",
        "quotes": (
            "01 Mayıs 2019 Ağlı - KASTAMONU",
            "Mermer ocağında taş düşmesi sonucu 2 maden emekçisi hayatını kaybetti",
        ),
        "codes": (("event_mechanism", "fall_of_object"),),
    },
    {
        "doc": "report",
        "date": "2020-04-10",
        "province": "45",
        "deaths": 3,
        "place": "Soma, Manisa",
        "quotes": (
            "10 Nisan 2020 Soma - MANİSA",
            "göçük sonucu 3 maden emekçisi hayatını kaybetmiştir",
        ),
        "codes": (("event_mechanism", "roof_or_ground_collapse"),),
    },
    # 2021, from the list article. The entries are monthly summaries of a
    # union's reports; each accident in them is its own record, at month
    # precision because the entry gives no day. January (five deaths at four
    # places, not divided) and March (a list whose closing verb is "injured")
    # cannot be split with confidence and are left out.
    {
        "doc": "list",
        "date": "2021-02",
        "province": "09",
        "deaths": 1,
        "place": "Karpuzlu, Aydın",
        "quotes": ("Aydın Karpuzlu ilçesi Güney köyü yakınındaki madende 1 işçi",),
        "codes": (),
    },
    {
        "doc": "list",
        "date": "2021-02",
        "province": "23",
        "deaths": 2,
        "place": "Palu, Elazığ",
        "quotes": ("Palu ilçesindeki krom madeni çıkarılan özel maden ocağında 2 işçi",),
        "codes": (),
    },
    {
        "doc": "list",
        "date": "2021-02",
        "province": "09",
        "deaths": 1,
        "place": "Söke, Aydın",
        "quotes": ("Söke ilçesindeki maden ocağında ise 1 işçi hayatını kaybetti",),
        "codes": (),
    },
    {
        "doc": "list",
        "date": "2021-04",
        "province": "67",
        "deaths": 1,
        "place": "İnağzı, Zonguldak",
        "quotes": ("kömür üretimi sırasında meydana gelen göçükte 1 işçi",),
        "codes": (("event_mechanism", "roof_or_ground_collapse"),),
    },
    {
        "doc": "list",
        "date": "2021-04",
        "province": "67",
        "deaths": 1,
        "place": "Kilimli, Zonguldak",
        "quotes": ("kaçak işletilen maden ocağında meydana gelen göçük sonucu 1 işçi",),
        "codes": (
            ("event_mechanism", "roof_or_ground_collapse"),
            ("contributing_condition", "informal_or_illegal_operation"),
        ),
    },
    {
        "doc": "list",
        "date": "2021-04",
        "province": "16",
        "deaths": 1,
        "place": "Harmancık, Bursa",
        "quotes": ("iş makinesinin uçurumdan yuvarlanmasıyla bir işçi hayatını kaybetti",),
        "codes": (("event_mechanism", "loss_of_vehicle_control"),),
    },
    {
        "doc": "list",
        "date": "2021-05",
        "province": "45",
        "deaths": 1,
        "place": "Soma, Manisa",
        "quotes": ("maden yolundaki döküm sahasında meydana gelen kazada 1 işçi",),
        "codes": (),
    },
    {
        "doc": "list",
        "date": "2021-05",
        "province": "20",
        "deaths": 1,
        "place": "Çal, Denizli",
        "quotes": ("Çal ilçesinde mermer ocağında meydana gelen iş kazasında 1 işçi",),
        "codes": (),
    },
    {
        "doc": "list",
        "date": "2021-05",
        "province": "16",
        "deaths": 1,
        "place": "Yenişehir, Bursa",
        "quotes": ("vinç kazası nedeniyle 1 işçi hayatını kaybetti",),
        "codes": (),
    },
)

#: English titles for records whose Turkish title is a name, not a generated label.
NAMED_TITLES_EN = {
    "TR-MINE-1983-0001": "1983 Armutçuk firedamp disaster",
    "TR-MINE-1990-0002": "1990 Amasya firedamp disaster",
    "TR-MINE-1992-0001": "1992 Kozlu coal mine disaster",
    "TR-MINE-2011-0001": "Çöllolar mine accident, Afşin-Elbistan (February 2011)",
    "TR-MINE-2016-0001": "Şirvan mine accident",
}

_TR_MONTH_NAMES = (
    "Ocak Şubat Mart Nisan Mayıs Haziran Temmuz Ağustos Eylül Ekim Kasım Aralık".split()
)
_EN_MONTH_NAMES = (
    "January February March April May June July August September October November December"
).split()
_GENERATED_TITLE = re.compile(r"^Maden kazası, (?P<place>[^()]+) \(\d{4}-\d{2}-\d{2}\)$")
_SYSTEMS = {
    "hazard": ("project_hazard", "hazards"),
    "event_mechanism": ("project_event_mechanism", "event_mechanisms"),
    "contributing_condition": ("project_contributing_condition", "contributing_conditions"),
}


# -- text handling ------------------------------------------------------------


def _key(value: str) -> str:
    """Comparable text: quotes and dashes unified, hyphenation and spacing removed."""
    value = unicodedata.normalize("NFKC", value).replace("­", "")
    value = re.sub(r"[‘’`´]", "'", value)
    value = re.sub(r"[“”]", '"', value)
    value = re.sub(r"-\s*\n\s*", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _pdf_text(payload: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(payload)
        handle.flush()
        result = subprocess.run(
            ["pdftotext", "-layout", handle.name, "-"], capture_output=True, check=True
        )
    return result.stdout.decode("utf-8", "replace")


def _html_text(payload: bytes) -> str:
    text = payload.decode("utf-8", "replace")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S)
    return unescape(re.sub(r"<[^>]+>", "\n", text))


def _retrieve(key: str) -> tuple[str, str, str]:
    """(comparable text, sha256, raw path). Uses the stored bytes when present."""
    spec = DOCUMENTS[key]
    extension = "pdf" if spec["kind"] == "pdf" else "html"
    stored = sorted(glob.glob(f"{spec['raw']}-*.{extension}"))
    if stored:
        path = Path(stored[-1])
        payload = path.read_bytes()
    else:
        payload = wd._http_get(str(spec["url"]), accept="*/*")
        path = Path(f"{spec['raw']}-{sha256_bytes(payload)[:12]}.{extension}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    text = _pdf_text(payload) if spec["kind"] == "pdf" else _html_text(payload)
    return _key(text), sha256_bytes(payload), path.as_posix()


# -- database helpers ---------------------------------------------------------


class Pass:
    def __init__(self, conn: sqlite3.Connection, reviewer: str) -> None:
        self.conn = conn
        self.reviewer = reviewer
        self.texts: dict[str, str] = {}
        self.documents: dict[str, int] = {}
        self.counts = {"claims": 0, "decisions": 0, "records": 0, "classifications": 0}

    def load_documents(self) -> None:
        for key, spec in DOCUMENTS.items():
            text, digest, raw_path = _retrieve(key)
            self.texts[key] = text
            row = self.conn.execute(
                "SELECT source_document_id FROM source_documents WHERE url = ? "
                "AND content_hash = ?",
                (spec["url"], digest),
            ).fetchone()
            if row:
                self.documents[key] = int(row[0])
                continue
            cur = self.conn.execute(
                "INSERT INTO source_documents (source_organization, title, document_type, url, "
                "publication_date, retrieved_at, language, content_hash, local_raw_path, "
                "attribution_required, source_tier, access_status, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, 'tr', ?, ?, 1, ?, 'open', ?)",
                (
                    spec["organization"],
                    spec["title"],
                    spec["document_type"],
                    spec["url"],
                    spec["publication_date"],
                    utc_now_iso(),
                    digest,
                    raw_path,
                    spec["tier"],
                    "Retrieved as one named document for the evidence pass of 2026-11-15. "
                    "Short quotations only; the document is not redistributed.",
                ),
            )
            self.documents[key] = int(cur.lastrowid)
        # The list article: the restored citation, anchored to its archived revision.
        row = self.conn.execute(
            "SELECT source_document_id, local_raw_path FROM source_documents "
            "WHERE title = ? AND local_raw_path IS NOT NULL ORDER BY source_document_id LIMIT 1",
            (wd.LIST_TITLE,),
        ).fetchone()
        if row is None:
            sys.exit("aborted: the archived list article is not in this database")
        self.documents["list"] = int(row["source_document_id"])
        self.list_wikitext = Path(row["local_raw_path"]).read_text(encoding="utf-8")
        self.texts["list"] = _key(
            re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", self.list_wikitext)
        )
        row = self.conn.execute(
            "SELECT source_document_id FROM source_documents WHERE url = ? "
            "ORDER BY source_document_id DESC LIMIT 1",
            ("https://www.taskomuru.gov.tr/ttk/tarihce/",),
        ).fetchone()
        if row is None:
            sys.exit("aborted: run scripts/organization_validity.py first (TTK chronology)")
        self.documents["ttk"] = int(row[0])
        self.conn.commit()

    def verify(self, key: str, quote: str) -> None:
        if _key(quote) not in self.texts[key]:
            sys.exit(f"aborted: quote not found in {key}: {quote!r}")

    def incident(self, public_id: str) -> int:
        row = self.conn.execute(
            "SELECT incident_id FROM incidents WHERE public_incident_id = ?", (public_id,)
        ).fetchone()
        if row is None:
            sys.exit(f"aborted: {public_id} is not in this database")
        return int(row[0])

    def claim(
        self,
        key: str,
        incident_id: int,
        field: str,
        value: str,
        quote: str,
        subject: str = "incident",
        method: str = "ai_assisted",
    ) -> int:
        """A claim with its quote. AI-assisted claims are created needs_review
        and reviewed as a logged act (constraint 5)."""
        self.verify(key, quote)
        validators.validate_excerpt_word_cap(quote)
        document_id = self.documents[key]
        row = self.conn.execute(
            "SELECT claim_id, review_status FROM claims WHERE source_document_id = ? "
            "AND incident_id = ? AND field_name = ? AND normalized_value = ? "
            "AND short_evidence_excerpt = ?",
            (document_id, incident_id, field, value, quote),
        ).fetchone()
        if row:
            claim_id = int(row["claim_id"])
            status = row["review_status"]
        else:
            status = "needs_review" if method == "ai_assisted" else "pending"
            cur = self.conn.execute(
                "INSERT INTO claims (incident_id, source_document_id, claim_subject_type, "
                "field_name, raw_value, normalized_value, short_evidence_excerpt, "
                "extraction_method, extractor_version, assertion_status, review_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'evidence_2026_11_15', 'reported', ?)",
                (incident_id, document_id, subject, field, value, value, quote, method, status),
            )
            claim_id = int(cur.lastrowid)
            self.counts["claims"] += 1
        if status != "reviewed":
            self.review_claim(claim_id, f"quote verified verbatim in document {document_id}")
        return claim_id

    def review_claim(self, claim_id: int, note: str) -> None:
        self.conn.execute(
            "UPDATE claims SET review_status = 'reviewed' WHERE claim_id = ?", (claim_id,)
        )
        review.log_review_action(
            self.conn,
            self.reviewer,
            "claim_reviewed",
            "claim",
            claim_id,
            after_summary="review_status=reviewed",
            notes=f"{note}. {DELEGATION}",
        )
        self.conn.commit()

    def decide(
        self,
        incident_id: int,
        field: str,
        claim_id: int,
        rationale: str,
        observed_as_of: str | None = None,
    ) -> None:
        # A claim this pass has already decided on is never decided again, so a
        # re-run cannot reorder a toll that was recorded as 13 and then 17.
        if self.conn.execute(
            "SELECT 1 FROM claim_decisions WHERE incident_id = ? AND field_name = ? "
            "AND selected_claim_id = ?",
            (incident_id, field, claim_id),
        ).fetchone():
            return
        active = review.get_active_decision(self.conn, incident_id, field)
        review.record_decision(
            self.conn,
            ClaimDecision(
                incident_id=incident_id,
                field_name=field,
                selected_claim_id=claim_id,
                decision="accept_claim",
                rationale=f"{rationale} {DELEGATION}",
                reviewer=self.reviewer,
                supersedes_decision_id=int(active["decision_id"]) if active else None,
                observed_as_of=observed_as_of,
            ),
        )
        self.counts["decisions"] += 1

    def classify(self, incident_id: int, key: str, field: str, code: str, quote: str) -> None:
        system, vocabulary = _SYSTEMS[field]
        validators.validate_classification_code(system, code)
        exists = self.conn.execute(
            "SELECT 1 FROM incident_classifications WHERE incident_id = ? "
            "AND classification_system = ? AND classification_code = ?",
            (incident_id, system, code),
        ).fetchone()
        if exists:
            return
        claim_id = self.claim(key, incident_id, field, code, quote, subject="classification")
        entry = next(e for e in vocabularies.load_vocabulary(vocabulary) if e.code == code)
        self.conn.execute(
            "INSERT INTO incident_classifications (incident_id, classification_system, "
            "classification_code, classification_label_tr, classification_label_en, "
            "assertion_status, source_claim_id, review_status) "
            "VALUES (?, ?, ?, ?, ?, 'reported', ?, 'reviewed')",
            (incident_id, system, code, entry.label_tr, entry.label_en, claim_id),
        )
        review.log_review_action(
            self.conn,
            self.reviewer,
            "classification_added",
            "incident",
            incident_id,
            after_summary=f"{system}={code} (claim {claim_id})",
            notes=f"What the source reports happened, not a cause. {DELEGATION}",
        )
        self.conn.commit()
        self.counts["classifications"] += 1


# -- steps --------------------------------------------------------------------


def step_ttk(run: Pass) -> None:
    """Armutçuk and Kozlu-İhsaniye: the operator's own chronology states the tolls."""
    for public_id, value in (("TR-MINE-1983-0001", "103"), ("TR-MINE-1983-0002", "10")):
        incident_id = run.incident(public_id)
        row = run.conn.execute(
            "SELECT claim_id, review_status FROM claims WHERE source_document_id = ? "
            "AND incident_id = ? AND field_name = 'fatalities_current' AND normalized_value = ?",
            (run.documents["ttk"], incident_id, value),
        ).fetchone()
        if row is None:
            sys.exit(f"aborted: no TTK toll claim for {public_id}")
        if row["review_status"] != "reviewed":
            run.review_claim(int(row["claim_id"]), "TTK chronology, quote verified on retrieval")
        run.decide(
            incident_id,
            "fatalities_current",
            int(row["claim_id"]),
            "The same figure, now from TTK's own chronology (tier 1) in place of the "
            "list article (tier 3).",
        )


def step_tolls(run: Pass) -> None:
    for public_id, key, quote, value, observed in TOLL_SUPPORT:
        incident_id = run.incident(public_id)
        claim_id = run.claim(key, incident_id, "fatalities_current", value, quote, "casualty")
        spec = DOCUMENTS[key]
        run.decide(
            incident_id,
            "fatalities_current",
            claim_id,
            f"{value} as stated by {spec['organization']}, {spec['title']} "
            f"(tier {spec['tier']}), in place of a tertiary source.",
            observed_as_of=observed,
        )


def step_fields(run: Pass) -> None:
    for public_id, key, field, value, quote in FIELD_DECISIONS:
        incident_id = run.incident(public_id)
        claim_id = run.claim(key, incident_id, field, value, quote)
        spec = DOCUMENTS[key]
        observed = "2026-10-02" if field == "injuries_current" else None
        run.decide(
            incident_id,
            field,
            claim_id,
            f"{field} = {value} from {spec['organization']}, {spec['title']}.",
            observed_as_of=observed,
        )
    for public_id, key, field, code, quote in CLASSIFICATIONS:
        run.classify(run.incident(public_id), key, field, code, quote)


def _titles(place: str, date: str) -> tuple[str, str]:
    year, month = int(date[:4]), int(date[5:7])
    if len(date) == 7:
        return (
            f"Maden kazası, {place} ({_TR_MONTH_NAMES[month - 1]} {year})",
            f"Mine accident, {place} ({_EN_MONTH_NAMES[month - 1]} {year})",
        )
    day = int(date[8:10])
    return (
        f"Maden kazası, {place} ({day} {_TR_MONTH_NAMES[month - 1]} {year})",
        f"Mine accident, {place} ({day} {_EN_MONTH_NAMES[month - 1]} {year})",
    )


def step_new_records(run: Pass) -> None:
    for record in NEW_RECORDS:
        key, date = str(record["doc"]), str(record["date"])
        title_tr, title_en = _titles(str(record["place"]), date)
        if run.conn.execute(
            "SELECT 1 FROM incidents WHERE canonical_title_tr = ?", (title_tr,)
        ).fetchone():
            continue
        quotes = tuple(record["quotes"])  # type: ignore[arg-type]
        for quote in quotes:
            run.verify(key, quote)
        precision = "month" if len(date) == 7 else "exact_date"
        start = f"{date}-01T00:00:00+03:00" if precision == "month" else f"{date}T00:00:00+03:00"
        spec = DOCUMENTS.get(key, {"organization": "Wikipedia (tr)", "title": wd.LIST_TITLE})
        cur = run.conn.execute(
            "INSERT INTO incidents (canonical_title_tr, canonical_title_en, "
            "canonical_title_tr_normalized, incident_kind, incident_status, scope_rationale) "
            "VALUES (?, ?, ?, 'fatal_accident', 'in_scope', ?)",
            (
                title_tr,
                title_en,
                normalize_tr(title_tr),
                f"Fatal mining or quarrying accident stated by {spec['organization']}, "
                f"{spec['title']}. Added in the evidence pass of 2026-11-15.",
            ),
        )
        incident_id = int(cur.lastrowid)
        why = f"New record from {spec['organization']}, {spec['title']}."
        date_quote, toll_quote = quotes[0], quotes[-1]
        for field, value, quote, subject in (
            ("incident_start_datetime", start, date_quote, "incident"),
            ("date_precision", precision, date_quote, "incident"),
            ("province_code", str(record["province"]), date_quote, "incident"),
            ("fatalities_current", str(record["deaths"]), toll_quote, "casualty"),
        ):
            claim_id = run.claim(key, incident_id, field, value, quote, subject)
            observed = REPORT_DATE if field == "fatalities_current" and key == "report" else None
            run.decide(incident_id, field, claim_id, why, observed_as_of=observed)
        for field, code in record["codes"]:  # type: ignore[union-attr]
            run.classify(incident_id, key, field, code, toll_quote)
        public_id = review.assign_public_incident_id(run.conn, incident_id, actor=run.reviewer)
        run.conn.execute(
            "UPDATE incidents SET verification_status = 'reviewed', "
            "publication_status = 'publishable' WHERE incident_id = ?",
            (incident_id,),
        )
        review.log_review_action(
            run.conn,
            run.reviewer,
            "publication_signoff",
            "incident",
            incident_id,
            after_summary=f"{public_id}: verification_status=reviewed, "
            "publication_status=publishable",
            notes=DELEGATION,
        )
        run.conn.commit()
        run.counts["records"] += 1


def _bullet_passage(line: str) -> str | None:
    """The words in a list entry that carry the toll, or None if unsafe.

    Only the matched span is kept, so a name earlier in the entry never
    travels. A span holding a capitalised word could itself hold a name and
    is refused.
    """
    match = wd._LIST_DEATHS.search(line) or wd._LIST_DEATHS_ONE.search(line)
    if not match:
        return None
    end = match.end()
    while end < len(line) and line[end].isalpha():
        end += 1
    passage = line[match.start() : end].strip()
    if any(token[:1].isupper() for token in passage.split()[1:]):
        return None
    return passage


def step_passages(run: Pass) -> None:
    """Give list-article toll citations the passage that supports them."""
    list_doc = run.documents["list"]
    bullets: dict[tuple[str, str], list[str]] = {}
    section_year = None
    for raw in run.list_wikitext.splitlines():
        heading = re.match(r"^===\s*(\d{4})\s*===", raw)
        if heading:
            section_year = heading.group(1)
            continue
        if not raw.startswith("*"):
            continue
        line = wd._REF_MARKUP.sub(" ", raw)
        line = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", line)
        dated = wd._bullet_date(line, section_year)
        province = wd._bullet_province(line)
        if dated and province:
            bullets.setdefault((dated[0][:10], province), []).append(line)
    rows = run.conn.execute(
        "SELECT i.incident_id, i.incident_start_datetime, i.province_code, i.fatalities_current, "
        "c.short_evidence_excerpt FROM incidents i "
        "JOIN claim_decisions d ON d.incident_id = i.incident_id "
        "AND d.field_name = 'fatalities_current' AND NOT EXISTS (SELECT 1 FROM "
        "claim_decisions s WHERE s.supersedes_decision_id = d.decision_id) "
        "JOIN claims c ON c.claim_id = d.selected_claim_id "
        "WHERE c.source_document_id = ? AND i.publication_status IN ('publishable','published')",
        (list_doc,),
    ).fetchall()
    for row in rows:
        if row["short_evidence_excerpt"]:
            continue
        lines = bullets.get((row["incident_start_datetime"][:10], row["province_code"]), [])
        passages = {p for p in (_bullet_passage(line) for line in lines) if p}
        if len(passages) != 1:
            continue  # no entry, several entries, or an unsafe passage
        passage = passages.pop()
        value = str(row["fatalities_current"])
        stated = re.match(r"\d+", passage)
        if (stated.group(0) if stated else "1") != value:
            continue
        if _key(passage) not in run.texts["list"]:
            continue
        claim_id = run.claim(
            "list",
            row["incident_id"],
            "fatalities_current",
            value,
            passage,
            "casualty",
            method="html_parser",
        )
        run.decide(
            row["incident_id"],
            "fatalities_current",
            claim_id,
            "Same value from the same document. The claim now carries the passage, read "
            "from the archived revision by pattern, with nothing but the words that state "
            "the toll.",
            observed_as_of=None,
        )


def step_titles(run: Pass) -> None:
    """Replace machine-dated generated titles and add missing English titles."""
    rows = run.conn.execute(
        "SELECT incident_id, public_incident_id, canonical_title_tr, canonical_title_en, "
        "incident_start_datetime, date_precision FROM incidents "
        "WHERE publication_status IN ('publishable','published') "
        "AND incident_kind = 'fatal_accident'"
    ).fetchall()
    for row in rows:
        title_tr, title_en = row["canonical_title_tr"], row["canonical_title_en"]
        match = _GENERATED_TITLE.match(title_tr or "")
        if match:
            date = row["incident_start_datetime"]
            stamp = date[:7] if row["date_precision"] == "month" else date[:10]
            title_tr, title_en = _titles(match.group("place"), stamp)
        elif not title_en:
            title_en = NAMED_TITLES_EN.get(row["public_incident_id"])
        if (title_tr, title_en) == (row["canonical_title_tr"], row["canonical_title_en"]):
            continue
        run.conn.execute(
            "UPDATE incidents SET canonical_title_tr = ?, canonical_title_tr_normalized = ?, "
            "canonical_title_en = ? WHERE incident_id = ?",
            (title_tr, normalize_tr(title_tr), title_en, row["incident_id"]),
        )
        review.log_review_action(
            run.conn,
            run.reviewer,
            "generated_title_set",
            "incident",
            row["incident_id"],
            before_summary=f"{row['canonical_title_tr']} | {row['canonical_title_en']}",
            after_summary=f"{title_tr} | {title_en}",
            notes="A descriptive label built from the decided date and place, not a claim. "
            "The date is written as the record's precision allows.",
        )
    run.conn.commit()


def step_statuses(run: Pass) -> None:
    """The Nesko quantity is 'about 4,500 tonnes' in its source; say so."""
    run.conn.execute(
        "UPDATE environmental_effects SET "
        "qualitative_value = 'Yaklaşık 4.500 ton kimyasal atık (kurşun, çinko, bakır "
        "zenginleştirme tesisi)', "
        "qualitative_value_en = 'About 4,500 tonnes of chemical waste from a lead, zinc and "
        "copper concentrator' "
        "WHERE effect_type = 'released_material' AND measure_value = 4500.0 "
        "AND qualitative_value NOT LIKE 'Yaklaşık%'"
    )
    run.conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db-path", default="database/mining_accidents.sqlite")
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    conn = get_connection(args.db_path)
    try:
        run = Pass(conn, args.reviewer)
        run.load_documents()
        step_ttk(run)
        step_tolls(run)
        step_fields(run)
        step_new_records(run)
        step_passages(run)
        step_titles(run)
        step_statuses(run)
        print(run.counts)
        row = conn.execute(
            "SELECT COUNT(*), SUM(fatalities_current) FROM incidents WHERE incident_kind = "
            "'fatal_accident' AND publication_status IN ('publishable','published')"
        ).fetchone()
        print(f"published fatal records: {row[0]}, deaths: {row[1]}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
