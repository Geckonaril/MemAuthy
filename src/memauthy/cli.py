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


if __name__ == "__main__":  # pragma: no cover
    app()
