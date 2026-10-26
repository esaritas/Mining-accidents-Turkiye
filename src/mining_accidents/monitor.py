"""The monthly check: what the open sources state now, against what is published.

Role in the evidence flow: discovery only, at the very front of it. The check
reads the assessed sources into a throwaway database, compares what they state
against the published export, and writes a report naming the candidates. It
records no reviewer decision and no canonical value, it changes no published
record, and nothing it finds reaches the public dataset except the ordinary way:
a reviewer's decision on a claim quoted from a source document.

Three deliberate limits:

* Only sources whose registry assessment permits automated collection are swept
  here, which today means Wikidata, Wikipedia and the İSİG Meclisi reports. The
  news assessment requires each article to be retrieved individually rather than
  crawled, so news discovery is a human-directed step and is not run from here.
* A month in which the check finds nothing means the swept sources published
  nothing new, never that nothing happened. The report says so in writing.
* A disagreement the register has already decided stays visible in the report
  but outside the review queue, listed with the decision that settled it. The
  check never resolves a conflict and never hides one.

Length: this module runs past the project's ~400 line guide because the check,
its report and the summary the page reads are one workflow. Splitting them would
scatter the single rule they exist to enforce, that discovery never decides.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from mining_accidents.adapters.isig import COMPARABILITY_NOTES as _ISIG_NOTE
from mining_accidents.adapters.isig import ISIGAdapter, MonthlyFigures
from mining_accidents.database import utc_now_iso
from mining_accidents.normalization import normalize_tr

DEFAULT_EXPORT_DIR = Path("data/public")
DEFAULT_REPORT_DIR = Path("data/interim/monthly_check")
DEFAULT_KNOWN_PATH = Path("docs/monitoring_known_disagreements.csv")

#: The register's own duplicate rule for an exactly dated source statement.
BLOCKING_DAYS = 3

#: What the check swept, named in the report and on the dashboard.
SWEPT_SOURCES = ("wikidata", "wikipedia", "isig_meclisi")

#: Published files the check compares against. A register of two kinds needs
#: both, or every environmental record reads as a missing accident.
PUBLISHED_FILES = (
    ("incidents.csv", "fatal_accident"),
    ("environmental_incidents.csv", "environmental"),
)

#: Said once in the report rather than implied by an empty list.
ABSENCE_NOTE = (
    "A candidate list that is empty means the swept sources published nothing "
    "this register does not already hold. It is not a statement that no accident "
    "happened. Incident-level recency rests on news reporting, which is "
    "retrieved article by article in review and is not swept here."
)


@dataclass(frozen=True)
class StatedEvent:
    """One event as the swept sources state it, with nothing resolved."""

    dates: tuple[str, ...] = ()
    date_precisions: tuple[str, ...] = ()
    province_codes: tuple[str, ...] = ()
    fatalities: tuple[str, ...] = ()
    titles: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    @property
    def coarsest_precision(self) -> str:
        """The widest precision any source states, which is the safe one to use.

        A source saying "August 2004" has not contradicted a register holding
        9 August 2004, so matching it day-to-day would invent a disagreement.
        """
        for precision in ("year", "month"):
            if precision in self.date_precisions:
                return precision
        return "exact_date"


@dataclass(frozen=True)
class Candidate:
    """Something a reviewer should look at, with the reason it surfaced."""

    source_key: str
    reason: str
    dates: tuple[str, ...]
    province_codes: tuple[str, ...]
    fatalities: tuple[str, ...]
    titles: tuple[str, ...]
    published_incident_ids: tuple[str, ...] = ()
    published_fatalities: str | None = None
    settled_by: str | None = None


@dataclass
class CheckReport:
    """One month's findings. Counts and quotes only, never a conclusion."""

    checked_at: str
    swept_sources: list[str]
    published_records: int
    published_deaths: int
    newest_published_incident: str | None
    candidates: list[Candidate] = field(default_factory=list)
    known_disagreements: list[Candidate] = field(default_factory=list)
    thin_source_entries: list[Candidate] = field(default_factory=list)
    isig_months: list[dict[str, object]] = field(default_factory=list)
    unreadable_documents: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=lambda: [ABSENCE_NOTE])

    @property
    def candidate_count(self) -> int:
        """The review queue alone. Settled and unplaceable entries are not work."""
        return len(self.candidates)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["candidate_count"] = self.candidate_count
        return payload


