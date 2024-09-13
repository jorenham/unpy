import errno
import sys
from pathlib import Path

import libcst as cst
import mainpy

from ._pep695 import PEP695Collector, TypeAliasTransformer, TypingImportTransformer


def transpile_from_string(source: str, /, *, is_pyi: bool = True) -> str:
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


@mainpy.main
def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: pythoff input.pyi", file=sys.stderr)
        sys.exit(1)

    _, file_in = sys.argv
    path_in = Path(file_in)

    ext = path_in.suffix
    if ext == "py":
        raise NotImplementedError("py files not supported yet")
    if ext not in {".py", ".pyi"}:
        print("Input must be a .py[i] file", file=sys.stderr)
        sys.exit(1)

    try:
        source_in = Path(file_in).read_text(encoding="utf-8", errors="strict")
    except FileNotFoundError:
        print(f"File not found: {file_in}", file=sys.stderr)
        sys.exit(errno.ENOENT)
    except IsADirectoryError:
        print(f"File is a directory: {file_in}", file=sys.stderr)
        sys.exit(errno.EISDIR)

    source_out = transpile_from_string(source_in)
    print(source_out, end=None)
