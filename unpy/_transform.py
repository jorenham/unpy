import collections
import functools
from collections.abc import Callable
from typing import Final, Literal, LiteralString, Self, cast, override

import libcst as cst
import libcst.matchers as m
from libcst.helpers import get_full_name_for_node_or_raise
from libcst.metadata import Scope, ScopeProvider

from ._types import Target
from ._utils import (
    node_hash,
    parse_assign,
    parse_bool,
    parse_call,
    parse_str,
    parse_subscript,
    parse_tuple,
)

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


_PY313_TYPING_NAMES: Final = frozenset({"NoDefault", "ReadOnly", "TypeIs"})
_PY312_TYPING_NAMES: Final = frozenset({"TypeAliasType", "override"})


def _backport_type_alias(node: cst.SimpleStatementLine) -> cst.SimpleStatementLine:
    assert len(node.body) == 1
    alias_original = cst.ensure_type(node.body[0], cst.TypeAlias)
    name = alias_original.name

    type_parameters = alias_original.type_parameters
    tpars = type_parameters.params if type_parameters else ()

    if len(tpars) > 1:
        # TODO: only do this if the order differs between the LHS and RHS.
        alias_updated = parse_assign(
            name,
            parse_call(
                "TypeAliasType",
                parse_str(name.value),
                alias_original.value,
                type_params=parse_tuple(p.param.name for p in tpars),
            ),
        )
    else:
        alias_updated = cst.AnnAssign(
            name,
            cst.Annotation(cst.Name("TypeAlias")),
            alias_original.value,
        )

    # if not tpars:
    return cst.SimpleStatementLine(
        [alias_updated],
        leading_lines=node.leading_lines,
        trailing_whitespace=node.trailing_whitespace,
    )

    # statements = [
    #     *(_backport_tpar(param) for param in tpars),
    #     alias_updated,
    # ]

    # lines: list[cst.SimpleStatementLine] = []
    # for i, statement in enumerate(statements):
    #     line = cst.SimpleStatementLine([statement])
    #     if i == 0:
    #         line = line.with_changes(leading_lines=node.leading_lines)
    #     elif i == len(statements) - 1:
    #         line = line.with_changes(
    #             trailing_whitespace=node.trailing_whitespace,
    #         )
    #     lines.append(line)

    # return cst.FlattenSentinel(lines)


def _backport_tpar(tpar: cst.TypeParam, /, *, variant: bool = False) -> cst.Assign:  # noqa: C901
    param = tpar.param
    name = param.name.value

    args: list[cst.BaseExpression] = [parse_str(name)]
    kwargs: dict[str, cst.BaseExpression] = {}

    match param:
        case cst.TypeVar(_, bound):
            if variant:
                if name.endswith(("_contra", "_in")):
                    variance = "contravariant"
                elif name.endswith(("_co", "_out")):
                    variance = "covariant"
                else:
                    variance = "infer_variance"
                kwargs[variance] = parse_bool(True)

            match bound:
                case (
                    cst.Name("object" | "Any")
                    | cst.Attribute(cst.Name("typing"), cst.Name("Any"))
                ):
                    bound = None
                case cst.Tuple(elements):
                    for el in elements:
                        con = cst.ensure_type(el, cst.Element).value
                        if isinstance(con, cst.Name) and con.value == "Any":
                            con = cst.Name("object")
                        args.append(con)
                    bound = None
                case cst.BaseExpression() | None:
                    pass

            if bound:
                kwargs["bound"] = bound

        case cst.TypeVarTuple(_) | cst.ParamSpec(_):
            bound = cst.Name("object")

    match default := tpar.default:
        case None:
            pass
        case cst.Name("Any"):
            default = bound or cst.Name("object")
        case cst.BaseExpression():
            pass

    if default:
        kwargs["default"] = default

    # TODO: deal with existing `import {tname} as {tname_alias}`
    tname = type(param).__name__
    return parse_assign(name, parse_call(tname, *args, **kwargs))


