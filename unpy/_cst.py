import functools
from collections.abc import Iterable
from itertools import starmap
from typing import Literal, TypeAlias, TypedDict, Unpack, cast, overload

import libcst as cst
from libcst.helpers import filter_node_fields

from ._types import Encoding, Indent, LineEnding, StringPrefix, StringQuote

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


def _name_or_expr[T: cst.BaseExpression](value: T | str, /) -> T | cst.Name:
    return cst.Name(value) if isinstance(value, str) else value


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


def parse_name(value: str, /) -> cst.Name | cst.Attribute:
    if "." in value:
        base, attr = value.rsplit(".", 1)
        return cst.Attribute(parse_name(base), cst.Name(attr))
    return cst.Name(value)
