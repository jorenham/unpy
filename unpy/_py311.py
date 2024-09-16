import collections
from collections.abc import Callable, Iterable
from typing import ClassVar, Final, Literal, LiteralString, Self, cast, override

import libcst as cst
import libcst.matchers as m
from libcst.metadata import BaseAssignment, Scope, ScopeProvider

type _BuiltinModule = Literal[
    "collections.abc",
    "inspect",
    "types",
    "typing",
    "typing_extensions",
    "warnings",
]
type _AnyDef = cst.ClassDef | cst.FunctionDef
type _NodeFlat[N: cst.CSTNode, FN: cst.CSTNode] = N | cst.FlattenSentinel[FN]
type _NodeOptional[N: cst.CSTNode] = N | cst.RemovalSentinel

__all__ = "PY311Collector", "PY311Transformer"

_PY313_TYPING_NAMES: Final = frozenset({"NoDefault", "ReadOnly", "TypeIs"})
_PY312_TYPING_NAMES: Final = frozenset({"TypeAliasType", "override"})


def bool_expr(value: bool, /) -> cst.Name:
    return cst.Name("True" if value else "False")


def str_expr(value: str, /) -> cst.SimpleString:
    return cst.SimpleString(f'"{value}"')


def kwarg_expr(key: str, value: cst.BaseExpression, /) -> cst.Arg:
    return cst.Arg(
        keyword=cst.Name(key),
        value=value,
        equal=cst.AssignEqual(cst.SimpleWhitespace(""), cst.SimpleWhitespace("")),
    )


def _backport_type_alias(
    node: cst.SimpleStatementLine,
) -> _NodeFlat[cst.SimpleStatementLine, cst.SimpleStatementLine]:
    assert len(node.body) == 1
    type_alias_original = cast(cst.TypeAlias, node.body[0])
    name = type_alias_original.name

    type_parameters = type_alias_original.type_parameters
    tpars = type_parameters.params if type_parameters else ()

    if len(tpars) > 1:
        # TODO: only do this if the order differs between the LHS and RHS.
        type_alias_updated = cst.Assign(
            [cst.AssignTarget(name)],
            cst.Call(
                cst.Name("TypeAliasType"),
                [
                    cst.Arg(str_expr(name.value)),
                    cst.Arg(type_alias_original.value),
                    kwarg_expr(
                        "type_params",
                        cst.Tuple([cst.Element(tpar.param.name) for tpar in tpars]),
                    ),
                ],
            ),
        )
    else:
        type_alias_updated = cst.AnnAssign(
            target=name,
            annotation=cst.Annotation(cst.Name("TypeAlias")),
            value=type_alias_original.value,
        )

    if not tpars:
        return cst.SimpleStatementLine(
            [type_alias_updated],
            leading_lines=node.leading_lines,
            trailing_whitespace=node.trailing_whitespace,
        )

    statements = [
        *(_backport_tpar(param) for param in tpars),
        type_alias_updated,
    ]

    lines: list[cst.SimpleStatementLine] = []
    for i, statement in enumerate(statements):
        line = cst.SimpleStatementLine([statement])
        if i == 0:
            line = line.with_changes(leading_lines=node.leading_lines)
        elif i == len(statements) - 1:
            line = line.with_changes(
                trailing_whitespace=node.trailing_whitespace,
            )
        lines.append(line)

    return cst.FlattenSentinel(lines)


def _backport_tpar(tpar: cst.TypeParam, /, *, variant: bool = False) -> cst.Assign:
    param = tpar.param
    name = param.name.value

    args = [cst.Arg(str_expr(name))]

    match param:
        case cst.TypeVar(_, bound):
            if variant:
                if name.endswith(("_contra", "_in")):
                    variance = "contravariant"
                elif name.endswith(("_co", "_out")):
                    variance = "covariant"
                else:
                    variance = "infer_variance"
            else:
                variance = None
            if variance:
                args.append(kwarg_expr(variance, bool_expr(True)))

            match bound:
                case (
                    None
                    | cst.Name("object")
                    | cst.Name("Any")
                    | cst.Attribute(cst.Name("typing"), cst.Name("Any"))
                ):
                    bound = None
                case cst.Tuple(elements):
                    for el in elements:
                        con = cst.ensure_type(el, cst.Element).value
                        if isinstance(con, cst.Name) and con.value == "Any":
                            # `Any` is literally Hitler
                            con = cst.Name("object")
                        args.append(cst.Arg(con))
                    bound = None
                case cst.BaseExpression():
                    pass

            if bound:
                args.append(kwarg_expr("bound", bound))

        case cst.TypeVarTuple(_) | cst.ParamSpec(_):
            bound = cst.Name("object")

    match default := tpar.default:
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


