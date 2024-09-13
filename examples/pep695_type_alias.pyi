from os import PathLike as _PathLike
from typing import LiteralString

type AnyStr = str | bytes
type PathLike[S: (str, bytes)] = S | _PathLike[S]
type RPair[RT, LT=RT] = tuple[LT, RT]  # noqa: E225  # fmt: skip

TMP_DIR: PathLike[LiteralString]
TWO_STRINGS: RPair[str]
