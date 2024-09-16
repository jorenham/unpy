<h1 align="center">unpy</h1>

<p align="center">
    Backports Python typing stubs to earlier Python versions
</p>

<p align="center">
    <a href="https://pypi.org/project/unpy/">
        <img
            alt="unpy - PyPI"
            src="https://img.shields.io/pypi/v/unpy?style=flat&color=olive"
        />
    </a>
    <a href="https://github.com/jorenham/unpy">
        <img
            alt="unpy - Python Versions"
            src="https://img.shields.io/pypi/pyversions/unpy?style=flat"
        />
    </a>
    <a href="https://github.com/jorenham/unpy">
        <img
            alt="unpy - license"
            src="https://img.shields.io/github/license/jorenham/unpy?style=flat"
        />
    </a>
</p>
<p align="center">
    <a href="https://github.com/jorenham/unpy/actions?query=workflow%3ACI">
        <img
            alt="unpy - CI"
            src="https://github.com/jorenham/unpy/workflows/CI/badge.svg"
        />
    </a>
    <!-- TODO -->
    <a href="https://github.com/pre-commit/pre-commit">
        <img
            alt="unpy - pre-commit"
            src="https://img.shields.io/badge/pre--commit-enabled-teal?logo=pre-commit"
        />
    </a>
    <!-- <a href="https://github.com/KotlinIsland/basedmypy">
        <img
            alt="unpy - basedmypy"
            src="https://img.shields.io/badge/basedmypy-checked-fd9002"
        />
    </a> -->
    <a href="https://detachhead.github.io/basedpyright">
        <img
            alt="unpy - basedpyright"
            src="https://img.shields.io/badge/basedpyright-checked-42b983"
        />
    </a>
    <a href="https://github.com/astral-sh/ruff">
        <img
            alt="unpy - ruff"
            src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json"
        />
    </a>
</p>

---

> [!IMPORTANT]
> This project is in the early stages of development;
> You probably shouldn't use it in production.
>
## Installation

The `unpy` package is available as on PyPI, and can be installed with e.g.

```shell
pip install unpy
```

## Usage

```console
$ unpy --help
Usage: unpy [OPTIONS] SOURCE [OUTPUT]

Arguments:
  SOURCE    Path to the input .pyi file or '-' to read from stdin.  [required]
  [OUTPUT]  Path to the output .pyi file. Defaults to stdout.

Options:
  -V, --version        Show the version and exit
  -P, --python [3.11]  The minimum Python version that should be supported.
                       [default: 3.11]
  --help               Show this message and exit.
```

## Features

- Python 3.13 => 3.12
    - [x] [PEP 742][PEP742]: `typing.TypeIs` => `typing_extensions.TypeIs`
    - [x] [PEP 705][PEP705]: `typing.ReadOnly` => `typing_extensions.ReadOnly`
    - [x] [PEP 702][PEP702]: `warnings.deprecated` => `typing_extensions.deprecated`
    - [x] [PEP 696][PEP696]: Backport [PEP 695][PEP695] type signatures i.f.f. it
    includes a type parameter with default
    - [x] [PEP 696][PEP696]: `typing.NoDefault` => `typing_extensions.NoDefault`
    - [x] `typing.get_protocol_members` => `typing_extensions.get_protocol_members`
    - [x] `typing.is_protocol` => `typing_extensions.is_protocol`
    - [x] `typing.is_protocol` => `typing_extensions.is_protocol`
    - [x] `types.CapsuleType` => `typing_extensions.CapsuleType`
    - [ ] nested `typing.Final` and `typing.ClassVar`
- Python 3.12 => 3.11
    - [x] [PEP 698][PEP698]: `typing.override` => `typing_extensions.override`
    - [x] [PEP 695][PEP695]: Backport generic functions
    - [x] [PEP 695][PEP695]: Backport generic classes
    - [x] [PEP 695][PEP695]: Backport generic protocols
    - [x] [PEP 695][PEP695]: `type {} = ...` => `{}: TypeAlias = ...` or
    - [x] [PEP 695][PEP695]: `typing.TypeAliasType` => `typing_extensions.TypeAliasType`
    - [x] [PEP 688][PEP688]: `collections.abc.Buffer` => `typing_extensions.Buffer`
    - [ ] [PEP 688][PEP688]: `inspect.BufferFlags` => `int`
    - [ ] Backport subclasses of `path.Path`