# ----------------------------------------------------------------------
# the published side
# ----------------------------------------------------------------------


def published_records(export_dir: str | Path = DEFAULT_EXPORT_DIR) -> list[dict[str, str]]:
    """The register as readers see it: both kinds of published record."""
    records: list[dict[str, str]] = []
    for filename, kind in PUBLISHED_FILES:
        path = Path(export_dir) / filename
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                records.append({**row, "record_kind": kind})
    return records


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _date_agrees(held: date, stated: date, precision: str) -> bool:
    """Does a published date agree with a stated one, at the stated precision?"""
    if precision == "year":
        return held.year == stated.year
    if precision == "month":
        return (held.year, held.month) == (stated.year, stated.month)
    return abs((held - stated).days) <= BLOCKING_DAYS


def _titles_of(record: dict[str, str]) -> set[str]:
    return {
        normalize_tr(record.get(key) or "")
        for key in ("canonical_title_tr", "canonical_title_en")
        if (record.get(key) or "").strip()
    }


def match_by_blocking_key(
    records: list[dict[str, str]], event: StatedEvent
) -> dict[str, str] | None:
    """Same province, date agreeing at the precision the source states."""
    precision = event.coarsest_precision
    wanted = [d for d in (_as_date(v) for v in event.dates) if d]
    if not wanted:
        return None
    for record in records:
        if event.province_codes and record.get("province_code") not in event.province_codes:
            continue
        held = _as_date(record.get("incident_start_datetime"))
        if held and any(_date_agrees(held, d, precision) for d in wanted):
            return record
    return None


def match_by_title(records: list[dict[str, str]], event: StatedEvent) -> list[dict[str, str]]:
    """Records whose own title matches one the source states for this event."""
    stated = {normalize_tr(t) for t in event.titles if t.strip()}
    if not stated:
        return []
    return [record for record in records if _titles_of(record) & stated]


# ----------------------------------------------------------------------
# the source side
# ----------------------------------------------------------------------

_EVENT_FIELDS = (
    "incident_start_datetime",
    "date_precision",
    "province_code",
    "fatalities_current",
)


def source_events(conn: sqlite3.Connection) -> list[StatedEvent]:
    """Group the scratch database's claims into one entry per event.

    Every distinct value a source states is kept. Where sources disagree the
    disagreement is reported, never resolved: that is a reviewer's act.
    """
    buckets: dict[int, dict[str, list[str]]] = {}
    rows = conn.execute(
        """
        SELECT c.incident_id, c.field_name, c.normalized_value, c.raw_value,
               d.source_organization
        FROM claims c
        JOIN source_documents d ON d.source_document_id = c.source_document_id
        WHERE c.incident_id IS NOT NULL
        ORDER BY c.incident_id, c.claim_id
        """
    )
    for row in rows:
        entry = buckets.setdefault(
            int(row["incident_id"]), {name: [] for name in (*_EVENT_FIELDS, "titles", "sources")}
        )
        value = row["normalized_value"] or row["raw_value"]
        name = row["field_name"]
        if name.startswith("canonical_title"):
            name = "titles"
        if name in entry and value and value not in entry[name]:
            entry[name].append(value)
        organization = row["source_organization"]
        if organization and organization not in entry["sources"]:
            entry["sources"].append(organization)
    return [
        StatedEvent(
            dates=tuple(entry["incident_start_datetime"]),
            date_precisions=tuple(entry["date_precision"]),
            province_codes=tuple(entry["province_code"]),
            fatalities=tuple(entry["fatalities_current"]),
            titles=tuple(entry["titles"]),
            sources=tuple(entry["sources"]),
        )
        for _, entry in sorted(buckets.items())
    ]


