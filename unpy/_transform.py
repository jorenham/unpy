import collections
import functools
from typing import (
    TYPE_CHECKING,
    Final,
    Literal,
    LiteralString,
    Self,
    assert_never,
    override,
)

import libcst as cst
import libcst.matchers as m
from libcst.metadata import Scope, ScopeProvider

from ._cst import (
    get_name,
    get_name_strict,
    node_hash,
    parse_assign,
    parse_bool,
    parse_call,
    parse_name,
    parse_str,
    parse_subscript,
    parse_tuple,
)
from ._types import AnyFunction, PythonVersion

if TYPE_CHECKING:
    from collections.abc import Generator

type _Node_01[N: cst.CSTNode] = N | cst.RemovalSentinel
type _Node_1N[N: cst.CSTNode, NN: cst.CSTNode] = N | cst.FlattenSentinel[N | NN]

type _BuiltinModule = Literal[
    "collections.abc",
    "inspect",
    "types",
    "typing",
    "typing_extensions",
    "warnings",
]


_MODULES_TYPING: Final[tuple[_BuiltinModule, ...]] = "typing", "typing_extensions"
_ILLEGAL_BASES: Final = (
    ("pathlib", "Path"),
    ("typing", "Any"),
    ("typing_extensions", "Any"),
)
_ILLEGAL_NAMES: Final = "inspect.BufferFlags"
_TYPEVAR_SUFFIXES_CONTRAVARIANT: Final = "_contra", "_in"
_TYPEVAR_SUFFIXES_COVARIANT: Final = "_co", "_out"
_TYPEVAR_SUFFIXES: Final = _TYPEVAR_SUFFIXES_CONTRAVARIANT + _TYPEVAR_SUFFIXES_COVARIANT


def _backport_type_alias(node: cst.SimpleStatementLine) -> cst.SimpleStatementLine:
    assert len(node.body) == 1
    alias_original = cst.ensure_type(node.body[0], cst.TypeAlias)
    name = alias_original.name

    type_parameters = alias_original.type_parameters
    tpars = type_parameters.params if type_parameters else ()

    alias_updated: cst.Assign | cst.AnnAssign
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


def _backport_tpar(tpar: cst.TypeParam, /, *, variant: bool = False) -> cst.Assign:  # noqa: C901
    param = tpar.param
    name = param.name.value

    args: list[cst.BaseExpression] = [parse_str(name)]
    kwargs: dict[str, cst.BaseExpression] = {}

    # otherwise mypy thinks it's undefined later on
    bound: cst.BaseExpression | None = None

    # TODO: replace with `if` statements
    match param:
        case cst.TypeVar(_, bound):
            if variant:
                variance = "infer_variance"
                # TODO: use regexes
                if name.endswith(_TYPEVAR_SUFFIXES_CONTRAVARIANT):
                    variance = "contravariant"
                elif name.endswith(_TYPEVAR_SUFFIXES_COVARIANT):
                    variance = "covariant"
                kwargs[variance] = parse_bool(True)

            # TODO: replace with `if` statements
            match bound:
                # TODO: resolve `builtins.object` and `typing[_extensions].Any`
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

        case _ as wtf:  # pyright: ignore[reportUnnecessaryComparison]
            assert_never(wtf)

    # TODO: replace with `if` statements
    match default := tpar.default:
        case None:
            pass
        # TODO: use the resolved `typing[_extensions].Any` name
        case cst.Name("Any"):
            default = bound or cst.Name("object")
        case cst.BaseExpression():
            pass

    if default:
        kwargs["default"] = default

    # TODO: deal with existing `import {tname} as {tname_alias}`
    tname = type(param).__name__
    return parse_assign(name, parse_call(tname, *args, **kwargs))


def _remove_tpars[N: (cst.ClassDef, cst.FunctionDef)](node: N, /) -> N:
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


