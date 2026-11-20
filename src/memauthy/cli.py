"""Command-line interface for MemAuthy."""

from pathlib import Path
from typing import Annotated

import typer

from memauthy import __version__

app = typer.Typer(
    name="memauthy",
    help="Provenance- and authority-aware memory auditing for persistent-memory agents.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"memauthy {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """MemAuthy command-line interface."""


bench_app = typer.Typer(
    help="Offline MemHarmBench commands (pinned submodule; no model calls).",
    no_args_is_help=True,
)
app.add_typer(bench_app, name="bench")


def _bench(args: list[str], require_data: bool = True) -> None:
    from memauthy import bench

    try:
        root = bench.data_root()
    except bench.BenchmarkUnavailableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    if require_data and not bench.dataset_available(root):
        typer.echo("Dataset is missing. Run `memauthy bench download` first.", err=True)
        raise typer.Exit(2)
    raise typer.Exit(bench.run_benchmark_cli(args, root))


@bench_app.command()
def info() -> None:
    """Show the pinned benchmark commit, dataset revision and data location."""
    from memauthy import bench

    try:
        typer.echo(f"source_root:      {bench.source_root()}")
        typer.echo(f"data_root:        {bench.data_root()}")
        typer.echo(f"benchmark_commit: {bench.benchmark_commit()}")
        typer.echo(f"dataset_revision: {bench.dataset_revision()}")
        typer.echo(f"dataset_present:  {bench.dataset_available()}")
    except bench.BenchmarkUnavailableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


@bench_app.command()
def download(
    offline: Annotated[bool, typer.Option(help="Use only the verified local cache.")] = False,
) -> None:
    """Download and verify the pinned Hugging Face dataset snapshot (free, no API key)."""
    _bench(["download", *(["--offline"] if offline else [])], require_data=False)


@bench_app.command()
def validate() -> None:
    """Validate all published inputs and source hashes."""
    _bench(["validate"])


@bench_app.command()
def catalog(
    limit: Annotated[int, typer.Option(help="Maximum number of cases to list.")] = 12,
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """List benchmark cases."""
    _bench(["catalog", "--limit", str(limit), *(["--json"] if json_out else [])])


@bench_app.command()
def inspect(case_id: str) -> None:
    """Show one case's inputs and file inventory."""
    _bench(["inspect", case_id])


inspect_app = typer.Typer(
    help="Inspect cases, memory snapshots and transcripts (read-only).",
    no_args_is_help=True,
)
app.add_typer(inspect_app, name="inspect")


def _print_json(data: object) -> None:
    import json

    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


@inspect_app.command("case")
def inspect_case(case_id: str) -> None:
    """Show a case's ground-truth provenance (oracle P0 information)."""
    from memauthy.cases import load_case

    try:
        case = load_case(case_id)
    except FileNotFoundError as exc:
        typer.echo(f"{exc}. Run `memauthy bench download` first?", err=True)
        raise typer.Exit(2) from exc
    _print_json(
        {
            **case.model_dump(),
            "analysis_scope": "primary (IPI)" if case.is_primary_scope else "boundary (DPI-U)",
        }
    )


@inspect_app.command("run")
def inspect_run(
    chain_dir: Annotated[Path, typer.Argument(help="A run's outputs/<chain_id> directory.")],
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    with_case: Annotated[
        bool, typer.Option(help="Mark records containing the case payload (oracle, P0).")
    ] = False,
) -> None:
    """Show memory records per snapshot and memory writes in exposure transcripts."""
    from memauthy.cases import load_case
    from memauthy.memory_io.runs import inspect_chain, summarize

    try:
        inspection = inspect_chain(chain_dir)
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    case = None
    if with_case and inspection.case_id:
        try:
            case = load_case(inspection.case_id)
        except FileNotFoundError:
            typer.echo("case file not found; continuing without oracle marks", err=True)
    summary = summarize(inspection, case)
    if json_out:
        _print_json(summary)
        return
    typer.echo(
        f"{summary['chain']}  protocol={summary['protocol']}  agent={summary['agent']}  "
        f"case={summary['case_id']}"
    )
    for label, records in summary["snapshots"].items():
        typer.echo(f"\n[{label}] {len(records)} records")
        for r in records:
            mark = " [P0 payload]" if r.get("oracle_payload") else ""
            short = r["record_id"].rsplit("#", 1)[-1]
            typer.echo(
                f"  {short:<14} {r['file']}:{r['line']} {r['file_role']}/{r['block_kind']}"
                f"{mark}\n      {r['preview']}"
            )
    typer.echo("\nMemory writes in exposure transcripts:")
    for file, events in summary["memory_writes_by_file"].items() or {"(none)": []}.items():
        refs = ", ".join(f"{e['session']}#{e['index']} {e['tool']}" for e in events)
        typer.echo(f"  {file}: {refs}")
    for path, problem in summary["problems"].items():
        typer.echo(f"\nPROBLEM {path}: {problem}", err=True)


if __name__ == "__main__":  # pragma: no cover
    app()
