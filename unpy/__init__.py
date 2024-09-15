from typing import Final, LiteralString

import mainpy

from unpy.cli import app

__all__ = ("__version__",)
__version__: LiteralString
__author__: Final = "Joren Hammdugolu"
__email__: Final = "jhammudoglu@gmail.com"

_ = mainpy.main(app)


def __getattr__(name: str, /) -> object:
    if name == "__version__":
        from unpy._meta import get_version  # noqa: PLC0415

        return get_version()

    import sys  # noqa: PLC0415

    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}",
        name=name,
        obj=sys.modules[__name__],
    )


def __dir__() -> list[str]:
    return list(__all__)
