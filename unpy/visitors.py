import collections
from typing import Final, override

import libcst as cst
import libcst.metadata as cst_meta

import unpy._cst as uncst
from unpy.exceptions import StubError

__all__ = ("StubVisitor",)

_MODULE_BUILTINS: Final = "builtins"
_MODULE_TP: Final = "typing"
_MODULE_TPX: Final = "typing_extensions"


def _check_annotation_expr(
    node: cst.BaseExpression,
    /,
    name: str | None = None,
) -> None:
    if isinstance(node, cst.BaseString):
        error = StubError("quoted annotations should not be included in stubs")
        if name:
            error.add_note(f"in {name!r}")
        raise error


class StubVisitor(cst.CSTVisitor):  # noqa: PLR0904
    """
    Collect all PEP-695 type-parameters & required imports in the module's functions,
    classes, and type-aliases.
    """

    METADATA_DEPENDENCIES = (cst_meta.ScopeProvider,)

    _global_scope: cst_meta.GlobalScope

    _stack_scope: Final[collections.deque[str]]
    _stack_attr: Final[collections.deque[cst.Attribute]]
    _in_import: bool

    # {import_fqn: alias, ...}
    imports: dict[str, str]
    # {alias: import_fqn, ...}
    imports_by_alias: dict[str, str]
    # {access_fqn: (import_fqn, attr_fqn), ...}
    imports_by_ref: dict[str, tuple[str, str | None]]
    # {import_fqn: alias, ...}
    _import_cache: dict[str, str | None]

    # {(generic_name, param_name): param, ...]
    type_params: dict[tuple[str, str], uncst.TypeParameter]
    # {generic_name: [param, ...], ...]
    type_params_grouped: dict[str, list[uncst.TypeParameter]]

    # {alias_name: [type_param, ...]}
    type_aliases: dict[str, list[uncst.TypeParameter]]

    # {class_qualname: [class_qualname, ...]}
    class_bases: dict[str, list[str]]

    nested_classvar_final: bool

    def __init__(self, /) -> None:
        self._stack_scope = collections.deque()
        self._stack_attr = collections.deque()
        self._in_import = False

        # TODO(jorenham): refactor this metadata
        # TODO(jorenham): support non-top-level imports with `collections.ChainMap`
        self.imports = {}
        self.imports_by_alias = {}
        self.imports_by_ref = {}
        self._import_cache = {}

        # TODO(jorenham): refactor type-param stuff as metadata
        self.type_params = {}
        self.type_params_grouped = collections.defaultdict(list)

        # TODO(jorenham): refactor this as metadata
        self.type_aliases = {}

        # TODO(jorenham): refactor this as metadata
        self.class_bases = {}

        self.nested_classvar_final = False

        super().__init__()

    @property
    def global_qualnames(self, /) -> frozenset[str]:
        # NOTE: This is only available after the `cst.Module` has been visited.
        # NOTE: This doesn't take redefined global names into account.
        return frozenset({
            assignment.name for assignment in self._global_scope.assignments
        })

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
        >>> visitor.imported_as(_MODULE_TPX, "Never")
        'tpx.Never'
        >>> visitor.imported_as("types", "NoneType")
        'NoneType'
        >>> visitor.imported_as(_MODULE_TP, "Protocol")
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
        if module == _MODULE_BUILTINS or (
            # type-check only
            module in {_MODULE_TP, _MODULE_TPX}
            and name in {"reveal_type", "reveal_locals"}
        ):
            default = name
            if name not in self.global_names:
                # if shadowing is a possibility; don't return the builtin name directly,
                # and prioritize returning an explicit import alias, if any.
                return name

        _imports = {_MODULE_BUILTINS: "__builtins__"} | imports

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

        return self.imported_as(_MODULE_TP, name) or self.imported_as(_MODULE_TPX, name)

    def _register_import(
        self,
        name: str,
        /,
        module: str | None = None,
        alias: str | None = None,
    ) -> str:
        # this `str.removesuffix` avoids a double `.` in case of `from . import name`
        fqn = f"{module.removesuffix(".")}.{name}" if module else name

        if fqn.startswith("__future__"):
            raise StubError("__future__ imports are useless in stubs")

        alias = alias or name

        if self.imports.setdefault(fqn, alias) != alias:
            raise NotImplementedError(f"{fqn!r} cannot be import as another name")

        if name != "*":
            self.imports_by_alias[alias] = fqn

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

    def _register_import_access(self, fqn: str, /) -> str | None:
        if fqn in (import_access := self.imports_by_ref):
            return import_access[fqn][0]
        if fqn in (import_alias := self.imports_by_alias):
            return import_alias[fqn]

        module, name = fqn, ""
        while "." in module:
            module, submodule = module.rsplit(".", 1)
            name = f"{submodule}.{name}" if name else submodule
            if fqn_import := import_alias.get(module):
                import_access[fqn] = fqn_import, name
                return fqn_import

        return None

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

        if default:
            _check_annotation_expr(default)

        name_any = self.imported_from_typing_as("Any")
        name_object = self.imported_as(_MODULE_BUILTINS, "object")
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
        else:
            _check_annotation_expr(bound)

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
    ) -> list[uncst.TypeParameter]:
        type_params, type_params_grouped = self.type_params, self.type_params_grouped
        registered: list[uncst.TypeParameter] = []
        for p in params.params:
            type_param = self._build_type_param(p, infer_variance=infer_variance)
            type_params[generic_name, type_param.name] = type_param
            type_params_grouped[generic_name].append(type_param)
            registered.append(type_param)
        return registered

    def __before_import(self, /) -> None:
        if self._stack_scope:
            raise NotImplementedError("only top-level import statements are supported")

        assert not self._in_import
        self._in_import = True

    def __after_import(self, /) -> None:
        assert self._in_import
        self._in_import = False

    def __check_assign_imported(self, node: cst.Assign | cst.AnnAssign, /) -> None:
        if not isinstance(node.value, cst.Name | cst.Attribute):
            return
        if (name := uncst.get_name_strict(node.value)) not in self.imports_by_alias:
            return

        # TODO(jorenham): support multiple import aliases
        # TODO(jorenham): support creating an import alias by assignment
        fqn = self.imports_by_alias[name]
        raise NotImplementedError(f"multiple import aliases for {fqn!r}")

    @override
    def on_visit(self, /, node: cst.CSTNode) -> bool:
        if isinstance(node, cst.BaseSmallStatement):
            if isinstance(
                node,
                cst.Del
                | cst.Pass
                | cst.Break
                | cst.Continue
                | cst.Return
                | cst.Raise
                | cst.Assert
                | cst.Global
                | cst.Nonlocal,
            ):
                keyword = type(node).__name__.lower()
                raise StubError(f"{keyword!r} statements are useless in stubs")
        elif isinstance(node, cst.BaseCompoundStatement):
            if isinstance(
                node,
                cst.Try | cst.TryStar | cst.With | cst.For | cst.While | cst.Match,
            ):
                keyword = type(node).__name__.lower()
                raise StubError(f"{keyword!r} statements are useless in stubs")
        elif isinstance(node, cst.BaseExpression):
            if isinstance(node, cst.BooleanOperation):
                raise StubError("boolean operations are useless in stubs")
            if isinstance(node, cst.FormattedString):
                raise StubError("f-strings are useless in stubs")
            if isinstance(node, cst.Lambda | cst.Await | cst.Yield):
                keyword = type(node).__name__.lower()
                raise StubError(f"{keyword!r} is an invalid expression")

        return super().on_visit(node)

    @override
    def visit_Module(self, /, node: cst.Module) -> None:
        node.validate_types_deep()

        scope = self.get_metadata(cst_meta.ScopeProvider, node)
        assert isinstance(scope, cst_meta.Scope)
        self._global_scope = scope.globals

    @override
    def visit_Import(self, /, node: cst.Import) -> None:
        self.__before_import()

        for alias in node.names:
            fqn = self._register_import_alias(alias)

            # NOTE: `import a.b.c` (without `as`) also does `import a.b` and `import a`
            if not alias.asname:
                while "." in fqn:
                    fqn = self._register_import(fqn.rsplit(".", 1)[0])

    @override
    def leave_Import(self, /, original_node: cst.Import) -> None:
        self.__after_import()

    @override
    def visit_ImportFrom(self, /, node: cst.ImportFrom) -> None:
        self.__before_import()

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
    def leave_ImportFrom(self, /, original_node: cst.ImportFrom) -> None:
        self.__after_import()

    @override
    def visit_Name(self, /, node: cst.Name) -> None:
        if self._in_import or self._stack_attr:
            return
        if (name := node.value) in (access := self.imports_by_ref):
            return
        if module := self.imports_by_alias.get(name):
            access[name] = module, None

    @override
    def visit_Attribute(self, /, node: cst.Attribute) -> None:
        if not self._stack_attr and isinstance(node.value, cst.Name | cst.Attribute):
            self._register_import_access(uncst.get_name_strict(node))

        self._stack_attr.append(node)

    @override
    def leave_Attribute(self, /, original_node: cst.Attribute) -> None:
        node = self._stack_attr.pop()
        assert node is original_node

    @override
    def visit_Annotation(self, /, node: cst.Annotation) -> None:
        _check_annotation_expr(node.annotation)

    @override
    def visit_Assign(self, node: cst.Assign) -> None:
        self.__check_assign_imported(node)

        # TODO(jorenham): enforce len(node.targets) == 1

        if (
            len(node.targets) == 1
            and isinstance(target := node.targets[0].target, cst.Name)
            and isinstance(node.value, cst.Call)
            # typevar-likes can only "contain" annotations if they have >1 [kw]args
            and len(node.value.args) > 1
            and isinstance(node.value.func, cst.Name | cst.Attribute)
            and isinstance(strname := node.value.args[0].value, cst.SimpleString)
            and strname.raw_value == target.value
        ):
            # this is (probably) a legacy typevar-like (or a manual `TypeAliasType`)
            # TODO(jorenham): either warn user & register, or just disallow this

            fname = ""  # set later if needed
            for arg in node.value.args[1:]:
                # annotations can only occur in the positional args and the
                # `bound` or `default` kwargs
                if arg.keyword is None or arg.keyword.value in {"bound", "default"}:
                    fname = fname or uncst.get_name_strict(node.value.func)
                    _check_annotation_expr(arg.value, f"{target.value} = {fname}(...)")

    @override
    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        self.__check_assign_imported(node)

        ann = node.annotation.annotation

        if (
            node.value
            and isinstance(node.target, cst.Name)
            and isinstance(ann, cst.Name | cst.Attribute)
            and (type_alias_name := self.imported_from_typing_as("TypeAlias"))
            and uncst.get_name_strict(ann) == type_alias_name
        ):
            # this is a legacy `typing[_extensions].TypeAlias`
            # TODO(jorenham): either warn user & register, or just disallow this
            _check_annotation_expr(node.value, f"{node.target.value}")

        # check for nested `ClassVar` and `Final`
        if (
            not self.nested_classvar_final
            and isinstance(ann, cst.Subscript)
            and isinstance(ann.value, cst.Name | cst.Attribute)
            and len(ann.slice) == 1
            and isinstance(index := ann.slice[0].slice, cst.Index)
            and isinstance(ann_sub := index.value, cst.Subscript)
            and isinstance(ann_sub.value, cst.Name | cst.Attribute)
            and len(ann_sub.slice) == 1
            and isinstance(ann.slice[0].slice, cst.Index)
            and (name_classvar := self.imported_from_typing_as("ClassVar"))
            and (name_final := self.imported_from_typing_as("Final"))
        ):
            # this is something of the form `_: _[_[_]] = ...`
            name_outer = uncst.get_name_strict(ann.value)
            name_inner = uncst.get_name_strict(ann_sub.value)
            names_typing = {name_classvar, name_final}
            if (
                name_outer != name_inner
                and name_outer in names_typing
                and name_inner in names_typing
            ):
                self.nested_classvar_final = True

    @override
    def visit_AssignTarget(self, node: cst.AssignTarget) -> None:
        assert not self._stack_attr

        # detect import shadowing
        if (
            isinstance(node.target, cst.Name)
            and (name := node.target.value) in self.imports_by_alias
        ):
            # TODO(jorenham): either allow this, or improve the reported error
            raise NotImplementedError(f"imported name {name!r} cannot be assigned to")

    @override
    def visit_TypeAlias(self, /, node: cst.TypeAlias) -> None:
        if self._stack_scope:
            raise NotImplementedError("only top-level type aliases are supported")

        name = node.name.value
        assert name not in self.type_aliases

        _check_annotation_expr(node.value, f"type {name}")

        if tpars := node.type_parameters:
            self.type_aliases[name] = self._register_type_params(name, tpars)
        else:
            self.type_aliases[name] = []

        # TODO(jorenham): report redundant type params
        # https://github.com/jorenham/unpy/issues/46

    @override
    def visit_FunctionDef(self, /, node: cst.FunctionDef) -> None:
        stack = self._stack_scope
        stack.append(name := node.name.value)

        if len(stack) == 1 and name in {"__getattr__", "__dir__"}:
            raise StubError(f"module-level {name}() cannot be used in a stub")

        assert isinstance(node.body, cst.SimpleStatementSuite | cst.IndentedBlock)
        if len(node.body.body) != 1 or not isinstance(node.body.body[0], cst.Ellipsis):
            error = StubError("function body must contain only `...`")
            qualname = ".".join(stack)
            error.add_note(qualname)

        if tpars := node.type_parameters:
            self._register_type_params(stack[0], tpars)

    @override
    def leave_FunctionDef(self, /, original_node: cst.FunctionDef) -> None:
        # TODO(jorenham): detect redundant type params
        # https://github.com/jorenham/unpy/issues/46

        _ = self._stack_scope.pop()

    @override
    def visit_ClassDef(self, /, node: cst.ClassDef) -> None:
        name = node.name.value

        stack = self._stack_scope
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
            cast_name = self.imported_as(_MODULE_TP, "cast")
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

        if tpars := node.type_parameters:
            self._register_type_params(stack[0], tpars, infer_variance=True)

    @override
    def leave_ClassDef(self, /, original_node: cst.ClassDef) -> None:
        # TODO(jorenham): detect redundant type params
        # https://github.com/jorenham/unpy/issues/46

        _ = self._stack_scope.pop()
