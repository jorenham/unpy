import builtins
from importlib.abc import Loader
from importlib.machinery import ModuleSpec
from typing import Final

__all__ = (
    "BASES_WITHOUT_BACKPORT",
    "GLOBALS_DEFAULT",
    "NAMES_BACKPORT_TPX",
    "NAMES_DEPRECATED_ALIASES",
    "NAMES_WITHOUT_BACKPORT",
)


GLOBALS_DEFAULT: Final[dict[str, type | object]] = {
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

NAMES_DEPRECATED_ALIASES: Final = {
    typing_module: {
        # builtins
        "Text": "builtins.str",
        **{
            alias: f"builtins.{alias.lower()}"
            for alias in ["Dict", "List", "Set", "FrozenSet", "Tuple", "Type"]
        },
        # typing
        "IntVar": f"{typing_module}.TypeVar",
        "runtime": f"{typing_module}.runtime_checkable",
        # collections
        "DefaultDict": "collections.defaultdict",
        "Deque": "collections.deque",
        "ChainMap": "collections.ChainMap",
        "Counter": "collections.Counter",
        "OrderedDict": "collections.OrderedDict",
        # collections.abc
        "AbstractSet": "collections.abc.Set",
        **{
            name: f"collections.abc.{name}"
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
        "ContextManager": "contextlib.ContextManager",
        "AsyncContextManager": "contextlib.AsyncContextManager",
        # re
        "Pattern": "re.Pattern",
        "Match": "re.Match",
    }
    for typing_module in ["typing", "typing_extensions"]
}

# stdlib imports that have a backport in `typing_extensions`
NAMES_BACKPORT_TPX: Final = {
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

NAMES_WITHOUT_BACKPORT: Final = {
    "builtins": {
        "_IncompleteInputError": (3, 13),
        "PythonFinalizationError": (3, 13),
        "BaseExceptionGroup": (3, 11),
        "ExceptionGroup": (3, 11),
        "EncodingWarning": (3, 10),
    },
}
BASES_WITHOUT_BACKPORT: Final = {
    "pathlib": {
        "Path": (3, 12),
    },
    "typing": {
        "Any": (3, 11),
    },
    "typing_extensions": {
        "Any": (3, 11),
    },
}
