import enum
from collections.abc import Callable
from typing import Literal

__all__ = (
    "AnyFunction",
    "Encoding",
    "LineEnding",
    "PythonVersion",
    "StringPrefix",
    "StringQuote",
)


type AnyFunction = Callable[..., object]  # type: ignore[no-any-explicit]
type Encoding = Literal["utf-8"]
type Indent = Literal["    ", "\t"]
type LineEnding = Literal["\n"]
type StringPrefix = Literal["", "r", "u", "b", "br", "rb"]
type StringQuote = Literal["'", '"', "'''", '"""']


class PythonVersion(tuple[int, ...], enum.ReprEnum):  # noqa: SLOT001
    PY310 = (3, 10)
    PY311 = (3, 11)
    PY312 = (3, 12)
    # PY313 = (3, 13)
