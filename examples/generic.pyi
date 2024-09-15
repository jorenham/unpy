from typing import Protocol, overload

class Simple: ...

class Stack[T]:
    def push(self, value: T, /) -> None: ...
    @overload
    def pop(self, /) -> T: ...
    @overload
    def pop[D](self, default: D, /) -> T | D: ...

class CanSubscript[T_in, T_out](Protocol):
    def __getitem__(self, k: T_in, /) -> T_out: ...