def _workaround_libcst_runtime_typecheck_bug[F: AnyFunction](f: F, /) -> F:
    # LibCST crashes if `cst.SimpleStatementLine` is included in the return type
    # annotation.
    # This workaround circumvents this by hiding the return type annation at runtime.
    del f.__annotations__["return"]  # type: ignore[no-any-expr]
    return f


class TypingCollector(cst.CSTVisitor):
    """
    Collect all PEP-695 type-parameters & required imports in the module's functions,
    classes, and type-aliases.
    """

    METADATA_DEPENDENCIES = (ScopeProvider,)

    _scope: Scope
    _stack: Final[collections.deque[str]]

    # {module.name: alias}
    imports: dict[str, str]
    imports_del: set[str]
    imports_add: set[str]
    _import_cache: dict[str, str | None]

    visited_tvars: dict[str, int]  # {typevar_name: typevar_hash}
    missing_tvars: dict[str, list[cst.Assign]]  # {root_node_name: [cst.Assign]}

    def __init__(self, /) -> None:
        self._stack = collections.deque()

        # TODO: support non-top-level imports with `collections.ChainMap`
        # TODO: try to refactor this import stuff as a one of those metadata providers
        self.imports = {}
        self.imports_del = set()
        self.imports_add = set()
        self._import_cache = {}

        # TODO: try to refactor this typevar stuff as a one of those metadata providers
        self.visited_tvars = {}
        self.missing_tvars = collections.defaultdict(list)

        super().__init__()

    @functools.cached_property
    def global_names(self, /) -> set[str]:
        # NOTE: This is only available after the `cst.Module` has been visited.
        # NOTE: This doesn't take redefined global names into account.
        return {assignment.name for assignment in self._scope.assignments}

    def imported_as(self, module: str, name: str, /) -> str | None:
        """
        Find the alias or attribute path used to access `{module}.{name}`, or return
        `None` if not imported.

        For example, consider the following `.pyi` code:

        ```python
        import collections as c
        import collections.abc
        import typing_extensions as tpx
        from types import *
        from typing import Protocol
        ```

        Then we'd get the following results

        ```pycon
        >>> import libcst as cst
        >>> source = "\n".join([
        ...     "import collections as col",
        ...     "import typing_extensions as tpx",
        ...     "from types import *",
        ...     "from typing import Protocol",
        ... ])
        >>> wrapper = cst.MetadataWrapper(cst.parse_module(source))
        >>> wrapper.visit(c := TypingCollector())
        >>> c.resolve_import_name("collections.abc", "Set")
        'col.abc.Set'
        >>> c.resolve_import_name("typing_extensions", "Never")
        'tpx.Never'
        >>> c.resolve_import_name("typing", "Union")
        'Union'
        ```

        Note that in the case of `collections.abc`, it assumed that `abc` is explicitly
        exported by `collections`.

        Todo:
            - Take the stdlib exports into account (e.g. by including typeshed)
            - Consider other packages and modules within this project
            - Support site-packages (those with a `py.typed`, at least)
            - Prevent shadowing, e.g. with `import builtins; class bool: ...`, prefer
            `builtins.bool` instead of `bool`
        """

        assert module
        # NOTE: this also prevent relative imports, which is fine for now
        assert all(map(str.isidentifier, module.split("."))), module
        # NOTE: this also requires non-empty `name`
        assert name.isidentifier(), name

        fqn = f"{module}.{name}"
        if fqn in (cache := self._import_cache):
            return cache[fqn]

        imports = self.imports
        if alias := imports.get(fqn) or imports.get(f"{module}.*"):
            cache[fqn] = alias = name if alias == "*" else alias
            return alias

        parts = fqn.split(".")
        assert len(parts) >= 1, fqn
        assert all(parts), fqn

        default: str | None = None
        if module == "builtins" or (
            # type-check only
            module in {"typing", "typing_extensions"}
            and name in {"reveal_type", "reveal_locals"}
        ):
            default = name
            if name not in self.global_names:
                # if shadowing is a possibility; don't return the builtin name directly,
                # and prioritize returning an explicit import alias, if any.
                return name

        # NOTE: This assumes that top-level modules export the submodule, e.g. having a
        # `import collections as cs` will cause `collections.abc.Buffer` to resolve
        # as `cs.abc.Buffer`.
        for i in range(len(parts) - 1, 0, -1):
            package = ".".join(parts[:i])
            if alias := imports.get(f"{package}.*") or imports.get(package):
                alias = ".".join(parts[i:] if alias == "*" else (alias, *parts[i:]))
                cache[fqn] = alias
                return alias

        return default

    def _register_import(
        self,
        name: str,
        /,
        module: str | None = None,
        alias: str | None = None,
    ) -> str:
        fqn = f"{module.removesuffix(".")}.{name}" if module else name
        alias = alias or name

        if self.imports.setdefault(fqn, alias) != alias:
            raise NotImplementedError(f"{fqn!r} cannot be import as another name")

        return fqn

    def _register_import_alias(
        self,
        node: cst.ImportAlias,
        /,
        module: str | None = None,
    ) -> str:
        return self._register_import(
            cst.ensure_type(node.name, cst.Name).value,
            alias=cst.ensure_type(node.asname, cst.Name).value if node.asname else None,
            module=module,
        )

    def _prevent_import(self, module: LiteralString, name: str, /) -> None:
        """
        Add the import to `imports_del` if needed, or remove from `imports_add` if
        previously desired.
        """
        fqn = f"{module}.{name}"

        # only consider "direct" imports, i.e. `from {module} import {name}`,
        # and ignore `from {module} import *` or `import {module}`
        if self.imported_as(module, name):
            self.imports_del.add(fqn)
            assert fqn not in self.imports_add, fqn

        self.imports_add.discard(fqn)

    def _desire_import(
        self,
        module: LiteralString,
        name: str,
        /,
        *,
        has_backport: bool = False,
    ) -> str:
        """Add the import to `imports_add` if needed."""
        assert name.isidentifier(), name
        fqn = f"{module}.{name}"

        # check if already imported or desired to be imported
        if alias := self.imported_as(module, name):
            assert fqn not in self.imports_add
            return alias
        if fqn in self.imports_add:
            return name

        if has_backport:
            # check if the typing_extensions backport is already desired or imported
            fqn_tpx = f"typing_extensions.{name}"
            assert fqn_tpx != fqn

            if fqn_tpx in self.imports_add:
                return name
            if alias_tpx := self.imported_as("typing_extensions", name):
                assert fqn_tpx not in self.imports_add
                return alias_tpx

        if name in self.global_names:
            # panic if the import will be shadowed
            # TODO: use an import alias in this case
            raise NotImplementedError(
                f"cannot import {name!r} from {module!r}: {name!r} is already defined",
            )

        self.imports_add.add(fqn)
        return name

    def _register_type_params(
        self,
        name: str,
        tpars: cst.TypeParameters,
        /,
        *,
        variant: bool = False,
    ) -> None:
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

            import_name = type(tpar.param).__name__
            if tpar.default or (variant and tname.endswith(_TYPEVAR_SUFFIXES)):
                self._desire_import("typing_extensions", import_name)
                self._prevent_import("typing", import_name)
            else:
                self._desire_import("typing", import_name, has_backport=True)

    def __check_import_scope(self, /) -> None:
        if self._stack:
            raise NotImplementedError("only top-level import statements are supported")

    @override
    def visit_Module(self, /, node: cst.Module) -> None:
        scope = self.get_metadata(ScopeProvider, node)
        assert isinstance(scope, Scope)
        self._scope = scope

    @override
    def visit_Import(self, /, node: cst.Import) -> None:
        self.__check_import_scope()

        for alias in node.names:
            self._register_import_alias(alias)

    @override
    def visit_ImportFrom(self, /, node: cst.ImportFrom) -> None:
        self.__check_import_scope()

        module = "." * len(node.relative)
        if node.module:
            name = get_name(node.module)
            assert name, node.module
            module += name

        if isinstance(node.names, cst.ImportStar):
            self._register_import(module, "*")
            raise NotImplementedError("wildcard imports are not supported")

        for alias in node.names:
            self._register_import_alias(alias, module=module)

    @override
    def visit_TypeAlias(self, /, node: cst.TypeAlias) -> None:
        if tpars := node.type_parameters:
            assert not self._stack

            name = node.name.value
            assert name not in self.missing_tvars

            self._register_type_params(name, tpars)

            # TODO: additionally require the LHS/RHS order to mismatch here
            if len(tpars.params) > 1:
                self._desire_import("typing_extensions", "TypeAliasType")
                return

        self._desire_import("typing", "TypeAlias")

    @override
    def visit_FunctionDef(self, /, node: cst.FunctionDef) -> None:
        self._stack.append(node.name.value)

        if tpars := node.type_parameters:
            self._register_type_params(self._stack[0], tpars)

    @override
    def leave_FunctionDef(self, /, original_node: cst.FunctionDef) -> None:
        _ = self._stack.pop()

    @functools.cached_property
    def _illegal_bases(self, /) -> frozenset[str]:
        return frozenset({
            base_name
            for module, name in _ILLEGAL_BASES
            if (base_name := self.imported_as(module, name))
        })

    @override
    def visit_ClassDef(self, /, node: cst.ClassDef) -> None:
        stack = self._stack
        stack.append(node.name.value)
        assert len(stack) > 1 or stack[0] not in self.missing_tvars

        bases = {
            base_name
            for arg in node.bases
            if not arg.keyword and not arg.star and (base_name := get_name(arg.value))
        }
        if bases and (illegal := bases & self._illegal_bases):
            if len(illegal) == 1:
                raise NotImplementedError(f"{illegal.pop()!r} as base class")
            raise ExceptionGroup(
                "unsupported base classes",
                [NotImplementedError(f"{base!r} as base class") for base in illegal],
            )

        if not (tpars := node.type_parameters):
            return

        if bases:
            if not (name_generic := self.imported_as("typing", "Generic")):
                name_generic = self.imported_as("typing_extensions", "Generic")

            if name_generic:
                if name_generic in bases:
                    raise TypeError(f"type parameters + {name_generic!r} base class")
            else:
                if not (name_protocol := self.imported_as("typing", "Protocol")):
                    name_protocol = self.imported_as("typing_extensions", "Protocol")

                if not (name_protocol and name_protocol in bases):
                    self._desire_import("typing", "Generic", has_backport=True)

        self._register_type_params(stack[0], tpars, variant=True)

    @override
    def leave_ClassDef(self, /, original_node: cst.ClassDef) -> None:
        _ = self._stack.pop()


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

            if isinstance(stmt, cst.ImportFrom):
                if stmt.relative or stmt.module is None:
                    return i
                if get_name_strict(stmt.module) > "typing":
                    # insert alphabetically, but before any relative imports
                    return i + 1

            i_insert = i + 1

        # if i - i_insert >= 5:
        #     # stop after encountering 5 non-import statements after the last import
        #     break
    return i_insert