# ----------------------------------------------------------------------
# classification
# ----------------------------------------------------------------------


def load_known_disagreements(
    path: str | Path = DEFAULT_KNOWN_PATH,
) -> list[dict[str, str]]:
    """Disagreements a reviewer has already decided, declared in the repository.

    A row keeps a settled matter out of the review queue without hiding it: the
    report still prints it, with the decision and open question that settled it.
    """
    file = Path(path)
    if not file.exists():
        return []
    with file.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _settled_by(known: list[dict[str, str]], candidate: Candidate) -> str | None:
    for row in known:
        stated_date = (row.get("stated_date") or "").strip()
        stated_province = (row.get("stated_province_code") or "").strip()
        if stated_date and stated_date not in candidate.dates:
            continue
        if stated_province and stated_province not in candidate.province_codes:
            continue
        if not stated_date and not stated_province:
            continue
        clean = {key: (value or "").strip() for key, value in row.items()}
        parts = [clean.get("published_incident_id", ""), clean.get("standing", "")]
        if clean.get("recorded_on"):
            parts.append(f"recorded {clean['recorded_on']}")
        if clean.get("open_question"):
            parts.append(f"open question {clean['open_question']}")
        return " · ".join(p for p in parts if p) or "declared"
    return None


def classify(
    records: list[dict[str, str]], event: StatedEvent, source_key: str
) -> Candidate | None:
    """What, if anything, a reviewer should be told about one stated event."""
    base = {
        "source_key": source_key,
        "dates": event.dates,
        "province_codes": event.province_codes,
        "fatalities": event.fatalities,
        "titles": event.titles,
    }
    match = match_by_blocking_key(records, event)
    if match is not None:
        held = (match.get("fatalities_current") or "").strip()
        stated = {f for f in event.fatalities if f}
        if held and stated and held not in stated:
            return Candidate(
                reason="toll_differs",
                published_incident_ids=(match.get("public_incident_id") or "",),
                published_fatalities=held,
                **base,
            )
        return None
    titled = match_by_title(records, event)
    if titled:
        # The register holds a record under this very name. A source that states
        # no date has not contradicted it, so nothing is reported unless the
        # dates or the tolls actually disagree.
        ids = tuple(r.get("public_incident_id") or "" for r in titled)
        held = {(r.get("fatalities_current") or "").strip() for r in titled} - {""}
        stated = {f for f in event.fatalities if f}
        if stated and held and not stated & held:
            return Candidate(
                reason="toll_differs",
                published_incident_ids=ids,
                published_fatalities=", ".join(sorted(held)),
                **base,
            )
        if any(_as_date(d) for d in event.dates):
            return Candidate(reason="date_differs", published_incident_ids=ids, **base)
        return None
    if not any(_as_date(d) for d in event.dates):
        # No date at all: the check cannot place the event, so it can neither
        # claim it is missing nor claim the register holds it (open question 25).
        return Candidate(reason="undated_source_entry", **base)
    return Candidate(reason="absent_from_register", **base)


def find_candidates(
    conn: sqlite3.Connection,
    records: list[dict[str, str]],
    source_key: str = "wikidata",
    known: list[dict[str, str]] | None = None,
) -> tuple[list[Candidate], list[Candidate], list[Candidate]]:
    """Split what the sources state into review queue, settled, and unplaceable."""
    declared = known if known is not None else load_known_disagreements()
    queue: list[Candidate] = []
    settled: list[Candidate] = []
    thin: list[Candidate] = []
    for event in source_events(conn):
        if not event.dates and not event.province_codes and not event.titles:
            continue
        candidate = classify(records, event, source_key)
        if candidate is None:
            continue
        if candidate.reason == "undated_source_entry":
            thin.append(candidate)
            continue
        reference = _settled_by(declared, candidate)
        if reference:
            settled.append(
                Candidate(**{**asdict(candidate), "settled_by": reference})  # type: ignore[arg-type]
            )
        else:
            queue.append(candidate)
    return queue, settled, thin


