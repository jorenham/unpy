import functools
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import starmap
from typing import (
    Literal,
    Self,
    TypeAlias,
    TypedDict,
    Unpack,
    cast,
    final,
    overload,
    override,
)

import libcst as cst
from libcst.helpers import filter_node_fields

from ._types import (
    Encoding,
    Indent,
    LineEnding,
    PythonVersion,
    StringPrefix,
    StringQuote,
)

__all__ = [
    "as_dict",
    "get_code",
    "get_name",
    "get_name_strict",
    "node_hash",
    "parse_assign",
    "parse_bool",
    "parse_call",
    "parse_kwarg",
    "parse_name",
    "parse_str",
    "parse_tuple",
]


# PEP 695 "syntax" breaks `isinstance`
_FullName: TypeAlias = cst.Name | cst.Attribute
_AssignTarget: TypeAlias = cst.BaseAssignTargetExpression | str


class _ModuleKwargs(TypedDict):
    encoding: Encoding
    default_indent: Indent
    default_newline: LineEnding
    has_trailing_newline: bool


def get_code(
    node: cst.CSTNode,
    /,
    **kwargs: Unpack[_ModuleKwargs],
) -> str:
    """
    Generate the code of the given node.

    Note:
        For simple nodes like `cst.Name` and `cst.Attribute` this can be ~50x slower
        than `get_name()`.
    """
    if isinstance(node, cst.Module):
        return node.code

    return cst.Module([], **kwargs).code_for_node(node)


@overload
def get_name(
    node: str
    | cst.Name
    | cst.TypeParam
    | cst.TypeAlias
    | cst.FunctionDef
    | cst.ClassDef
    | cst.Ellipsis,
    /,
) -> str: ...
@overload
def get_name(node: cst.CSTNode, /) -> str | None: ...
def get_name(node: str | cst.CSTNode, /) -> str | None:  # noqa: C901, PLR0911
    if isinstance(node, str):
        return node
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        # avoid excess recursion by looking (at most) 2 steps ahead
        attr = node.attr.value
        if isinstance(b0 := node.value, cst.Name):
            return f"{b0.value}.{attr}"
        if isinstance(b0, cst.Attribute):
            if isinstance(b1 := b0.value, cst.Name):
                return f"{b1.value}.{b0.attr.value}.{attr}"
            return f"{get_name(b1)}.{b0.attr.value}.{attr}"
        return f"{get_name(b0)}.{attr}"
    # if isinstance(node, cst.Subscript):
    #     return get_name(node.value)
    # if isinstance(node, cst.Call):
    #     return get_name(node.func)
    if isinstance(node, cst.Decorator):
        return get_name(node.decorator)
    if isinstance(node, cst.TypeParam):
        return node.param.name.value
    if isinstance(node, cst.TypeVar | cst.TypeVarTuple | cst.ParamSpec):
        return node.name.value
    if isinstance(node, cst.Ellipsis):
        return "Ellipsis"

    return None


def get_name_strict(node: str | cst.CSTNode, /) -> str:
    if name := get_name(node):
        return name

    from libcst.display import dump  # noqa: PLC0415

    assert not isinstance(node, str)
    raise NotImplementedError(f"not able to parse full name for: {dump(node)}")


def as_dict(
    node: cst.CSTNode,
    /,
    *,
    defaults: bool = False,
    syntax: bool = False,
    whitespace: bool = False,
) -> dict[str, object]:
    kwargs = {
        "defaults": defaults,
        "syntax": syntax,
        "whitespace": whitespace,
    }

    out: dict[str, object] = {}
    for field in filter_node_fields(
        node,
        show_syntax=syntax,
        show_defaults=defaults,
        show_whitespace=whitespace,
    ):
        key = field.name
        value: object = getattr(node, key)

        if isinstance(value, cst.CSTNode):
            value = as_dict(value, **kwargs)
        elif isinstance(value, list) and value and isinstance(value[0], cst.CSTNode):
            value = [as_dict(v, **kwargs) for v in cast(list[cst.CSTNode], value)]

        out[key] = value

    return out


