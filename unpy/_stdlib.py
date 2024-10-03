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
    "annotationlib.ForwardRef": (3, 14),
    "ast.TryStar": (3, 11),
    "ast.TypeAlias": (3, 12),
    "ast.TypeVar": (3, 12),
    "ast.TypeVarTuple": (3, 12),
    "ast.ParamSpec": (3, 12),
    "ast.PyCF_OPTIMIZED_AST": (3, 13),
    "asyncio.Barrier": (3, 11),
    "asyncio.Runner": (3, 11),
    "asyncio.TaskGroup": (3, 11),
    "builtins._IncompleteInputError": (3, 13),
    "builtins.BaseExceptionGroup": (3, 11),
    "builtins.ExceptionGroup": (3, 11),
    "builtins.reveal_locals": (4, 0),
    "builtins.reveal_type": (4, 0),
    "enum.verify": (3, 11),
    "enum.member": (3, 11),
    "enum.property": (3, 11),
    "enum.global_enum": (3, 11),
    "functools.cache": (4, 0),
    "functools.lru_cache": (4, 0),
    "functools.singledispatch": (4, 0),
    "inspect.markcoroutinefunction": (4, 0),  # use `async def` instead
    "typing.ByteString": (4, 0),
    "typing.Text": (4, 0),
    "typing.cast": (4, 0),
    "typing.assert_never": (4, 0),
    "typing.assert_type": (4, 0),
    "typing.clear_overloads": (4, 0),
    "typing.no_type_check_decorator": (4, 0),
    "typing.reveal_type": (4, 0),
    # https://github.com/python/cpython/blob/3.11/Lib/wsgiref/types.py
    "wsgiref.types.WSGIEnvironment": (3, 11),
    "wsgiref.types.WSGIApplication": (3, 11),
    "wsgiref.types.StartResponse": (3, 11),
    "wsgiref.types.InputStream": (3, 11),
    "wsgiref.types.ErrorStream": (3, 11),
    "wsgiref.types.FileWrapper": (3, 11),
}
UNSUPPORTED_BASES: Final = {
    "builtins.bool": (4, 0),
    "builtins.object": (4, 0),
    "calendar.Month": (3, 12),
    "calendar.Day": (3, 12),
    "inspect.BufferFlags": (3, 12),
    "inspect.FrameInfo": (3, 11),
    "inspect.Traceback": (3, 11),
    "pathlib.PurePath": (3, 12),
    "pathlib.Path": (3, 12),
}


# stdlib imports that have a backport in `typing_extensions`
_BACKPORTS_TPX: Final = {
    "annotationlib": {
        "Format": (3, 14),
    },
    "collections.abc": {
        "Buffer": (3, 12),
    },
    "typing": {
        "Concatenate": (3, 10),
        "ParamSpec": (3, 10),
        "ParamSpecArgs": (3, 10),
        "ParamSpecKwargs": (3, 10),
        "TypeAlias": (3, 10),
        "TypeGuard": (3, 10),
        "is_typeddict": (3, 10),
        "LiteralString": (3, 11),
        "Never": (3, 11),
        "NotRequired": (3, 11),
        "Required": (3, 11),
        "Self": (3, 11),
        "TypeVarTuple": (3, 11),
        "Unpack": (3, 11),
        "dataclass_transform": (3, 11),
        "TypeAliasType": (3, 12),
        "override": (3, 12),
        "NoDefault": (3, 13),
        "ReadOnly": (3, 13),
        "TypeIs": (3, 13),
        "get_protocol_members": (3, 13),
        "is_protocol": (3, 13),
        "Doc": (3, 14),  # provisional (PEP 727)
        "TypeForm": (3, 14),  # provisional (PEP 747)
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
        "BrokenBarrierError": ("builtins", "RuntimeError", (3, 11)),
        "QueueShutDown": ("builtins", "Exception", (3, 13)),
    },
    "builtins": {
        "EncodingWarning": ("builtins", "Warning", (3, 10)),
        "PythonFinalizationError": ("builtins", "RuntimeError", (3, 13)),
    },
    # TODO(jorenham): backport as literals
    # https://github.com/jorenham/unpy/issues/92
    "calendar": {
        "Month": ("builtins", "int", (3, 12)),
        "Day": ("builtins", "int", (3, 12)),
    },
    "collections.abc": {},  # filled in later
    "datetime": {
        "UTC": ("datetime.timezone", "utc", (3, 11)),
    },
    "dbm.sqlite3": {
        "error": ("builtins", "OSError", (3, 13)),
    },
    "enum": {
        "EnumType": ("enum", "EnumMeta", (3, 11)),
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
    "sys.monitoring": {
        "events": ("builtins", "int", (3, 12)),
    },
    "types": {
        "EllipsisType": ("builtins", "type", (3, 10)),
        "NoneType": ("builtins", "type", (3, 10)),
        "NotImplementedType": ("builtins", "type", (3, 10)),
        "UnionType": ("typing", "_UnionGenericAlias", (3, 10)),
        "CapsuleType": ("typing_extensions", "CapsuleType", (3, 13)),
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
