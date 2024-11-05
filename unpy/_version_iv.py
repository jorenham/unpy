# mypy: disable-error-code=callable-functiontype
"""
Utility types for modelling `sys.version_info` conditions (under `>=` or `<`) as slice
(càglàd interval), but with a set-like interface, assuming `(major, minor)` as version.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Final, Literal, cast, final, override

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import EllipsisType


__all__ = ("VersionIV",)

VERSION_MIN: Final = (0,)
VERSION_MAX: Final = (0x7FFF_FFFF,)

type _ReleaseLevel = Literal["alpha", "beta", "candidate", "final"]
type _VersionBound = tuple[int] | tuple[int, int]
type VersionInfo = tuple[int, int, int, _ReleaseLevel, int]
type Version = _VersionBound | VersionInfo


def _format_version(version: _VersionBound, /) -> str:
    if version == VERSION_MAX:
        return "..."
    return ".".join(map(str, version))


def _binop[FT: Callable[[VersionIV, VersionIV], VersionIV]](f: FT, /) -> FT:
    @functools.wraps(f)
    def _wrapper(self: VersionIV, x: VersionIV, /) -> VersionIV:
        return f(self, x) if isinstance(x, VersionIV) else NotImplemented  # type: ignore[redundant-expr]  # pyright: ignore[reportUnnecessaryIsInstance]

    return _wrapper  # type: ignore[return-value]  # pyright: ignore[reportReturnType]


@final  # noqa: PLR0904
class VersionIV:
    """Represents the set of all versions `x` s.t. `a <= x < b`."""

    __slots__ = "a", "b"
    __match_args__ = "start", "stop"

    a: Final[_VersionBound]
    b: Final[_VersionBound]

    def __init__(
        self,
        /,
        start: _VersionBound | EllipsisType,
        stop: _VersionBound | EllipsisType = ...,
    ) -> None:
        a = cast(_VersionBound, VERSION_MIN if start is ... else start)
        b = VERSION_MAX if stop is ... else stop
        self.a, self.b = (a, b) if a < b else (VERSION_MIN, VERSION_MIN)

    @property
    def start(self, /) -> _VersionBound:
        return self.a

    @property
    def stop(self, /) -> _VersionBound | None:
        return None if (b := self.b) == VERSION_MAX else b

    @property
    def step(self, /) -> tuple[Literal[0], Literal[0, 1]]:
        return (0, 1 if self else 0)

    @property
    def bounded(self, /) -> bool:
        return self.a > VERSION_MIN and self.b < VERSION_MAX or not self

    @property
    def bounded_below(self, /) -> bool:
        return self.a != VERSION_MIN or not self

    @property
    def bounded_above(self, /) -> bool:
        return self.b != VERSION_MAX

    @override
    def __repr__(self, /) -> str:
        return f"{type(self).__name__}({self.a}, {self.stop or '...'})"

    @override
    def __str__(self, /) -> str:
        a, b = self.a, self.b
        return f"[{_format_version(a)}; {_format_version(b)})" if a < b else "∅"

    def __bool__(self, /) -> bool:
        """True unless empty."""
        return self.b > VERSION_MIN

    def __contains__(self, version: Version, /) -> bool:
        return version >= self.a and version < self.b

    @override
    def __hash__(self, /) -> int:
        return hash((type(self), self.a, self.b))

    @override
    def __eq__(self, other: object, /) -> bool:
        """Set equality `A = B`."""
        if not isinstance(other, VersionIV):
            return NotImplemented
        return self is other or (self.a, self.b) == (other.a, other.b)

    @override
    def __ne__(self, other: object, /) -> bool:
        """Set inequality `A ≠ B`."""
        if not isinstance(other, VersionIV):
            return NotImplemented
        return (self.a, self.b) != (other.a, other.b)

    def __lt__(self, other: VersionIV, /) -> bool:
        """Strict subset relation `A ⊂ B`."""
        return self <= other and self != other

    def __le__(self, other: VersionIV, /) -> bool:
        """Subset relation `A ⊆ B`."""
        return self is other or not self or self.a >= other.a and self.b <= other.b

    def __ge__(self, other: VersionIV, /) -> bool:
        """Superset relation `A ⊇ B`."""
        return self is other or not other or self.a <= other.a and self.b >= other.b

    def __gt__(self, other: VersionIV, /) -> bool:
        """Strict superset relation `A ⊃ B`."""
        return self >= other and self != other

    @_binop
    def __and__(self, other: VersionIV, /) -> VersionIV:
        """Set intersection `A ⋂ B`."""
        return VersionIV(max(self.a, other.a), min(self.b, other.b))

    @_binop
    def __or__(self, other: VersionIV, /) -> VersionIV:
        """Set union `A ⋃ B`, or raise `ValueError` if (strictly) disjoint."""
        if not other:
            return self
        if not self:
            return other

        if not self & other and self.a != other.b and self.b != other.a:
            raise ValueError(f"{self} and {other} are strictly disjoint")

        return VersionIV(min(self.a, other.a), max(self.b, other.b))

    @_binop
    def __sub__(self, other: VersionIV, /) -> VersionIV:
        """Set difference `A \\ B`, or raise `ValueError` iff `A ⊃ B`."""
        if not self or not other:
            return self
        if self.a < other.a and self.b > other.b:
            raise ValueError(f"{self} is a two-sided strict superset of {other}")
        if self <= other:
            return VersionIV(VERSION_MAX, VERSION_MIN)

        if self.a >= other.a:
            return VersionIV(other.b, max(self.b, other.b))
        if self.b <= other.b:
            return VersionIV(min(self.a, other.a), other.a)

        raise NotImplementedError
