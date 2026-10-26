"""The monthly check: synthetic fixtures only, never a real report.

Role in the evidence flow: guards that discovery stays discovery. The check may
report, count and quote; it may not decide, publish or resolve a conflict.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from conftest import make_claim, make_incident, make_source_document
from mining_accidents import analysis, monitor
from mining_accidents.adapters.isig import MonthlyFigures, parse_monthly_report

#: A report in the shape the Assembly publishes, with invented figures. Two
#: traps are deliberate: "zorlanıyoruz" holds the memorial verb inside an
#: ordinary word before the tables, and a second mining line sits after the
#: memorial sentence where the names begin.
SYNTHETIC_REPORT = """
TEST sentetik rapor. Gerçek bir rapor değildir.
Mart ayında en az 99 iş cinayeti
Bilgi almakta zorlanıyoruz, bu yüzden sayılar alt sınırdır.
Böylece 2099 yılının ilk üç ayında iş cinayeti sayısı artmıştır.
2099 yılının ilk üç ayında iş cinayetlerinin aylara göre dağılımı şöyle:
Ocak ayında en az 50 işçi,
Şubat ayında en az 50 işçi,
Mart ayında en az 99 işçi iş cinayetlerinde hayatını kaybetti…
Mart ayında iş cinayetlerinin işkollarına göre dağılımı şöyle:
İnşaat, Yol işkolunda 40 işçi; Madencilik işkolunda 7 işçi; Metal işkolunda 2 işçi;
2099 yılının Mart ayında hayatını kaybeden 99 işçiyi saygıyla anıyoruz…
TEST Birinci Kisi, TEST Ikinci Kisi, Madencilik işkolunda 999 işçi
"""


def test_reads_the_month_its_total_and_its_mining_figure() -> None:
    parsed = parse_monthly_report(SYNTHETIC_REPORT)
    assert parsed is not None
    assert (parsed.year, parsed.month) == (2099, 3)
    assert parsed.total_deaths == 99
    assert parsed.mining_deaths == 7


def test_parsing_stops_where_the_names_begin() -> None:
    """The figure after the memorial sentence must never be read, nor a name."""
    parsed = parse_monthly_report(SYNTHETIC_REPORT)
    assert parsed is not None
    assert parsed.mining_deaths == 7, "read a figure from the memorial section"
    assert "TEST Birinci Kisi" not in (parsed.mining_excerpt or "")
    assert "TEST Birinci Kisi" not in (parsed.total_excerpt or "")


def test_an_ordinary_word_holding_the_marker_does_not_cut_the_report() -> None:
    """Regression: "zorlanıyoruz" once cut a real report short of its tables."""
    assert "zorlanıyoruz" in SYNTHETIC_REPORT
    parsed = parse_monthly_report(SYNTHETIC_REPORT)
    assert parsed is not None and parsed.mining_deaths == 7


def test_a_report_whose_month_cannot_be_read_is_not_guessed_at() -> None:
    assert parse_monthly_report("TEST metin, hiçbir tablo yok. saygıyla anıyoruz") is None


def _published_csv(tmp_path: Path) -> Path:
    export_dir = tmp_path / "public"
    export_dir.mkdir()
    (export_dir / "incidents.csv").write_text(
        "public_incident_id,canonical_title_tr,incident_start_datetime,province_code,"
        "fatalities_current\n"
        "TEST-2099-0001,TEST olay kaydı,2099-05-10T00:00:00+03:00,67,3\n",
        encoding="utf-8",
    )
    return export_dir


def _stated_event(conn: sqlite3.Connection, date: str, province: str, deaths: str) -> int:
    doc = make_source_document(conn, url=f"file:///dev/null/TEST-{date}", content_hash="1" * 64)
    incident = make_incident(conn)
    for field, value in (
        ("incident_start_datetime", date),
        ("province_code", province),
        ("fatalities_current", deaths),
    ):
        make_claim(conn, doc, incident_id=incident, field_name=field, normalized_value=value)
    return incident


def test_an_event_the_register_does_not_hold_is_named_as_a_candidate(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    _stated_event(conn, "2099-09-01T00:00:00+03:00", "45", "5")
    records = monitor.published_records(_published_csv(tmp_path))
    queue, settled, thin = monitor.find_candidates(conn, records, known=[])
    assert [c.reason for c in queue] == ["absent_from_register"]
    assert queue[0].province_codes == ("45",)
    assert (settled, thin) == ([], [])


def test_a_toll_that_differs_is_reported_against_the_published_record(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    _stated_event(conn, "2099-05-10T00:00:00+03:00", "67", "9")
    records = monitor.published_records(_published_csv(tmp_path))
    queue, _, _ = monitor.find_candidates(conn, records, known=[])
    assert [c.reason for c in queue] == ["toll_differs"]
    assert queue[0].published_incident_ids == ("TEST-2099-0001",)
    assert queue[0].published_fatalities == "3"
    assert queue[0].fatalities == ("9",)


def test_an_event_already_held_is_not_reported(conn: sqlite3.Connection, tmp_path: Path) -> None:
    _stated_event(conn, "2099-05-11T00:00:00+03:00", "67", "3")
    records = monitor.published_records(_published_csv(tmp_path))
    assert monitor.find_candidates(conn, records, known=[]) == ([], [], [])


def test_a_month_precision_date_does_not_contradict_an_exact_one(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """A source saying "May 2099" has not disagreed with 10 May 2099."""
    incident = _stated_event(conn, "2099-05-01T00:00:00+03:00", "67", "3")
    doc = make_source_document(conn, url="file:///dev/null/TEST-prec", content_hash="3" * 64)
    make_claim(
        conn, doc, incident_id=incident, field_name="date_precision", normalized_value="month"
    )
    records = monitor.published_records(_published_csv(tmp_path))
    assert monitor.find_candidates(conn, records, known=[]) == ([], [], [])


def test_a_record_of_the_other_kind_is_not_reported_as_missing(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Environmental records are published too, in their own file."""
    _stated_event(conn, "2099-07-04T00:00:00+03:00", "28", "")
    export_dir = _published_csv(tmp_path)
    (export_dir / "environmental_incidents.csv").write_text(
        "public_incident_id,canonical_title_tr,incident_start_datetime,province_code\n"
        "TEST-ENV-2099-0001,TEST atık barajı,2099-07-04T00:00:00+03:00,28\n",
        encoding="utf-8",
    )
    records = monitor.published_records(export_dir)
    assert monitor.find_candidates(conn, records, known=[]) == ([], [], [])


