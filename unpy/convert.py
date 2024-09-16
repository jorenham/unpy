import enum

import libcst as cst

from ._py311 import transform as transform_py311

__all__ = "PythonVersion", "convert"


class PythonVersion(enum.StrEnum):
    # PY313 = "3.13"
    # PY312 = "3.12"
    PY311 = "3.11"
    # PY310 = "3.10"
    # PY39 = "3.9"
    # PY38 = "3.8"


def convert(source: str, /, python: PythonVersion = PythonVersion.PY311) -> str:
    if python != PythonVersion.PY311:
        raise NotADirectoryError(f"Python {python.value}")  # pyright: ignore[reportUnreachable]
    return transform_py311(cst.parse_module(source)).code
