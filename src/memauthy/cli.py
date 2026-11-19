"""Command-line interface for MemAuthy."""

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


if __name__ == "__main__":  # pragma: no cover
    app()
