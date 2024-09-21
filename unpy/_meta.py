import functools
import importlib.metadata

__all__ = ("get_version",)


@functools.cache  # type: ignore[no-any-expr]
def get_version() -> str:
    return importlib.metadata.version(__package__ or __file__.split("/")[-1])
