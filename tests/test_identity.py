import pytest
from pythoff.convert import convert


@pytest.mark.parametrize("source", ["", "\n", "    \n        \n\n\n"])
def test_whitespace(source: str) -> None:
    assert convert(source) == source


@pytest.mark.parametrize("source", ["# comment", '"""docstring"""'])
def test_comments(source: str) -> None:
    assert convert(source) == source


@pytest.mark.parametrize(
    "source",
    [
        "import sys\nprint(*sys.argv)\n",
        "__version__: str = '3.14'\n",
        "def concat(*args: str) -> str: ...\n",
        "class C:\n    def f(self, /) -> None: ...\n",
        "raise NotImplementedError\n",
    ],
)
def test_already_compatible(source: str) -> None:
    assert convert(source) == source
