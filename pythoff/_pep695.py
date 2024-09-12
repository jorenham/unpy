import collections
import enum
from collections.abc import Mapping
from typing import Final, cast, override

import libcst as cst
from libcst.metadata import ParentNodeProvider


class ScopeKind(enum.IntEnum):
    # TODO: `MODULE = 0`  (e.g. `T = TypeVar("T, ...)`)

    TYPE = 1  # type alias type

    CLASS = 2
    # TODO: `PROTOCOL = 3` (i.e. has `typing[_extensions].Protocol` as a base class)

    DEF = 4
    DEF_OVERLOAD = 5


class PEP695Collector(cst.CSTVisitor):
    """
    Collect all PEP-695 type-parameters in functions / classes / type-aliases.

    TODO:
        - `type {name}[...] = ...`
        - `def {name}[...]: ...`
            - global functions
            - inner functions (closures)
            - instance/class/static methods
        - `class {name}[...]: ...`
        - `.py` only: detect/stringify forward references in `bounds=_` and `default=_`
        - detect `covariance` / `contravariance` (or use `infer_variance=True`)
            - implement `visit_Attribute` or `visit_AnnAssign` for attrs
            - inspect `FunctionDef.params.params.*annotation: *Annotation`
            - inspect `FunctionDef.returns: Annotation`
        - move `python>=3.12` imports from `typing` to `typing_extensions`
        - in case of `import typing[ as _]` or `import typing_extensions[ as _]`, use
            those later on.
        - detect existing typevar-likes
    """

    METADATA_DEPENDENCIES = ()

    _stack: collections.deque[str]

    is_pyi: Final[bool]
    # [(name, ...)] -> (type_params, infer_variance)
    type_params: dict[tuple[str, ...], list[tuple[cst.TypeParam, ScopeKind]]]
    # [(name, ...) -> count]
    overloads: dict[tuple[str, ...], int]

    # TODO: `from {module} import {name} as {alias}`
    cur_imports_typing: set[str]
    cur_imports_typing_extensions: set[str]
    req_imports_typing: set[str]
    req_imports_typing_extensions: set[str]

    def __init__(self, /, *, is_pyi: bool) -> None:
        self.is_pyi = is_pyi
        self._stack = collections.deque()
        self.type_params = collections.defaultdict(list)
        self.overloads = collections.defaultdict(int)

        self.cur_imports_typing = set()
        self.cur_imports_typing_extensions = set()
        self.req_imports_typing = set()
        self.req_imports_typing_extensions = set()

        super().__init__()

    @override
    def visit_ImportFrom(self, /, node: cst.ImportFrom) -> bool | None:
        if node.relative or not (module := node.module):
            return False

        from_ = module.value
        if from_ not in {"typing", "typing_extensions"}:
            return False

        if isinstance(node.names, cst.ImportStar):
            raise NotImplementedError(f"from {from_} import *")

        imported: set[str] = set()
        for alias in node.names:
            name = alias.name.value
            assert isinstance(name, str)

            if alias.asname:
                # `from _ import {a} as {b}` is no problem if `{a} == {b}`
                as_ = getattr(alias.asname.name, "value", None)
                assert as_
                if as_ != name:
                    raise NotImplementedError(f"from {from_} import _ as _")

            imported.add(name)

        if from_ == "typing":
            self.cur_imports_typing.update(imported)
        else:
            self.cur_imports_typing_extensions.update(imported)

        return False

    @override
    def visit_TypeAlias(self, /, node: cst.TypeAlias) -> bool | None:
        # no need to push to the stack

        imported = False
        if type_params := node.type_parameters:
            assert not self._stack

            key = (node.name.value,)
            assert key not in self.type_params

            self.type_params[key] = [(p, ScopeKind.TYPE) for p in type_params.params]

            if len(type_params.params) > 1:
                # TODO: only do this if the order differs between the LHS and RHS.
                self.req_imports_typing_extensions.add("TypeAliasType")
                imported = True
                return False

        if not imported:
            self.req_imports_typing.add("TypeAlias")

        # no need to traverse the body
        # TODO: traverse and check the usage order of the type-parameters
        return False

    @override
    def visit_ClassDef(self, /, node: cst.ClassDef) -> bool | None:
        stack = self._stack
        stack.append(node.name.value)

        key = tuple(stack)
        assert key not in self.type_params

        # TODO: detect if this is a protocol
        # TODO: extact old-style `Generic[T]` and `Protocol[T]` generic type params

        if not (type_params := node.type_parameters):
            self.type_params[key] = []
            return

        self.type_params[key] = [(p, ScopeKind.CLASS) for p in type_params.params]
        # infer_variance requires typing_extensions
        self.req_imports_typing_extensions.update(
            type(p.param).__name__ for p in type_params.params
        )

    @override
    def leave_ClassDef(self, /, original_node: cst.ClassDef) -> None:
        name = self._stack.pop()
        assert name == original_node.name.value

    @override
    def visit_FunctionDef(self, /, node: cst.FunctionDef) -> bool | None:
        stack = self._stack
        stack.append(node.name.value)

        kind = ScopeKind.DEF

        if type_params := node.type_parameters:
            key = tuple(stack)

            if node.decorators and (
                "overload" in self.cur_imports_typing
                or "overload" in self.cur_imports_typing_extensions
            ):
                for decorator in node.decorators:
                    match decorator.decorator:
                        case cst.Name("overload"):
                            kind = ScopeKind.DEF_OVERLOAD
                            break
                        case _:
                            pass

            self.type_params[key] += [(p, kind) for p in type_params.params]
            import_names = (type(p.param).__name__ for p in type_params.params)
            if any(p.default for p in type_params.params):
                self.req_imports_typing.update(import_names)
            else:
                self.req_imports_typing_extensions.update(import_names)

        # stubs don't define function bodies
        return False if kind is ScopeKind.DEF_OVERLOAD or self.is_pyi else None

    @override
    def leave_FunctionDef(self, /, original_node: cst.FunctionDef) -> None:
        name = self._stack.pop()
        assert name == original_node.name.value


