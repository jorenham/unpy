import collections
from collections.abc import Callable
from typing import ClassVar, Final, Literal, LiteralString, Self, cast, override

import libcst as cst
import libcst.matchers as m

type _TypingModule = Literal["typing", "typing_extensions"]
type _AnyDef = cst.ClassDef | cst.FunctionDef
type _NodeFlat[N: cst.CSTNode, FN: cst.CSTNode] = N | cst.FlattenSentinel[FN]

_TYPING_MODULES: Final = "typing", "typing_extensions"


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


def _backport_type_alias(
    node: cst.SimpleStatementLine,
) -> cst.SimpleStatementLine | cst.FlattenSentinel[cst.SimpleStatementLine]:
    assert len(node.body) == 1
    type_alias_original = cast(cst.TypeAlias, node.body[0])
    name = type_alias_original.name

    type_parameters = type_alias_original.type_parameters
    type_params = type_parameters.params if type_parameters else ()

    if len(type_params) > 1:
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

    if not type_params:
        return cst.SimpleStatementLine(
            [type_alias_updated],
            leading_lines=node.leading_lines,
            trailing_whitespace=node.trailing_whitespace,
        )

    statements = [
        *(_backport_tpar(param) for param in type_params),
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
    # This works around this bug by hiding the return type annation at runtime.
    del f.__annotations__["return"]
    return f


class PEP695Collector(cst.CSTVisitor):
    """
    Collect all PEP-695 type-parameters & required imports in the module's functions,
    classes, and type-aliases.
    """

    _stack: Final[collections.deque[str]]

    # {module}
    current_imports: set[_TypingModule]
    # {module: {name: alias}}
    current_imports_from: dict[_TypingModule, dict[str, str]]
    # {module: name}
    missing_imports_from: dict[_TypingModule, set[str]]

    # {outer_scope: [typevar-like, ...]}
    missing_tvars: dict[str, list[cst.Assign]]

    def __init__(self, /) -> None:
        self._stack = collections.deque()

        self.current_imports = set()
        self.current_imports_from = {m: {} for m in _TYPING_MODULES}
        self.missing_imports_from = {m: set() for m in _TYPING_MODULES}

        self.missing_tvars = collections.defaultdict(list)

        super().__init__()

    @override
    def visit_Import(self, /, node: cst.Import) -> bool | None:
        # `import typing as something_else` is not yet supported; so explicitly raise
        # if it's encountered
        for alias in node.names:
            match alias.name:
                case cst.Name("typing" | "typing_extensions" as name):
                    if alias.asname:
                        raise NotImplementedError(f"import {name} as _")
                    self.current_imports.add(name)
                case cst.Attribute(cst.Name("collections"), cst.Name("abc")):
                    raise NotImplementedError("import collections.abc")
                case _:
                    pass

    @override
    def visit_ImportFrom(self, /, node: cst.ImportFrom) -> None:
        if node.relative:
            return

        match node.module:
            case cst.Name("typing" | "typing_extensions" as module):
                pass
            case _:
                return

        if isinstance(node.names, cst.ImportStar):
            raise NotImplementedError(f"from {module} import *")

        imported = self.current_imports_from[module]
        for alias in node.names:
            name = cst.ensure_type(alias.name, cst.Name).value

            if alias.asname:
                as_ = cst.ensure_type(alias.asname, cst.Name).value
            else:
                as_ = name

            imported[name] = as_

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
                import_from = "typing_extensions" if tpar.default else "typing"
                missing_imports[import_from].add(type(tpar.param).__name__)

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
            module = (
                "typing_extensions"
                if tpar.default
                or (len(name) >= 4 and name.endswith(("_contra", "_in", "_co", "_out")))
                else "typing"
            )
            imports[module].add(type(tpar.param).__name__)

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


class TypeAliasTransformer(m.MatcherDecoratableTransformer):
    _stack: collections.deque[str]

    current_imports: frozenset[_TypingModule]
    current_imports_from: dict[_TypingModule, dict[str, str]]
    missing_tvars: dict[str, list[cst.Assign]]

    def __init__(
        self,
        /,
        *,
        current_imports: set[_TypingModule],
        current_imports_from: dict[_TypingModule, dict[str, str]],
        missing_tvars: dict[str, list[cst.Assign]],
    ) -> None:
        self._stack = collections.deque()
        self.current_imports = frozenset(current_imports)
        self.current_imports_from = current_imports_from
        self.missing_tvars = missing_tvars
        super().__init__()

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
        # TODO: subscript if `Protocol` is a base class, or add `Generic` as base
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

    @classmethod
    def from_collector(cls, collector: PEP695Collector, /) -> Self:
        return cls(
            current_imports=collector.current_imports,
            current_imports_from=collector.current_imports_from,
            missing_tvars=collector.missing_tvars,
        )


class TypingImportTransformer(m.MatcherDecoratableTransformer):
    _TYPING_MODULES: ClassVar = m.Name("typing") | m.Name("typing_extensions")

    current_imports: frozenset[_TypingModule]
    current_imports_from: dict[_TypingModule, dict[str, str]]
    missing_imports_from: dict[_TypingModule, set[str]]

    def __init__(
        self,
        /,
        *,
        current_imports: set[_TypingModule],
        current_imports_from: dict[_TypingModule, dict[str, str]],
        missing_imports_from: dict[_TypingModule, set[str]],
    ) -> None:
        self.current_imports = frozenset(current_imports)
        self.current_imports_from = current_imports_from
        self.missing_imports_from = missing_imports_from

        super().__init__()

    @property
    def _del_from_typing(self) -> set[str]:
        """
        The current `typing` imports that should be imported from `typing_extensions`
        instead.

        Todo:
            Remove aliases as well (requires renaming references).
        """
        missing_tpx = self.missing_imports_from["typing_extensions"]
        return {
            name
            for name, as_ in self.current_imports_from["typing"].items()
            if name == as_ and name in missing_tpx
        }

    @property
    def _add_from_typing(self) -> set[str]:
        """The `typing` imports that are missing."""
        # return self._req_typing - self._cur_typing - self._req_typing_extensions
        return (
            self.missing_imports_from["typing"]
            - set(self.current_imports_from["typing"])
            - self.missing_imports_from["typing_extensions"]
        )

    @property
    def _add_from_typing_extensions(self) -> set[str]:
        """The `typing_extensions` imports that are missing."""
        return self.missing_imports_from["typing_extensions"] - set(
            self.current_imports_from["typing_extensions"],
        )

    @m.call_if_inside(m.SimpleStatementLine([m.OneOf(m.ImportFrom(_TYPING_MODULES))]))
    @m.leave(m.ImportFrom(_TYPING_MODULES))
    def transform_typing_import(
        self,
        /,
        _: cst.ImportFrom,
        updated_node: cst.ImportFrom,
    ) -> cst.ImportFrom:
        module = cst.ensure_type(updated_node.module, cst.Name).value

        assert not isinstance(updated_node.names, cst.ImportStar)
        aliases = updated_node.names

        if module == "typing":
            names_del = self._del_from_typing
            names_add = self._add_from_typing
        else:
            assert module == "typing_extensions"
            names_del = set[str]()
            names_add = self._add_from_typing_extensions

        if not names_del and not names_add:
            return updated_node

        aliases_new = [a for a in aliases if a.name.value not in names_del]
        aliases_new.extend(cst.ImportAlias(cst.Name(name)) for name in names_add)
        aliases_new.sort(key=lambda a: cst.ensure_type(a.name, cst.Name).value)
        return updated_node.with_changes(names=aliases_new)

    @override
    def leave_Module(
        self,
        /,
        original_node: cst.Module,
        updated_node: cst.Module,
    ) -> cst.Module:
        new_statements: list[cst.SimpleStatementLine] = []

        if not self.current_imports_from["typing"] and self._add_from_typing:
            new_statements.append(
                cst.SimpleStatementLine([
                    cst.ImportFrom(
                        cst.Name("typing"),
                        [cst.ImportAlias(cst.Name(n)) for n in self._add_from_typing],
                    ),
                ]),
            )

        if not self.current_imports_from["typing_extensions"] and (
            add_tpx := self._add_from_typing_extensions
        ):
            new_statements.append(
                cst.SimpleStatementLine([
                    cst.ImportFrom(
                        cst.Name("typing_extensions"),
                        [cst.ImportAlias(cst.Name(n)) for n in add_tpx],
                    ),
                ]),
            )

        if not new_statements:
            return updated_node

        i_insert = self._new_import_statement_index(updated_node)

        # NOTE: newlines and other formatting won't be done here; use e.g. ruff instead
        return updated_node.with_changes(
            body=[
                *updated_node.body[:i_insert],
                *new_statements,
                *updated_node.body[i_insert:],
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
    def from_collector(cls, /, collector: PEP695Collector) -> Self:
        return cls(
            current_imports=collector.current_imports,
            current_imports_from=collector.current_imports_from,
            missing_imports_from=collector.missing_imports_from,
        )
