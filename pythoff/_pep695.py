import collections
import enum
from collections.abc import Callable, Sequence
from typing import ClassVar, Final, cast, override

import libcst as cst
import libcst.matchers as m

type _TypeParamDict = dict[tuple[str, ...], list[tuple[cst.TypeParam, _TypeParamScope]]]


class _TypeParamScope(enum.IntEnum):
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
        - move `python>=3.12` imports from `typing` to `typing_extensions`
        - `def {name}[...]: ...`
            - global functions
            - inner functions (closures)
            - instance/class/static methods
        - `class {name}[...]: ...`
        - detect `covariance` / `contravariance` (or use `infer_variance=True`)
            - implement `visit_Attribute` or `visit_AnnAssign` for attrs
            - inspect `FunctionDef.params.params.*annotation: *Annotation`
            - inspect `FunctionDef.returns: Annotation`
        - in case of `import typing` or `import typing_extensions`; use those later on.
        - detect existing typevar-likes
    """

    METADATA_DEPENDENCIES = ()

    _stack: collections.deque[str]

    is_pyi: Final[bool]
    # [(name, ...)] -> (type_params, infer_variance)
    type_params: _TypeParamDict
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

            self.type_params[key] = [
                (p, _TypeParamScope.TYPE) for p in type_params.params
            ]

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
        # TODO: extract old-style `Generic[T]` and `Protocol[T]` generic type params

        if not (type_params := node.type_parameters):
            self.type_params[key] = []
            return

        self.type_params[key] = [(p, _TypeParamScope.CLASS) for p in type_params.params]
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

        kind = _TypeParamScope.DEF

        if type_params := node.type_parameters:
            key = tuple(stack)

            if node.decorators and (
                "overload" in self.cur_imports_typing
                or "overload" in self.cur_imports_typing_extensions
            ):
                for decorator in node.decorators:
                    match decorator.decorator:
                        case cst.Name("overload"):
                            kind = _TypeParamScope.DEF_OVERLOAD
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
        return False if kind is _TypeParamScope.DEF_OVERLOAD or self.is_pyi else None

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


def backport_type_param(
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


def _workaround_libcst_runtime_typecheck_bug[F: Callable[..., object]](f: F, /) -> F:
    # LibCST crashes if `cst.SimpleStatementLine` is included in the return type
    # annotation.
    # This works around this bug by hiding the return type annation at runtime.
    del f.__annotations__["return"]
    return f


# class TypeAliasTransformer(cst.CSTTransformer):
class TypeAliasTransformer(m.MatcherDecoratableTransformer):
    type_params: Final[_TypeParamDict]

    def __init__(self, /, *, type_params: _TypeParamDict) -> None:
        self.type_params = type_params
        super().__init__()

    @m.call_if_inside(m.Module([m.ZeroOrMore(m.SimpleStatementLine())]))
    @m.leave(m.SimpleStatementLine([m.TypeAlias()]))
    @_workaround_libcst_runtime_typecheck_bug
    def desugar_type_alias(
        self,
        /,
        _: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> cst.SimpleStatementLine | cst.FlattenSentinel[cst.SimpleStatementLine]:
        assert len(updated_node.body) == 1
        type_alias_original = cast(cst.TypeAlias, updated_node.body[0])
        name = type_alias_original.name

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
            backport_type_param(param, infer_variance=scope == _TypeParamScope.CLASS)
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


class TypingImportTransformer(m.MatcherDecoratableTransformer):
    """
    TODO:
        - B
    """

    _TYPING_MODULES: ClassVar = m.Name("typing") | m.Name("typing_extensions")

    _cur_typing: Final[frozenset[str]]
    _cur_typing_extensions: Final[frozenset[str]]
    _req_typing: Final[frozenset[str]]
    _req_typing_extensions: Final[frozenset[str]]

    def __init__(
        self,
        /,
        cur_imports_typing: set[str],
        cur_imports_typing_extensions: set[str],
        req_imports_typing: set[str],
        req_imports_typing_extensions: set[str],
    ) -> None:
        self._cur_typing = frozenset(cur_imports_typing)
        self._cur_typing_extensions = frozenset(cur_imports_typing_extensions)
        self._req_typing = frozenset(req_imports_typing)
        self._req_typing_extensions = frozenset(req_imports_typing_extensions)

        super().__init__()

    @property
    def _del_typing(self) -> frozenset[str]:
        """
        The current `typing` imports that should be imported from `typing_extensions`
        instead.
        """
        return self._cur_typing & self._req_typing_extensions

    @property
    def _add_typing(self) -> frozenset[str]:
        """The `typing` imports that are missing."""
        return self._req_typing - self._cur_typing - self._req_typing_extensions

    @property
    def _add_typing_extensions(self) -> frozenset[str]:
        """The `typing_extensions` imports that are missing."""
        return self._req_typing_extensions - self._cur_typing_extensions

    @m.call_if_inside(m.SimpleStatementLine([m.OneOf(m.ImportFrom(_TYPING_MODULES))]))
    @m.leave(m.ImportFrom(_TYPING_MODULES))
    def update_typing_import(
        self,
        /,
        _: cst.ImportFrom,
        updated_node: cst.ImportFrom,
    ) -> cst.ImportFrom:
        module = cst.ensure_type(updated_node.module, cst.Name).value

        aliases = cast(Sequence[cst.ImportAlias], updated_node.names)

        names_del: frozenset[str]
        if module == "typing":
            names_del = self._del_typing
            names_add = self._add_typing
        else:
            assert module == "typing_extensions"
            names_del = frozenset()
            names_add = self._add_typing_extensions

        if not names_del and not names_add:
            return updated_node

        aliases_new = [a for a in aliases if a.name.value not in names_del]
        aliases_new.extend(cst.ImportAlias(cst.Name(name)) for name in names_add)
        aliases_new.sort(key=lambda a: cast(str, a.name.value))

        return updated_node.with_changes(names=aliases_new)

    @override
    def leave_Module(
        self,
        /,
        original_node: cst.Module,
        updated_node: cst.Module,
    ) -> cst.Module:
        new_statements: list[cst.SimpleStatementLine] = []

        if not self._cur_typing and self._req_typing:
            new_statements.append(
                cst.SimpleStatementLine([
                    cst.ImportFrom(
                        cst.Name("typing"),
                        [cst.ImportAlias(cst.Name(n)) for n in self._add_typing],
                    ),
                ]),
            )

        if not self._cur_typing_extensions and self._add_typing_extensions:
            new_statements.append(
                cst.SimpleStatementLine([
                    cst.ImportFrom(
                        cst.Name("typing_extensions"),
                        [
                            cst.ImportAlias(cst.Name(n))
                            for n in self._add_typing_extensions
                        ],
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
                else:
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
