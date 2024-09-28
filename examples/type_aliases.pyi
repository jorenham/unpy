from collections.abc import Callable

type Binary = bytes | bytearray | memoryview
type Vector[R: float] = tuple[R, ...]
type tciD[V, K] = dict[K, V]
type Things[*Ts] = tuple[*Ts]
type Callback[**Tss] = Callable[Tss, None]
