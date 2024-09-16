import fileinput
import sys
from pathlib import Path
from typing import Annotated, Final

import typer

from .convert import PythonVersion, convert

__all__ = "app", "convert_command"

_PATH_STD: Final = Path("-")


app: Final = typer.Typer(
    no_args_is_help=True,
    short_help="-h",
    add_completion=False,
    pretty_exceptions_enable=False,
)


def _version_callback(*, value: bool) -> None:
    if not value:
        return

    from ._meta import get_version  # noqa: PLC0415

    typer.echo(f"unpy {get_version()}")
    raise typer.Exit


@app.command("convert")
def convert_command(
    source: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            allow_dash=True,
            help="Path to the input .pyi file or '-' to read from stdin.",
        ),
    ],
    output: Annotated[
        Path,
        typer.Argument(
            dir_okay=False,
            writable=True,
            allow_dash=True,
            show_default=False,
            help="Path to the output .pyi file. Defaults to stdout.",
        ),
    ] = _PATH_STD,
    version: Annotated[  # noqa: ARG001
        bool | None,
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit",
        ),
    ] = None,
    python: Annotated[
        PythonVersion,
        typer.Option(
            "--python",
            "-P",
            help="The minimum Python version that should be supported.",
        ),
    ] = PythonVersion.PY311,
) -> None:
    if str(source) == "-":
        if sys.stdin.isatty():
            typer.echo("Input must be a .pyi file", err=True)
            raise typer.Exit(1)
        with fileinput.input(source) as fp:
            source_in = "".join(fp)
    else:
        ext = source.suffix
        if ext == "py":
            raise NotImplementedError("py files not supported yet")

        if ext not in {".py", ".pyi"}:
            typer.echo("Input must be a .pyi file", err=True)
            raise typer.Exit(1)

        source_in = source.read_text(encoding="utf-8", errors="strict")

    source_out = convert(source_in, python)

    if str(output) == "-":
        typer.echo(source_out, nl=False)
    else:
        _ = output.write_text(source_out)