def as_tuple(
    node: cst.CSTNode,
    /,
    *,
    defaults: bool = False,
    syntax: bool = False,
    whitespace: bool = False,
) -> tuple[str, tuple[object, ...]]:
    kwargs = {
        "defaults": defaults,
        "syntax": syntax,
        "whitespace": whitespace,
    }

    out: list[object] = []
    for field in filter_node_fields(
        node,
        show_defaults=defaults,
        show_syntax=syntax,
        show_whitespace=whitespace,
    ):
        key = field.name
        value: object = getattr(node, key)

        if isinstance(value, cst.CSTNode):
            value = as_tuple(value, **kwargs)
        elif isinstance(value, list):
            value = tuple(
                as_tuple(v, **kwargs) if isinstance(v, cst.CSTNode) else v
                for v in cast(list[object], value)
            )

        out.append(value)

    return type(node).__name__, tuple(out)


def node_hash(node: cst.CSTNode, /, **kwargs: bool) -> int:
    return hash((type(node).__name__, as_tuple(node, **kwargs)))


@functools.cache  # type: ignore[no-any-expr]
def parse_bool(value: bool | Literal[0, 1], /) -> cst.Name:
    return cst.Name("True" if value else "False")


def parse_str(
    value: str,
    /,
    *,
    quote: StringQuote = '"',
    prefix: StringPrefix = "",
) -> cst.SimpleString:
    return cst.SimpleString(f"{prefix}{quote}{value}{quote}")


def parse_kwarg(key: str, value: cst.BaseExpression, /) -> cst.Arg:
    return cst.Arg(
        keyword=cst.Name(key),
        value=value,
        equal=cst.AssignEqual(cst.SimpleWhitespace(""), cst.SimpleWhitespace("")),
    )


def parse_tuple(
    exprs: Iterable[cst.BaseExpression],
    /,
    *,
    star: cst.BaseExpression | None = None,
    parens: bool = True,
) -> cst.Tuple:
    elems: list[cst.BaseElement] = [cst.Element(el) for el in exprs]
    if star is not None:
        elems.append(cst.StarredElement(star))

    return cst.Tuple(elems) if parens else cst.Tuple(elems, [], [])


def parse_name(value: str, /) -> _FullName:
    if "." in value:
        base, attr = value.rsplit(".", 1)
        return cst.Attribute(parse_name(base), cst.Name(attr))
    return cst.Name(value)


@overload
def _name_or_expr[T: cst.BaseExpression](value: T, /) -> T: ...
@overload
def _name_or_expr[T: cst.BaseExpression](value: str, /) -> cst.Name | cst.Attribute: ...
def _name_or_expr[T: cst.BaseExpression](
    value: T | str,
    /,
) -> T | cst.Name | cst.Attribute:
    return parse_name(value) if isinstance(value, str) else value


def parse_call(
    func: cst.BaseExpression | str,
    /,
    *args: cst.BaseExpression,
    **kwargs: cst.BaseExpression,
) -> cst.Call:
    return cst.Call(
        _name_or_expr(func),
        [*map(cst.Arg, args), *starmap(parse_kwarg, kwargs.items())],
    )


def parse_subscript(
    base: cst.BaseExpression | str,
    /,
    *ixs: cst.BaseSlice | cst.BaseExpression,
) -> cst.Subscript:
    elems = [
        cst.SubscriptElement(ix if isinstance(ix, cst.BaseSlice) else cst.Index(ix))
        for ix in ixs
    ]
    return cst.Subscript(_name_or_expr(base), elems)


def parse_assign(
    target: _AssignTarget | tuple[_AssignTarget, ...],
    value: cst.BaseExpression,
    /,
) -> cst.Assign:
    if isinstance(target, _AssignTarget):
        targets = [_name_or_expr(target)]
    else:
        targets = [_name_or_expr(t) for t in target]
    return cst.Assign(list(map(cst.AssignTarget, targets)), value)


