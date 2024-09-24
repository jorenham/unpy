import collections
import functools
from typing import Final, assert_never, override

import libcst as cst
from libcst.metadata import Scope, ScopeProvider

from ._cst import (
    get_name,
    get_name_strict,
    node_hash,
    parse_assign,
    parse_bool,
    parse_call,
    parse_str,
)

__all__ = ("StubVisitor",)

_ILLEGAL_BASES: Final = (
    ("builtins", "BaseExceptionGroup"),
    ("builtins", "ExceptionGroup"),
    ("builtins", "_IncompleteInputError"),
    ("builtins", "PythonFinalizationError"),
    ("builtins", "EncodingWarning"),
    ("pathlib", "Path"),
    ("typing", "Any"),
    ("typing_extensions", "Any"),
)

_TYPEVAR_SUFFIXES_CONTRAVARIANT: Final = "_contra", "_in"
_TYPEVAR_SUFFIXES_COVARIANT: Final = "_co", "_out"
_TYPEVAR_SUFFIXES: Final = _TYPEVAR_SUFFIXES_CONTRAVARIANT + _TYPEVAR_SUFFIXES_COVARIANT


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


class StubVisitor(cst.CSTVisitor):
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

    # {typevar_name: typevar_hash}
    visited_tvars: dict[str, int]
    # {root_node_name: [cst.Assign]}
    missing_tvars: dict[str, list[cst.Assign]]

    # {fqn: [bases]}
    baseclasses: dict[str, list[str]]

    def __init__(self, /) -> None:
        self._stack = collections.deque()

        # TODO: refactor import stuff as metadata
        # TODO: support non-top-level imports with `collections.ChainMap`
        self.imports = {}
        self.imports_del = set()
        self.imports_add = set()
        self._import_cache = {}

        # TODO: refactor typevar stuff as metadata
        self.visited_tvars = {}
        self.missing_tvars = collections.defaultdict(list)

        # TODO: refactor baseclass stuff as metadata
        self.baseclasses = {}

        super().__init__()

    @property
    def global_qualnames(self, /) -> frozenset[str]:
        # NOTE: This is only available after the `cst.Module` has been visited.
        # NOTE: This doesn't take redefined global names into account.
        return frozenset({assignment.name for assignment in self._scope.assignments})

    @property
    def global_names(self, /) -> frozenset[str]:
        return frozenset({qn.split(".", 1)[0] for qn in self.global_qualnames})

    def imported_as(self, module: str, name: str, /) -> str | None:
        """
        Find the alias or attribute path used to access `{module}.{name}`, or return
        `None` if not imported.

        For example, consider the following `.pyi` code:

        ```python
        import collections as c
        import collections.abc
        import typing_extensions as tpx
        from types import NoneType
        from typing import *
        ```

        Then we'd get the following results

        ```pycon
        >>> import libcst as cst
        >>> source = "\\n".join([
        ...     "import collections as col",
        ...     "import typing_extensions as tpx",
        ...     "from types import *",
        ...     "from typing import Protocol",
        ... ]) + "\\n"
        >>> wrapper = cst.MetadataWrapper(cst.parse_module(source))
        >>> _ = wrapper.visit(visitor := StubVisitor())
        >>> visitor.imported_as("collections.abc", "Set")
        'col.abc.Set'
        >>> visitor.imported_as("typing_extensions", "Never")
        'tpx.Never'
        >>> visitor.imported_as("types", "NoneType")
        'NoneType'
        >>> visitor.imported_as("typing", "Protocol")
        'Protocol'

        ```

        Note that in the case of `collections.abc`, it assumed that `abc` is explicitly
        exported by `collections`.

        Todo:
            - Take the stdlib exports into account (e.g. by including typeshed)
            - Consider other packages and modules within this project
            - Support site-packages (those with a `py.typed`, at least)
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

        _imports = {"builtins": "__builtins__"} | imports

        # NOTE: This assumes that top-level modules export the submodule, e.g. having a
        # `import collections as cs` will cause `collections.abc.Buffer` to resolve
        # as `cs.abc.Buffer`.
        for i in range(len(parts) - 1, 0, -1):
            package = ".".join(parts[:i])
            if alias := _imports.get(f"{package}.*") or _imports.get(package):
                alias = ".".join(parts[i:] if alias == "*" else (alias, *parts[i:]))
                cache[fqn] = alias
                return alias

        return default

    def imported_from_typing_as(self, name: str, /) -> str | None:
        assert name.isidentifier(), name

        return (
            self.imported_as("typing", name)
            or self.imported_as("typing_extensions", name)
        )  # fmt: skip

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
            get_name_strict(node.name),
            module,
            get_name_strict(as_.name) if (as_ := node.asname) else None,
        )

    def prevent_import(self, module: str, name: str, /) -> None:
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

    def desire_import(
        self,
        module: str,
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
                self.desire_import("typing_extensions", import_name)
                self.prevent_import("typing", import_name)
            else:
                self.desire_import("typing", import_name, has_backport=True)

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
            fqn = self._register_import_alias(alias)

            # NOTE: `import a.b.c` (without `as`) also does `import a.b` and `import a`
            if not alias.asname:
                while "." in fqn:
                    fqn = self._register_import(fqn.rsplit(".", 1)[0])

    @override
    def visit_ImportFrom(self, /, node: cst.ImportFrom) -> None:
        self.__check_import_scope()

        module = "." * len(node.relative)
        if node.module:
            name = get_name(node.module)
            assert name, node.module
            module += name

        if isinstance(node.names, cst.ImportStar):
            self._register_import("*", module=module)
        else:
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
                self.desire_import("typing_extensions", "TypeAliasType")
                return

        self.desire_import("typing", "TypeAlias")

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
        name = node.name.value

        stack = self._stack
        stack.append(name)

        is_global = len(stack) == 1
        assert not (is_global and name in self.missing_tvars)

        qualname = name if is_global else ".".join(stack)
        assert qualname not in self.baseclasses

        bases: list[str]
        self.baseclasses[qualname] = bases = []

        for arg in node.bases:
            # class kwargs aren't relevant (for now)
            if arg.keyword or arg.star == "**":
                continue
            if arg.star == "*":
                raise NotImplementedError(f"{qualname!r}: starred base classes")

            base = arg.value

            # unwrap `typing.cast` calls
            while isinstance(base, cst.Call) and get_name(base.func) == "typing.cast":
                assert len(base.args) == 2
                base = base.args[1].value

            if not (basename := get_name(base)):
                _expr = type(base).__qualname__
                raise NotImplementedError(
                    f"{qualname!r}: unsupported class argument expression ({_expr})",
                )

            # TODO: figure out the FQN if not a global name (i.e. locally scoped)
            bases.append(basename)

        base_set = set(bases)
        if base_set and (illegal := base_set & self._illegal_bases):
            if len(illegal) == 1:
                raise NotImplementedError(f"{illegal.pop()!r} as base class")
            raise ExceptionGroup(
                "unsupported base classes",
                [NotImplementedError(f"{base!r} as base class") for base in illegal],
            )

        if tpars := node.type_parameters:
            if self.imported_from_typing_as("Protocol") not in base_set:
                self.desire_import("typing", "Generic", has_backport=True)

            self._register_type_params(stack[0], tpars, variant=True)

    @override
    def leave_ClassDef(self, /, original_node: cst.ClassDef) -> None:
        _ = self._stack.pop()
