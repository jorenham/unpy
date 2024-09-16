import textwrap

from unpy.convert import PythonVersion, convert


def _src(source: str, /) -> str:
    return textwrap.dedent(source).lstrip("\n")


def test_type_alias_simple():
    pyi_in = _src("""
    type AnyStr = str | bytes
    """)
    pyi_expect = _src("""
    from typing import TypeAlias
    AnyStr: TypeAlias = str | bytes
    """)
    pyi_out = convert(pyi_in, python=PythonVersion.PY311)
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
    pyi_out = convert(pyi_in, python=PythonVersion.PY311)
    assert pyi_out == pyi_expect


def test_type_alias_param():
    pyi_in = _src("""
    type Pair[T] = tuple[T, T]
    """)
    pyi_expect = _src("""
    from typing import TypeAlias, TypeVar
    T = TypeVar("T")
    Pair: TypeAlias = tuple[T, T]
    """)
    pyi_out = convert(pyi_in, python=PythonVersion.PY311)
    assert pyi_out == pyi_expect


def test_type_alias_param_bound():
    pyi_in = _src("""
    type Shape2D[N: int] = tuple[N, N]
    """)
    pyi_expect = _src("""
    from typing import TypeAlias, TypeVar
    N = TypeVar("N", bound=int)
    Shape2D: TypeAlias = tuple[N, N]
    """)
    pyi_out = convert(pyi_in, python=PythonVersion.PY311)
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
    pyi_out = convert(pyi_in, python=PythonVersion.PY311)
    assert pyi_out == pyi_expect


def test_type_alias_param_default():
    pyi_in = _src("""
    type OneOrMany[T = object] = T | tuple[T, ...]
    """)
    pyi_expect = _src("""
    from typing import TypeAlias
    from typing_extensions import TypeVar
    T = TypeVar("T", default=object)
    OneOrMany: TypeAlias = T | tuple[T, ...]
    """)
    pyi_out = convert(pyi_in, python=PythonVersion.PY311)
    assert pyi_out == pyi_expect


def test_type_alias_params_order_mismatch():
    pyi_in = _src("""
    type RPair[T1, T0] = tuple[T0, T1]
    """)
    pyi_expect = _src("""
    from typing import TypeVar
    from typing_extensions import TypeAliasType
    T1 = TypeVar("T1")
    T0 = TypeVar("T0")
    RPair = TypeAliasType("RPair", tuple[T0, T1], type_params=(T1, T0))
    """)
    pyi_out = convert(pyi_in, python=PythonVersion.PY311)
    assert pyi_out == pyi_expect


def test_generic_function():
    pyi_in = _src("""
    def spam[T](x: T) -> T: ...
    """)
    pyi_expect = _src("""
    from typing import TypeVar
    T = TypeVar("T")
    def spam(x: T) -> T: ...
    """)
    pyi_out = convert(pyi_in, python=PythonVersion.PY311)
    assert pyi_out == pyi_expect


def test_generic_function_bound():
    pyi_in = _src("""
    def f[Z: complex](z: Z) -> Z: ...
    """)
    pyi_expect = _src("""
    from typing import TypeVar
    Z = TypeVar("Z", bound=complex)
    def f(z: Z) -> Z: ...
    """)
    pyi_out = convert(pyi_in, python=PythonVersion.PY311)
    assert pyi_out == pyi_expect


def test_generic_function_constraints():
    pyi_in = _src("""
    def f[Z: (int, float, complex)](z: Z) -> Z: ...
    """)
    pyi_expect = _src("""
    from typing import TypeVar
    Z = TypeVar("Z", int, float, complex)
    def f(z: Z) -> Z: ...
    """)
    pyi_out = convert(pyi_in, python=PythonVersion.PY311)
    assert pyi_out == pyi_expect


def test_generic_function_default():
    pyi_in = _src("""
    def f[Z: complex = complex](z: Z = ...) -> Z: ...
    """)
    pyi_expect = _src("""
    from typing_extensions import TypeVar
    Z = TypeVar("Z", bound=complex, default=complex)
    def f(z: Z = ...) -> Z: ...
    """)
    pyi_out = convert(pyi_in, python=PythonVersion.PY311)
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
    pyi_out = convert(pyi_in, python=PythonVersion.PY311)
    assert pyi_out == pyi_expect
