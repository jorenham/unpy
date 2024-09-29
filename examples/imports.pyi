from types import CapsuleType
from typing import override
from warnings import deprecated

@deprecated("RTFM")
class Spam:
    __pyx_capi__: dict[str, CapsuleType]
    @override
    def __hash__(self, /) -> int: ...
