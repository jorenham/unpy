# ruff: noqa: FLY002

import libcst as cst
import pytest
from unpy.exceptions import StubError
from unpy.visitors import StubVisitor


def _visit(*lines: str) -> StubVisitor:
    source = "\n".join(lines).rstrip() + "\n"
    _ = cst.MetadataWrapper(cst.parse_module(source)).visit(visitor := StubVisitor())
    return visitor


# stub errors


def test_illegal_future_import():
    # https://github.com/jorenham/unpy/issues/43
    with pytest.raises(StubError):
        _visit("from __future__ import annotations")


@pytest.mark.parametrize(
    "source",
    [
        "Const: 'str' = ...",
        "type Alias = 'str'",
        "from typing import TypeAlias\nAlias: TypeAlias = 'str'",
        "from typing import TypeAliasType\nAlias = TypeAliasType('Alias', 'str')",
        "from typing import TypeVar\nT = TypeVar('T', bound='str')",
        "from typing import TypeVar\nT = TypeVar('T', default='str')",
        "def f(x: 'str') -> str: ...",
        "def f(x: str) -> 'str': ...",
        "def f[T: 'str'](x: T) -> T: ...",
        "def f[T: str = 'str'](x: T) -> T: ...",
        "class C[T: 'str']: ...",
        "class C[T: str = 'str']: ...",
    ],
)
def test_illegal_stringified_annotations(source: str):
    with pytest.raises(StubError):
        _visit(source)


@pytest.mark.parametrize(
    "source",
    [
        "def __dir__() -> list[str]: ...",
        "def __getattr__(name: str, /) -> object: ...",
    ],
)
def test_illegal_special_functions_at_module_lvl(source: str):
    with pytest.raises(StubError):
        _visit(source)


# imports


def test_import_builtins() -> None:
    visitor = _visit("...")
    assert not visitor.global_names
    assert not visitor.imports
    assert visitor.imported_as("builtins", "bool") == "bool"
    assert visitor.imported_as("a", "bool") is None


def test_import_builtins_shadowing() -> None:
    visitor = _visit("class bool: ...")
    assert visitor.global_names == {"bool"}
    assert not visitor.imports
    assert visitor.imported_as("builtins", "bool") == "__builtins__.bool"


def test_import_single() -> None:
    visitor = _visit("import a")
    assert visitor.global_names == {"a"}
    assert visitor.imports == {"a": "a"}
    assert visitor.imported_as("a", "x") == "a.x"
    assert visitor.imported_as("b", "x") is None


def test_import_single_deep() -> None:
    visitor = _visit("import a.b.c")
    assert visitor.global_names == {"a"}
    imports_expected = {"a": "a", "a.b": "a.b", "a.b.c": "a.b.c"}
    assert visitor.imports == imports_expected
    assert visitor.imports_by_alias == imports_expected
    assert visitor.imported_as("a.b.c", "x") == "a.b.c.x"
    assert visitor.imported_as("a.b", "x") == "a.b.x"
    assert visitor.imported_as("a", "x") == "a.x"
    assert visitor.imported_as("b", "x") is None
    assert visitor.imported_as("c", "x") is None
    assert visitor.imported_as("b.c", "x") is None


def test_import_single_as() -> None:
    visitor = _visit("import a as _a")
    assert visitor.global_names == {"_a"}
    assert visitor.imports == {"a": "_a"}
    assert visitor.imported_as("a", "x") == "_a.x"
    assert visitor.imported_as("b", "x") is None


def test_import_single_deep_as() -> None:
    visitor = _visit("import a.b.c as _abc")
    assert visitor.global_names == {"_abc"}
    assert visitor.imports == {"a.b.c": "_abc"}
    assert visitor.imported_as("a.b.c", "x") == "_abc.x"
    assert visitor.imported_as("a.b.f", "x") is None
    assert visitor.imported_as("a.b", "x") is None
    assert visitor.imported_as("a", "x") is None


