"""İSİG Meclisi work-death reports (Tier 2) — monthly aggregate context.

Role in the evidence flow: aggregate context only. The Assembly publishes
monthly and annual counts of work deaths broken down by branch of work, by
cause, by age band and by province, but it publishes no per-incident rows.
Figures taken from here feed ``aggregate_occupational_statistics`` and never
incidents, claims or decisions, exactly as SGK aggregates do.

Assessment (recorded in docs/source_registry.csv, 2026-10-26): the reports are
open HTML with a real text layer, no robots.txt is served, and the footer of
every page grants reuse site-wide on condition that the source is cited, so
automated collection is permitted and attribution is required.

Handling rules this module enforces:

* Every monthly report ends with the names of the dead. Parsing stops at the
  memorial sentence, so no name can reach a figure, an excerpt or an export.
  The page as retrieved stays in ``data/raw/`` alone, which is never committed
  and never exported (privacy_and_persons_protocol.md §2).
* The Assembly states its counts as lower bounds ("en az"), compiled from the
  national press and from workplace networks, and counts all work deaths from
  all causes. Its figures are never a count of mining accidents and never a
  rate; the comparability note travels with every row.
* A figure is recorded only where its pattern matches the retrieved text. An
  unparsed report is reported as unparsed, never guessed at.
"""

from __future__ import annotations

import html
import re
import sqlite3
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from mining_accidents.adapters.base import ClaimDraft, SourceAdapter, SourceAssessment
from mining_accidents.adapters.wikidata import _http_get, _insert_document, _store_raw
from mining_accidents.database import utc_now_iso
from mining_accidents.provenance import sha256_bytes

ISIG_HOME = "https://isigmeclisi.org"
REPORT_INDEX = f"{ISIG_HOME}/is-cinayetleri-raporlari"
DEFAULT_RAW_DIR = Path("data/raw/isig")

#: Attribution the footer grant requires, carried on every stored document.
LICENCE_NOTES = (
    "İSİG Meclisi: free reuse on condition the source is cited "
    "(site-wide footer grant, assessed 2026-10-26). Attribution required."
)

#: What every figure from this source means, and what it does not.
COMPARABILITY_NOTES = (
    "İSİG Meclisi monthly report, taken from the Assembly's own page. A lower "
    "bound by its own statement ('en az'), compiled from the national press and "
    "from colleagues, families, unions, workplace doctors and local press. "
    "Counts all work deaths from all causes, including traffic and service "
    "vehicle crashes, heart attacks, violence and suicide, so it is NOT a count "
    "of mining accidents and NOT comparable to the per-incident register. Never "
    "a rate: no exposure denominator."
)

MONTHS_TR: dict[str, int] = {
    "Ocak": 1,
    "Şubat": 2,
    "Mart": 3,
    "Nisan": 4,
    "Mayıs": 5,
    "Haziran": 6,
    "Temmuz": 7,
    "Ağustos": 8,
    "Eylül": 9,
    "Ekim": 10,
    "Kasım": 11,
    "Aralık": 12,
}
_MONTH_ALT = "|".join(MONTHS_TR)

#: Where the names of the dead begin. The memorial phrase is matched first; the
#: bare verb is the fallback, and it needs a word boundary because "anıyoruz"
#: also sits inside ordinary words ("zorlanıyoruz"), which cut a July report
#: short of its own tables. Parsing never goes past the FIRST match: cutting
#: early can only lose a figure, while cutting late would admit a name.
NAME_ROLL_MARKERS: tuple[str, ...] = (
    r"saygıyla\s+anıyoruz",
    r"(?<!\w)anıyoruz",
)

#: Ordered patterns for the report's calendar year. Most specific first; a
#: report whose year no pattern yields is reported unparsed.
_YEAR_PATTERNS: tuple[str, ...] = (
    r"(\d{4})\s*yılının[^.:]{0,60}aylara göre dağılımı",
    r"(\d{4})\s*yılının\s+ilk\s",
    r"Böylece\s+(\d{4})\s*yılı",
)

#: Ordered patterns for the report's month, from its own section headings.
_MONTH_PATTERNS: tuple[str, ...] = (
    rf"({_MONTH_ALT})\s+ayında iş cinayetlerinin işkollarına göre",
    rf"({_MONTH_ALT})\s+ayında iş cinayetlerinin nedenlerine göre",
    rf"({_MONTH_ALT})\s+ayında en az \d+ iş cinayeti",
)

#: The branch-of-work breakdown, where the mining figure lives.
_BRANCH_HEADING = rf"({_MONTH_ALT})\s+ayında iş cinayetlerinin işkollarına göre[^:]*:"
_BRANCH_WINDOW = 2600