def _remove_tpars[N: _AnyDef](node: N, /) -> N:
    if node.type_parameters:
        return node.with_changes(type_parameters=None)
    return node


def _get_typing_baseclass(
    node: cst.ClassDef,
    base_name: LiteralString,
    /,
    modules: set[str] | None = None,
) -> cst.Name | cst.Attribute | None:
    if modules is None:
        modules = {"typing", "typing_extensions"}

    base_expr_matches: list[cst.Name | cst.Attribute] = []
    for base_arg in node.bases:
        if base_arg.keyword or base_arg.star:
            break

        match base_expr := base_arg.value:
            case cst.Name(_name) if _name == base_name:
                return base_expr
            case cst.Attribute(cst.Name(_module), cst.Name(_name)) if (
                _name == base_name and _module in modules
            ):
                base_expr_matches.append(base_expr)
            case cst.Subscript(cst.Name(_name)) if _name == base_name:
                raise NotImplementedError(f"{base_name!r} base class with type params")
            case cst.Subscript(cst.Attribute(cst.Name(_module), cst.Name(_name))) if (
                _name == base_name and _module in modules
            ):
                base_qname = f"{_module}.{_name}"
                raise NotImplementedError(f"{base_qname!r} base class with type params")
            case _:
                # maybe raise here?
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


