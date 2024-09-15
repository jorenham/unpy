import libcst as cst

from ._py311 import transform as transform_py311

__all__ = ("convert",)


def convert(source: str, /) -> str:
    return transform_py311(cst.parse_module(source)).code
