from pathlib import Path

from typer.testing import CliRunner
from unpy._meta import get_version
from unpy.cli import app

runner = CliRunner()

_PYI_CONTENT = "answer = 42\n"


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout == f"unpy {get_version()}\n"


def test_stdin_stdout():
    result = runner.invoke(app, ["-"], _PYI_CONTENT)
    assert result.exit_code == 0
    assert result.stdout == _PYI_CONTENT


def test_file_stdout(tmp_path: Path):
    d = tmp_path / "unpy"
    d.mkdir()
    p = d / "test.pyi"
    _ = p.write_text(_PYI_CONTENT, encoding="utf-8")

    result = runner.invoke(app, [str(p)])
    assert result.exit_code == 0
    assert result.stdout == _PYI_CONTENT


def test_file_file(tmp_path: Path):
    d = tmp_path / "unpy"
    d.mkdir()
    p_in = d / "test_in.pyi"
    p_out = d / "test_out.pyi"
    _ = p_in.write_text(_PYI_CONTENT, encoding="utf-8")

    result = runner.invoke(app, [str(p_in), str(p_out)])
    assert result.exit_code == 0
    assert not result.stdout
    assert p_out.read_text() == _PYI_CONTENT
