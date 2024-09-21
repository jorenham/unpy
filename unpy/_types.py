import enum
from collections.abc import Callable

__all__ = "AnyFunction", "Target"


type AnyFunction = Callable[..., object]  # type: ignore[no-any-explicit]


class Target(enum.StrEnum):
    # PY313 = "3.13"
    # PY312 = "3.12"
    PY311 = "3.11"
    # PY310 = "3.10"
    # PY39 = "3.9"
    # PY38 = "3.8"
