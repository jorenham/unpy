import fileinput
import sys
from pathlib import Path
from typing import Annotated, Final

import typer

from .convert import convert

__all__ = "app", "convert_command"

PATH_STD: Final = Path("-")
app: Final = typer.Typer()


@app.command("convert")
def convert_command(
    file_in: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, allow_dash=True),
    ],
    file_out: Annotated[
        Path,
        typer.Argument(dir_okay=False, writable=True, allow_dash=True),
    ] = PATH_STD,
) -> None:
    if str(file_in) == "-":
        # source_in = sys.stdin.read()
        with fileinput.input(file_in) as fp:
            source_in = "".join(fp)
    else:
        ext = file_in.suffix
        if ext == "py":
            raise NotImplementedError("py files not supported yet")

        if ext not in {".py", ".pyi"}:
            typer.echo(f"{file_in = }")
            typer.echo(f"{file_in.is_mount() = }")
            typer.echo(f"{file_in.is_block_device() = }")
            typer.echo(f"{file_in.is_char_device() = }")
            typer.echo(f"{file_in.is_fifo() = }")
            typer.echo(f"{file_in.is_junction() = }")
            typer.echo(f"{file_in.is_reserved() = }")
            typer.echo(f"{file_in.is_socket() = }")
            typer.echo(f"{file_in.is_symlink() = }")
            print("Input must be a .py[i] file", file=sys.stderr)
            raise typer.Exit(1)

        source_in = file_in.read_text(encoding="utf-8", errors="strict")

    source_out = convert(source_in)

    if str(file_out) == "-":
        typer.echo(source_out, nl=False)
    else:
        _ = file_out.write_text(source_out)
