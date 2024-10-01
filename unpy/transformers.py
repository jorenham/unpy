import collections
import sys
from typing import Final, override

if sys.version_info >= (3, 13):
    from typing import TypeIs  # pyright: ignore[reportUnreachable]
else:
    try:
        from typing_extensions import TypeIs
    except ImportError:
        from typing import TypeGuard as TypeIs  # type: ignore[assignment]

import libcst as cst

import unpy._cst as uncst
from unpy._stdlib import BACKPORTS, UNSUPPORTED_BASES
from unpy._types import PythonVersion
from unpy.visitors import StubVisitor

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
    # {(fqn_old, fqn_new), ...}
    _renames: Final[dict[str, str]]
    # whether the type alias parameters are referenced in the order they are defined
    _type_alias_alignment: Final[dict[str, bool]]

    _stack_scope: Final[collections.deque[str]]
    _stack_attr: Final[collections.deque[cst.Attribute]]

    def __init__(self, visitor: StubVisitor, /, target: PythonVersion) -> None:
        self.visitor = visitor
        self.target = target

        self._stack_scope = collections.deque()
        self._stack_attr = collections.deque()

        self._imports_del = set()
        self._imports_add = set()
        self._renames = {}
        self._type_alias_alignment = {}

        self.__check_base_classes()
        self.__collect_imports_typevars()
        self.__collect_imports_backport()
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
                or module in BACKPORTS
                and name in BACKPORTS[module]
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

    def __check_base_classes(self, /) -> None:
        # raise for unsupported base classes
        target = self.target
        visitor = self.visitor

        illegal_fqn = {base for base, req in UNSUPPORTED_BASES.items() if target < req}
        illegal_names = {
            alias: base
            for base in illegal_fqn
            if (alias := visitor.imported_as(*base.rsplit(".", 1)))
        }

        for bases in self.visitor.class_bases.values():
            for base in bases:
                if base in illegal_names:
                    raise NotImplementedError(f"{illegal_names[base]!r} as base class")
                base = base.replace("__builtins__.", "builtins.")  # noqa: PLW2901
                if (fqn := visitor.imports_by_alias.get(base, base)) in illegal_fqn:
                    raise NotImplementedError(f"{fqn!r} as base class")
                if base in visitor.imports_by_ref:
                    module, name = visitor.imports_by_ref[base]
                    fqn = f"{module}.{name}" if name else module
                    if fqn in illegal_fqn:
                        raise NotImplementedError(f"{fqn!r} as base class")

    def __collect_imports_typevars(self, /) -> None:
        # collect the missing imports for the typevar-likes
        target = self.target
        for type_param in self.visitor.type_params.values():
            for module, name in type_param.required_imports(target):
                self._require_import(module, name, has_backport=module == _MODULE_TP)
                if module == _MODULE_TPX:
                    self._discard_import(_MODULE_TP, name)

    def __collection_import_backport_single(self, fqn: str, alias: str, /) -> None:
        if fqn[0] == "." or "." not in fqn or alias == fqn:
            return

        module, name = fqn.rsplit(".", 1)
        if not (backports := BACKPORTS.get(module)):
            return

        target = self.target

        if name == "*":
            for name_old in frozenset(backports) & self.visitor.global_names:
                module_new, name_new, req = backports[name_old]
                if target < req:
                    self._require_import(module_new, name_new, has_backport=False)
            return

        if name not in backports:
            return

        module_new, name_new, req = backports[name]
        if target < req:
            self._discard_import(module, name)
            self._require_import(module_new, name_new, has_backport=False)
            if alias != name_new:
                self._renames[name] = name_new

    def __collect_imports_backport(self, /) -> None:
        # collect the imports that should replaced with a `typing_extensions` backport
        visitor = self.visitor

        for fqn, alias in visitor.imports.items():
            self.__collection_import_backport_single(fqn, alias)

        for ref, (package, attr) in visitor.imports_by_ref.items():
            if not attr:
                continue

            if "." in attr:
                submodule, name = attr.rsplit(".", 1)
                module = f"{package}.{submodule}"
            else:
                module, name = package, attr

            assert name.isidentifier(), name

            if (
                (backports := BACKPORTS.get(module))
                and name in backports
                and self.target < backports[name][2]
            ):
                new_module, new_name, _ = backports[name]

                new_ref = self._require_import(new_module, new_name, has_backport=False)
                if ref != new_ref:
                    self._renames[ref] = new_ref

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
    def visit_Import(self, /, node: cst.Import) -> bool:
        return False

    @override
    def visit_ImportFrom(self, /, node: cst.ImportFrom) -> bool:
        return False

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
    def leave_Name(
        self,
        /,
        original_node: cst.Name,
        updated_node: cst.Name,
    ) -> cst.Attribute | cst.Name:
        if not self._stack_attr and (rename := self._renames.get(updated_node.value)):
            return uncst.parse_name(
                rename,
                lpar=updated_node.lpar,
                rpar=updated_node.rpar,
            )

        return updated_node

    @override
    def visit_Attribute(self, /, node: cst.Attribute) -> bool:
        self._stack_attr.append(node)
        return False

    @override
    def leave_Attribute(
        self,
        /,
        original_node: cst.Attribute,
        updated_node: cst.Attribute,
    ) -> cst.Attribute | cst.Name:
        stack = self._stack_attr
        node = stack.pop()
        assert node is original_node

        if stack or not isinstance(updated_node.value, cst.Name | cst.Attribute):
            return updated_node

        name = uncst.get_name_strict(node)
        if new_name := self._renames.get(name):
            assert new_name != name
            return uncst.parse_name(
                new_name,
                lpar=updated_node.lpar,
                rpar=updated_node.rpar,
            )

        return updated_node

    def _is_variadic_type(
        self,
        node: cst.BaseExpression,
        /,
    ) -> TypeIs[cst.Name | cst.Subscript]:
        # check whether the node can be used in `typing.Unpack`

        visitor = self.visitor

        # check if the name refers to a variadic type parameter
        if isinstance(node, cst.Name):
            name = node.value
            scope = list(self._stack_scope)
            for i in range(len(scope), 0, -1):
                fqn = ".".join(scope[:i])
                for tpar in visitor.type_params_grouped[fqn]:
                    if name != tpar.name:
                        continue
                    if not isinstance(tpar, uncst.TypeVarTuple):
                        raise TypeError(f"cannot unpack a {type(tpar).__name__}")
                    return True

            # TODO(jorenham): also unpack existing (legacy) TypeVarTuple names
            if visitor.imported_from_typing_as("TypeVarTuple"):
                raise NotImplementedError("manual TypeVarTuple")

            return False

        # check if the subscripted value is a `builtins.tuple`
        if isinstance(node, cst.Subscript) and (subname := uncst.get_name(node.value)):
            return subname in {
                visitor.imported_as("builtins", "tuple"),
                visitor.imported_from_typing_as("Tuple"),
            }

        return False

    def _unpack_variadic_type(self, node: cst.Name | cst.Subscript, /) -> cst.Subscript:
        # wrap the variadic type in `Unpack[_]`
        name_new = self._require_import(_MODULE_TPX, "Unpack", has_backport=False)
        return cst.Subscript(
            uncst.parse_name(name_new),
            [cst.SubscriptElement(cst.Index(node))],
        )

    @override
    def leave_Index(
        self,
        /,
        original_node: cst.Index,
        updated_node: cst.Index,
    ) -> cst.Index:
        # desugar variadic type args as `*Ts` => `Unpack[Ts]` before Python 3.11
        if (
            self.target < (3, 11)
            and updated_node.star
            and self._is_variadic_type(value := updated_node.value)
        ):
            updated_node = updated_node.with_changes(
                value=self._unpack_variadic_type(value),
                star=None,
            )

        return updated_node

    @override
    def leave_Annotation(
        self,
        /,
        original_node: cst.Annotation,
        updated_node: cst.Annotation,
    ) -> cst.Annotation:
        # desugar variadic type args annotations like `*_: *Ts` as `*_: Unpack[Ts]`
        # before Python 3.11

        # TODO(jorenham): disallow `node.annotation <: cst.SimpleString`
        # https://github.com/jorenham/unpy/issues/59

        if (
            self.target < (3, 11)
            and isinstance(updated_node.annotation, cst.StarredElement)
            and self._is_variadic_type(value := updated_node.annotation.value)
        ):
            updated_node = updated_node.with_changes(
                annotation=self._unpack_variadic_type(value),
            )
        return updated_node

    @override
    def visit_TypeAlias(self, /, node: cst.TypeAlias) -> None:
        self._stack_scope.append(node.name.value)

    @override
    def leave_TypeAlias(
        self,
        /,
        original_node: cst.TypeAlias,
        updated_node: cst.TypeAlias,
    ) -> cst.TypeAlias | cst.Assign | cst.AnnAssign:
        if self.target >= (3, 13):
            self._stack_scope.pop()
            return updated_node

        name = updated_node.name.value
        value = updated_node.value

        type_parameters = updated_node.type_parameters
        type_params = type_parameters.params if type_parameters else ()

        new_node: cst.TypeAlias | cst.Assign | cst.AnnAssign
        if self.target >= (3, 12) and all(p.default is None for p in type_params):
            new_node = updated_node
        elif not self._type_alias_alignment[name]:
            module = _MODULE_TP if self.target >= (3, 12) else _MODULE_TPX
            new_node = uncst.parse_assign(
                name,
                uncst.parse_call(
                    self._require_import(
                        module,
                        _NAME_ALIAS_PEP695,
                        has_backport=module == _MODULE_TP,
                    ),
                    uncst.parse_str(name),
                    value,
                    type_params=uncst.parse_tuple(p.param.name for p in type_params),
                ),
            )
        else:
            type_alias = self._require_import(
                _MODULE_TP,
                _NAME_ALIAS,
                has_backport=True,
            )
            new_node = cst.AnnAssign(
                cst.Name(name),
                cst.Annotation(uncst.parse_name(type_alias)),
                value,
            )

        self._stack_scope.pop()
        return new_node

    @override
    def visit_FunctionDef(self, /, node: cst.FunctionDef) -> None:
        self._stack_scope.append(node.name.value)

    @override
    def leave_FunctionDef(
        self,
        /,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> cst.FunctionDef | cst.FlattenSentinel[cst.BaseStatement]:
        if (
            (tpars := updated_node.type_parameters)
            and self.target < (3, 13)
            and (self.target < (3, 12) or any(tpar.default for tpar in tpars.params))
        ):
            updated_node = updated_node.with_changes(type_parameters=None)

            if self.target < (3, 11):
                # TODO(jorenham): unpack all `*Ts` param and return type annotations
                ...

        self._stack_scope.pop()
        return updated_node

    @override
    def visit_ClassDef(self, /, node: cst.ClassDef) -> None:
        self._stack_scope.append(node.name.value)

    @override
    def leave_ClassDef(
        self,
        /,
        original_node: cst.ClassDef,
        updated_node: cst.ClassDef,
    ) -> cst.ClassDef | cst.FlattenSentinel[cst.ClassDef | cst.BaseStatement]:
        stack = self._stack_scope
        name = stack.pop()

        if not (tpars := original_node.type_parameters):
            return updated_node
        if self.target >= (3, 12) and not any(tpar.default for tpar in tpars.params):
            return updated_node

        qualname = ".".join((*stack, name))
        assert qualname == updated_node.name.value or len(stack)

        visitor = self.visitor
        base_list = visitor.class_bases[qualname]
        base_set = set(base_list)

        name_protocol = visitor.imported_from_typing_as(_NAME_PROTOCOL)
        name_generic = visitor.imported_from_typing_as(_NAME_GENERIC)
        assert name_generic not in base_set

        subscript_elements = [
            tpar.as_subscript_element(target=self.target)
            for tpar in visitor.type_params_grouped[qualname]
        ]

        new_bases = list(updated_node.bases)
        if base_set and name_protocol and name_protocol in base_set:
            assert name_protocol
            expr_protocol = uncst.parse_name(name_protocol)

            i = base_list.index(name_protocol)
            new_bases[i] = new_bases[i].with_changes(
                value=cst.Subscript(expr_protocol, subscript_elements),
            )
        else:
            # insert `Generic` after all other positional class args
            i = len(base_list)
            generic = uncst.parse_name(name_generic or _NAME_GENERIC)
            new_bases.insert(i, cst.Arg(cst.Subscript(generic, subscript_elements)))

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
    target: PythonVersion = PythonVersion.PY310,
) -> str:
    return transform_module(cst.parse_module(source), target=target).code