#: Mining is written either way across the years.
_MINING_PATTERNS: tuple[str, ...] = (
    r"Madencilik\s+işkolunda\s+(\d+)\s+(?:işçi|emekçi)",
    r"Maden\s+işkolunda\s+(\d+)\s+(?:işçi|emekçi)",
)


@dataclass(frozen=True)
class ParsedReport:
    """What one report's own text states, before it is tied to a document."""

    year: int
    month: int
    total_deaths: int | None = None
    mining_deaths: int | None = None
    total_excerpt: str | None = None
    mining_excerpt: str | None = None


@dataclass(frozen=True)
class MonthlyFigures:
    """One monthly report's figures, as published, with nothing inferred."""

    year: int
    month: int
    url: str
    source_document_id: int
    total_deaths: int | None = None
    mining_deaths: int | None = None
    total_excerpt: str | None = None
    mining_excerpt: str | None = None

    @property
    def period_start(self) -> str:
        return f"{self.year:04d}-{self.month:02d}-01"

    @property
    def period_end(self) -> str:
        last = _last_day(self.year, self.month)
        return f"{self.year:04d}-{self.month:02d}-{last:02d}"


def _last_day(year: int, month: int) -> int:
    import calendar

    return calendar.monthrange(year, month)[1]


def _plain_text(raw: bytes) -> str:
    """HTML to text: scripts and styles dropped, entities decoded, tags spaced."""
    markup = raw.decode("utf-8", errors="replace")
    markup = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", markup)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", markup))
    return re.sub(r"[ \t ]+", " ", text)


def _before_name_roll(text: str) -> str | None:
    """The report up to the memorial sentence, or None when it cannot be found.

    A report whose marker is absent is skipped rather than parsed, because the
    names cannot be located and a stored excerpt might then carry one.
    """
    for marker in NAME_ROLL_MARKERS:
        found = re.search(marker, text)
        if found:
            return text[: found.start()]
    return None


def _first_match(patterns: tuple[str, ...], text: str) -> re.Match[str] | None:
    for pattern in patterns:
        found = re.search(pattern, text)
        if found:
            return found
    return None


#: Clause boundaries. The branch and cause breakdowns are semicolon lists, so
#: splitting on full stops alone would quote half the page.
_CLAUSE_EDGE = re.compile(r"[.;:\u2026]")


def _clause_around(text: str, match: re.Match[str], cap: int = 160) -> str:
    """The clause holding a matched figure: a short, attributable quote."""
    window_start = max(0, match.start() - cap)
    edges = [m.end() for m in _CLAUSE_EDGE.finditer(text, window_start, match.start())]
    start = edges[-1] if edges else window_start
    end_edge = _CLAUSE_EDGE.search(text, match.end(), match.end() + cap)
    end = end_edge.start() if end_edge else min(len(text), match.end() + cap)
    return " ".join(text[start:end].split())


def parse_monthly_report(text: str) -> ParsedReport | None:
    """Read one report's month, its total and its mining figure, with quotes.

    Returns None when the year or the month cannot be read from the report's own
    headings, which is the only honest outcome: both are needed to date a row.
    """
    body = _before_name_roll(text)
    if body is None:
        return None
    year_match = _first_match(_YEAR_PATTERNS, body)
    month_match = _first_match(_MONTH_PATTERNS, body)
    if not year_match or not month_match:
        return None
    year = int(year_match.group(1))
    month_name = month_match.group(1)
    month = MONTHS_TR[month_name]

    total = total_excerpt = None
    total_patterns = (
        rf"{month_name}\s+ayında en az (\d+) iş cinayeti",
        rf"{month_name}\s+ayında en az (\d+) işçi",
        rf"{month_name}\s+ayında (\d+) iş cinayeti",
    )
    total_match = _first_match(total_patterns, body)
    if total_match:
        total = int(total_match.group(1))
        total_excerpt = _clause_around(body, total_match)

    # The mining figure is read only inside the branch-of-work breakdown, so an
    # annual table elsewhere on the page cannot be mistaken for this month's.
    mining = mining_excerpt = None
    heading = re.search(_BRANCH_HEADING, body)
    if heading:
        window = body[heading.end() : heading.end() + _BRANCH_WINDOW]
        mining_match = _first_match(_MINING_PATTERNS, window)
        if mining_match:
            mining = int(mining_match.group(1))
            mining_excerpt = _clause_around(window, mining_match)
    return ParsedReport(
        year=year,
        month=month,
        total_deaths=total,
        mining_deaths=mining,
        total_excerpt=total_excerpt,
        mining_excerpt=mining_excerpt,
    )