def test_import_multi() -> None:
    visitor = _visit(
        "import a1, a2",
        "import b1, b2",
    )
    assert visitor.global_names == {"a1", "a2", "b1", "b2"}
    assert visitor.imports == {
        "a1": "a1",
        "a2": "a2",
        "b1": "b1",
        "b2": "b2",
    }
    assert visitor.imported_as("a1", "x") == "a1.x"
    assert visitor.imported_as("a2", "x") == "a2.x"
    assert visitor.imported_as("b1", "x") == "b1.x"
    assert visitor.imported_as("b2", "x") == "b2.x"


def test_import_access() -> None:
    visitor = _visit(
        "import warnings as w",
        '@w.deprecated("RTFM")',
        "def f() -> None: ...",
    )
    assert visitor.global_names == {"w", "f"}
    assert visitor.imports == {"warnings": "w"}
    assert visitor.imports_by_alias == {"w": "warnings"}
    assert visitor.imports_by_ref == {"w.deprecated": ("warnings", "deprecated")}


def test_import_access_deep() -> None:
    visitor = _visit(
        "import collections as cs",
        "type CanBuffer = cs.abc.Buffer",
    )
    assert visitor.global_names == {"cs", "CanBuffer"}
    assert visitor.imports == {"collections": "cs"}
    assert visitor.imports_by_alias == {"cs": "collections"}
    assert visitor.imports_by_ref == {"cs.abc.Buffer": ("collections", "abc.Buffer")}


def test_import_multiple_alias() -> None:
    with pytest.raises(NotImplementedError):
        _ = _visit(
            "import typing",
            "import typing as tp",
        )


def test_import_assignment_alias() -> None:
    with pytest.raises(NotImplementedError):
        _ = _visit(
            "import typing",
            "tp = typing",
        )


def test_import_assignment_alias_deep() -> None:
    with pytest.raises(NotImplementedError):
        _ = _visit(
            "import collections.abc",
            "cols = collections",
        )


def test_importfrom_single() -> None:
    visitor = _visit("from a import x")
    assert visitor.imports == {"a.x": "x"}
    assert visitor.imports_by_alias == {"x": "a.x"}
    assert visitor.imports_by_ref == {}
    assert visitor.imported_as("a", "x") == "x"


def test_importfrom_single_deep() -> None:
    visitor = _visit("from a.b.c import x")
    assert visitor.imports == {"a.b.c.x": "x"}
    assert visitor.imports_by_alias == {"x": "a.b.c.x"}
    assert visitor.imports_by_ref == {}
    assert visitor.imported_as("a.b.c", "x") == "x"


def test_importfrom_single_package() -> None:
    visitor = _visit("from a import b")
    assert visitor.imports == {"a.b": "b"}
    assert visitor.imports_by_alias == {"b": "a.b"}
    assert visitor.imports_by_ref == {}
    assert visitor.imported_as("a.b", "c") == "b.c"
    assert visitor.imported_as("a.b.c", "x") == "b.c.x"


def test_importfrom_single_as() -> None:
    visitor = _visit("from a import x as _x")
    assert visitor.imports == {"a.x": "_x"}
    assert visitor.imports_by_alias == {"_x": "a.x"}
    assert visitor.imports_by_ref == {}
    assert visitor.imported_as("a", "x") == "_x"
    assert visitor.imported_as("a", "_x") is None
    assert visitor.imported_as("a", "y") is None
    assert visitor.imported_as("b", "x") is None


def test_importfrom_single_deep_as() -> None:
    visitor = _visit("from a.b.c import x as _x")
    assert visitor.imports == {"a.b.c.x": "_x"}
    assert visitor.imports_by_alias == {"_x": "a.b.c.x"}
    assert visitor.imports_by_ref == {}
    assert visitor.imported_as("a.b.c", "_x") is None
    assert visitor.imported_as("a.b.c", "y") is None
    assert visitor.imported_as("a.b", "c") is None
    assert visitor.imported_as("a", "b") is None


