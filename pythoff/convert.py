import libcst as cst

from ._pep695 import PEP695Collector, TypeAliasTransformer, TypingImportTransformer

__all__ = ("convert",)


def convert(source: str, /, *, is_pyi: bool = True) -> str:
    visitor = PEP695Collector(is_pyi=is_pyi)
    module = cst.parse_module(source)

    wrapper = cst.MetadataWrapper(module)
    _ = wrapper.visit(visitor)

    alias_transformer = TypeAliasTransformer(type_params=visitor.type_params)
    module_out = wrapper.module.visit(alias_transformer)

    import_transformer = TypingImportTransformer(
        cur_imports_typing=visitor.cur_imports_typing,
        cur_imports_typing_extensions=visitor.cur_imports_typing_extensions,
        req_imports_typing=visitor.req_imports_typing,
        req_imports_typing_extensions=visitor.req_imports_typing_extensions,
    )
    module_out = module_out.visit(import_transformer)

    return module_out.code