# ----------------------------------------------------------------------
# İSİG monthly context
# ----------------------------------------------------------------------


def register_deaths_in_month(records: list[dict[str, str]], year: int, month: int) -> int:
    """Published deaths dated inside one calendar month."""
    total = 0
    for record in records:
        held = _as_date(record.get("incident_start_datetime"))
        if held and held.year == year and held.month == month:
            try:
                total += int(record.get("fatalities_current") or 0)
            except ValueError:
                continue
    return total


def sweep_isig(
    conn: sqlite3.Connection,
    records: list[dict[str, str]],
    pages: int = 1,
    limit: int | None = 3,
    raw_dir: str | Path | None = None,
) -> tuple[list[dict[str, object]], list[str], list[MonthlyFigures]]:
    """The Assembly's own monthly figures, beside what this register publishes.

    The two numbers measure different things, which is the point of showing them
    together: the Assembly counts all miner work deaths from all causes, this
    register counts deaths in reviewed published incidents. The difference is
    loss not represented here, not loss no source recorded.
    """
    adapter = ISIGAdapter(raw_dir) if raw_dir else ISIGAdapter()
    months: list[dict[str, object]] = []
    unreadable: list[str] = []
    figures: list[MonthlyFigures] = []
    for doc_id in adapter.fetch(conn, pages=pages, limit=limit):
        parsed = adapter.monthly_figures(doc_id, conn)
        if parsed is None:
            row = conn.execute(
                "SELECT url FROM source_documents WHERE source_document_id = ?", (doc_id,)
            ).fetchone()
            unreadable.append(str(row["url"]) if row else f"document {doc_id}")
            continue
        figures.append(parsed)
        months.append(
            {
                "period_start": parsed.period_start,
                "period_end": parsed.period_end,
                "isig_mining_deaths": parsed.mining_deaths,
                "isig_all_branches_deaths": parsed.total_deaths,
                "register_deaths_published": register_deaths_in_month(
                    records, parsed.year, parsed.month
                ),
                "url": parsed.url,
                "mining_excerpt": parsed.mining_excerpt,
            }
        )
    return months, unreadable, figures


def record_monthly_aggregates(conn: sqlite3.Connection, figures: list[MonthlyFigures]) -> int:
    """Write the Assembly's monthly figures into the aggregate context table.

    Aggregate context only, as the registry requires of aggregate sources, and
    distinguishable from the legacy annual series by institution and by carrying
    an explicit branch classification, so neither can be mixed into the other.
    """
    written = 0
    for figure in figures:
        for code, value, excerpt in (
            ("madencilik", figure.mining_deaths, figure.mining_excerpt),
            ("all_branches", figure.total_deaths, figure.total_excerpt),
        ):
            if value is None:
                continue
            exists = conn.execute(
                "SELECT 1 FROM aggregate_occupational_statistics "
                "WHERE reporting_institution = ? AND period_start = ? "
                "AND classification_code = ?",
                ("İSİG Meclisi", figure.period_start, code),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                "INSERT INTO aggregate_occupational_statistics ("
                "reporting_institution, period_start, period_end, "
                "classification_system, classification_code, numerator, unit, "
                "source_document_id, comparability_notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "İSİG Meclisi",
                    figure.period_start,
                    figure.period_end,
                    "isig_branch_of_work",
                    code,
                    float(value),
                    "deaths",
                    figure.source_document_id,
                    f'{_ISIG_NOTE} Quoted: "{excerpt}".' if excerpt else _ISIG_NOTE,
                ),
            )
            written += 1
    conn.commit()
    return written


# ----------------------------------------------------------------------
# the report
# ----------------------------------------------------------------------


def newest_published(records: list[dict[str, str]]) -> str | None:
    dates = [d for d in (_as_date(r.get("incident_start_datetime")) for r in records) if d]
    return max(dates).isoformat() if dates else None


def total_published_deaths(records: list[dict[str, str]]) -> int:
    total = 0
    for record in records:
        try:
            total += int(record.get("fatalities_current") or 0)
        except ValueError:
            continue
    return total


