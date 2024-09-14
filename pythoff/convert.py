import libcst as cst

from ._pep695 import PEP695Collector, TypeAliasTransformer, TypingImportTransformer

__all__ = ("convert",)


def convert(source: str, /) -> str:
    return (
        cst.parse_module(source)
        .visit(collector := PEP695Collector())
        .visit(TypeAliasTransformer.from_collector(collector))
        .visit(TypingImportTransformer.from_collector(collector))
        .code
    )
