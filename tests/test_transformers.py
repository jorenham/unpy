# ruff: noqa: N802

import textwrap

import pytest
from unpy._types import PythonVersion
from unpy.transformers import transform_source


def _src(source: str, /) -> str:
    out = textwrap.dedent(source).lstrip("\n")
    if not out.endswith("\n"):
        out += "\n"
    return out


@pytest.mark.parametrize("source", ["", "\n", "    \n        \n\n\n"])
def test_whitespace(source: str) -> None:
    assert transform_source(source) == source


@pytest.mark.parametrize("source", ["# comment", '"""docstring"""'])
def test_comments(source: str) -> None:
    assert transform_source(source) == source


@pytest.mark.parametrize(
    "source",
    [
        "import sys\nprint(*sys.argv)\n",
        "__version__: str = '3.14'\n",
        "def concat(*args: str) -> str: ...\n",
        "class C:\n    def f(self, /) -> None: ...\n",
    ],
)
def test_already_compatible(source: str) -> None:
    assert transform_source(source) == source


def test_type_alias_simple():
    pyi_in = _src("type AnyStr = str | bytes")
    pyi_expect = _src("""
    from typing import TypeAlias
    AnyStr: TypeAlias = str | bytes
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_type_alias_simple_typing_import():
    pyi_in = _src("""
    from typing import Literal

    type AnyBool = Literal[False, 0, True, 1]
    """)
    pyi_expect = _src("""
    from typing import Literal, TypeAlias

    AnyBool: TypeAlias = Literal[False, 0, True, 1]
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_type_alias_param():
    pyi_in = _src("type Pair[T] = tuple[T, T]")
    pyi_expect = _src("""
    from typing import TypeAlias, TypeVar

    _T = TypeVar("_T")
    Pair: TypeAlias = tuple[_T, _T]
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_type_alias_param_bound():
    pyi_in = _src("type Shape2D[N: int] = tuple[N, N]")
    pyi_expect = _src("""
    from typing import TypeAlias, TypeVar

    _N = TypeVar("_N", bound=int)
    Shape2D: TypeAlias = tuple[_N, _N]
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_type_alias_param_constraints():
    pyi_in = _src("""
    import os

    type PathLike[S: (bytes, str)] = S | os.PathLike[S]
    """)
    pyi_expect = _src("""
    import os
    from typing import TypeAlias, TypeVar

    _S = TypeVar("_S", bytes, str)

    PathLike: TypeAlias = _S | os.PathLike[_S]
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_type_alias_param_default():
    pyi_in = _src("type OneOrMany[T = object] = T | tuple[T, ...]")
    pyi_expect = _src("""
    from typing import TypeAlias
    from typing_extensions import TypeVar

    _T = TypeVar("_T", default=object)
    OneOrMany: TypeAlias = _T | tuple[_T, ...]
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_type_alias_params_order_mismatch():
    pyi_in = _src("type RPair[T1, T0] = tuple[T0, T1]")
    pyi_expect = _src("""
    from typing import TypeVar
    from typing_extensions import TypeAliasType

    _T1 = TypeVar("_T1")
    _T0 = TypeVar("_T0")
    RPair = TypeAliasType("RPair", tuple[_T0, _T1], type_params=(_T1, _T0))
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_type_alias_dupe_same():
    pyi_in = _src("""
    type Solo[T] = tuple[T]
    type Pair[T] = tuple[T, T]
    """)
    pyi_expect = _src("""
    from typing import TypeAlias, TypeVar

    _T = TypeVar("_T")
    Solo: TypeAlias = tuple[_T]
    Pair: TypeAlias = tuple[_T, _T]
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_type_alias_dupe_clash():
    pyi_in = _src("""
    type Solo[T] = tuple[T]
    type SoloName[T: str] = tuple[T]
    """)
    with pytest.raises(NotImplementedError):
        transform_source(pyi_in)


def test_generic_function():
    pyi_in = _src("def spam[T](x: T) -> T: ...")
    pyi_expect = _src("""
    from typing import TypeVar

    _T = TypeVar("_T")
    def spam(x: _T) -> _T: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_generic_function_bound():
    pyi_in = _src("def f[Z: complex](z: Z) -> Z: ...")
    pyi_expect = _src("""
    from typing import TypeVar

    _Z = TypeVar("_Z", bound=complex)
    def f(z: _Z) -> _Z: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_generic_function_constraints():
    pyi_in = _src("def f[Z: (int, float, complex)](z: Z) -> Z: ...")
    pyi_expect = _src("""
    from typing import TypeVar

    _Z = TypeVar("_Z", int, float, complex)
    def f(z: _Z) -> _Z: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_generic_function_default():
    pyi_in = _src("def f[Z: complex = complex](z: Z = ...) -> Z: ...")
    pyi_expect = _src("""
    from typing_extensions import TypeVar

    _Z = TypeVar("_Z", bound=complex, default=complex)
    def f(z: _Z = ...) -> _Z: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_generic_function_default_other():
    pyi_in = _src("def f[T, T0 = T](x: T, x0: T0 = ...) -> T | T0: ...")
    pyi_expect = _src("""
    from typing_extensions import TypeVar

    _T = TypeVar("_T")
    _T0 = TypeVar("_T0", default=_T)
    def f(x: _T, x0: _T0 = ...) -> _T | _T0: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_generic_function_default_other_union():
    pyi_in = _src("def f[T, T0 = T | None](x: T, x0: T0 = ...) -> T | T0: ...")
    pyi_expect = _src("""
    from typing_extensions import TypeVar

    _T = TypeVar("_T")
    _T0 = TypeVar("_T0", default=_T | None)
    def f(x: _T, x0: _T0 = ...) -> _T | _T0: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_generic_function_variadic_py311():
    pyi_in = _src("def f[*Ts](*args: *Ts) -> tuple[*Ts]: ...")
    pyi_expect = _src("""
    from typing import TypeVarTuple

    _Ts = TypeVarTuple("_Ts")
    def f(*args: *_Ts) -> tuple[*_Ts]: ...
    """)
    pyi_out = transform_source(pyi_in, target=PythonVersion.PY311)
    assert pyi_out == pyi_expect


def test_generic_function_variadic_py310():
    pyi_in = _src("def f[*Ts](*args: *Ts) -> tuple[*Ts]: ...")
    pyi_expect = _src("""
    from typing_extensions import TypeVarTuple, Unpack

    _Ts = TypeVarTuple("_Ts")
    def f(*args: Unpack[_Ts]) -> tuple[Unpack[_Ts]]: ...
    """)
    pyi_out = transform_source(pyi_in, target=PythonVersion.PY310)
    assert pyi_out == pyi_expect


def test_generic_function_variadic_default_py311():
    pyi_in = _src("def f[*Ts = *tuple[()]](*args: *Ts) -> tuple[*Ts]: ...")
    pyi_expect = _src("""
    from typing import TypeVarTuple, Unpack

    _Ts = TypeVarTuple("_Ts", default=Unpack[tuple[()]])
    def f(*args: *_Ts) -> tuple[*_Ts]: ...
    """)
    pyi_out = transform_source(pyi_in, target=PythonVersion.PY311)
    assert pyi_out == pyi_expect


def test_generic_function_variadic_default_py310():
    pyi_in = _src("def f[*Ts = *tuple[()]](*args: *Ts) -> tuple[*Ts]: ...")
    pyi_expect = _src("""
    from typing_extensions import TypeVarTuple, Unpack

    _Ts = TypeVarTuple("_Ts", default=Unpack[tuple[()]])
    def f(*args: Unpack[_Ts]) -> tuple[Unpack[_Ts]]: ...
    """)
    pyi_out = transform_source(pyi_in, target=PythonVersion.PY310)
    assert pyi_out == pyi_expect


def test_generic_function_default_any():
    pyi_in = _src("""
    from typing import Any

    def f[Z: complex = Any](z: Z = ...) -> Z: ...
    """)
    pyi_expect = _src("""
    from typing import Any
    from typing_extensions import TypeVar

    _Z = TypeVar("_Z", bound=complex, default=complex)

    def f(z: _Z = ...) -> _Z: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_generic_function_dupe_same():
    pyi_in = _src("""
    def f[T](x: T, /) -> T: ...
    def g[T](y: T, /) -> T: ...
    """)
    pyi_expect = _src("""
    from typing import TypeVar

    _T = TypeVar("_T")
    def f(x: _T, /) -> _T: ...
    def g(y: _T, /) -> _T: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_generic_function_dupe_clash_bound():
    pyi_in = _src("""
    def f[T](x: T, /) -> T: ...
    def g[T: str](v: T, /) -> T: ...
    """)
    with pytest.raises(NotImplementedError):
        transform_source(pyi_in)


def test_generic_function_dupe_clash_type():
    pyi_in = _src("""
    def f[T](x: T, /) -> T: ...
    def g[*T](*xs: *T) -> T: ...
    """)
    with pytest.raises(NotImplementedError):
        transform_source(pyi_in)


def test_generic_class():
    pyi_in = _src("class C[T_contra, T, T_co]: ...")
    pyi_expect = _src("""
    from typing import Generic
    from typing_extensions import TypeVar

    _T_contra = TypeVar("_T_contra", contravariant=True)
    _T = TypeVar("_T", infer_variance=True)
    _T_co = TypeVar("_T_co", covariant=True)
    class C(Generic[_T_contra, _T, _T_co]): ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_generic_protocol():
    pyi_in = _src("""
    from typing import Protocol

    class C[T_contra, T, T_co](Protocol): ...
    """)

    pyi_expect = _src("""
    from typing import Protocol
    from typing_extensions import TypeVar

    _T_contra = TypeVar("_T_contra", contravariant=True)
    _T = TypeVar("_T", infer_variance=True)
    _T_co = TypeVar("_T_co", covariant=True)

    class C(Protocol[_T_contra, _T, _T_co]): ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_generic_variadic_default_py311():
    pyi_in = _src("""
    class A[T, *Ts = *tuple[()]]:
        a: tuple[T, *Ts]
    """)
    pyi_expect = _src("""
    from typing import Generic, TypeVarTuple, Unpack
    from typing_extensions import TypeVar

    _T = TypeVar("_T", infer_variance=True)
    _Ts = TypeVarTuple("_Ts", default=Unpack[tuple[()]])
    class A(Generic[_T, *_Ts]):
        a: tuple[_T, *_Ts]
    """)
    pyi_out = transform_source(pyi_in, target=PythonVersion.PY311)
    assert pyi_out == pyi_expect


def test_generic_variadic_default_py310():
    pyi_in = _src("""
    class A[T, *Ts = *tuple[()]]:
        a: tuple[T, *Ts]
    """)
    pyi_expect = _src("""
    from typing import Generic
    from typing_extensions import TypeVar, TypeVarTuple, Unpack

    _T = TypeVar("_T", infer_variance=True)
    _Ts = TypeVarTuple("_Ts", default=Unpack[tuple[()]])
    class A(Generic[_T, Unpack[_Ts]]):
        a: tuple[_T, Unpack[_Ts]]
    """)
    pyi_out = transform_source(pyi_in, target=PythonVersion.PY310)
    assert pyi_out == pyi_expect


def test_import_override():
    pyi_in = _src("""
    from typing import Protocol, override

    class A(Protocol):
        def f(self, /) -> bool: ...

    class B(A, Protocol):
        @override
        def f(self, /) -> int: ...
    """)
    pyi_expect = _src("""
    from typing import Protocol
    from typing_extensions import override

    class A(Protocol):
        def f(self, /) -> bool: ...

    class B(A, Protocol):
        @override
        def f(self, /) -> int: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_import_type_alias_type():
    pyi_in = _src("""
    from typing import TypeAliasType

    Alias = TypeAliasType("Alias", object)
    """)
    pyi_expect = _src("""
    from typing_extensions import TypeAliasType

    Alias = TypeAliasType("Alias", object)
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_import_buffer():
    pyi_in = _src("""
    from collections.abc import Buffer

    def f(x: Buffer, /) -> bytes: ...
    """)
    pyi_expect = _src("""
    from typing_extensions import Buffer

    def f(x: Buffer, /) -> bytes: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_import_collection_abs_buffer():
    pyi_in = _src("""
    import collections.abc
    def f(x: collections.abc.Buffer, /) -> collections.abc.Sequence[int]: ...
    """)
    pyi_expect = _src("""
    import collections.abc
    from typing_extensions import Buffer
    def f(x: Buffer, /) -> collections.abc.Sequence[int]: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_import_type_is():
    pyi_in = _src("""
    from typing import TypeIs

    def is_str(x: object, /) -> TypeIs[str]: ...
    """)
    pyi_expect = _src("""
    from typing_extensions import TypeIs

    def is_str(x: object, /) -> TypeIs[str]: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_import_readonly():
    pyi_in = _src("""
    from typing import ReadOnly, TypedDict

    class BoringDict(TypedDict):
        key: ReadOnly[object]
    """)
    pyi_expect = _src("""
    from typing import TypedDict
    from typing_extensions import ReadOnly

    class BoringDict(TypedDict):
        key: ReadOnly[object]
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_import_deprecated():
    pyi_in = _src("""
    from warnings import deprecated

    @deprecated("RTFM")
    def dont_use_me() -> None: ...
    """)
    pyi_expect = _src("""
    from typing_extensions import deprecated

    @deprecated("RTFM")
    def dont_use_me() -> None: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_import_no_default():
    pyi_in = _src("""
    from typing import NoDefault

    def getname(obj: object, default: NoDefault = ..., /) -> str: ...
    """)
    pyi_expect = _src("""
    from typing_extensions import NoDefault

    def getname(obj: object, default: NoDefault = ..., /) -> str: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_import_capsule_type():
    pyi_in = _src("""
    from types import CapsuleType
    from typing import Protocol

    class HasArrayStruct(Protocol):
        __array_struct__: CapsuleType
    """)
    pyi_expect = _src("""
    from typing import Protocol
    from typing_extensions import CapsuleType

    class HasArrayStruct(Protocol):
        __array_struct__: CapsuleType
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_backport_exceptions():
    pyi_in = _src("""
    import re
    from asyncio import QueueShutDown
    from pathlib import UnsupportedOperation
    from queue import ShutDown

    class AsyncShutdownError(QueueShutDown): ...
    class ShutdownError(ShutDown): ...
    class UnsupportedError(UnsupportedOperation): ...
    class RegexError(re.PatternError): ...
    """)
    pyi_expect = _src("""
    import re

    class AsyncShutdownError(Exception): ...
    class ShutdownError(Exception): ...
    class UnsupportedError(NotImplementedError): ...
    class RegexError(re.error): ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_backport_enum_ReprEnum():
    pyi_in = _src("""
    from enum import ReprEnum

    class StrEnum(str, ReprEnum): ...
    """)
    pyi_expect = _src("""
    from enum import Enum

    class StrEnum(str, Enum): ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_backport_enum_StrEnum():
    pyi_in = _src("""
    from enum import StrEnum

    class Truth(StrEnum):
        TRUE = "true"
        FALSE = "false"
    """)
    pyi_expect = _src("""
    from enum import Enum

    class Truth(str, Enum):
        TRUE = "true"
        FALSE = "false"
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_backport_inspect_BufferFlags():
    pyi_in = _src("""
    from inspect import BufferFlags
    from optype import CanBuffer

    def buffer(obj: CanBuffer[BufferFlags], flags: BufferFlags, /) -> memoryview: ...
    """)
    pyi_expect = _src("""
    from optype import CanBuffer

    def buffer(obj: CanBuffer[int], flags: int, /) -> memoryview: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_subclass_pathlib_Path():
    pyi_import = _src("""
    import pathlib

    class MyPath(pathlib.Path): ...
    """)
    with pytest.raises(NotImplementedError):
        transform_source(pyi_import)

    pyi_import_from = _src("""
    from pathlib import Path

    class MyPath(Path): ...
    """)
    with pytest.raises(NotImplementedError):
        transform_source(pyi_import_from)


def test_subclass_object():
    pyi_direct = _src("class OldStyle(object): ...")
    with pytest.raises(NotImplementedError):
        transform_source(pyi_direct)


def test_subclass_builtins_object():
    pyi_direct = _src("class OldStyle(__builtins__.object): ...")
    with pytest.raises(NotImplementedError):
        transform_source(pyi_direct)


def test_subclass_builtins_object_import():
    pyi_direct = _src("""
    import builtins

    class OldStyle(builtins.object): ...
    """)
    with pytest.raises(NotImplementedError):
        transform_source(pyi_direct)


def test_subclass_builtins_object_alias():
    pyi_direct = _src("""
    from builtins import object as Object

    class OldStyle(Object): ...
    """)
    with pytest.raises(NotImplementedError):
        transform_source(pyi_direct)


def test_nested_ClassVar_Final_TN():
    pyi_in = pyi_expect = _src("""
    from typing import ClassVar, Final

    class C:
        a: ClassVar[int] = 0
        b: Final[int]
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_nested_ClassVar_Final_TP():
    pyi_in = _src("""
    from typing import ClassVar, Final

    class C:
        a: ClassVar[Final[int]] = 1
    """)
    pyi_expect = _src("""
    from typing_extensions import ClassVar, Final

    class C:
        a: ClassVar[Final[int]] = 1
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_nested_ClassVar_Final_TP_inv():
    pyi_in = _src("""
    from typing import ClassVar, Final

    class C:
        a: Final[ClassVar[int]] = -1
    """)
    pyi_expect = _src("""
    from typing_extensions import ClassVar, Final

    class C:
        a: Final[ClassVar[int]] = -1
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_nested_ClassVar_Final_TP_indirect():
    pyi_in = _src("""
    import typing as tp

    class C:
        a: tp.ClassVar[tp.Final[int]] = 1
    """)
    pyi_expect = _src("""
    import typing as tp
    from typing_extensions import ClassVar, Final

    class C:
        a: ClassVar[Final[int]] = 1
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect
