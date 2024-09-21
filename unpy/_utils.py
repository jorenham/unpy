import functools
from collections.abc import Iterable
from itertools import starmap
from typing import Literal, TypeAlias, cast

import libcst as cst
from libcst.helpers import filter_node_fields, get_full_name_for_node

__all__ = [
    "as_dict",
    "as_module",
    "node_code",
    "node_hash",
    "parse_assign",
    "parse_bool",
    "parse_call",
    "parse_kwarg",
    "parse_str",
    "parse_tuple",
]

type StringPrefix = Literal["", "r", "u", "b", "br", "rb"]
type StringQuote = Literal["'", '"', "'''", '"""']

# PEP 695 "syntax" breaks `isinstance`
_AssignTarget: TypeAlias = cst.BaseAssignTargetExpression | str
_AnyNode: TypeAlias = (
    cst.CSTNode
    | cst.RemovalSentinel
    | cst.FlattenSentinel[cst.CSTNode]
)  # fmt: skip


def as_module(node: _AnyNode, /) -> cst.Module:
    match node:
        case cst.Module() as module:
            return module
        case cst.SimpleStatementLine() | cst.BaseCompoundStatement() as stmt:
            return cst.Module([stmt])
        case cst.BaseSmallStatement() as stmt:
            return cst.Module([cst.SimpleStatementLine([stmt])])
        case cst.RemovalSentinel():
            return cst.Module([])
        case cst.FlattenSentinel(nodes=nodes):
            body: list[cst.SimpleStatementLine | cst.BaseCompoundStatement] = []
            for n in nodes:
                body.extend(as_module(n).body)
            return cst.Module(body)
        case _:
            raise TypeError(type(node))


def node_code(node: _AnyNode, /) -> str:
    if isinstance(node, cst.CSTNode):
        return get_full_name_for_node(node) or as_module(node).code
    return as_module(node).code


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
