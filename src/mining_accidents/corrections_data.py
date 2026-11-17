"""Standing tables of the audit corrections of July 2026.

Role in the evidence flow: the record-level actions the external audit of
2026-07-17 and the review of 2026-07-25 called for, written down as data:
what to withdraw, what to split, which values to correct and why, and what
could not be verified and is only logged. The programmes that apply them are
``corrections.py`` and ``corrections_review2.py``; nothing here touches the
database.
"""

from __future__ import annotations

from pathlib import Path

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
        "Maden kazası, Amasra, Bartın (2014-11-01)",
        "2014-11-01T00:00:00+03:00",
        "74",
        2,
        "roof_or_ground_collapse",
        "1 Kasım 2014",
    ),
    (
        "audit2026:zonguldak-gelik-2014",
        "Maden kazası, Gelik, Zonguldak (2014-11-01)",
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

_REVIEW2_PREFIX = (
    "Senior analyst review of 2026-07-25 (owner-forwarded), verified against the "
    "stored raw source documents. "
)

#: Canonical-value corrections the 2026-07-25 review found and that our own
#: stored sources confirm. Each becomes a superseding manual_override decision,
#: so the prior (mis-parsed) claim is preserved, not overwritten.
#: (public_id, field_name, value, fragment_hint, reason). fragment_hint picks
#: the supporting claim whose raw text states the corrected value; None falls
#: back to any claim on the incident.
REVIEW2_VALUE_OVERRIDES: tuple[tuple[str, str, str, str | None, str], ...] = (
    (
        "TR-MINE-2019-0002",
        "incident_start_datetime",
        "2019-01-13T00:00:00+03:00",
        "13 Ocak",
        "The stored source bullet reads \"13 Ocak'ta Manisa'nin Soma ilcesinde "
        'meydana gelen kaza": the event date is 13 January 2019. The published '
        "2019-02-03 was a parser error (a reference/access date read as the event "
        "date). Corrects a day/date inversion of our own extraction.",
    ),
    (
        "TR-MINE-2019-0002",
        "injuries_current",
        "1",
        "13 Ocak",
        'The same source clause states "1 isci yaralandi" (1 injured); the value '
        "was present in the source but not extracted.",
    ),
    (
        "TR-MINE-2019-0002",
        "canonical_title_tr",
        "Maden kazası, Manisa (2019-01-13)",
        None,
        "Project-assigned descriptive title updated to the corrected event date.",
    ),
    (
        "TR-MINE-2003-0002",
        "casualty_status",
        "disputed",
        None,
        "The 8 August 2003 Askale (Erzurum) grizu explosion toll differs across "
        "sources (reports of 7, 8 and 9 dead). Marked disputed pending a primary or "
        "authoritative source; the stored value of 7 is retained meanwhile.",
    ),
)

#: Source-dependent items from the 2026-07-25 review: logged, not applied,
#: because acting would change canonical numbers without a document we hold.
REVIEW2_PENDING: tuple[tuple[str, str], ...] = (
    (
        "İSİG mining totals 2016/2018/2019 -> 74/67/64",
        "The review cites revised retrospective İSİG figures (2016 73->74, 2018 "
        "66->67, 2019 63->64). Our stored series holds 73/66/63; updating requires "
        "the revised İSİG source. Pending İSİG source re-assessment.",
    ),
    (
        "TR-MINE-2022-0001 (Amasra) cumulative 42 -> 43 with structure",
        "The review asks for an immediate/subsequent split (42 initial + 1 April "
        "2023 = 43 cumulative, with an as-of date). Needs the casualty-qualifier "
        "schema and the TBMM source (TO_ASSESS); already tracked as open question "
        "#20. casualty_status stays 'disputed' meanwhile.",
    ),
    (
        "extractor: guard access-date-as-event-date and day/date inversions",
        "The 2019-0002 error shows the list parser can take a reference access date "
        "as the event date. Add a parser rule and a regression test; pending "
        "extractor work (review P2).",
    ),
)


_DASH_RETITLE_RATIONALE = (
    "Style correction: project-assigned descriptive titles use a comma instead "
    "of a long dash (owner directive, 2026-07-24). No factual change."
)


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
        "Çöllolar maden kazası, Afşin-Elbistan (Şubat 2011)",
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
