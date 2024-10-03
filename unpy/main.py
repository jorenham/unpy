# ruff: noqa: UP040
from __future__ import annotations

import difflib
import enum
import fileinput
import sys
from pathlib import Path
from typing import Annotated, Final, TypeAlias, cast

import typer

from ._types import PythonVersion
from .transformers import transform_source

__all__ = ("app",)


class Target(enum.StrEnum):
    PY310 = "3.10"
    PY311 = "3.11"
    PY312 = "3.12"
    PY313 = "3.13"

    @property
    def version(self, /) -> PythonVersion:
        return cast(PythonVersion, getattr(PythonVersion, self.name))


def _version_callback(*, value: bool) -> None:
    if not value:
        return

    from ._meta import get_version  # noqa: PLC0415

    typer.echo(f"unpy {get_version()}")
    raise typer.Exit


_ArgumentSource: TypeAlias = Annotated[
    Path,
    typer.Argument(
        exists=True,
        dir_okay=False,
        readable=True,
        allow_dash=True,
        help="Path to the input .pyi file or '-' to read from stdin.",
    ),
]
_ArgumentOutput: TypeAlias = Annotated[
    Path,
    typer.Argument(
        dir_okay=False,
        writable=True,
        allow_dash=True,
        show_default=False,
        help="Path to the output .pyi file. Defaults to stdout.",
    ),
]
_OptionVersion: TypeAlias = Annotated[
    bool | None,
    typer.Option(
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit",
    ),
]
_OptionTarget: TypeAlias = Annotated[
    Target,
    typer.Option(
        "--target",
        help="The minimum Python version that should be supported.",
    ),
]
_OptionDiff: TypeAlias = Annotated[
    bool,
    typer.Option(
        "--diff",
        help="Show the changes between the input and output in unified diff format",
    ),
]

_DEFAULT_OUTPUT: Final = Path("-")
_DEFAULT_TARGET: Final = Target.PY310


def _read_source(source: Path, /) -> str:
    if str(source) == "-":
        if sys.stdin.isatty():  # type: ignore[no-any-expr]
            typer.echo("Input must be a .pyi file", err=True)
            raise typer.Exit(1)
        with fileinput.input(source) as fp:
            return "".join(fp)

    ext = source.suffix
    if ext == "py":
        raise NotImplementedError("py files not supported yet")

    if ext not in {".py", ".pyi"}:
        typer.echo("Input must be a .pyi file", err=True)
        raise typer.Exit(1)

    return source.read_text(encoding="utf-8", errors="strict")


def _write_output(output: Path, /, output_str: str) -> None:
    if str(output) == "-":
        typer.echo(output_str, nl=False)
    else:
        _ = output.write_text(output_str)


def _echo_diff(file_in: str, src_in: str, file_out: str, src_out: str) -> None:
    diff_lines = difflib.unified_diff(
        src_in.splitlines(keepends=True),
        src_out.splitlines(keepends=True),
        fromfile=file_in,
        tofile=file_out,
    )
    for line in diff_lines:
        fg = None
        bold = dim = False
        match line[0]:
            case "@" if line[:2] == "@@":
                bold = dim = True
            case "-" if line[:3] == "---":
                if file_out == str(_DEFAULT_OUTPUT):
                    continue
                dim = True
            case "+" if line[:3] == "+++":
                dim = True
            case "-":
                fg = typer.colors.RED
            case "+":
                fg = typer.colors.GREEN
            case "?":
                fg = typer.colors.YELLOW
            case _:
                pass

        # add some space after the diff prefix
        msg = line if dim else f"{line[0]} {line[1:]}"

        typer.secho(msg, fg=fg, bold=bold, dim=dim, nl=False)


app: Final = typer.Typer(
    name="unpy",
    no_args_is_help=True,
    short_help="-h",
    add_completion=False,
    pretty_exceptions_enable=False,
)


@app.command()  # type: ignore[no-any-expr]
def build(
    source: _ArgumentSource,
    output: _ArgumentOutput = _DEFAULT_OUTPUT,
    *,
    # command-line options options
    version: _OptionVersion = None,
    diff: _OptionDiff = False,
    # build options
    target: _OptionTarget = _DEFAULT_TARGET,
) -> None:
    assert not version

    filename = "<stdin>" if str(source) == "-" else str(source.resolve())

    source_str = _read_source(source)
    output_str = transform_source(source_str, filename=filename, target=target.version)

    if diff:
        _echo_diff(str(source), source_str, str(output), output_str)

        if output == _DEFAULT_OUTPUT:
            return

    _write_output(output, output_str)
