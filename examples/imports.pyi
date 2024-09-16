from collections.abc import Buffer
from typing import TypeAliasType
from warnings import deprecated

Alias = TypeAliasType("Alias", object)  # noqa: UP040

@deprecated("RTFM")
def dont_use_me(x: Buffer, /) -> bytes: ...