# TODO: `@sealed`
@dataclass(frozen=True, slots=True)
class TypeParameter:
    type: Literal["TypeVar", "TypeVarTuple", "ParamSpec"]

    name: str
    default: cst.BaseExpression | None = None

    @property
    def invariant(self, /) -> bool:
        return True

    def required_imports(self, /, target: PythonVersion) -> frozenset[str]:
        """The imports it would require to use this as typevar-like (no PEP 695)."""
        raise NotImplementedError

    def as_assign(self, /, target: PythonVersion) -> cst.Assign:
        raise NotImplementedError

    def as_subscript_element(self, /, target: PythonVersion) -> cst.SubscriptElement:  # noqa: ARG002
        return cst.SubscriptElement(cst.Index(cst.Name(self.name)))

    @classmethod
    def from_cst(cls, node: cst.TypeParam, /) -> Self:
        # TODO
        raise NotImplementedError


@final
@dataclass(frozen=True, slots=True)
class TypeVar(TypeParameter):
    covariant: bool = False
    contravariant: bool = False
    infer_variance: bool = False

    bound: cst.BaseExpression | None = None
    constraints: tuple[cst.BaseExpression, ...] = ()

    alias_type: str = "TypeVar"

    @property
    @override
    def invariant(self, /) -> bool:
        return not (self.covariant or self.contravariant or self.infer_variance)

    @override
    def required_imports(self, /, target: PythonVersion) -> frozenset[str]:
        module = (
            "typing_extensions"
            if (target < (3, 13) and self.default)
            or (target < (3, 12) and self.infer_variance)
            else "typing"
        )
        return frozenset({f"{module}.TypeVar"})

    @override
    def as_assign(self, /, target: PythonVersion) -> cst.Assign:
        kwargs: dict[str, cst.BaseExpression] = {}

        for key in ("covariant", "contravariant", "infer_variance"):
            if value := cast(bool, getattr(self, key)):
                kwargs[key] = parse_bool(value)

        if bound := self.bound:
            kwargs["bound"] = bound
        if default := self.default:
            kwargs["default"] = default

        return parse_assign(
            cst.Name(self.name),
            parse_call(
                parse_name(self.alias_type),
                parse_str(self.name),
                *self.constraints,
                **kwargs,
            ),
        )


@final
@dataclass(frozen=True, slots=True)
class TypeVarTuple(TypeParameter):
    default_star: bool = False

    alias_type: str = "TypeVarTuple"
    alias_unpack: str = "Unpack"

    @override
    def required_imports(self, /, target: PythonVersion) -> frozenset[str]:
        # `typing.TypeVarTuple` exists since 3.11, and supports `default=` since 3.13

        if target < (3, 11) or self.default_star:
            # unpacking a `default=` always requires `Unpack`
            module = "typing_extensions" if target < (3, 13) else "typing"
            return frozenset({f"{module}.TypeVarTuple", f"{module}.Unpack"})

        module = "typing_extensions" if target < (3, 13) and self.default else "typing"
        return frozenset({f"{module}.TypeVarTuple"})

    @override
    def as_assign(self, /, target: PythonVersion) -> cst.Assign:
        kwargs: dict[str, cst.BaseExpression] = {}
        if self.default_star:
            kwargs["default"] = self.as_unpack(target)
        elif default := self.default:
            kwargs["default"] = default

        return parse_assign(
            cst.Name(self.name),
            parse_call(parse_name(self.alias_type), parse_str(self.name), **kwargs),
        )

    @override
    def as_subscript_element(self, /, target: PythonVersion) -> cst.SubscriptElement:
        if target < (3, 11):
            index = cst.Index(self.as_unpack(target))
        else:
            index = cst.Index(cst.Name(self.name), star="*")
        return cst.SubscriptElement(index)

    def as_unpack(self, /, target: PythonVersion) -> cst.BaseExpression:
        return cst.Subscript(
            parse_name(self.alias_unpack),
            [super().as_subscript_element(target)],
        )


@final
@dataclass(frozen=True, slots=True)
class ParamSpec(TypeParameter):
    alias_type: str = "ParamSpec"

    @override
    def required_imports(self, /, target: PythonVersion) -> frozenset[str]:
        module = "typing_extensions" if target < (3, 13) and self.default else "typing"
        return frozenset({f"{module}.{self.type}"})

    @override
    def as_assign(self, /, target: PythonVersion) -> cst.Assign:
        return parse_assign(
            cst.Name(self.name),
            parse_call(
                parse_name(self.alias_type),
                parse_str(self.name),
                **({"default": default} if (default := self.default) else {}),
            ),
        )