class PY311Transformer(m.MatcherDecoratableTransformer):
    collector: Final[TypingCollector]
    _stack: Final[collections.deque[str]]

    @classmethod
    def from_collector(cls, collector: TypingCollector, /) -> Self:
        return cls(collector)

    def __init__(self, /, collector: TypingCollector) -> None:
        assert collector.imports_del <= set(collector.imports), collector.imports_del
        assert not collector.imports_add & set(collector.imports), collector.imports_add

        self.collector = collector
        self._stack = collections.deque()

        super().__init__()

    @property
    def missing_tvars(self, /) -> dict[str, list[cst.Assign]]:
        return self.collector.missing_tvars

    @override
    def leave_ImportFrom(
        self,
        /,
        original_node: cst.ImportFrom,
        updated_node: cst.ImportFrom,
    ) -> _Node_01[cst.ImportFrom]:
        """Add or remove imports from this `from {module} import {*names}` statement."""
        if updated_node.relative or isinstance(updated_node.names, cst.ImportStar):
            return updated_node
        assert updated_node.module

        col = self.collector
        fqn_del, fqn_add = col.imports_del, col.imports_add
        if not fqn_del and not fqn_add:
            return updated_node

        module = get_name_strict(updated_node.module)
        assert module
        assert all(map(str.isidentifier, module.split("."))), module

        prefix = f"{module}."
        i0 = len(prefix)
        names_del = {fqn[i0:]: fqn for fqn in fqn_del if fqn.startswith(prefix)}
        names_add = {fqn[i0:]: fqn for fqn in fqn_add if fqn.startswith(prefix)}

        if not (names_del or names_add):
            return updated_node

        assert all(map(str.isidentifier, names_del)), names_add
        assert all(map(str.isidentifier, names_add)), names_add

        aliases = updated_node.names

        aliases_new = [a for a in aliases if a.name.value not in names_del]
        aliases_new.extend(cst.ImportAlias(cst.Name(name)) for name in names_add)
        aliases_new.sort(key=lambda a: get_name_strict(a.name))

        if not aliases_new:
            return cst.RemoveFromParent()

        # remove trailing comma
        if isinstance(aliases_new[-1].comma, cst.Comma):
            aliases_new[-1] = aliases_new[-1].with_changes(comma=None)

        return updated_node.with_changes(names=aliases_new)

    def _prepend_tvars[
        N: (cst.ClassDef, cst.FunctionDef),
    ](self, /, node: N) -> _Node_1N[N, cst.SimpleStatementLine]:
        if not (tvars := self.missing_tvars.get(node.name.value, [])):
            return node

        leading_lines = node.leading_lines or [cst.EmptyLine()]
        lines: Generator[cst.SimpleStatementLine] = (
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
    ) -> _Node_1N[cst.SimpleStatementLine, cst.SimpleStatementLine]:
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
    ) -> _Node_1N[cst.ClassDef, cst.BaseStatement]:
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
        if not (imports_add := self.collector.imports_add):
            return updated_node

        # all modules that were seen in the `from {module} import ...` statements
        from_modules = {
            fqn.rsplit(".", 1)[0]
            for fqn, alias in self.collector.imports.items()
            if fqn != alias
        }

        # group the to-add imports statements per module like {module: [name, ...]}
        imports_from_add: dict[str, list[str]] = collections.defaultdict(list)
        for fqn in imports_add:
            module, name = fqn.rsplit(".", 1)
            if module not in from_modules:
                imports_from_add[module].append(name)

        if not imports_from_add:
            return updated_node

        new_statements = [
            cst.SimpleStatementLine([
                cst.ImportFrom(
                    parse_name(module),
                    [cst.ImportAlias(cst.Name(n)) for n in sorted(names)],
                ),
            ])
            for module, names in imports_from_add.items()
        ]

        if not new_statements:
            return updated_node

        i_insert = _new_typing_import_index(updated_node)
        updated_body = [
            *updated_node.body[:i_insert],
            *new_statements,
            *updated_node.body[i_insert:],
        ]
        return updated_node.with_changes(body=updated_body)


def transform_module(original: cst.Module, /) -> cst.Module:
    wrapper = cst.MetadataWrapper(original)

    collector = TypingCollector()
    _ = wrapper.visit(collector)

    transformer = PY311Transformer.from_collector(collector)
    return wrapper.visit(transformer)


def transform_source(
    source: str,
    /,
    *,
    target: PythonVersion = PythonVersion.PY311,
) -> str:
    if target != PythonVersion.PY311:
        raise NotADirectoryError(f"Python {target}")
    return transform_module(cst.parse_module(source)).code
