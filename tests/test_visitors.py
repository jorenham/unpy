# ruff: noqa: FLY002

import libcst as cst
import pytest
from unpy.visitors import StubVisitor


def _visit(*lines: str) -> StubVisitor:
    source = "\n".join(lines).rstrip() + "\n"
    _ = cst.MetadataWrapper(cst.parse_module(source)).visit(visitor := StubVisitor())
    return visitor


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
    assert visitor._import_access == {"w.deprecated": ("warnings", "deprecated")}


def test_import_access_deep() -> None:
    visitor = _visit(
        "import collections as cs",
        "type CanBuffer = cs.abc.Buffer",
    )
    assert visitor.global_names == {"cs", "CanBuffer"}
    assert visitor.imports == {"collections": "cs"}
    assert visitor.imports_by_alias == {"cs": "collections"}
    assert visitor._import_access == {"cs.abc.Buffer": ("collections", "abc.Buffer")}


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
    assert visitor._import_access == {}
    assert visitor.imported_as("a", "x") == "x"


def test_importfrom_single_deep() -> None:
    visitor = _visit("from a.b.c import x")
    assert visitor.imports == {"a.b.c.x": "x"}
    assert visitor.imports_by_alias == {"x": "a.b.c.x"}
    assert visitor._import_access == {}
    assert visitor.imported_as("a.b.c", "x") == "x"


def test_importfrom_single_package() -> None:
    visitor = _visit("from a import b")
    assert visitor.imports == {"a.b": "b"}
    assert visitor.imports_by_alias == {"b": "a.b"}
    assert visitor._import_access == {}
    assert visitor.imported_as("a.b", "c") == "b.c"
    assert visitor.imported_as("a.b.c", "x") == "b.c.x"


def test_importfrom_single_as() -> None:
    visitor = _visit("from a import x as _x")
    assert visitor.imports == {"a.x": "_x"}
    assert visitor.imports_by_alias == {"_x": "a.x"}
    assert visitor._import_access == {}
    assert visitor.imported_as("a", "x") == "_x"
    assert visitor.imported_as("a", "_x") is None
    assert visitor.imported_as("a", "y") is None
    assert visitor.imported_as("b", "x") is None


def test_importfrom_single_deep_as() -> None:
    visitor = _visit("from a.b.c import x as _x")
    assert visitor.imports == {"a.b.c.x": "_x"}
    assert visitor.imports_by_alias == {"_x": "a.b.c.x"}
    assert visitor._import_access == {}
    assert visitor.imported_as("a.b.c", "_x") is None
    assert visitor.imported_as("a.b.c", "y") is None
    assert visitor.imported_as("a.b", "c") is None
    assert visitor.imported_as("a", "b") is None


def test_importfrom_star() -> None:
    visitor = _visit("from a import *")
    assert visitor.imports == {"a.*": "*"}
    assert visitor.imports_by_alias == {}
    assert visitor._import_access == {}
    assert visitor.imported_as("a", "x") == "x"


def test_importfrom_deep_star() -> None:
    visitor = _visit("from a.b.c import *")
    assert visitor.imports == {"a.b.c.*": "*"}
    assert visitor.imports_by_alias == {}
    assert visitor._import_access == {}
    assert visitor.imported_as("a.b.c", "x") == "x"
    assert visitor.imported_as("a.b", "x") is None
    assert visitor.imported_as("a.b", "c") is None
    assert visitor.imported_as("a", "x") is None
    assert visitor.imported_as("a", "b") is None


# accessed imports


def test_import_access_unused() -> None:
    visitor = _visit("import a")
    assert visitor._import_access == {}


def test_import_access_module() -> None:
    visitor = _visit(
        "import typing",
        "typing",
    )
    assert visitor._import_access == {"typing": ("typing", None)}


def test_import_access_module_alias() -> None:
    visitor = _visit(
        "import typing as tp",
        "tp",
    )
    assert visitor._import_access == {"tp": ("typing", None)}


def test_import_access_module_attr() -> None:
    visitor = _visit(
        "import typing",
        "Char: typing.TypeAlias = str | int",
    )
    assert visitor._import_access == {"typing.TypeAlias": ("typing", "TypeAlias")}


def test_import_access_module_alias_attr() -> None:
    visitor = _visit(
        "import typing as tp",
        "Char: tp.TypeAlias = str | int",
    )
    assert visitor._import_access == {"tp.TypeAlias": ("typing", "TypeAlias")}


def test_import_access_package_module_attr() -> None:
    visitor = _visit(
        "import collections.abc",
        "def f() -> collections.abc.Sequence[int]: ...",
    )
    assert visitor._import_access == {
        "collections.abc.Sequence": ("collections.abc", "Sequence"),
    }


def test_import_access_package_module_alias_attr() -> None:
    visitor = _visit(
        "import collections.abc as abcol",
        "def f() -> abcol.Sequence[int]: ...",
    )
    assert visitor._import_access == {
        "abcol.Sequence": ("collections.abc", "Sequence"),
    }


def test_import_access_package_attr_attr() -> None:
    visitor = _visit(
        "import collections",
        "def f() -> collections.abc.Sequence[int]: ...",
    )
    assert visitor._import_access == {
        "collections.abc.Sequence": ("collections", "abc.Sequence"),
    }


# baseclass
# TODO: more tests


def test_baseclasses_single() -> None:
    visitor = _visit(
        "from typing import Protocol as Interface",
        "class C[T](Interface): ...",
    )
    assert visitor.class_bases == {"C": ["Interface"]}


# type params
# TODO