- Python 3.11 => 3.10
    - [ ] [PEP 681][PEP681]: `typing.dataclass_transform` =>
    `typing_extensions.dataclass_transform`
    - [ ] [PEP 680][PEP680]: `tomllib` => `tomli`
    - [ ] [PEP 675][PEP675]: `typing.LiteralString` => `typing_extensions.LiteralString`
    - [ ] [PEP 673][PEP673]: `typing.Self` => `typing_extensions.Self`
    - [ ] [PEP 655][PEP655]: `typing.[Not]Required` => `typing_extensions.[Not]Required`
    - [ ] [PEP 646][PEP646]: `*Ts` => `typing_extensions.Unpack[Ts]`
- Generated `TypeVar`s
    - [ ] Prefix extracted `TypeVar`s names with `_`
    - [ ] De-duplicate extracted `TypeVar`s
    - [ ] Prevent `TypeVar` name clashes (rename or merge)
    - [ ] Infer variance of `typing_extensions.TypeVar(..., infer_variance=True)` whose
      name does not end with `_contra`/`_in` (`contravariant=True`) or `_co`/`_out`
      (`covariant=True`)
    - [x] Convert `default=Any` to `default={bound}` or `default=object`
    - [x] Remove `bound=Any` and `bound=object`
    - [ ] Importing `TypeVar`'s (not recommended)
- Imports
    - [x] Reuse existing `from typing[_extensions] import {name}` imports instead of
    adding new ones
    - [ ] Reuse `from {module} import {name} as {alias}` import aliases if present, e.g.
    `from typing import TypeVar as TypeParam`
    - [ ] Reuse `import {module} as {alias}` if present, e.g. `import typing as tp`
    - [ ] Support for custom `typing` modules (like `[tool.ruff.lint.typing-modules]`)
    - [ ] Support for `from typing[_extensions] import *` (not recommended)
- Interface
    - [x] Backport from stdin / to stdout
    - [x] Backport a single `.pyi` file
    - [ ] Backport all `.pyi` files in package
    - [ ] Configuration options in `pyproject.toml` as `[tools.unpy]`
    - [ ] Project build tools
    - [ ] Configurable type-checker integration
    - [ ] Configurable post processing with e.g. `ruff format`
- Integration
    - [ ] File watcher
    - [ ] Pre-commit
    - [ ] VSCode extension
    - [ ] (based)mypy plugin
- Misc
    - [ ] `.py` support
    - [ ] Transform `self` parameters to be positional-only
    - [ ] Use `None` as the default return type
    - [ ] De-duplicate and flatten unions and literals
    - [ ] `type[S] | type[T]` => `type[S | T]`
- Extended syntax
    - [ ] Write `_: True | 1 | "a"` instead of `_: Literal[True, 1, "a"]`
    - [ ] Allow omitting `@overload`
    - [ ] Intersection types
    - [ ] Mapped types
    - [ ] Higher-kinded types

[PEP646]: https://peps.python.org/pep-0646/
[PEP655]: https://peps.python.org/pep-0655/
[PEP673]: https://peps.python.org/pep-0673/
[PEP675]: https://peps.python.org/pep-0675/
[PEP680]: https://peps.python.org/pep-0680/
[PEP681]: https://peps.python.org/pep-0681/
[PEP688]: https://peps.python.org/pep-0688/
[PEP695]: https://peps.python.org/pep-0695/
[PEP696]: https://peps.python.org/pep-0696/
[PEP698]: https://peps.python.org/pep-0698/
[PEP702]: https://peps.python.org/pep-0702/
[PEP705]: https://peps.python.org/pep-0705/
[PEP742]: https://peps.python.org/pep-0705/