class TypingCollector(cst.CSTVisitor):
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

    missing_tvars: dict[str, list[cst.Assign]]  # {root_node_name: [cst.Assign]}
    visited_tvars: dict[str, int]  # {typevar_name: typevar_hash}

    def __init__(self, /) -> None:
        self._stack = collections.deque()

        self.current_imports = {}
        self.current_imports_from = collections.defaultdict(dict)
        self.missing_imports_from = collections.defaultdict(set)

        self.missing_tvars = collections.defaultdict(list)
        self.visited_tvars = {}

        super().__init__()

    @functools.cached_property
    def _global_names(self, /) -> set[str]:
        # NOTE: This is only available after the `cst.Module` has been visited.
        # NOTE: This doesn't take redefined global names into account.
        return {assignment.name for assignment in self._scope.assignments}

    def _current_import_alias(
        self,
        module: _BuiltinModule,
        name: str,
        /,
        *,
        typing_extensions: bool = True,
        allow_alias: bool = False,
    ) -> str | None:
        current_imports = self.current_imports_from

        alias = current_imports[module].get(name)
        if not alias and typing_extensions and module != "typing_extensions":
            alias = current_imports["typing_extensions"].get(name)

        if alias and not allow_alias and alias != name:
            raise NotImplementedError(f"importing {name} as a different name")

        if not alias and name in self._global_names:
            raise NotImplementedError(f"{name} is a global name and cannot be imported")

        return alias

    def _require_typing_import(
        self,
        module: _BuiltinModule,
        name: str,
        /,
        *,
        allow_alias: bool = False,
    ) -> str:
        imports = self.missing_imports_from
        if name in imports["typing_extensions"] or name in imports[module]:
            return name

        if module == "typing_extensions":
            # prevent double import
            imports["typing"].discard(name)
        elif alias := self._current_import_alias(module, name, allow_alias=allow_alias):
            return alias

        imports[module].add(name)
        return name

    def _register_type_params(
        self,
        name: str,
        tpars: cst.TypeParameters,
        /,
        *,
        variant: bool = False,
    ) -> None:
        variant_suffixes = "_contra", "_in", "_co", "_out"

        visited_tvars = self.visited_tvars
        missing_tvars = self.missing_tvars[name]
        for tpar in tpars.params:
            tname = tpar.param.name.value
            thash = node_hash(tpar)

            if tname in visited_tvars:
                if visited_tvars[tname] != thash:
                    raise NotImplementedError(f"Duplicate type param {tname!r}")
                continue

            visited_tvars[tname] = thash

            missing_tvars.append(_backport_tpar(tpar, variant=variant))

            if tpar.default or (variant and tname.endswith(variant_suffixes)):
                module = "typing_extensions"
            else:
                module = "typing"
            self._require_typing_import(module, type(tpar.param).__name__)

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
    def visit_ImportFrom(self, /, node: cst.ImportFrom) -> None:  # noqa: C901
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
                        self._require_typing_import("typing_extensions", name)
                        break
            case cst.Name("types" as module):
                for alias in node.names:
                    name = cst.ensure_type(alias.name, cst.Name).value
                    if name == "CapsuleType":
                        if alias.asname:
                            raise NotImplementedError(f"from types import {name} as _")
                        self._require_typing_import("typing_extensions", name)
                        break
            case cst.Name("warnings" as module):
                for alias in node.names:
                    # PEP 702
                    if alias.name.value == "deprecated":
                        if alias.asname:
                            raise NotImplementedError(
                                "from warnings import deprecated as _",
                            )
                        self._require_typing_import("typing_extensions", "deprecated")
                        break
            case cst.Attribute(cst.Name("collections"), cst.Name("abc")):
                module = "collections.abc"
                for alias in node.names:
                    # PEP 688
                    if alias.name.value == "Buffer":
                        if alias.asname:
                            raise NotImplementedError("from typing import Buffer as _")
                        self._require_typing_import("typing_extensions", "Buffer")
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

            self._register_type_params(name, tpars)

            # TODO: additionally require the LHS/RHS order to mismatch here
            if len(tpars.params) > 1:
                import_from, import_name = "typing_extensions", "TypeAliasType"

        self._require_typing_import(import_from, import_name)

    @override
    def visit_FunctionDef(self, /, node: cst.FunctionDef) -> bool | None:
        stack = self._stack
        stack.append(node.name.value)

        if tpars := node.type_parameters:
            self._register_type_params(stack[0], tpars)

    @override
    def leave_FunctionDef(self, /, original_node: cst.FunctionDef) -> None:
        name = self._stack.pop()
        assert name == original_node.name.value

    @override
    def visit_ClassDef(self, /, node: cst.ClassDef) -> bool | None:
        stack = self._stack
        stack.append(node.name.value)
        assert len(stack) > 1 or stack[0] not in self.missing_tvars

        if _get_typing_baseclass(node, "Path", modules={"pathlib"}):
            raise NotImplementedError("subclassing 'pathlib.Path` is not supported")

        if not (tpars := node.type_parameters):
            return

        if _get_typing_baseclass(node, "Generic"):
            raise TypeError("can't use type params with a `Generic` base class")

        if not _get_typing_baseclass(node, "Protocol"):
            # this will require an additional `typing.Generic` base class
            self._require_typing_import("typing", "Generic")

        self._register_type_params(stack[0], tpars, variant=True)

    @override
    def leave_ClassDef(self, /, original_node: cst.ClassDef) -> None:
        name = self._stack.pop()
        assert name == original_node.name.value


def _new_typing_import_index(module_node: cst.Module) -> int:
    """
    Get the index of the module body at which to insert a new
    `from typing[_extensions] import _` statement.

    This will look through the imports at the beginning of the module, it will insert:
    - *after* the last `from {module} import _` statement s.t. `module <= "typing"`
    - *before* the first `from {module} import _` s.t. `module > "typing"`
    - *before* the first function-, or class definition
    - *before* the first compound statement
    """
    i_insert = 0
    for i, statement in enumerate(module_node.body):
        if not isinstance(statement, cst.SimpleStatementLine):
            # NOTE: assume that all imports come before any compound statements
            # TODO: continue if we're in a .py file
            break

        for stmt in statement.body:
            if not isinstance(stmt, cst.Import | cst.ImportFrom):
                continue

            if isinstance(stmt, cst.ImportFrom) and (
                stmt.relative
                or stmt.module is None
                or get_full_name_for_node_or_raise(stmt.module.value) > "typing"
            ):
                # insert alphabetically, but before any relative imports
                return i

            i_insert = i + 1

        if i - i_insert >= 5:
            # stop after encountering 5 non-import statements after the last import
            break
    return i_insert