def bool_expr(value: bool, /) -> cst.Name:
    return cst.Name("True" if value else "False")


def str_expr(value: str, /) -> cst.SimpleString:
    # TODO: Configurable quote style
    return cst.SimpleString(f"'{value}'")


def kwarg_expr(key: str, value: cst.BaseExpression, /) -> cst.Arg:
    return cst.Arg(
        keyword=cst.Name(key),
        value=value,
        equal=cst.AssignEqual(cst.SimpleWhitespace(""), cst.SimpleWhitespace("")),
    )


def backport_type_param(  # noqa: C901
    type_param: cst.TypeParam,
    /,
    *,
    contravariant: bool = False,
    covariant: bool = False,
    infer_variance: bool = False,
) -> cst.Assign:
    param = type_param.param
    name = param.name.value

    args = [cst.Arg(str_expr(name))]

    match param:
        case cst.TypeVar(_, bound):
            if infer_variance:
                if len(name) > 6 and name.endswith("_contra"):
                    variance = "contravariant"
                elif len(name) > 3 and name.endswith("_co"):
                    variance = "covariant"
                else:
                    variance = "infer_variance"
            elif contravariant:
                variance = "contravariant"
            elif covariant:
                variance = "covariant"
            else:
                variance = None
            if variance:
                args.append(kwarg_expr(variance, bool_expr(True)))

            match bound:
                case None | cst.Name("object"):
                    # `bound=object` is the default, so can be skipped
                    bound = None
                case cst.Tuple(elements):
                    # TODO: Configurable flag to convert constraints to `bound`
                    for el in elements:
                        assert isinstance(el, cst.Element)
                        con = el.value
                        if isinstance(con, cst.Name) and con.value == "Any":
                            # `Any` is literally Hitler
                            con = cst.Name("object")
                        args.append(cst.Arg(con))
                    bound = None
                case cst.Name("Any") as bound_any:
                    # `Any` is literally Hitler; use `object` instead
                    bound = cst.Name("object", lpar=bound_any.lpar, rpar=bound_any.rpar)
                case cst.BaseExpression():
                    pass

            if bound:
                args.append(kwarg_expr("bound", bound))

        case cst.TypeVarTuple(_) | cst.ParamSpec(_):
            bound = cst.Name("object")

    match default := type_param.default:
        case None:
            pass
        case cst.Name("Any") as _b:
            default = bound or cst.Name("object", lpar=_b.lpar, rpar=_b.rpar)
        case cst.BaseExpression():
            pass

    if default:
        args.append(kwarg_expr("default", default))

    return cst.Assign(
        targets=[cst.AssignTarget(target=cst.Name(name))],
        value=cst.Call(func=cst.Name(type(param).__name__), args=args),
    )


