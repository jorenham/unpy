from collections.abc import Hashable
from typing import Generic, Protocol, TypeAlias, TypeVar

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)
_VT = TypeVar("_VT", bound=Hashable)

Pair: TypeAlias = tuple[_T, _T]

class CanNext(Protocol[_T_co]):
    def __next__(self, /) -> _T_co: ...

class Bag(Generic[_VT]):
    def __len__(self, /) -> int: ...
    def __iter__(self, /) -> CanNext[_VT]: ...
    def add(self, key: _VT, /) -> None: ...