class PY311Transformer(m.MatcherDecoratableTransformer):
    _stack: collections.deque[str]

    current_imports: dict[_BuiltinModule, str]
    current_imports_from: dict[_BuiltinModule, dict[str, str]]
    missing_imports_from: dict[_BuiltinModule, set[str]]
    missing_tvars: dict[str, list[cst.Assign]]

    @classmethod
    def from_collector(cls, collector: TypingCollector, /) -> Self:
        return cls(
            current_imports=collector.current_imports,
            current_imports_from=collector.current_imports_from,
            missing_imports_from=collector.missing_imports_from,
            missing_tvars=collector.missing_tvars,
        )

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
        self.missing_imports_from = missing_imports_from
        self.missing_tvars = missing_tvars
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

    def _prepend_tvars[N: _AnyDef](
        self,
        /,
        node: N,
    ) -> _NodeFlat[N, N | cst.SimpleStatementLine]:
        if not (tvars := self.missing_tvars.get(node.name.value, [])):
            return node

        leading_lines = node.leading_lines or [cst.EmptyLine()]
        lines = (
            cst.SimpleStatementLine([tvar], () if i else leading_lines)
            for i, tvar in enumerate(tvars)
        )
        return cst.FlattenSentinel([*lines, node])

    @m.call_if_inside(m.Module([m.ZeroOrMore(m.SimpleStatementLine())]))
    @m.leave(m.SimpleStatementLine([m.TypeAlias()]))
    @_workaround_libcst_runtime_typecheck_bug
    def leave_type_alias_statement(
        self,
        /,
        original_node: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> _NodeFlat[cst.SimpleStatementLine, cst.SimpleStatementLine]:
        node = _backport_type_alias(updated_node)

        alias_original = cst.ensure_type(original_node.body[0], cst.TypeAlias)
        if not (tvars := self.missing_tvars.get(alias_original.name.value, [])):
            return node

        leading_lines = node.leading_lines or [cst.EmptyLine()]
        lines = (
            cst.SimpleStatementLine([tvar], () if i else leading_lines)
            for i, tvar in enumerate(tvars)
        )
        return cst.FlattenSentinel([*lines, node])

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
        self._stack.pop()

        updated_node = _remove_tpars(updated_node)
        return updated_node if self._stack else self._prepend_tvars(updated_node)

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
        stack = self._stack
        stack.pop()

        if not (tpars := original_node.type_parameters):
            return updated_node

        tpar_names = (tpar.param.name for tpar in tpars.params)
        if base_protocol := _get_typing_baseclass(original_node, "Protocol"):
            new_bases = [
                cst.Arg(parse_subscript(base_protocol, *tpar_names))
                if base_arg.value is base_protocol
                else base_arg
                for base_arg in original_node.bases
            ]
        else:
            new_bases = [
                *updated_node.bases,
                cst.Arg(parse_subscript("Generic", *tpar_names)),
            ]

        updated_node = updated_node.with_changes(type_parameters=None, bases=new_bases)
        return self._prepend_tvars(updated_node) if not stack else updated_node

    @override
    def leave_Module(
        self,
        /,
        original_node: cst.Module,
        updated_node: cst.Module,
    ) -> cst.Module:
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
            return updated_node

        i_insert = _new_typing_import_index(updated_node)
        return updated_node.with_changes(
            body=[
                *updated_node.body[:i_insert],
                *new_statements,
                *updated_node.body[i_insert:],
            ],
        )


def transform_module(original: cst.Module, /) -> cst.Module:
    wrapper = cst.MetadataWrapper(original)

    collector = TypingCollector()
    _ = wrapper.visit(collector)

    transformer = PY311Transformer.from_collector(collector)
    return wrapper.visit(transformer)


def transform_source(source: str, /, *, target: Target = Target.PY311) -> str:
    if target != Target.PY311:
        raise NotADirectoryError(f"Python {target.value}")  # pyright: ignore[reportUnreachable]
    return transform_module(cst.parse_module(source)).code