"""Review-packet generator.

Role in the evidence flow: turns the claims gathered for one incident into a
structured markdown worksheet a human reviewer completes (see
docs/manual_review_protocol.md). Packets present evidence and conflicts; they
never pre-resolve anything.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_OUTPUT_DIR = Path("data/review_packets")

SECTION_TEMPLATE = """# Review packet — {identity}

> Generated worksheet. Complete per docs/manual_review_protocol.md.
> Decisions are recorded in the database via review tooling, never by editing
> this file; the completed packet is filed in data/reviewed/ for audit.

## 1. Candidate incident identity

{identity_block}

## 2. Source inventory

{source_inventory}

## 3. Extracted claims

{claims_table}

## 4. Conflicts

{conflicts_block}

## 5. Proposed canonical values

| Field | Proposed value | Supporting claim id(s) | Notes |
|---|---|---|---|
| incident_start_datetime | | | |
| province_code | | | |
| fatalities_current | | | |

## 6. Unresolved questions

- [ ] (list questions that require editorial input; register lasting ones in docs/open_questions.md)

## 7. Cause classifications (four axes — source-backed only)

| Axis | Code | Supporting claim id | Assertion status |
|---|---|---|---|
| hazard | | | |
| event_mechanism | | | |
| mode_of_harm | | | |
| contributing_condition | | | |

## 8. Location & precision

- Coordinates (WGS84): —
- coordinate_precision: —
- location_uncertainty_m: —
- Supporting claim id: —
- Privacy check (informal operations — privacy protocol §5): [ ] done

## 9. Publication recommendation

- [ ] publishable — all seven publication rules satisfied
- [ ] not yet — blockers: —

## 10. Reviewer sign-off

