from collections.abc import Callable, Mapping
from os import PathLike as _PathLike
from typing import Concatenate

# simple alias
type AnyStr = str | bytes

# type constraints
type PathLike[S: (str, bytes)] = S | _PathLike[S]

# type bounds
type KwArgs[K: str, V] = Mapping[K, V]

# reversed type param definition order
type Tuple2R[R, L] = tuple[L, R]

# variadic type params
type NonEmptyTuple[T0, *Ts] = tuple[T0, *Ts]

# paramspec
type ObjectiveFunction[XT, **Tss] = Callable[Concatenate[XT, Tss], XT]
