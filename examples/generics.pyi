from typing import Protocol, overload

class Boring: ...

class CanGetItem[T_contra, T_co](Protocol):
    def __getitem__(self, k: T_contra, /) -> T_co: ...

class Stack[T]:
    def push(self, value: T, /) -> None: ...
    @overload
    def pop(self, /) -> T: ...
    @overload
    def pop[D](self, default: D, /) -> T | D: ...

class Named[NameT: str, QualNameT: str = NameT]:
    __name__: NameT
    __qualname__: QualNameT