| Role | Identity | Date | Signature/handle |
|---|---|---|---|
| Content reviewer | | | |
| Editorial approver | | | |
"""

#: Selection criteria for the twelve pilot slots (criterion only — populating
#: them requires collected source documents, outside the foundation build).
PILOT_SLOTS: list[tuple[str, str]] = [
    ("PILOT-01", "large casualty count"),
    ("PILOT-02", "small casualty count"),
    ("PILOT-03", "underground coal mining"),
    ("PILOT-04", "metal mining"),
    ("PILOT-05", "quarrying"),
    ("PILOT-06", "open-pit operation"),
    ("PILOT-07", "informal/illegal operation"),
    ("PILOT-08", "explosion event"),
    ("PILOT-09", "collapse event"),
    ("PILOT-10", "flooding/inrush event"),
    ("PILOT-11", "machinery or transport event"),
    ("PILOT-12", "conflicting local sources"),
]


def _claims_table(conn: sqlite3.Connection, incident_id: int) -> str:
    rows = conn.execute(
        """
        SELECT c.claim_id, c.field_name, c.raw_value, c.normalized_value,
               c.assertion_status, c.review_status, c.extraction_method,
               sd.source_organization, sd.title
        FROM claims c JOIN source_documents sd ON sd.source_document_id = c.source_document_id
        WHERE c.incident_id = ?
        ORDER BY c.field_name, c.claim_id
        """,
        (incident_id,),
    ).fetchall()
    if not rows:
        return "_No claims linked to this incident yet._"
    lines = [
        "| Claim | Field | Raw | Normalized | Assertion | Review | Method | Source |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['claim_id']} | {r['field_name']} | {r['raw_value'] or ''} "
            f"| {r['normalized_value'] or ''} | {r['assertion_status']} "
            f"| {r['review_status']} | {r['extraction_method']} "
            f"| {r['source_organization']}: {r['title']} |"
        )
    return "\n".join(lines)


def _source_inventory(conn: sqlite3.Connection, incident_id: int) -> str:
    rows = conn.execute(
        """
        SELECT DISTINCT sd.source_document_id, sd.source_organization, sd.title,
               sd.document_type, sd.publication_date, sd.source_tier
        FROM source_documents sd
        JOIN claims c ON c.source_document_id = sd.source_document_id
        WHERE c.incident_id = ?
        ORDER BY sd.source_document_id
        """,
        (incident_id,),
    ).fetchall()
    if not rows:
        return "_No source documents linked yet._"
    lines = [
        "| Doc | Organization | Title | Type | Published | Tier |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['source_document_id']} | {r['source_organization']} | {r['title']} "
            f"| {r['document_type'] or ''} | {r['publication_date'] or ''} "
            f"| {r['source_tier'] or ''} |"
        )
    return "\n".join(lines)


def _conflicts_block(conn: sqlite3.Connection, incident_id: int) -> str:
    rows = conn.execute(
        """
        SELECT field_name,
               COUNT(DISTINCT COALESCE(normalized_value, raw_value)) AS distinct_values
        FROM claims WHERE incident_id = ?
        GROUP BY field_name HAVING distinct_values > 1
        ORDER BY field_name
        """,
        (incident_id,),
    ).fetchall()
    if not rows:
        return "_No conflicting claims detected._"
    return "\n".join(
        f"- **{r['field_name']}**: {r['distinct_values']} distinct values — requires a decision"
        for r in rows
    )


def generate_packet(conn: sqlite3.Connection, incident_id: int) -> str:
    row = conn.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
    if row is None:
        raise ValueError(f"Incident {incident_id} does not exist")
    identity = row["public_incident_id"] or f"incident-{incident_id}"
    identity_block = "\n".join(
        [
            f"- Internal id: {incident_id}",
            f"- Public id: {row['public_incident_id'] or '— (not yet assigned)'}",
            f"- Working title: {row['canonical_title_tr'] or '—'}",
            f"- Incident window: {row['incident_start_datetime'] or '—'} → "
            f"{row['incident_end_datetime'] or '—'} ({row['date_precision'] or 'precision —'})",
            f"- Scope status: {row['incident_status']} — "
            f"{row['scope_rationale'] or 'no rationale recorded'}",
            f"- Verification: {row['verification_status']}; "
            f"publication: {row['publication_status']}",
            "- Duplicate candidates: check quality report (QC-W02) before proceeding",
        ]
    )
    return SECTION_TEMPLATE.format(
        identity=identity,
        identity_block=identity_block,
        source_inventory=_source_inventory(conn, incident_id),
        claims_table=_claims_table(conn, incident_id),
        conflicts_block=_conflicts_block(conn, incident_id),
    )


def generate_all(
    conn: sqlite3.Connection, output_dir: str | Path = DEFAULT_OUTPUT_DIR
) -> list[Path]:
    """Write a packet for every incident that has linked claims."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for row in conn.execute(
        "SELECT DISTINCT incident_id FROM claims WHERE incident_id IS NOT NULL ORDER BY incident_id"
    ):
        incident_id = row["incident_id"]
        content = generate_packet(conn, incident_id)
        public_id = conn.execute(
            "SELECT public_incident_id FROM incidents WHERE incident_id = ?", (incident_id,)
        ).fetchone()[0]
        path = output_dir / f"{public_id or f'incident-{incident_id}'}.md"
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    return paths


def create_pilot_slots(output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> list[Path]:
    """Write the twelve EMPTY pilot slot templates (criterion annotation only)."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for slot, criterion in PILOT_SLOTS:
        header = (
            f"<!-- Selection criterion: {criterion}. This slot is EMPTY by design: "
            "no incident is named. Populating it requires collected source documents "
            "(see data/review_packets/README.md). -->\n\n"
        )
        content = SECTION_TEMPLATE.format(
            identity=f"{slot} (empty slot — criterion: {criterion})",
            identity_block="_To be selected: an incident matching the criterion above._",
            source_inventory="_No sources collected yet._",
            claims_table="_No claims extracted yet._",
            conflicts_block="_Not applicable until claims exist._",
        )
        path = output_dir / f"{slot}.md"
        path.write_text(header + content, encoding="utf-8")
        paths.append(path)
    return paths
