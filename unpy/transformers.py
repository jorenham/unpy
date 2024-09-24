import collections
from typing import TYPE_CHECKING, Final, override

import libcst as cst
import libcst.matchers as m

from ._cst import (
    get_name_strict,
    parse_assign,
    parse_call,
    parse_name,
    parse_str,
    parse_subscript,
    parse_tuple,
)
from ._types import AnyFunction, PythonVersion
from .visitors import StubVisitor

if TYPE_CHECKING:
    from collections.abc import Generator

__all__ = ("StubTransformer",)

type _Node_01[N: cst.CSTNode] = N | cst.RemovalSentinel
type _Node_1N[N: cst.CSTNode, NN: cst.CSTNode] = N | cst.FlattenSentinel[N | NN]


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


def _remove_tpars[N: (cst.ClassDef, cst.FunctionDef)](node: N, /) -> N:
    if node.type_parameters:
        return node.with_changes(type_parameters=None)
    return node


def _workaround_libcst_runtime_typecheck_bug[F: AnyFunction](f: F, /) -> F:
    # LibCST crashes if `cst.SimpleStatementLine` is included in the return type
    # annotation.
    # This workaround circumvents this by hiding the return type annation at runtime.
    del f.__annotations__["return"]  # type: ignore[no-any-expr]
    return f


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


class StubTransformer(m.MatcherDecoratableTransformer):
    visitor: Final[StubVisitor]
    _stack: Final[collections.deque[str]]

    def __init__(self, /, visitor: StubVisitor) -> None:
        assert visitor.imports_del <= set(visitor.imports), visitor.imports_del
        assert not visitor.imports_add & set(visitor.imports), visitor.imports_add

        self.visitor = visitor
        self._stack = collections.deque()

        super().__init__()

    @property
    def missing_tvars(self, /) -> dict[str, list[cst.Assign]]:
        return self.visitor.missing_tvars

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

        col = self.visitor
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

        if not (tpars := original_node.type_parameters):
            return updated_node

        base_args = updated_node.bases
        tpar_names = (tpar.param.name for tpar in tpars.params)

        qualname = ".".join(stack)

        visitor = self.visitor
        base_list = visitor.baseclasses[qualname]
        base_set = set(base_list)

        name_generic = visitor.imported_from_typing_as("Generic")
        assert name_generic not in base_set

        new_bases = list(base_args)
        if base_set and (
            (fqn_protocol := "typing.Protocol") in base_set
            or (fqn_protocol := "typing_extensions.Protocol") in base_set
        ):
            name_protocol = visitor.imported_from_typing_as("Protocol")
            assert name_protocol
            expr_protocol = parse_name(name_protocol)

            i = base_list.index(fqn_protocol)
            new_bases[i] = cst.Arg(parse_subscript(expr_protocol, *tpar_names))
        else:
            # insert `Generic` after all other positional class args
            i = len(base_list)
            expr_generic = parse_name(name_generic or "Generic")
            new_bases.insert(i, cst.Arg(parse_subscript(expr_generic, *tpar_names)))

        updated_node = updated_node.with_changes(type_parameters=None, bases=new_bases)

        stack.pop()
        return self._prepend_tvars(updated_node) if not stack else updated_node

    @override
    def leave_Module(
        self,
        /,
        original_node: cst.Module,
        updated_node: cst.Module,
    ) -> cst.Module:
        if not (imports_add := self.visitor.imports_add):
            return updated_node

        # all modules that were seen in the `from {module} import ...` statements
        from_modules = {
            fqn.rsplit(".", 1)[0]
            for fqn, alias in self.visitor.imports.items()
            if fqn != alias
        }

        # group the to-add imports statements per module like {module: [name, ...]}
        imports_from_add: dict[str, list[str]] = collections.defaultdict(list)
        for fqn in sorted(imports_add):
            module, name = fqn.rsplit(".", 1)
            if module not in from_modules:
                imports_from_add[module].append(name)

        if not imports_from_add:
            return updated_node

        new_statements = [
            cst.SimpleStatementLine([
                cst.ImportFrom(
                    parse_name(module),
                    [cst.ImportAlias(cst.Name(n)) for n in names],
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

    visitor = StubVisitor()
    _ = wrapper.visit(visitor)

    transformer = StubTransformer(visitor)
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