class ISIGAdapter(SourceAdapter):
    """Fetches the Assembly's monthly reports and reads their figures."""

    source_key = "isig_meclisi"
    adapter_version = "1.0.0"

    def __init__(self, raw_dir: str | Path = DEFAULT_RAW_DIR) -> None:
        self.raw_dir = Path(raw_dir)

    def assess(self) -> SourceAssessment:
        return SourceAssessment(
            source_key="isig_meclisi",
            tier_proposed=2,
            automated_collection_permitted="yes",
            access_notes=(
                "Open HTML, no registration or paywall. No robots.txt is served "
                "(checked 2026-10-26, HTTP 404), so there are no directives to "
                "honour. The site-wide footer grants free reuse on condition the "
                "source is cited, so attribution is required on every row."
            ),
            coverage_notes=(
                "Monthly and annual reports from 2013 to the present month. "
                "Aggregate only: month totals with breakdowns by branch of work, "
                "cause, age band and province, and no per-incident rows, so the "
                "figures feed aggregate_* tables and never incidents. Counts are "
                "the Assembly's own lower bounds and cover all work deaths from "
                "all causes, not mining accidents."
            ),
            format_risks=(
                "HTML with a real text layer, no PDF and no OCR. The one risk is "
                "personal: each report ends with the names of the dead, so "
                "parsing stops at the memorial sentence."
            ),
        )

    # ------------------------------------------------------------------
    # fetch
    # ------------------------------------------------------------------

    def discover_monthly_reports(self, pages: int = 1) -> list[tuple[str, str]]:
        """Index pages to (url, title) pairs for reports that look monthly."""
        found: list[tuple[str, str]] = []
        seen: set[str] = set()
        for page in range(1, max(pages, 1) + 1):
            params = {} if page == 1 else {"sayfa": str(page)}
            payload = _http_get(REPORT_INDEX, params, accept="text/html")
            _store_raw(self.raw_dir, payload, f"index-page-{page}")
            markup = payload.decode("utf-8", errors="replace")
            for href, label in re.findall(r'href="([0-9]{3,}-[^"]+)"[^>]*>([^<]{10,})', markup):
                title = html.unescape(label).strip()
                if not re.search(rf"({_MONTH_ALT})\s+ayında", title):
                    continue
                url = f"{ISIG_HOME}/{urllib.parse.quote(href, safe='/-?=')}"
                if url in seen:
                    continue
                seen.add(url)
                found.append((url, title))
        return found

    def fetch(  # type: ignore[override]
        self,
        conn: sqlite3.Connection,
        pages: int = 1,
        limit: int | None = None,
    ) -> list[int]:
        """Store the monthly reports as source documents; return their ids.

        Idempotent: a document already held under the same url and content hash
        is reused, so a re-run of the monthly check creates nothing new.
        """
        document_ids: list[int] = []
        reports = self.discover_monthly_reports(pages)
        for url, title in reports[: limit if limit is not None else len(reports)]:
            payload = _http_get(url, {}, accept="text/html")
            digest = sha256_bytes(payload)
            raw_path, _ = _store_raw(self.raw_dir, payload, f"report-{digest[:12]}")
            document_ids.append(
                _insert_document(
                    conn,
                    source_organization="İSİG Meclisi",
                    title=title[:300],
                    document_type="report",
                    url=url,
                    retrieved_at=utc_now_iso(),
                    language="tr",
                    content_hash=digest,
                    local_raw_path=str(raw_path),
                    licence_or_reuse_notes=LICENCE_NOTES,
                    attribution_required=1,
                    source_tier=2,
                    access_status="open",
                    notes="kind=isig_monthly_report",
                )
            )
        conn.commit()
        return document_ids

    # ------------------------------------------------------------------
    # parse
    # ------------------------------------------------------------------

    def parse(  # type: ignore[override]
        self, source_document_id: int, conn: sqlite3.Connection | None = None
    ) -> list[ClaimDraft]:
        """No claims: this source is aggregate, so it never states an incident.

        Aggregate figures are context, not evidence about a particular accident,
        and the registry rule for aggregate sources (SGK, and this one) is that
        they feed ``aggregate_*`` tables only. Use :meth:`monthly_figures`.
        """
        return []

    def monthly_figures(
        self, source_document_id: int, conn: sqlite3.Connection
    ) -> MonthlyFigures | None:
        """Read one stored report's figures, or None when it cannot be read."""
        row = conn.execute(
            "SELECT url, local_raw_path FROM source_documents WHERE source_document_id = ?",
            (source_document_id,),
        ).fetchone()
        if row is None:
            return None
        raw = Path(row["local_raw_path"]).read_bytes()
        parsed = parse_monthly_report(_plain_text(raw))
        if parsed is None:
            return None
        return MonthlyFigures(
            year=parsed.year,
            month=parsed.month,
            url=row["url"],
            source_document_id=source_document_id,
            total_deaths=parsed.total_deaths,
            mining_deaths=parsed.mining_deaths,
            total_excerpt=parsed.total_excerpt,
            mining_excerpt=parsed.mining_excerpt,
        )
