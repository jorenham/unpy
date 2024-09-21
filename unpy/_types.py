import enum
from collections.abc import Callable
from typing import Literal

__all__ = "AnyFunction", "Target"


type AnyFunction = Callable[..., object]  # type: ignore[no-any-explicit]

type _PythonVersionMajor = Literal[3]
type _PythonVersionMinor = Literal[8, 9, 10, 11, 12, 13]


class Target(tuple[_PythonVersionMajor, _PythonVersionMinor], enum.ReprEnum):  # noqa: SLOT001
    # PY313 = 3, 13
    PY312 = 3, 12
    PY311 = 3, 11
    # PY310 = 3, 10
    # PY39 = 3, 9
    # PY38 = 3, 8