def _remove_tpars[N: _AnyDef](node: N, /) -> N:
    if node.type_parameters:
        return node.with_changes(type_parameters=None)
    return node


def _get_typing_baseclass(
    node: cst.ClassDef,
    base_name: LiteralString,
    /,
) -> cst.Name | cst.Attribute | None:
    base_expr_matches: list[cst.Name | cst.Attribute] = []
    for base_arg in node.bases:
        if base_arg.keyword or base_arg.star:
            break

        match base_expr := base_arg.value:
            case cst.Name(_name) if _name == base_name:
                return base_expr
            case cst.Attribute(
                cst.Name("typing" | "typing_extensions"),
                cst.Name(_name),
            ) if _name == base_name:
                base_expr_matches.append(base_expr)
            case cst.Subscript(
                cst.Name(_name)
                | cst.Attribute(
                    cst.Name("typing" | "typing_extensions"),
                    cst.Name(_name),
                ),
            ) if _name == base_name:
                raise NotImplementedError(f"{base_name!r} base class with type params")
            case _:
                pass

    match base_expr_matches:
        case []:
            return None
        case [base_expr]:
            return base_expr
        case _:
            # TODO: resolve by considering all available `typing` imports and aliases
            raise NotImplementedError(
                f"multiple {base_name!r} base classes found in {node.name.value}",
            )


def _workaround_libcst_runtime_typecheck_bug[F: Callable[..., object]](f: F, /) -> F:
    # LibCST crashes if `cst.SimpleStatementLine` is included in the return type
    # annotation.
    # This workaround circumvents this by hiding the return type annation at runtime.
    del f.__annotations__["return"]
    return f


def _as_name(name: cst.Name | cst.Attribute) -> str:
    match name:
        case cst.Name(value):
            return value
        case cst.Attribute(cst.Name(root), cst.Name(stem)):
            return f"{root}.{stem}"
        case cst.Attribute(cst.Attribute() as base, cst.Name(stem)):
            return f"{_as_name(base)}.{stem}"
        case _:
            raise NotImplementedError(f"unhandled name type: {name!r}")


