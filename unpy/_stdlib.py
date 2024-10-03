import builtins
from importlib.abc import Loader
from importlib.machinery import ModuleSpec
from typing import Final

__all__ = (
    "BACKPORTS",
    "DEFAULT_GLOBALS",
    "UNSUPPORTED_BASES",
    "UNSUPPORTED_NAMES",
)

DEFAULT_GLOBALS: Final[dict[str, type | object]] = {
    "__name__": str,
    "__doc__": str | None,
    "__package__": str | None,
    "__loader__": type[Loader],
    "__spec__": ModuleSpec | None,
    "__annotations__": dict[str, type | object],
    "__builtins__": type(builtins),
    "__file__": str | None,
    "__cached__": str | None,
}

UNSUPPORTED_NAMES: Final = {
    "ast.TryStar": (3, 11),
    "ast.TypeAlias": (3, 12),
    "ast.TypeVar": (3, 12),
    "ast.TypeVarTuple": (3, 12),
    "ast.ParamSpec": (3, 12),
    "ast.PyCF_OPTIMIZED_AST": (3, 13),
    "asyncio.TaskGroup": (3, 11),
    "builtins._IncompleteInputError": (3, 13),
    "builtins.PythonFinalizationError": (3, 13),
    "builtins.BaseExceptionGroup": (3, 11),
    "builtins.ExceptionGroup": (3, 11),
    "builtins.EncodingWarning": (3, 10),
    "builtins.reveal_locals": (4, 0),
    "builtins.reveal_type": (4, 0),
    "typing.ByteString": (4, 0),
    "typing.Text": (4, 0),
    "typing.cast": (4, 0),
    "typing.reveal_type": (4, 0),
}
UNSUPPORTED_BASES: Final = {
    "builtins.object": (4, 0),
    "inspect.BufferFlags": (3, 12),
    "pathlib.Path": (3, 12),
}


# stdlib imports that have a backport in `typing_extensions`
_BACKPORTS_TPX: Final = {
    "collections.abc": {
        "Buffer": (3, 12),
    },
    "types": {
        # TODO: `python<3.10` backports for `NoneType`, `EllipsisType`, `UnionType`
        "CapsuleType": (3, 13),
        "get_original_bases": (3, 13),
    },
    "typing": {
        # >= 3.10
        "Concatenate": (3, 10),
        "ParamSpec": (3, 10),
        "ParamSpecArgs": (3, 10),
        "ParamSpecKwargs": (3, 10),
        "TypeAlias": (3, 10),
        "TypeGuard": (3, 10),
        "is_typeddict": (3, 10),
        # >= 3.11
        "LiteralString": (3, 11),
        "Never": (3, 11),
        "NotRequired": (3, 11),
        "Required": (3, 11),
        "Self": (3, 11),
        "TypeVarTuple": (3, 11),
        "Unpack": (3, 11),
        "assert_never": (3, 11),
        "assert_type": (3, 11),
        "clear_overloads": (3, 11),
        "dataclass_transform": (3, 11),
        "get_overloads": (3, 11),
        "reveal_type": (3, 11),
        # >= 3.12
        "TypeAliasType": (3, 12),
        "override": (3, 12),
        # >= 3.13
        "NoDefault": (3, 13),
        "ReadOnly": (3, 13),
        "TypeIs": (3, 13),
        "get_protocol_members": (3, 13),
        "is_protocol": (3, 13),
        # >= 3.14 (subject to change)
        "Doc": (3, 14),
        "evaluate_forward_ref": (3, 14),
    },
    "warnings": {
        "deprecated": (3, 13),
    },
}
_BACKPORTS_DEPRECATED: Final = {
    typing_module: {
        # builtins
        "Text": ("builtins", "str"),
        **{
            alias: ("builtins", alias.lower())
            for alias in ["Dict", "List", "Set", "FrozenSet", "Tuple", "Type"]
        },
        # typing
        "IntVar": (typing_module, "TypeVar"),
        "runtime": (typing_module, "runtime_checkable"),
        # collections
        "DefaultDict": ("collections", "defaultdict"),
        "Deque": ("collections", "deque"),
        "ChainMap": ("collections", "ChainMap"),
        "Counter": ("collections", "Counter"),
        "OrderedDict": ("collections", "OrderedDict"),
        # collections.abc
        "AbstractSet": ("collections.abc", "Set"),
        **{
            name: ("collections.abc", name)
            for name in [
                "Collection",
                "Container",
                "ItemsView",
                "KeysView",
                "ValuesView",
                "Mapping",
                "MappingView",
                "MutableMapping",
                "MutableSequence",
                "MutableSet",
                "Sequence",
                "Coroutine",
                "AsyncGenerator",
                "AsyncIterable",
                "AsyncIterator",
                "Awaitable",
                "Iterable",
                "Iterator",
                "Callable",
                "Generator",
                "Hashable",
                "Reversible",
                "Sized",
            ]
        },
        # contextlib
        "ContextManager": ("contextlib", "AbstractContextManager"),
        "AsyncContextManager": ("contextlib", "AbstractAsyncContextManager"),
        # re
        "Pattern": ("re", "Pattern"),
        "Match": ("re", "Match"),
    }
    for typing_module in ["typing", "typing_extensions"]
}

BACKPORTS: Final = {
    "asyncio": {
        "QueueShutDown": ("builtins", "Exception", (3, 13)),
    },
    "collections.abc": {},
    "enum": {
        "ReprEnum": ("enum", "Enum", (3, 11)),
        # NOTE: `enum.StrEnum` should only be used as baseclass, and is backported
        # as `str & enum.Enum`
        "StrEnum": ("enum", "Enum", (3, 11)),
    },
    "inspect": {
        "BufferFlags": ("builtins", "int", (3, 12)),
    },
    "pathlib": {
        "UnsupportedOperation": ("builtins", "NotImplementedError", (3, 13)),
    },
    "queue": {
        "ShutDown": ("builtins", "Exception", (3, 13)),
    },
    "re": {
        "PatternError": ("re", "error", (3, 13)),
    },
}


def __collect_backports() -> None:
    for module, reqs in _BACKPORTS_TPX.items():
        if module not in BACKPORTS:
            BACKPORTS[module] = {}
        BACKPORTS[module] |= {
            name: ("typing_extensions", name, req) for name, req in reqs.items()
        }

    for module, aliases in _BACKPORTS_DEPRECATED.items():
        if module not in BACKPORTS:
            BACKPORTS[module] = {}
        BACKPORTS[module] |= {
            name: (module_new, name_new, (4, 0))
            for name, (module_new, name_new) in aliases.items()
        }


__collect_backports()
