import collections
from typing import Final, override

import libcst as cst

import unpy._cst as uncst

from ._stdlib import NAMES_BACKPORT_TPX, NAMES_DEPRECATED_ALIASES
from ._types import PythonVersion
from .visitors import StubVisitor

__all__ = ("StubTransformer",)


_MODULE_TP: Final = "typing"
_MODULE_TPX: Final = "typing_extensions"

_NAME_GENERIC: Final = "Generic"
_NAME_PROTOCOL: Final = "Protocol"
_NAME_ALIAS: Final = "TypeAlias"
_NAME_ALIAS_PEP695: Final = "TypeAliasType"


def _new_typing_import_index(module_node: cst.Module) -> int:
    """
    Get the index of the module body at which to insert a new
    `from typing[_extensions] import _` statement.

    This will look through the imports at the beginning of the module, it will insert:
    - *after* the last `from {module} import _` statement s.t. `module <= _MODULE_TP`
    - *before* the first `from {module} import _` s.t. `module > _MODULE_TP`
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
                if uncst.get_name_strict(stmt.module) > _MODULE_TP:
                    # insert alphabetically, but before any relative imports
                    return i + 1

            i_insert = i + 1

        if i - i_insert >= 5:
            # stop after encountering 5 non-import statements after the last import
            break
    return i_insert


def _new_typevars_index(module_node: cst.Module) -> int:
    """
    Returns the index of either the
    - the statement after the last import
    - the first the first definition of a constant, typealias, function, or class.
    """
    i_insert = 0
    for i, statement in enumerate(module_node.body):
        if (
            isinstance(statement, cst.Import | cst.ImportFrom)
            or (
                # conditional imports
                isinstance(statement, cst.If)
                and isinstance(statement.body, cst.IndentedBlock)
                and isinstance(stmt0 := statement.body.body[0], cst.SimpleStatementLine)
                and isinstance(stmt0.body[0], cst.Import | cst.ImportFrom)
            )
            or (
                isinstance(statement, cst.Assign)
                and len(statement.targets) == 1
                and isinstance(name := statement.targets[0].target, cst.Name)
                and name.value == "__all__"
            )
        ):
            i_insert = i + 1
        else:
            break

    return i_insert


class StubTransformer(cst.CSTTransformer):
    visitor: Final[StubVisitor]
    target: Final[PythonVersion]

    # {(module, name), ...}
    _imports_del: Final[set[tuple[str, str]]]
    _imports_add: Final[set[tuple[str, str]]]

    # whether the type alias parameters are referenced in the order they are defined
    _type_alias_alignment: Final[dict[str, bool]]

    _stack: Final[collections.deque[str]]

    def __init__(self, visitor: StubVisitor, /, target: PythonVersion) -> None:
        self.visitor = visitor
        self.target = target

        self._imports_del = set()
        self._imports_add = set()
        self._type_alias_alignment = {}
        self._stack = collections.deque()

        self.__collect_imports_typevars()
        self.__collect_imports_backports()
        self.__collect_imports_generic()
        self.__collect_imports_type_aliases()

        super().__init__()

    def _require_import(
        self,
        module: str,
        name: str,
        /,
        *,
        has_backport: bool | None = None,
    ) -> str:
        """Get or add the import and return the full name or alias."""
        assert name.isidentifier(), name

        if has_backport is None:
            has_backport = (
                module == _MODULE_TP
                or module in NAMES_BACKPORT_TPX
                and name in NAMES_BACKPORT_TPX[module]
            )
        elif has_backport:
            assert module != _MODULE_TPX

        visitor = self.visitor

        if has_backport and module == _MODULE_TP:
            alias = visitor.imported_from_typing_as(name)
        else:
            alias = visitor.imported_as(module, name)
        if alias:
            return alias

        if (module, name) in (imports_add := self._imports_add):
            return name

        if has_backport:
            # check if the typing_extensions backport is already desired or imported
            if (_MODULE_TPX, name) in imports_add:
                return name
            if alias_tpx := visitor.imported_as(_MODULE_TPX, name):
                assert (_MODULE_TPX, name) not in imports_add
                return alias_tpx

        imports_add.add((module, name))
        return name

    def _discard_import(self, module: str, name: str, /) -> str | None:
        """Remove the import, or prevent it from being added."""
        if alias := self.visitor.imported_as(module, name):
            self._imports_del.add((module, name))
            assert (module, name) not in self._imports_add, (module, name)
            return alias

        if (module, name) in self._imports_add:
            self._imports_add.discard((module, name))
            return name

        return None

    def __collect_imports_typevars(self, /) -> None:
        # collect the missing imports for the typevar-likes
        target = self.target
        for type_param in self.visitor.type_params.values():
            for module, name in type_param.required_imports(target):
                self._require_import(module, name)
                if module == _MODULE_TPX:
                    self._discard_import(_MODULE_TP, name)

    def __collect_imports_backports(self, /) -> None:
        # collect the imports that should replaced with a `typing_extensions` backport
        visitor = self.visitor
        target = self.target

        for fqn in visitor.imports:
            if fqn[0] == "." or fqn[-1] == "*" or "." not in fqn:
                continue

            if fqn.startswith("__future__"):
                # TODO(jorenham): report that `__future__.annotations` is redundant
                # https://github.com/jorenham/unpy/issues/43
                raise NotImplementedError("__future__")

            module, name = fqn.rsplit(".", 1)

            # TODO(jorenham): report that `typing.TYPE_CHECKING` is redundant
            # https://github.com/jorenham/unpy/issues/45

            if (
                (reqs := NAMES_BACKPORT_TPX.get(module))
                and (req := reqs.get(name))
                and target < req
            ):
                self._discard_import(module, name)
                self._require_import(_MODULE_TPX, name, has_backport=False)
            elif (orig_fqns := NAMES_DEPRECATED_ALIASES.get(module)) and (
                orig_fqn := orig_fqns.get(name)
            ):
                self._discard_import(module, name)
                module_new, name_new = orig_fqn.rsplit(".", 1)

                if name_new != name:
                    # TODO: rename the references
                    continue

                self._require_import(module_new, name_new)

    def __collect_imports_type_aliases(self, /) -> None:
        # collect the imports for `TypeAlias` and/or `TypeAliasType`
        aligned = self._type_alias_alignment
        for name, access_order in self.visitor.type_aliases.items():
            # ixs = [ix for ix in access_order.values() if ix is not None]
            # aligned[name] = all(ix_lhs == ix_rhs for ix_lhs, ix_rhs in enumerate(ixs))
            aligned[name] = len(access_order) < 2

        total = sum(aligned.values())
        if total and self.target < (3, 12):
            self._require_import(_MODULE_TP, _NAME_ALIAS, has_backport=True)
        if len(aligned) - total:
            self._require_import(_MODULE_TPX, _NAME_ALIAS_PEP695, has_backport=False)

    def __collect_imports_generic(self, /) -> None:
        # add the `typing.Generic` if needed
        visitor = self.visitor
        if visitor.imported_from_typing_as(_NAME_GENERIC):
            return

        class_bases = visitor.class_bases
        class_type_params = visitor.type_params_grouped

        alias_protocol = visitor.imported_from_typing_as(_NAME_PROTOCOL)
        for name, bases in class_bases.items():
            if class_type_params.get(name) and alias_protocol not in bases:
                self._require_import(_MODULE_TP, _NAME_GENERIC, has_backport=True)
                break

    @override
    def leave_ImportFrom(
        self,
        /,
        original_node: cst.ImportFrom,
        updated_node: cst.ImportFrom,
    ) -> cst.ImportFrom | cst.RemovalSentinel:
        if updated_node.relative or isinstance(updated_node.names, cst.ImportStar):
            return updated_node
        assert updated_node.module

        module = uncst.get_name_strict(updated_node.module)
        names_del = {name for _module, name in self._imports_del if _module == module}
        names_add = {name for _module, name in self._imports_add if _module == module}

        if not (names_del or names_add):
            return updated_node

        aliases_new = [a for a in updated_node.names if a.name.value not in names_del]
        aliases_new.extend(cst.ImportAlias(cst.Name(name)) for name in names_add)
        aliases_new.sort(key=lambda a: uncst.get_name_strict(a.name))

        if not aliases_new:
            return cst.RemoveFromParent()

        # remove trailing comma
        if isinstance(aliases_new[-1].comma, cst.Comma):
            aliases_new[-1] = aliases_new[-1].with_changes(comma=None)

        return updated_node.with_changes(names=aliases_new)

    @override
    def leave_TypeAlias(
        self,
        /,
        original_node: cst.TypeAlias,
        updated_node: cst.TypeAlias,
    ) -> cst.TypeAlias | cst.Assign | cst.AnnAssign:
        if self.target >= (3, 13):
            return updated_node

        name = updated_node.name.value
        value = updated_node.value

        type_parameters = updated_node.type_parameters
        type_params = type_parameters.params if type_parameters else ()

        if self.target >= (3, 12) and all(p.default is None for p in type_params):
            return updated_node

        if not self._type_alias_alignment[name]:
            module = _MODULE_TP if self.target >= (3, 12) else _MODULE_TPX
            return uncst.parse_assign(
                name,
                uncst.parse_call(
                    self._require_import(module, _NAME_ALIAS_PEP695),
                    uncst.parse_str(name),
                    value,
                    type_params=uncst.parse_tuple(p.param.name for p in type_params),
                ),
            )

        type_alias = self._require_import(_MODULE_TP, _NAME_ALIAS, has_backport=True)
        return cst.AnnAssign(
            cst.Name(name),
            cst.Annotation(uncst.parse_name(type_alias)),
            value,
        )

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

        if not (tpars := updated_node.type_parameters):
            return updated_node
        if self.target >= (3, 13):
            return updated_node
        if self.target >= (3, 12) and not any(tpar.default for tpar in tpars.params):
            return updated_node

        return updated_node.with_changes(type_parameters=None)

    @override
    def visit_ClassDef(self, /, node: cst.ClassDef) -> None:
        self._stack.append(node.name.value)

    @override
    def leave_ClassDef(
        self,
        /,
        original_node: cst.ClassDef,
        updated_node: cst.ClassDef,
    ) -> cst.ClassDef | cst.FlattenSentinel[cst.ClassDef | cst.BaseStatement]:
        stack = self._stack
        name = stack.pop()

        if not (tpars := original_node.type_parameters):
            return updated_node
        if self.target >= (3, 12) and not any(tpar.default for tpar in tpars.params):
            return updated_node

        qualname = ".".join((*stack, name))
        assert qualname == updated_node.name.value or len(stack)

        base_args = updated_node.bases
        tpar_names = (tpar.param.name for tpar in tpars.params)

        visitor = self.visitor
        base_list = visitor.class_bases[qualname]
        base_set = set(base_list)

        name_protocol = visitor.imported_from_typing_as(_NAME_PROTOCOL)
        name_generic = visitor.imported_from_typing_as(_NAME_GENERIC)
        assert name_generic not in base_set

        new_bases = list(base_args)
        if base_set and name_protocol and name_protocol in base_set:
            assert name_protocol
            expr_protocol = uncst.parse_name(name_protocol)

            i = base_list.index(name_protocol)
            new_bases[i] = new_bases[i].with_changes(
                value=uncst.parse_subscript(expr_protocol, *tpar_names),
            )
        else:
            # insert `Generic` after all other positional class args
            i = len(base_list)
            generic = uncst.parse_name(name_generic or _NAME_GENERIC)
            new_bases.insert(i, cst.Arg(uncst.parse_subscript(generic, *tpar_names)))

            self._require_import(_MODULE_TP, _NAME_GENERIC, has_backport=True)

        return updated_node.with_changes(type_parameters=None, bases=new_bases)

    @override
    def leave_Module(
        self,
        /,
        original_node: cst.Module,
        updated_node: cst.Module,
    ) -> cst.Module:
        # all modules that were seen in the `from {module} import ...` statements
        from_modules = {
            fqn.rsplit(".", 1)[0]
            for fqn, alias in self.visitor.imports.items()
            if fqn != alias
        }

        # group the to-add imports statements per module like {module: [name, ...]}
        imports_from_add: dict[str, list[str]] = collections.defaultdict(list)
        for module, name in sorted(self._imports_add):
            if module not in from_modules:
                imports_from_add[module].append(name)

        new_import_stmts = [
            cst.SimpleStatementLine([
                cst.ImportFrom(
                    uncst.parse_name(module),
                    [cst.ImportAlias(cst.Name(n)) for n in names],
                ),
            ])
            for module, names in imports_from_add.items()
        ]

        new_typevar_stmts: list[cst.SimpleStatementLine] = []
        tpars: dict[str, uncst.TypeParameter] = {}
        for (_, name), tpar in self.visitor.type_params.items():
            if name in tpars:
                if tpar == tpars[name]:
                    continue

                # TODO(jorenham): rename in this case
                raise NotImplementedError(f"conflicting typevar definitions: {name!r}")

            tpars[name] = tpar
            new_typevar_stmts.append(cst.SimpleStatementLine([tpar.as_assign()]))

        if not new_import_stmts and not new_typevar_stmts:
            return updated_node

        new_body = list(updated_node.body)
        if new_import_stmts:
            i0_import = _new_typing_import_index(updated_node)
            new_body = [*new_body[:i0_import], *new_import_stmts, *new_body[i0_import:]]
        else:
            i0_import = 0

        if new_typevar_stmts:
            i0_typevars = _new_typevars_index(updated_node) or i0_import
            assert i0_typevars >= i0_import, (i0_typevars, i0_import)
            i0_typevars += len(new_import_stmts)

            if i0_typevars:
                new_typevar_stmts[0] = new_typevar_stmts[0].with_changes(
                    leading_lines=[cst.EmptyLine()],  # type: ignore[no-any-expr]
                )

            new_body = [
                *new_body[:i0_typevars],
                *new_typevar_stmts,
                *new_body[i0_typevars:],
            ]

        return updated_node.with_changes(body=new_body)


def transform_module(original: cst.Module, /, target: PythonVersion) -> cst.Module:
    wrapper = cst.MetadataWrapper(original)

    visitor = StubVisitor()
    _ = wrapper.visit(visitor)

    transformer = StubTransformer(visitor, target=target)
    return wrapper.visit(transformer)


def transform_source(
    source: str,
    /,
    *,
    target: PythonVersion = PythonVersion.PY311,
) -> str:
    return transform_module(cst.parse_module(source), target=target).code