class PY311Collector(cst.CSTVisitor):
    """
    Collect all PEP-695 type-parameters & required imports in the module's functions,
    classes, and type-aliases.
    """

    METADATA_DEPENDENCIES = (
        # ParentNodeProvider,
        # ExpressionContextProvider,
        ScopeProvider,
    )

    _scope: Scope
    _stack: Final[collections.deque[str]]

    current_imports: dict[_BuiltinModule, str]
    current_imports_from: dict[_BuiltinModule, dict[str, str]]
    missing_imports_from: dict[_BuiltinModule, set[str]]
    missing_tvars: dict[str, list[cst.Assign]]

    def __init__(self, /) -> None:
        self._stack = collections.deque()

        self.current_imports = {}
        self.current_imports_from = collections.defaultdict(dict)
        self.missing_imports_from = collections.defaultdict(set)
        self.missing_tvars = collections.defaultdict(list)

        super().__init__()

    @property
    def _globals(self, /) -> Iterable[tuple[str, BaseAssignment]]:
        for a in self._scope.assignments:
            yield a.name, a

    @override
    def visit_Module(self, node: cst.Module) -> None:
        self._scope = cst.ensure_type(self.get_metadata(ScopeProvider, node), Scope)

    @override
    def visit_Import(self, /, node: cst.Import) -> None:
        for alias in node.names:
            match alias.name:
                case cst.Name("inspect" | "warnings" as name):
                    self.current_imports[name] = alias.evaluated_alias or name
                case cst.Name("typing" | "typing_extensions" as name):
                    self.current_imports[name] = alias.evaluated_alias or name
                    raise NotImplementedError(f"import {name}")
                case cst.Attribute(cst.Name("collections"), cst.Name("abc")):
                    name = "collections.abc"
                    self.current_imports[name] = alias.evaluated_alias or name
                    raise NotImplementedError(f"import {name}")
                case _:
                    pass

    @override
    def visit_ImportFrom(self, /, node: cst.ImportFrom) -> None:
        if node.relative:
            return

        if isinstance(node.names, cst.ImportStar):
            raise NotImplementedError("from _ import *")

        # TODO: clean this up
        match node.module:
            case cst.Name("typing_extensions" as module):
                pass
            case cst.Name("typing" as module):
                for alias in node.names:
                    # PEP {742, 705, 698, 695}
                    name = cst.ensure_type(alias.name, cst.Name).value
                    if name in (_PY313_TYPING_NAMES | _PY312_TYPING_NAMES):
                        if alias.asname:
                            raise NotImplementedError(f"from typing import {name} as _")
                        self.missing_imports_from["typing_extensions"].add(name)
                        self.missing_imports_from["typing"].discard(name)
                        break
            case cst.Name("types" as module):
                for alias in node.names:
                    name = cst.ensure_type(alias.name, cst.Name).value
                    if name == "CapsuleType":
                        if alias.asname:
                            raise NotImplementedError(f"from types import {name} as _")
                        self.missing_imports_from["typing_extensions"].add(name)
                        break
            case cst.Name("warnings" as module):
                for alias in node.names:
                    # PEP 702
                    if alias.name.value == "deprecated":
                        if alias.asname:
                            raise NotImplementedError(
                                "from warnings import deprecated as _",
                            )
                        self.missing_imports_from["typing_extensions"].add("deprecated")
                        break
            case cst.Attribute(cst.Name("collections"), cst.Name("abc")):
                module = "collections.abc"
                for alias in node.names:
                    # PEP 688
                    if alias.name.value == "Buffer":
                        if alias.asname:
                            raise NotImplementedError("from typing import Buffer as _")
                        self.missing_imports_from["typing_extensions"].add("Buffer")
                        break
            case cst.Name("collections") if (
                any(alias.name.value == "abc" for alias in node.names)
            ):
                raise NotImplementedError("from collections import abc")
            case cst.Name("inspect") if (
                any(alias.name.value == "BufferFlags" for alias in node.names)
            ):
                # `inspect.BufferFlags` (PEP 688) has no backport in `typing_extensions`
                raise NotImplementedError("from inspect import BufferFlags")
            case _:
                return

        if isinstance(node.names, cst.ImportStar):
            raise NotImplementedError(f"from {module} import *")

        self.current_imports_from[module] |= {
            (aname := alias.evaluated_name): alias.evaluated_alias or aname
            for alias in node.names
        }

    @override
    def visit_Attribute(self, /, node: cst.Attribute) -> None:
        if (
            (warnings_alias := self.current_imports.get("warnings"))
            and m.matches(node.value, m.Name(warnings_alias))
            and m.matches(node.attr, m.Name("deprecated"))
        ):
            # PEP 702
            raise NotImplementedError("'warnings.deprecated' must be used directly")
        if (
            (inspect_alias := self.current_imports.get("inspect"))
            and m.matches(node.value, m.Name(inspect_alias))
            and m.matches(node.attr, m.Name("BufferFlags"))
        ):
            # `inspect.BufferFlags` (PEP 688) has no backport in `typing_extensions`
            raise NotImplementedError("inspect.BufferFlags")

    @override
    def visit_TypeAlias(self, /, node: cst.TypeAlias) -> None:
        import_from, import_name = "typing", "TypeAlias"
        if tpars := node.type_parameters:
            assert not self._stack

            name = node.name.value
            assert name not in self.missing_tvars

            self.missing_tvars[name].extend(
                map(_backport_tpar, tpars.params),
            )

            missing_imports = self.missing_imports_from
            for tpar in tpars.params:
                tname = type(tpar.param).__name__
                if tpar.default:
                    missing_imports["typing_extensions"].add(tname)
                    missing_imports["typing"].discard(tname)
                elif tname not in missing_imports["typing_extensions"]:
                    missing_imports["typing"].add(tname)

            if len(tpars.params) > 1:
                # TODO: check the RHS order
                import_from, import_name = "typing_extensions", "TypeAliasType"

        self.missing_imports_from[import_from].add(import_name)

    @override
    def visit_ClassDef(self, /, node: cst.ClassDef) -> bool | None:
        stack = self._stack
        stack.append(node.name.value)

        if not (tpars := node.type_parameters):
            return

        if _get_typing_baseclass(node, "Generic"):
            raise TypeError("can't use type params with a `Generic` base class")

        if not _get_typing_baseclass(node, "Protocol"):
            # this will require an additional `typing.Generic` base class
            self.missing_imports_from["typing"].add("Generic")

        assert len(stack) > 1 or stack[0] not in self.missing_tvars
        self.missing_tvars[stack[0]].extend(
            _backport_tpar(tpar, variant=True) for tpar in tpars.params
        )

        # infer_variance requires typing_extensions
        imports = self.missing_imports_from
        for tpar in tpars.params:
            name = tpar.param.name.value
            tname = type(tpar.param).__name__

            if tname in imports["typing_extensions"]:
                continue
            if tpar.default or not name.endswith(("_contra", "_in", "_co", "_out")):
                imports["typing_extensions"].add(tname)
                imports["typing"].discard(tname)
            else:
                imports["typing"].add(tname)

    @override
    def leave_ClassDef(self, /, original_node: cst.ClassDef) -> None:
        name = self._stack.pop()
        assert name == original_node.name.value

    @override
    def visit_FunctionDef(self, /, node: cst.FunctionDef) -> bool | None:
        stack = self._stack
        stack.append(node.name.value)

        if not (tpars := node.type_parameters):
            return

        self.missing_tvars[stack[0]].extend(map(_backport_tpar, tpars.params))

        imports = self.missing_imports_from
        for tpar in tpars.params:
            module = "typing_extensions" if tpar.default else "typing"
            imports[module].add(type(tpar.param).__name__)

    @override
    def leave_FunctionDef(self, /, original_node: cst.FunctionDef) -> None:
        name = self._stack.pop()
        assert name == original_node.name.value


