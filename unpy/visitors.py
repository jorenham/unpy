import collections
import functools
from typing import Final, override

import libcst as cst
from libcst.metadata import Scope, ScopeProvider

import unpy._cst as uncst

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


class StubVisitor(cst.CSTVisitor):
    """
    Collect all PEP-695 type-parameters & required imports in the module's functions,
    classes, and type-aliases.
    """

    METADATA_DEPENDENCIES = (ScopeProvider,)

    _scope: Scope
    _stack: Final[collections.deque[str]]

    # {import_fqn: alias_fqn, ...}
    imports: dict[str, str]
    imports_del: set[str]
    imports_add: set[str]
    _import_cache: dict[str, str | None]

    # {(generic_name, param_name), param), ...]
    type_params: dict[tuple[str, str], uncst.TypeParameter]
    type_params_grouped: dict[str, list[uncst.TypeParameter]]

    # {alias_name: {param_name: access_index}}
    type_alias_access_order: dict[str, dict[str, int | None]]

    # {class_qualname: [class_qualname, ...]}
    class_bases: dict[str, list[str]]

    def __init__(self, /) -> None:
        self._stack = collections.deque()

        # TODO(jorenham): refactor this metadata
        # TODO(jorenham): support non-top-level imports with `collections.ChainMap`
        self.imports = {}
        self._import_cache = {}

        # TODO(jorenham): move these to the `StubTransformer`
        self.imports_del = set()
        self.imports_add = set()

        # TODO(jorenham): refactor type-param stuff as metadata
        self.type_params = {}
        self.type_params_grouped = collections.defaultdict(list)

        # TODO(jorenham): refactor this as metadata
        self.type_alias_access_order = {}

        # TODO(jorenham): refactor this as metadata
        self.class_bases = {}

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
            uncst.get_name_strict(node.name),
            module,
            uncst.get_name_strict(as_.name) if (as_ := node.asname) else None,
        )

    def _build_type_param(  # noqa: C901
        self,
        tpar: cst.TypeParam,
        /,
        *,
        infer_variance: bool = False,
    ) -> uncst.TypeParameter:
        param = tpar.param
        name = param.name.value
        default = tpar.default

        if isinstance(default, cst.BaseString):
            raise NotImplementedError("stringified type parameter defaults")

        name_any = self.imported_from_typing_as("Any")
        name_object = self.imported_as("builtins", "object")
        assert name_object

        if _default_any := (
            default
            and isinstance(default, cst.Name | cst.Attribute)
            and uncst.get_name_strict(default) == name_any
        ):
            # use `builtins.object` as the default `default=` default (not a typo)
            default = uncst.parse_name(name_object)

        if isinstance(param, cst.TypeVarTuple):
            return uncst.TypeVarTuple(
                name=name,
                default=default,
                default_star=bool(tpar.star),
            )

        if isinstance(param, cst.ParamSpec):
            return uncst.ParamSpec(name=name, default=default)

        assert isinstance(param, cst.TypeVar)

        constraints: tuple[cst.BaseExpression, ...] = ()
        if not (bound := param.bound):
            pass
        elif isinstance(bound, cst.BaseString):
            raise NotImplementedError("stringified type parameter bounds")
        elif (
            name_any
            and isinstance(bound, cst.Name | cst.Attribute)
            and uncst.get_name_strict(bound) in {name_object, name_any}
        ):
            bound = None
        elif isinstance(bound, cst.Tuple):
            cons: list[cst.BaseExpression] = []
            for el in bound.elements:
                if isinstance(el, cst.StarredElement):
                    raise NotImplementedError("starred type constraints")
                assert isinstance(el, cst.Element)

                con = el.value
                if isinstance(con, cst.BaseString):
                    raise NotImplementedError("stringified type constraints")

                if (
                    name_any
                    and isinstance(con, cst.Name | cst.Attribute)
                    and uncst.get_name_strict(con) == name_any
                ):
                    con = uncst.parse_name(name_object)
                cons.append(con)

            constraints = tuple(cons)
            bound = None

        if _default_any and bound is not None:
            # if `default=Any`, replace it the value of `bound` (`Any` is horrible)
            default = bound

        covariant = contravariant = False
        if infer_variance:
            # TODO(jorenham): actually infer the variance
            # https://github.com/jorenham/unpy/issues/44
            if name.endswith("_co"):
                covariant, infer_variance = True, False
            elif name.endswith("_contra"):
                contravariant, infer_variance = True, False

            if constraints:
                if infer_variance:
                    infer_variance = False
                else:
                    # TODO(jorenham): proper error reporting
                    # https://github.com/jorenham/unpy/issues/50
                    raise NotImplementedError("type constraints require invariance")

        return uncst.TypeVar(
            name=name,
            covariant=covariant,
            contravariant=contravariant,
            infer_variance=infer_variance,
            constraints=constraints,
            bound=bound,
            default=default,
        )

    def _register_type_params(
        self,
        generic_name: str,
        params: cst.TypeParameters,
        /,
        *,
        infer_variance: bool = False,
    ) -> tuple[str, ...]:
        type_params, type_params_grouped = self.type_params, self.type_params_grouped
        names: list[str] = []
        for p in params.params:
            type_param = self._build_type_param(p, infer_variance=infer_variance)
            type_params[generic_name, type_param.name] = type_param
            type_params_grouped[generic_name].append(type_param)
            names.append(type_param.name)
        return tuple(names)

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
            name = uncst.get_name(node.module)
            assert name, node.module
            module += name

        if isinstance(node.names, cst.ImportStar):
            self._register_import("*", module=module)
        else:
            for alias in node.names:
                self._register_import_alias(alias, module=module)

    @override
    def visit_TypeAlias(self, /, node: cst.TypeAlias) -> None:
        if self._stack:
            raise NotImplementedError("only top-level type aliases are supported")

        name = node.name.value
        assert name not in self.type_alias_access_order

        if tpars := node.type_parameters:
            tpar_names = self._register_type_params(name, tpars)
            access_order = uncst.get_access_order(node, tpar_names)
            self.type_alias_access_order[name] = access_order

            # TODO(jorenham): report redundant type params (i.e. access order `None`)
            # https://github.com/jorenham/unpy/issues/46
        else:
            self.type_alias_access_order[name] = {}

    @override
    def visit_FunctionDef(self, /, node: cst.FunctionDef) -> None:
        self._stack.append(node.name.value)

        if tpars := node.type_parameters:
            self._register_type_params(self._stack[0], tpars)

    @override
    def leave_FunctionDef(self, /, original_node: cst.FunctionDef) -> None:
        # TODO(jorenham): detect redundant type params
        # https://github.com/jorenham/unpy/issues/46

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

        qualname = name if len(stack) == 1 else ".".join(stack)
        assert qualname not in self.class_bases

        bases: list[str]
        self.class_bases[qualname] = bases = []

        for arg in node.bases:
            # class kwargs aren't relevant (for now)
            if arg.keyword or arg.star == "**":
                continue
            if arg.star == "*":
                raise NotImplementedError(f"{qualname!r}: starred base classes")

            base = arg.value

            # unwrap `typing.cast` calls
            cast_name = self.imported_as("typing", "cast")
            while isinstance(base, cst.Call) and uncst.get_name(base.func) == cast_name:
                assert len(base.args) == 2
                base = base.args[1].value

            if not (basename := uncst.get_name(base)):
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
            self._register_type_params(stack[0], tpars, infer_variance=True)

    @override
    def leave_ClassDef(self, /, original_node: cst.ClassDef) -> None:
        # TODO(jorenham): detect redundant type params
        # https://github.com/jorenham/unpy/issues/46

        _ = self._stack.pop()
