"""Command-line interface.

Thin by design: commands parse input, call the service layer, and hand results to the
renderer. No business logic lives here.
"""

from typing import Annotated

import typer

from anthropic_prospector import __version__

app = typer.Typer(
    name="prospector",
    help="Signal-based MEDDPICC qualification engine for West Coast B2B startups.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"anthropic-prospector {__version__}")
        raise typer.Exit


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
    """Signal-based MEDDPICC qualification engine for West Coast B2B startups."""
