"""Offline parsing tests for the Wikidata/Wikipedia adapter.

No network: everything here parses synthetic (TEST-) payloads shaped like the
real APIs' output. Fetch behaviour is exercised only in real runs.
"""

from __future__ import annotations

from mining_accidents.adapters.wikidata import _parse_article, _parse_entity

SYNTHETIC_ENTITY = {
    "id": "Q999999999",
    "labels": {
        "tr": {"value": "TEST maden kazası"},
        "en": {"value": "TEST mine accident"},
    },
    "claims": {
        "P585": [
            {
                "rank": "normal",
                "mainsnak": {
                    "datavalue": {"value": {"time": "+2099-05-10T00:00:00Z", "precision": 11}}
                },
            }
        ],
        "P1120": [
            {
                "rank": "normal",
                "mainsnak": {"datavalue": {"value": {"amount": "+7"}}},
            },
            {
                "rank": "preferred",
                "mainsnak": {"datavalue": {"value": {"amount": "+9"}}},
            },
        ],
        "P625": [
            {
                "rank": "normal",
                "mainsnak": {"datavalue": {"value": {"latitude": 39.5, "longitude": 32.25}}},
            }
        ],
    },
}


def _by_field(drafts: list) -> dict[str, object]:
    return {d.field_name: d for d in drafts}


def test_entity_parsing_uses_preferred_rank() -> None:
    fields = _by_field(_parse_entity(SYNTHETIC_ENTITY))
    assert fields["canonical_title_tr"].normalized_value == "TEST maden kazası"
    assert fields["incident_start_datetime"].normalized_value == "2099-05-10T00:00:00+03:00"
    assert fields["date_precision"].normalized_value == "exact_date"
    # rank=preferred (9) beats the earlier normal statement (7).
    assert fields["fatalities_current"].normalized_value == "9"
    assert fields["latitude"].normalized_value == "39.500000"
    assert all(d.extraction_method == "api" for d in fields.values())


def test_infobox_extraction_is_mechanical() -> None:
    wikitext = (
        "{{Olay bilgi kutusu\n"
        "| tarih = {{Başlangıç tarihi|2099|5|10}}\n"
        "| koordinatlar = {{Koordinat|39|30|0.0|N|32|15|0.0|E|type:landmark}}\n"
        "| ölüsayısı = 12\n"
        "}}\n"
        "'''TEST kazası''' [[Zonguldak (il)|Zonguldak]] ilinde meydana geldi. "
        "[[Zonguldak]] valisi açıklama yaptı."
    )
    fields = _by_field(_parse_article(wikitext))
    deaths = fields["fatalities_current"]
    assert deaths.normalized_value == "12"
    assert deaths.extraction_method == "html_parser"
    assert deaths.review_status == "pending"
    assert fields["incident_start_datetime"].normalized_value == "2099-05-10T00:00:00+03:00"
    assert fields["latitude"].normalized_value == "39.500000"
    assert fields["longitude"].normalized_value == "32.250000"
    assert fields["province_code"].normalized_value == "67"


def test_prose_deaths_are_ai_assisted_and_queued() -> None:
    wikitext = (
        "'''TEST kazası''' [[Karaman]]'ın bir ilçesinde meydana geldi; "
        "18 işçinin mahsur kalarak hayatını kaybettiği olaydır."
    )
    fields = _by_field(_parse_article(wikitext))
    deaths = fields["fatalities_current"]
    assert deaths.normalized_value == "18"
    assert deaths.extraction_method == "ai_assisted"
    assert deaths.review_status == "needs_review"  # hard constraint 5 in action
    assert fields["province_code"].normalized_value == "70"


def test_province_frequency_beats_stray_mention() -> None:
    wikitext = (
        "Bir başka olay için bkz. [[Diyarbakır]] örneği.\n"
        "'''TEST kazası''' [[Bartın (il)|Bartın]] ilinin ilçesinde oldu. "
        "[[Bartın]] merkezine uzaklığı azdır."
    )
    fields = _by_field(_parse_article(wikitext))
    assert fields["province_code"].normalized_value == "74"


def test_article_without_extractable_values_yields_no_claims() -> None:
    assert _parse_article("'''TEST''' hakkında kısa bir metin.") == []


def test_list_bullet_parsing_mechanical() -> None:
    from mining_accidents.adapters.wikidata import parse_list_article

    wikitext = (
        "== Kazalar ==\n=== 2099 ===\n"
        "* 10 Mayıs 2099 tarihinde [[Zonguldak (il)|Zonguldak]]'ın TEST ocağında "
        "meydana gelen grizu patlamasında 30 işçi yaşamını yitirmiştir.\n"
        "== Ayrıca bakınız ==\n"
    )
    drafts = parse_list_article(wikitext)
    fields = {d.field_name: d for d in drafts}
    assert fields["incident_start_datetime"].normalized_value == "2099-05-10T00:00:00+03:00"
    assert fields["fatalities_current"].normalized_value == "30"
    assert fields["fatalities_current"].extraction_method == "html_parser"
    assert fields["province_code"].normalized_value == "67"
    assert fields["event_mechanism"].normalized_value == "gas_explosion"
    assert fields["hazard"].normalized_value == "methane"
    assert len({d.notes["group"] for d in drafts}) == 1


def test_list_bullet_ambiguous_numbers_go_to_review() -> None:
    from mining_accidents.adapters.wikidata import parse_list_article

    wikitext = (
        "== Kazalar ==\n=== 2099 ===\n"
        "* Ocak ayında TEST ocağında 46 işçiden 13 işçi göçük altında kalarak "
        "hayatını kaybetmiştir.\n"
    )
    drafts = parse_list_article(wikitext)
    deaths = next(d for d in drafts if d.field_name == "fatalities_current")
    assert deaths.extraction_method == "ai_assisted"  # ambiguous -> human review
    assert deaths.review_status == "needs_review"
    assert deaths.normalized_value == "13"  # last-number candidate for the reviewer
    date = next(d for d in drafts if d.field_name == "incident_start_datetime")
    assert date.normalized_value == "2099-01-01T00:00:00+03:00"
    assert next(d for d in drafts if d.field_name == "date_precision").normalized_value == "month"


def test_list_bullet_without_deaths_is_dropped() -> None:
    from mining_accidents.adapters.wikidata import parse_list_article

    wikitext = (
        "== Kazalar ==\n=== 2099 ===\n"
        "* 10 Mayıs 2099 tarihinde TEST ocağında göçük meydana geldi, işçiler kurtarıldı.\n"
    )
    assert parse_list_article(wikitext) == []


def test_isig_table_parsing() -> None:
    from mining_accidents.adapters.wikidata import parse_isig_table

    wikitext = (
        '{| class="wikitable"\n|+TEST tablo\n!Yıl\n!Sayı\n'
        "|-\n|2098\n|81\n|-\n|2099\n|93\n|-\n|'''Toplam'''\n|'''174'''\n|}"
    )
    assert parse_isig_table(wikitext) == [(2098, 81), (2099, 93)]
