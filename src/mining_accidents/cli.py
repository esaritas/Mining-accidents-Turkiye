"""Typer CLI — operational entry points for the evidence pipeline.

Role in the evidence flow: the CLI is the only supported way to create the
database, import evidence, run quality checks, build exports, and generate
review packets. Commands are thin wrappers over the library modules so every
operation is scriptable and testable.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from mining_accidents import database, vocabularies

app = typer.Typer(
    name="mining-accidents",
    help="Turkey Mining & Quarrying Accidents Database — evidence pipeline CLI.",
    no_args_is_help=True,
)
console = Console()

DB_OPTION = typer.Option(
    Path("database/mining_accidents.sqlite"), "--db-path", help="SQLite database path."
)


@app.command("create-db")
def create_db(
    db_path: Path = DB_OPTION,
    migrations_dir: Path = typer.Option(
        Path("database/migrations"), help="Directory of numbered migration SQL files."
    ),
    snapshot: bool = typer.Option(
        True, help="Regenerate database/schema.sql after applying migrations."
    ),
) -> None:
    """Create or upgrade the database by applying pending migrations."""
    applied = database.create_database(
        db_path=db_path,
        migrations_dir=migrations_dir,
        snapshot_path=database.DEFAULT_SCHEMA_SNAPSHOT if snapshot else None,
    )
    if applied:
        console.print(f"[green]Applied migrations:[/green] {', '.join(applied)}")
    else:
        console.print("[green]Database is up to date; no migrations pending.[/green]")
    console.print(f"Database: {db_path}")


@app.command("validate-vocabularies")
def validate_vocabularies(
    vocab_dir: Path = typer.Option(Path("data/vocabularies"), help="Directory of vocabulary CSVs."),
) -> None:
    """Validate every controlled-vocabulary CSV (unique codes, required labels)."""
    counts = vocabularies.validate_all(vocab_dir)
    for name, count in sorted(counts.items()):
        console.print(f"  {name}: {count} codes")
    console.print("[green]All vocabularies valid.[/green]")


@app.command("import-manual")
def import_manual(
    db_path: Path = DB_OPTION,
    documents: Path = typer.Option(None, help="CSV/YAML file of source documents to import."),
    claims: Path = typer.Option(None, help="CSV/YAML file of claims to import."),
    actor: str = typer.Option("manual-import", help="Actor recorded on the ingestion run."),
) -> None:
    """Import source documents and claims prepared for manual entry."""
    from mining_accidents.adapters import manual

    if documents is None and claims is None:
        console.print("[red]Nothing to import: pass --documents and/or --claims.[/red]")
        raise typer.Exit(code=2)
    conn = database.get_connection(db_path)
    try:
        result = manual.import_files(
            conn, documents_path=documents, claims_path=claims, actor=actor
        )
    finally:
        conn.close()
    console.print(
        f"[green]Imported[/green] {result.documents_created} documents, "
        f"{result.claims_created} claims "
        f"({result.records_skipped} skipped). Run id: {result.run_id}"
    )


@app.command("qc")
def qc(
    db_path: Path = DB_OPTION,
    report_path: Path = typer.Option(
        Path("data/interim/quality_report.json"), help="Where to write the JSON report."
    ),
) -> None:
    """Run the quality-check suite; exit non-zero if any critical check fails."""
    from mining_accidents import quality

    conn = database.get_connection(db_path)
    try:
        findings = quality.run_all_checks(conn)
    finally:
        conn.close()
    quality.write_report(findings, report_path)
    quality.print_report(findings, console)
    if quality.has_critical(findings):
        raise typer.Exit(code=1)


@app.command("export")
def export(
    db_path: Path = DB_OPTION,
    output_dir: Path = typer.Option(Path("data/public"), help="Public export directory."),
) -> None:
    """Build the public export. Aborts (non-zero) on any critical QC failure."""
    from mining_accidents import export as export_mod

    conn = database.get_connection(db_path)
    try:
        try:
            manifest = export_mod.build_public_export(conn, output_dir)
        except export_mod.ExportBlockedError as exc:
            console.print(f"[red]Export blocked:[/red] {exc}")
            raise typer.Exit(code=1) from exc
    finally:
        conn.close()
    console.print(
        f"[green]Export complete:[/green] {manifest['row_counts']['incidents']} incidents "
        f"-> {output_dir}"
    )


@app.command("packets")
def packets(
    db_path: Path = DB_OPTION,
    output_dir: Path = typer.Option(
        Path("data/review_packets"), help="Directory for generated packets."
    ),
    pilot_slots: bool = typer.Option(
        False, "--pilot-slots", help="Regenerate the twelve empty PILOT slot templates."
    ),
) -> None:
    """Generate review packets for incidents (or the empty pilot slot templates)."""
    from mining_accidents import packets as packets_mod

    if pilot_slots:
        paths = packets_mod.create_pilot_slots(output_dir)
        console.print(f"[green]Wrote {len(paths)} pilot slot templates.[/green]")
        return
    conn = database.get_connection(db_path)
    try:
        paths = packets_mod.generate_all(conn, output_dir)
    finally:
        conn.close()
    console.print(f"[green]Generated {len(paths)} review packet(s).[/green]")


@app.command("ingest-wikidata")
def ingest_wikidata_cmd(
    db_path: Path = DB_OPTION,
    reviewer: str = typer.Option(
        None,
        help="Human reviewer identity for bulk decisions. Omit to ingest evidence only "
        "(no decisions, nothing published).",
    ),
    publish: bool = typer.Option(
        True, help="Sign off complete in-scope records as publishable (needs --reviewer)."
    ),
) -> None:
    """Fetch the Wikidata/Wikipedia seed and route it through the evidence pipeline."""
    from mining_accidents import ingest

    conn = database.get_connection(db_path)
    try:
        summary = ingest.ingest_wikidata(conn, reviewer=reviewer, publish=publish)
    finally:
        conn.close()
    console.print(
        f"[green]Ingest complete[/green] (run {summary.run_id}): "
        f"{summary.documents} documents, {summary.incidents_created} new incidents, "
        f"{summary.claims_created} new claims, {summary.decisions_recorded} decisions, "
        f"{summary.classifications_created} cause classifications."
    )
    if summary.published:
        console.print(f"Published: {', '.join(summary.published)}")
    for qid, blockers in summary.unpublished.items():
        console.print(f"[yellow]Not published[/yellow] {qid}: {', '.join(blockers)}")
    if summary.claims_needing_review:
        console.print(
            f"[yellow]{summary.claims_needing_review} claim(s) await human review[/yellow] "
            "(ai_assisted prose extractions — see docs/manual_review_protocol.md)."
        )


@app.command("ingest-sites")
def ingest_sites_cmd(
    db_path: Path = DB_OPTION,
    reviewer: str = typer.Option(
        None,
        help="Human reviewer identity signing off site registrations. Omit to "
        "ingest evidence only (roles stay pending, no sign-off logged).",
    ),
) -> None:
    """Fetch Wikidata mining-site items into the facilities context registry."""
    from mining_accidents import ingest_sites

    conn = database.get_connection(db_path)
    try:
        summary = ingest_sites.ingest_wikidata_sites(conn, reviewer=reviewer)
    finally:
        conn.close()
    console.print(
        f"[green]Sites ingest complete[/green] (run {summary.run_id}): "
        f"{summary.documents} documents, {summary.facilities_created} new facilities "
        f"({summary.facilities_updated} refreshed), {summary.claims_created} new claims, "
        f"{summary.organizations_created} organizations, {summary.roles_created} role rows."
    )
    console.print(
        "[yellow]Coverage note:[/yellow] open structured sources document a fraction "
        "of licensed operations — this layer is labeled partial wherever shown."
    )


@app.command("build-dashboard")
def build_dashboard(
    db_path: Path = DB_OPTION,
    public_dir: Path = typer.Option(Path("data/public"), help="Public export directory."),
    output: Path = typer.Option(Path("dashboard/data.js"), help="Generated data file."),
) -> None:
    """Package the public export + pipeline status into dashboard/data.js."""
    from mining_accidents import dashboard as dashboard_mod

    conn = database.get_connection(db_path)
    try:
        path = dashboard_mod.build_dashboard_data(conn, public_dir, output)
    finally:
        conn.close()
    console.print(f"[green]Dashboard data written:[/green] {path}")


@app.command("build-artifact")
def build_artifact_cmd(
    db_path: Path = DB_OPTION,
    public_dir: Path = typer.Option(Path("data/public"), help="Public export directory."),
    output: Path = typer.Option(
        Path("dashboard/artifact.html"), help="Self-contained artifact output."
    ),
) -> None:
    """Build the self-contained artifact page from dashboard/index.html."""
    from mining_accidents import artifact as artifact_mod

    conn = database.get_connection(db_path)
    try:
        path = artifact_mod.build_artifact(conn, public_dir, output_path=output)
    finally:
        conn.close()
    console.print(f"[green]Artifact written:[/green] {path}")


@app.command("import-registry")
def import_registry(
    db_path: Path = DB_OPTION,
    registry_csv: Path = typer.Option(
        Path("docs/source_registry.csv"), help="Source registry CSV to synchronize."
    ),
) -> None:
    """Synchronize docs/source_registry.csv into the source_registry table."""
    from mining_accidents import provenance

    conn = database.get_connection(db_path)
    try:
        created, updated = provenance.import_source_registry(conn, registry_csv)
    finally:
        conn.close()
    console.print(f"[green]Registry synchronized:[/green] {created} created, {updated} updated.")


@app.command("decide")
def decide(
    db_path: Path = DB_OPTION,
    incident_id: int = typer.Option(..., help="Incident the decision applies to."),
    field: str = typer.Option(..., help="Field name (e.g. fatalities_current)."),
    decision: str = typer.Option(..., help="accept_claim | reject_field | manual_override | defer"),
    rationale: str = typer.Option(..., help="Why this decision was taken (required)."),
    reviewer: str = typer.Option(..., help="Reviewer identity (required; never automated)."),
    claim_id: int = typer.Option(None, help="Selected claim (required for accept_claim)."),
    manual_value: str = typer.Option(None, help="Value for manual_override."),
    rationale_claim_id: list[int] = typer.Option(
        None, help="Supporting claim id (repeatable; required for manual_override)."
    ),
    supersedes: int = typer.Option(
        None, help="Decision id being superseded (required if one is active)."
    ),
) -> None:
    """Record a reviewer decision; the canonical value is promoted by code."""
    from mining_accidents import review
    from mining_accidents.models import ClaimDecision

    conn = database.get_connection(db_path)
    try:
        try:
            decision_id = review.record_decision(
                conn,
                ClaimDecision(
                    incident_id=incident_id,
                    field_name=field,
                    decision=decision,  # validated by the model
                    selected_claim_id=claim_id,
                    manual_value=manual_value,
                    rationale=rationale,
                    rationale_claim_ids=list(rationale_claim_id or []),
                    reviewer=reviewer,
                    supersedes_decision_id=supersedes,
                ),
            )
        except (review.ReviewError, ValueError) as exc:
            console.print(f"[red]Decision rejected:[/red] {exc}")
            raise typer.Exit(code=1) from exc
    finally:
        conn.close()
    console.print(f"[green]Decision {decision_id} recorded[/green] ({decision} on {field}).")


@app.command("assign-public-id")
def assign_public_id(
    db_path: Path = DB_OPTION,
    incident_id: int = typer.Option(..., help="Incident to assign a public id to."),
    actor: str = typer.Option(..., help="Actor recorded in the review log."),
) -> None:
    """Assign the next TR-MINE-YYYY-NNNN id (once; never reused)."""
    from mining_accidents import review

    conn = database.get_connection(db_path)
    try:
        try:
            public_id = review.assign_public_incident_id(conn, incident_id, actor=actor)
        except review.ReviewError as exc:
            console.print(f"[red]Assignment rejected:[/red] {exc}")
            raise typer.Exit(code=1) from exc
    finally:
        conn.close()
    console.print(f"[green]Assigned[/green] {public_id} to incident {incident_id}.")


@app.command("merge")
def merge(
    db_path: Path = DB_OPTION,
    surviving_id: int = typer.Option(..., help="Incident that remains canonical."),
    merged_id: int = typer.Option(..., help="Duplicate incident being merged away."),
    reason: str = typer.Option(..., help="Why these records are the same incident."),
    reviewer: str = typer.Option(..., help="Reviewer identity."),
) -> None:
    """Record a reviewed merge; the merged public id stays as an export redirect."""
    from mining_accidents import review

    conn = database.get_connection(db_path)
    try:
        try:
            review.merge_incidents(conn, surviving_id, merged_id, reason, reviewer)
        except review.ReviewError as exc:
            console.print(f"[red]Merge rejected:[/red] {exc}")
            raise typer.Exit(code=1) from exc
    finally:
        conn.close()
    console.print(f"[green]Merged[/green] incident {merged_id} into {surviving_id}.")


if __name__ == "__main__":
    app()