def test_an_undated_source_entry_is_not_called_missing(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Without a date the check cannot place the event, so it claims neither way."""
    doc = make_source_document(conn, url="file:///dev/null/TEST-thin", content_hash="4" * 64)
    incident = make_incident(conn)
    make_claim(conn, doc, incident_id=incident, field_name="province_code", normalized_value="67")
    records = monitor.published_records(_published_csv(tmp_path))
    queue, settled, thin = monitor.find_candidates(conn, records, known=[])
    assert (queue, settled) == ([], [])
    assert [c.reason for c in thin] == ["undated_source_entry"]


def test_a_declared_disagreement_leaves_the_queue_but_stays_visible(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Settled matters are not put to a reviewer again, and are not hidden."""
    _stated_event(conn, "2099-09-01T00:00:00+03:00", "45", "5")
    records = monitor.published_records(_published_csv(tmp_path))
    known = [
        {
            "stated_date": "2099-09-01T00:00:00+03:00",
            "stated_province_code": "45",
            "published_incident_id": "TEST-2099-0001",
            "standing": "decided",
            "recorded_on": "2099-10-01",
            "open_question": "99",
            "note": "TEST synthetic declaration.",
        }
    ]
    queue, settled, _ = monitor.find_candidates(conn, records, known=known)
    assert queue == []
    assert [c.reason for c in settled] == ["absent_from_register"]
    assert "decided" in (settled[0].settled_by or "")
    assert "open question 99" in (settled[0].settled_by or "")


def test_the_check_records_no_decision_and_publishes_nothing(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """The whole point: discovery may not become a canonical value."""
    _stated_event(conn, "2099-09-01T00:00:00+03:00", "45", "5")
    records = monitor.published_records(_published_csv(tmp_path))
    monitor.find_candidates(conn, records, known=[])
    assert conn.execute("SELECT COUNT(*) FROM claim_decisions").fetchone()[0] == 0
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM incidents "
            "WHERE publication_status IN ('publishable', 'published')"
        ).fetchone()[0]
        == 0
    )


def _figures(conn: sqlite3.Connection) -> list[MonthlyFigures]:
    doc = make_source_document(conn, url="file:///dev/null/TEST-isig", content_hash="2" * 64)
    return [
        MonthlyFigures(
            year=2099,
            month=3,
            url="file:///dev/null/TEST-isig",
            source_document_id=doc,
            total_deaths=99,
            mining_deaths=7,
            total_excerpt="Mart ayında en az 99 iş cinayeti",
            mining_excerpt="Madencilik işkolunda 7 işçi",
        )
    ]


def test_monthly_aggregates_are_written_once_and_carry_their_limits(
    conn: sqlite3.Connection,
) -> None:
    figures = _figures(conn)
    assert monitor.record_monthly_aggregates(conn, figures) == 2
    assert monitor.record_monthly_aggregates(conn, figures) == 0, "second run duplicated rows"
    rows = conn.execute(
        "SELECT classification_code, numerator, comparability_notes "
        "FROM aggregate_occupational_statistics WHERE reporting_institution = 'İSİG Meclisi' "
        "ORDER BY classification_code"
    ).fetchall()
    assert [(r["classification_code"], r["numerator"]) for r in rows] == [
        ("all_branches", 99.0),
        ("madencilik", 7.0),
    ]
    for row in rows:
        assert "NOT a count of mining accidents" in row["comparability_notes"]


def test_monthly_rows_stay_out_of_the_published_annual_series(
    conn: sqlite3.Connection,
) -> None:
    """The gap chart's series is an editorial selection, not a prefix match."""
    monitor.record_monthly_aggregates(conn, _figures(conn))
    assert analysis.isig_aggregates(conn) == []


def test_a_month_with_no_candidates_still_says_what_it_cannot_tell_you(
    tmp_path: Path,
) -> None:
    report = monitor.CheckReport(
        checked_at="2099-03-01T00:00:00Z",
        swept_sources=list(monitor.SWEPT_SOURCES),
        published_records=1,
        published_deaths=3,
        newest_published_incident="2099-05-10",
    )
    json_path, md_path = monitor.write_report(report, tmp_path)
    assert json_path.exists() and md_path.exists()
    prose = md_path.read_text(encoding="utf-8")
    assert "It is not a statement that no accident happened" in prose
    assert report.to_dict()["candidate_count"] == 0
