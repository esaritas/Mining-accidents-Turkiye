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


if __name__ == "__main__":
    app()
