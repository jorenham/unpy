import os

type PathLike[S: (str, bytes)] = S | os.PathLike[S]
type RPair[RT, LT=RT] = tuple[LT, RT]  # noqa: E225  # fmt: skip
