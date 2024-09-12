import os
from typing import overload
from typing_extensions import Protocol  # noqa: UP035

__all__ = "Box", "ensure_tuple"

type PathLike[S: (str, bytes)] = S | os.PathLike[S]
type RPair[RT, LT = RT] = tuple[LT, RT]  # noqa: E251

class _CanNext[V_co: object](Protocol):
    def __next__(self, /) -> V_co: ...

class _CanIter[Vs_co: _CanNext[object]](Protocol):
    def __iter__(self, /) -> Vs_co: ...

class _CanGetItem[K_contra, V_co = object](Protocol):  # noqa: E251
    def __getitem__(self, key: K_contra, /) -> V_co: ...

# anything that can iterated over with e.g. iter() or a for loop
type Iterand[V] = _CanIter[_CanNext[V]] | _CanGetItem[int, V]

@overload
def ensure_tuple[*Vs](values: tuple[*Vs], /) -> tuple[*Vs]: ...
@overload
def ensure_tuple[V](iterable: Iterand[V], /) -> tuple[V, ...]: ...
@overload
def ensure_tuple[V](value: V, /) -> tuple[V, ...]: ...

class Box[S, T]:  # `S` is contravariant, `T` is covariant
    def __init__(self, value: T, /) -> None: ...
    @overload
    def __call__(self, /) -> T: ...
    @overload
    def __call__(self, value: S, /) -> T: ...