class PEP695Transformer(cst.CSTTransformer):
    """
    Backports PEP 695 (`python>=3.12`) syntax to be compatible with `python>=3.11<3.12`.

    - TODO: Adds global `TypeVar`, `TypeVarTuple`, and `ParamSpec` assignments
        - TODO: User-configurable placement (top of the file / near the first reference)
        - TODO: Uses `infer_variance=True` for class-scoped type params
        - TODO: Import `TypeVar[Tuple]` and / or `ParamSpec` from `typing_extensions`
    - TODO: Replaces `type {} = ...` type-aliases with `{}: TypeAlias = ...`
        - TODO: Use `TypeAliasType` if the LHS/RHS type-param have a different order
    - Strip PEP 695 type-param signatures from generic functions and classes
    - TODO: Rename `T@Spam` to `_T__Spam` (use `visit_Annotation`)
    - TODO: Covariance and contravariance
    - TODO: bounds
    - TODO: constraints
    - TODO: Backport PEP-646 variadic generic (`python>=3.11`) with `Unpack[]`
    - TODO: Backport PEP-696 type parameter defaults (`python>=3.13`) with `default=`
    """

    METADATA_DEPENDENCIES = (ParentNodeProvider,)

    stack: collections.deque[str]

    is_pyi: Final[bool]
    type_params: Final[Mapping[tuple[str, ...], list[tuple[cst.TypeParam, ScopeKind]]]]
    cur_imports_typing: Final[frozenset[str]]
    cur_imports_typing_extensions: Final[frozenset[str]]
    req_imports_typing: Final[frozenset[str]]
    req_imports_typing_extensions: Final[frozenset[str]]

    def __init__(
        self,
        /,
        *,
        is_pyi: bool,
        type_params: dict[tuple[str, ...], list[tuple[cst.TypeParam, ScopeKind]]],
        cur_imports_typing: set[str],
        cur_imports_typing_extensions: set[str],
        req_imports_typing: set[str],
        req_imports_typing_extensions: set[str],
    ) -> None:
        self.stack = collections.deque()

        self.is_pyi = is_pyi
        self.type_params = type_params
        self.cur_imports_typing = frozenset(cur_imports_typing)
        self.cur_imports_typing_extensions = frozenset(cur_imports_typing_extensions)
        self.req_imports_typing = frozenset(req_imports_typing)
        self.req_imports_typing_extensions = frozenset(req_imports_typing_extensions)

        super().__init__()

    @property
    def has_imports_typing(self) -> bool:
        return bool(self.cur_imports_typing)

    @property
    def has_imports_typing_extensions(self) -> bool:
        return bool(self.cur_imports_typing)

    @property
    def old_imports_typing(self) -> frozenset[str]:
        """The `typing` imports that should be imported from `typing_extensions`."""
        return self.req_imports_typing_extensions & self.cur_imports_typing

    @property
    def new_imports_typing(self) -> frozenset[str]:
        """The currently missing `typing` imports that should be added."""
        return (
            self.req_imports_typing
            - self.cur_imports_typing
            - self.req_imports_typing_extensions
        )

    @property
    def new_imports_typing_extensions(self) -> frozenset[str]:
        """The currently missing `typing_extensions` imports that should be added."""
        return self.req_imports_typing_extensions - self.cur_imports_typing_extensions

    @override
    def leave_SimpleStatementLine(
        self,
        /,
        original_node: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> cst.SimpleStatementLine | cst.FlattenSentinel[cst.SimpleStatementLine]:
        if not any(isinstance(child, cst.TypeAlias) for child in updated_node.body):
            return updated_node

        assert len(updated_node.body) == 1
        type_alias_original = cast(cst.TypeAlias, updated_node.body[0])
        name = type_alias_original.name

        # type_params = updated_node.type_parameters
        type_params = self.type_params[name.value,]

        if type_params and len(type_params) > 1:
            # TODO: only do this if the order differs between the LHS and RHS.
            type_alias_updated = cst.Assign(
                [cst.AssignTarget(name)],
                cst.Call(
                    cst.Name("TypeAliasType"),
                    [cst.Arg(str_expr(name.value)), cst.Arg(type_alias_original.value)],
                ),
            )
        else:
            type_alias_updated = cst.AnnAssign(
                target=name,
                annotation=cst.Annotation(cst.Name("TypeAlias")),
                value=type_alias_original.value,
            )

        typevars = [
            backport_type_param(param, infer_variance=scope == ScopeKind.CLASS)
            for param, scope in type_params
        ]
        if not typevars:
            return cst.SimpleStatementLine(
                [type_alias_updated],
                leading_lines=updated_node.leading_lines,
                trailing_whitespace=updated_node.trailing_whitespace,
            )

        statements = [*typevars, type_alias_updated]

        lines: list[cst.SimpleStatementLine] = []
        for i, statement in enumerate(statements):
            if i == 0:
                line = cst.SimpleStatementLine(
                    [statement],
                    leading_lines=updated_node.leading_lines,
                )
            elif i == len(statements) - 1:
                line = cst.SimpleStatementLine(
                    [statement],
                    trailing_whitespace=updated_node.trailing_whitespace,
                )
            else:
                line = cst.SimpleStatementLine([statement])

            lines.append(line)

        return cst.FlattenSentinel(lines)

    # TODO: imports
    # TODO: classes
    # TODO: functions
    # TODO inner classes / inner functions