def write_report(
    report: CheckReport, report_dir: str | Path = DEFAULT_REPORT_DIR
) -> tuple[Path, Path]:
    """Write the month's report as data and as prose; return both paths."""
    directory = Path(report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = report.checked_at[:7]
    json_path = directory / f"{stem}.json"
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    md_path = directory / f"{stem}.md"
    md_path.write_text(_as_markdown(report), encoding="utf-8")
    return json_path, md_path


def _candidate_line(candidate: Candidate) -> str:
    bits = [
        f"**{' / '.join(t for t in candidate.titles if t) or 'untitled in the source'}**",
        f"({candidate.reason})",
        f"stated date {', '.join(candidate.dates) or 'none'}",
        f"province {', '.join(candidate.province_codes) or 'none'}",
        f"deaths stated {', '.join(candidate.fatalities) or 'none'}",
    ]
    if candidate.published_fatalities:
        bits.append(f"published here {candidate.published_fatalities}")
    if any(candidate.published_incident_ids):
        bits.append(f"record {', '.join(i for i in candidate.published_incident_ids if i)}")
    if candidate.settled_by:
        bits.append(f"settled by {candidate.settled_by}")
    return "- " + "; ".join(bits)


def _as_markdown(report: CheckReport) -> str:
    lines = [
        f"# Monthly source check, {report.checked_at[:10]}",
        "",
        f"Swept: {', '.join(report.swept_sources)}.",
        f"Published register at the time of the check: {report.published_records} records, "
        f"{report.published_deaths} deaths, newest dated "
        f"{report.newest_published_incident or 'unknown'}.",
        "",
        f"## For review ({report.candidate_count})",
        "",
    ]
    if not report.candidates:
        lines.append("Nothing. The swept sources state nothing this register does not hold.")
    lines += [_candidate_line(c) for c in report.candidates]
    if report.known_disagreements:
        lines += [
            "",
            f"## Already known ({len(report.known_disagreements)})",
            "",
            "Disagreements between the sources and the register that are already on the "
            "record, each with how it stands: decided, or disclosed and still open. Listed "
            "so they stay visible, and kept out of the queue above so the same matter is "
            "not put to a reviewer every month.",
            "",
        ]
        lines += [_candidate_line(c) for c in report.known_disagreements]
    if report.thin_source_entries:
        lines += [
            "",
            f"## Too thin to place ({len(report.thin_source_entries)})",
            "",
            "Source entries stating no date. The check can neither call them missing "
            "nor confirm the register holds them (open question 25).",
            "",
        ]
        lines += [_candidate_line(c) for c in report.thin_source_entries]
    lines += ["", "## İSİG Meclisi monthly figures beside this register", ""]
    if report.isig_months:
        lines += [
            "| Month | İSİG mining deaths | İSİG all branches | Published here |",
            "|---|---|---|---|",
        ]
        for month in report.isig_months:
            lines.append(
                f"| {str(month['period_start'])[:7]} | {month['isig_mining_deaths']} | "
                f"{month['isig_all_branches_deaths']} | {month['register_deaths_published']} |"
            )
        lines += [
            "",
            "The two columns count different populations and are never added or "
            "subtracted. The Assembly counts all miner work deaths from all causes and "
            "states its figures as lower bounds.",
        ]
    else:
        lines.append("No monthly report could be read this run.")
    if report.unreadable_documents:
        lines += ["", "## Documents that could not be read", ""]
        lines += [f"- {url}" for url in report.unreadable_documents]
    lines += ["", "## What this check does not tell you", ""]
    lines += [f"- {note}" for note in report.notes]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------
# what the page reads
# ----------------------------------------------------------------------


def load_latest_report(report_dir: str | Path = DEFAULT_REPORT_DIR) -> dict[str, object] | None:
    """The most recent month's report, or None when the check has never run."""
    directory = Path(report_dir)
    reports = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if not reports:
        return None
    return json.loads(reports[-1].read_text(encoding="utf-8"))


def outstanding_candidates(
    report: dict[str, object], records: list[dict[str, str]]
) -> list[dict[str, object]]:
    """Review-queue candidates the current export still does not hold.

    Re-checked against the export rather than taken from the report, so a
    candidate that has since been reviewed and published stops being counted
    without waiting for the next check to run.
    """
    still: list[dict[str, object]] = []
    for candidate in report.get("candidates", []) or []:  # type: ignore[union-attr]
        event = StatedEvent(
            dates=tuple(candidate.get("dates") or ()),
            date_precisions=tuple(candidate.get("date_precisions") or ()),
            province_codes=tuple(candidate.get("province_codes") or ()),
            fatalities=tuple(candidate.get("fatalities") or ()),
            titles=tuple(candidate.get("titles") or ()),
        )
        if classify(records, event, str(candidate.get("source_key") or "")) is not None:
            still.append(candidate)
    return still


def summary(
    report_dir: str | Path = DEFAULT_REPORT_DIR,
    export_dir: str | Path = DEFAULT_EXPORT_DIR,
) -> dict[str, object]:
    """The check's own facts, for the page: when it ran and what is waiting.

    Counts only. A candidate has no reviewed standing, so it is never named,
    dated or given a death toll here.
    """
    records = published_records(export_dir)
    block: dict[str, object] = {
        "schedule": "monthly",
        "swept_sources": list(SWEPT_SOURCES),
        "newest_published_incident": newest_published(records),
        "last_checked": None,
        "candidates_waiting": None,
        "isig_latest_month": None,
    }
    report = load_latest_report(report_dir)
    if report is None:
        return block
    block["last_checked"] = report.get("checked_at")
    block["candidates_waiting"] = len(outstanding_candidates(report, records))
    months = report.get("isig_months") or []
    if months:
        latest = max(months, key=lambda m: str(m.get("period_start")))  # type: ignore[union-attr]
        block["isig_latest_month"] = {
            "period": str(latest.get("period_start"))[:7],
            "isig_mining_deaths": latest.get("isig_mining_deaths"),
            "register_deaths_published": latest.get("register_deaths_published"),
        }
    return block


# ----------------------------------------------------------------------
# the run
# ----------------------------------------------------------------------


def run_check(
    scratch_conn: sqlite3.Connection,
    export_dir: str | Path = DEFAULT_EXPORT_DIR,
    *,
    sweep_seed: bool = True,
    isig_pages: int = 1,
    isig_limit: int | None = 3,
    raw_dir: str | Path | None = None,
    known_path: str | Path = DEFAULT_KNOWN_PATH,
) -> tuple[CheckReport, list[MonthlyFigures]]:
    """Run the check against a throwaway database; return the report.

    ``scratch_conn`` must be a database the caller is willing to discard. The
    seed ingest runs with no reviewer, so it writes evidence and makes no
    decisions, and the working register is never opened.
    """
    records = published_records(export_dir)
    report = CheckReport(
        checked_at=utc_now_iso(),
        swept_sources=list(SWEPT_SOURCES),
        published_records=len(records),
        published_deaths=total_published_deaths(records),
        newest_published_incident=newest_published(records),
    )
    if sweep_seed:
        from mining_accidents import ingest

        ingest.ingest_wikidata(scratch_conn, reviewer=None, publish=False)
        queue, settled, thin = find_candidates(
            scratch_conn, records, known=load_known_disagreements(known_path)
        )
        report.candidates = queue
        report.known_disagreements = settled
        report.thin_source_entries = thin
    months, unreadable, figures = sweep_isig(
        scratch_conn, records, pages=isig_pages, limit=isig_limit, raw_dir=raw_dir
    )
    report.isig_months = months
    report.unreadable_documents = unreadable
    return report, figures


def stale_after(reference: str | None, days: int = 45) -> bool:
    """Has the check gone quiet for longer than a month and a half?"""
    start = _as_date(reference)
    return start is None or (datetime.now().date() - start) > timedelta(days=days)
