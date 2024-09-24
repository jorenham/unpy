import enum
from collections.abc import Callable
from typing import Literal, TypeAlias

__all__ = (
    "AnyFunction",
    "Encoding",
    "LineEnding",
    "PythonVersion",
    "PythonVersionTuple",
    "StringPrefix",
    "StringQuote",
)


type Encoding = Literal["utf-8"]
type Indent = Literal["    ", "\t"]
type LineEnding = Literal["\n"]
type StringPrefix = Literal["", "r", "u", "b", "br", "rb"]
type StringQuote = Literal["'", '"', "'''", '"""']

type AnyFunction = Callable[..., object]  # type: ignore[no-any-explicit]

PythonVersionTuple: TypeAlias = tuple[
    Literal[2, 3],
    Literal[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
]


class PythonVersion(tuple[int, ...], enum.ReprEnum):  # noqa: SLOT001
    # PY39 = (3, 9)
    PY310 = (3, 10)
    PY311 = (3, 11)
    PY312 = (3, 12)
    # PY313 = (3, 13)