class PY311Transformer(m.MatcherDecoratableTransformer):
    _MATCH_TYPING_IMPORT: ClassVar = m.ImportFrom(
        m.Name("typing") | m.Name("typing_extensions"),
    )

    _stack: collections.deque[str]

    current_imports: dict[_BuiltinModule, str]
    current_imports_from: dict[_BuiltinModule, dict[str, str]]
    missing_imports_from: dict[_BuiltinModule, set[str]]
    missing_tvars: dict[str, list[cst.Assign]]

    def __init__(
        self,
        /,
        *,
        current_imports: dict[_BuiltinModule, str],
        current_imports_from: dict[_BuiltinModule, dict[str, str]],
        missing_imports_from: dict[_BuiltinModule, set[str]],
        missing_tvars: dict[str, list[cst.Assign]],
    ) -> None:
        self._stack = collections.deque()
        self.current_imports = current_imports
        self.current_imports_from = current_imports_from
        self.missing_tvars = missing_tvars
        self.missing_imports_from = missing_imports_from
        super().__init__()

    def _del_imports_from(self, module: _BuiltinModule, /) -> set[str]:
        if module == "typing_extensions":
            return set()

        missing_tpx = self.missing_imports_from["typing_extensions"]
        return {
            name
            for name, as_ in self.current_imports_from[module].items()
            if name == as_ and name in missing_tpx
        }

    def _add_imports_from(self, module: _BuiltinModule, /) -> set[str]:
        return self.missing_imports_from[module] - set(
            self.current_imports_from[module],
        )

    @m.call_if_inside(m.Module([m.ZeroOrMore(m.SimpleStatementLine())]))
    @m.leave(m.SimpleStatementLine([m.TypeAlias()]))
    @_workaround_libcst_runtime_typecheck_bug
    def desugar_type_alias(  # noqa: PLR6301
        self,
        /,
        _: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> _NodeFlat[cst.SimpleStatementLine, cst.SimpleStatementLine]:
        return _backport_type_alias(updated_node)

    def _prepend_tvars[N: _AnyDef](self, /, node: N) -> _NodeFlat[N, cst.BaseStatement]:
        if not (tvars := self.missing_tvars.get(node.name.value, [])):
            return node

        lines = (
            cst.SimpleStatementLine([tvar], node.leading_lines if i == 0 else ())
            for i, tvar in enumerate(tvars)
        )
        return cst.FlattenSentinel([*lines, node])

    @override
    def visit_ClassDef(self, /, node: cst.ClassDef) -> None:
        self._stack.append(node.name.value)

    @override
    def leave_ClassDef(
        self,
        /,
        original_node: cst.ClassDef,
        updated_node: cst.ClassDef,
    ) -> _NodeFlat[cst.ClassDef, cst.BaseStatement]:
        name = self._stack.pop()
        assert name == updated_node.name.value

        if not (tpars := original_node.type_parameters):
            return updated_node

        subscripts = [
            cst.SubscriptElement(cst.Index(type_param.param.name))
            for type_param in tpars.params
        ]

        if base_protocol := _get_typing_baseclass(original_node, "Protocol"):
            new_bases = [
                cst.Arg(cst.Subscript(base_protocol, subscripts))
                if base_arg.value is base_protocol
                else base_arg
                for base_arg in original_node.bases
            ]
        else:
            new_bases = [
                *updated_node.bases,
                cst.Arg(cst.Subscript(cst.Name("Generic"), subscripts)),
            ]

        updated_node = updated_node.with_changes(type_parameters=None, bases=new_bases)

        return self._prepend_tvars(updated_node) if not self._stack else updated_node

    @override
    def visit_FunctionDef(self, /, node: cst.FunctionDef) -> None:
        self._stack.append(node.name.value)

    @override
    def leave_FunctionDef(
        self,
        /,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> cst.FunctionDef | cst.FlattenSentinel[cst.BaseStatement]:
        name = self._stack.pop()
        assert name == updated_node.name.value

        updated_node = _remove_tpars(updated_node)

        if self._stack:
            return updated_node

        return self._prepend_tvars(updated_node)

    @override
    def leave_ImportFrom(
        self,
        /,
        original_node: cst.ImportFrom,
        updated_node: cst.ImportFrom,
    ) -> _NodeOptional[cst.ImportFrom]:
        if updated_node.relative or not updated_node.module:
            return updated_node

        module = cast(_BuiltinModule, _as_name(updated_node.module))

        names_del = self._del_imports_from(module)
        names_add = self._add_imports_from(module)

        if not (names_del or names_add):
            return updated_node

        aliases = updated_node.names
        assert not isinstance(aliases, cst.ImportStar)

        aliases_new = [a for a in aliases if a.name.value not in names_del]
        aliases_new.extend(cst.ImportAlias(cst.Name(name)) for name in names_add)
        aliases_new.sort(key=lambda a: cst.ensure_type(a.name, cst.Name).value)

        if not aliases_new:
            return cst.RemoveFromParent()

        # remove trailing comma
        if isinstance(aliases_new[-1].comma, cst.Comma):
            aliases_new[-1] = aliases_new[-1].with_changes(comma=None)

        return updated_node.with_changes(names=aliases_new)

    @override
    def leave_Module(
        self,
        /,
        original_node: cst.Module,
        updated_node: cst.Module,
    ) -> cst.Module:
        return self._update_imports(updated_node)

    def _update_imports(self, /, module_node: cst.Module) -> cst.Module:
        new_statements = [
            cst.SimpleStatementLine([
                cst.ImportFrom(
                    cst.Name(tp_module),
                    [cst.ImportAlias(cst.Name(n)) for n in sorted(add_imports_from)],
                ),
            ])
            for tp_module in ("typing", "typing_extensions")
            if not self.current_imports_from[tp_module]
            and (add_imports_from := self._add_imports_from(tp_module))
        ]

        if not new_statements:
            return module_node

        i_insert = self._new_import_statement_index(module_node)

        # NOTE: newlines and other formatting won't be done here; use e.g. ruff instead
        return module_node.with_changes(
            body=[
                *module_node.body[:i_insert],
                *new_statements,
                *module_node.body[i_insert:],
            ],
        )

    @staticmethod
    def _new_import_statement_index(module_node: cst.Module) -> int:
        # find the first import statement in the module body
        i_insert = 0
        illegal_direct_imports = frozenset({"typing", "typing_extensions"})
        for i, statement in enumerate(module_node.body):
            if not isinstance(statement, cst.SimpleStatementLine):
                continue

            for node in statement.body:
                if not isinstance(node, cst.Import | cst.ImportFrom):
                    continue

                _done = False
                if isinstance(node, cst.Import):
                    if any(a.name.value in illegal_direct_imports for a in node.names):
                        raise NotImplementedError("import typing[_extensions]")
                    # insert after all `import ...` statements
                    i_insert = i + 1
                    continue

                if node.relative:
                    # insert before the first relative import
                    return i

                match node.module:
                    case cst.Name("typing"):
                        # insert the (`typing_extensions`) import after `typing`
                        return i + 1
                    case cst.Name("typing_extensions"):
                        # insert the (`typing`) import before `typing_extensions`
                        return i
                    case cst.Name(name):
                        # otherwise, assume alphabetically sorted on module, and
                        # and insert to maintain the order
                        if name > "typing_extensions":
                            return i

                        i_insert = i + 1
                    case _:
                        continue
        return i_insert

    @classmethod
    def from_collector(cls, collector: PY311Collector, /) -> Self:
        return cls(
            current_imports=collector.current_imports,
            current_imports_from=collector.current_imports_from,
            missing_imports_from=collector.missing_imports_from,
            missing_tvars=collector.missing_tvars,
        )


def transform(original: cst.Module, /) -> cst.Module:
    wrapper = cst.MetadataWrapper(original)

    collector = PY311Collector()
    _ = wrapper.visit(collector)

    transformer = PY311Transformer.from_collector(collector)
    return wrapper.visit(transformer)
