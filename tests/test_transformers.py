import textwrap

import pytest
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
        "raise NotImplementedError\n",
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

    T = TypeVar("T")
    Pair: TypeAlias = tuple[T, T]
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_type_alias_param_bound():
    pyi_in = _src("type Shape2D[N: int] = tuple[N, N]")
    pyi_expect = _src("""
    from typing import TypeAlias, TypeVar

    N = TypeVar("N", bound=int)
    Shape2D: TypeAlias = tuple[N, N]
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

    S = TypeVar("S", bytes, str)

    PathLike: TypeAlias = S | os.PathLike[S]
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_type_alias_param_default():
    pyi_in = _src("type OneOrMany[T = object] = T | tuple[T, ...]")
    pyi_expect = _src("""
    from typing import TypeAlias
    from typing_extensions import TypeVar

    T = TypeVar("T", default=object)
    OneOrMany: TypeAlias = T | tuple[T, ...]
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_type_alias_params_order_mismatch():
    pyi_in = _src("type RPair[T1, T0] = tuple[T0, T1]")
    pyi_expect = _src("""
    from typing import TypeVar
    from typing_extensions import TypeAliasType

    T1 = TypeVar("T1")
    T0 = TypeVar("T0")
    RPair = TypeAliasType("RPair", tuple[T0, T1], type_params=(T1, T0))
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

    T = TypeVar("T")
    Solo: TypeAlias = tuple[T]
    Pair: TypeAlias = tuple[T, T]
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

    T = TypeVar("T")
    def spam(x: T) -> T: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_generic_function_bound():
    pyi_in = _src("def f[Z: complex](z: Z) -> Z: ...")
    pyi_expect = _src("""
    from typing import TypeVar

    Z = TypeVar("Z", bound=complex)
    def f(z: Z) -> Z: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_generic_function_constraints():
    pyi_in = _src("def f[Z: (int, float, complex)](z: Z) -> Z: ...")
    pyi_expect = _src("""
    from typing import TypeVar

    Z = TypeVar("Z", int, float, complex)
    def f(z: Z) -> Z: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_generic_function_default():
    pyi_in = _src("def f[Z: complex = complex](z: Z = ...) -> Z: ...")
    pyi_expect = _src("""
    from typing_extensions import TypeVar

    Z = TypeVar("Z", bound=complex, default=complex)
    def f(z: Z = ...) -> Z: ...
    """)
    pyi_out = transform_source(pyi_in)
    assert pyi_out == pyi_expect


def test_generic_function_default_any():
    pyi_in = _src("""
    from typing import Any

    def f[Z: complex = Any](z: Z = ...) -> Z: ...
    """)
    pyi_expect = _src("""
    from typing import Any
    from typing_extensions import TypeVar

    Z = TypeVar("Z", bound=complex, default=complex)

    def f(z: Z = ...) -> Z: ...
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

    T = TypeVar("T")
    def f(x: T, /) -> T: ...
    def g(y: T, /) -> T: ...
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

    T_contra = TypeVar("T_contra", contravariant=True)
    T = TypeVar("T", infer_variance=True)
    T_co = TypeVar("T_co", covariant=True)
    class C(Generic[T_contra, T, T_co]): ...
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

    T_contra = TypeVar("T_contra", contravariant=True)
    T = TypeVar("T", infer_variance=True)
    T_co = TypeVar("T_co", covariant=True)

    class C(Protocol[T_contra, T, T_co]): ...
    """)
    pyi_out = transform_source(pyi_in)
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


# TODO: move the following tests to a `py313 => py312` test suite


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


def test_subclass_path():
    pyi_in = _src("""
    from pathlib import Path

    class MyPath(Path): ...
    """)
    with pytest.raises(NotImplementedError):
        transform_source(pyi_in)


def test_subclass_pathlib_path():
    pyi_in = _src("""
    import pathlib

    class MyPath(pathlib.Path): ...
    """)
    with pytest.raises(NotImplementedError):
        transform_source(pyi_in)