def test_importfrom_star() -> None:
    visitor = _visit("from a import *")
    assert visitor.imports == {"a.*": "*"}
    assert visitor.imports_by_alias == {}
    assert visitor.imports_by_ref == {}
    assert visitor.imported_as("a", "x") == "x"


def test_importfrom_deep_star() -> None:
    visitor = _visit("from a.b.c import *")
    assert visitor.imports == {"a.b.c.*": "*"}
    assert visitor.imports_by_alias == {}
    assert visitor.imports_by_ref == {}
    assert visitor.imported_as("a.b.c", "x") == "x"
    assert visitor.imported_as("a.b", "x") is None
    assert visitor.imported_as("a.b", "c") is None
    assert visitor.imported_as("a", "x") is None
    assert visitor.imported_as("a", "b") is None


# accessed imports


def test_import_access_unused() -> None:
    visitor = _visit("import a")
    assert visitor.imports_by_ref == {}


def test_import_access_module() -> None:
    visitor = _visit(
        "import typing",
        "typing",
    )
    assert visitor.imports_by_ref == {"typing": ("typing", None)}


def test_import_access_module_alias() -> None:
    visitor = _visit(
        "import typing as tp",
        "tp",
    )
    assert visitor.imports_by_ref == {"tp": ("typing", None)}


def test_import_access_module_attr() -> None:
    visitor = _visit(
        "import typing",
        "Char: typing.TypeAlias = str | int",
    )
    assert visitor.imports_by_ref == {"typing.TypeAlias": ("typing", "TypeAlias")}


def test_import_access_module_alias_attr() -> None:
    visitor = _visit(
        "import typing as tp",
        "Char: tp.TypeAlias = str | int",
    )
    assert visitor.imports_by_ref == {"tp.TypeAlias": ("typing", "TypeAlias")}


def test_import_access_package_module_attr() -> None:
    visitor = _visit(
        "import collections.abc",
        "def f() -> collections.abc.Sequence[int]: ...",
    )
    assert visitor.imports_by_ref == {
        "collections.abc.Sequence": ("collections.abc", "Sequence"),
    }


def test_import_access_package_module_alias_attr() -> None:
    visitor = _visit(
        "import collections.abc as abcol",
        "def f() -> abcol.Sequence[int]: ...",
    )
    assert visitor.imports_by_ref == {
        "abcol.Sequence": ("collections.abc", "Sequence"),
    }


def test_import_access_package_attr_attr() -> None:
    visitor = _visit(
        "import collections",
        "def f() -> collections.abc.Sequence[int]: ...",
    )
    assert visitor.imports_by_ref == {
        "collections.abc.Sequence": ("collections", "abc.Sequence"),
    }


# baseclasses

def test_baseclasses_single() -> None:
    visitor = _visit(
        "from typing import Protocol as Interface",
        "class C[T](Interface): ...",
    )
    assert visitor.class_bases == {"C": ["Interface"]}


# type params
# TODO

# nested ClassVar and Final
def test_nested_classvar_final() -> None:
    visitor_tn = _visit(
        "from typing import ClassVar, Final",
        "class C:",
        "    a: ClassVar[int] = 1",
        "    b: Final[int]",
    )
    visitor_tp = _visit(
        "from typing import ClassVar, Final",
        "class C:",
        "    a: ClassVar[Final[int]] = 1",
    )
    visitor_tp_inv = _visit(
        "from typing import ClassVar, Final",
        "class C:",
        "    a: Final[ClassVar[int]] = 1",
    )
    visitor_tp_indirect = _visit(
        "import typing as tp",
        "class C:",
        "    a: tp.ClassVar[tp.Final[int]] = 1",
    )
    assert not visitor_tn.nested_classvar_final
    assert visitor_tp.nested_classvar_final
    assert visitor_tp_inv.nested_classvar_final
    assert visitor_tp_indirect.nested_classvar_final
