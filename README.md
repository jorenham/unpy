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
    <a href="https://github.com/KotlinIsland/basedmypy">
        <img
            alt="unpy - basedmypy"
            src="https://img.shields.io/badge/basedmypy-checked-fd9002"
        />
    </a>
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
  --version        Show the version and exit
  --diff           Show the changes between the input and output in unified
                   diff format
  --target [3.11]  The minimum Python version that should be supported.
                   [default: 3.11]
  --help           Show this message and exit.
```

## Examples

Some simple examples of Python 3.13 stubs that are backported to Python 3.11.

### Imports

```console
unpy examples/imports.pyi --diff
```

```diff
+++ -
@@ -1,6 +1,4 @@
- from types import CapsuleType
- from typing import override
- from warnings import deprecated
+ from typing_extensions import CapsuleType, deprecated, override

  @deprecated("RTFM")
  class Spam:
      __pyx_capi__: dict[str, CapsuleType]
      @override
      def __hash__(self, /) -> int: ...

```

Note the alphabetical order of the generated imports.

### Type Aliases

```console
unpy examples/type_aliases.pyi --diff
```

```diff
+++ -
@@ -1,7 +1,15 @@
  from collections.abc import Callable
+ from typing import ParamSpec, TypeAlias, TypeVar, TypeVarTuple
+ from typing_extensions import TypeAliasType

- type Binary = bytes | bytearray | memoryview
- type Vector[R: float] = tuple[R, ...]
- type tciD[V, K] = dict[K, V]
- type Things[*Ts] = tuple[*Ts]
- type Callback[**Tss] = Callable[Tss, None]
+ R = TypeVar("R", bound=float)
+ V = TypeVar("V")
+ K = TypeVar("K")
+ Ts = ParamSpec("Ts")
+ Tss = ParamSpec("Tss")
+
+ Binary: TypeAlias = bytes | bytearray | memoryview
+ Vector: TypeAlias = tuple[R, ...]
+ tciD = TypeAliasType("tciD", dict[K, V], type_params=(V, K))
+ Things: TypeAlias = tuple[*Ts]
+ Callback: TypeAlias = Callable[Tss, None]

```

Note that `TypeAlias` cannot be used with `tciD` because the definition order of the
type parameters (at the left-hand side) does not match the order in which they are
accessed (at the right-hand side), and the backported `TypeAliasType` must be used
instead.

### Functions

```console
unpy examples/functions.pyi --diff
```

```diff
+++ -
@@ -1,6 +1,11 @@
+ T = TypeVar("T")
+ S = TypeVar("S", str, bytes)
+ X = TypeVar("X")
+ Theta = ParamSpec("Theta")
+ Y = TypeVar("Y")
  from collections.abc import Callable as Def
- from typing import Concatenate as Concat
+ from typing import Concatenate as Concat, ParamSpec, TypeVar

- def noop[T](x: T, /) -> T: ...
- def concat[S: (str, bytes)](left: S, right: S) -> S: ...
- def curry[X, **Theta, Y](f: Def[Concat[X, Theta], Y], /) -> Def[[X], Def[Theta, Y]]: ...
+ def noop(x: T, /) -> T: ...
+ def concat(left: S, right: S) -> S: ...
+ def curry(f: Def[Concat[X, Theta], Y], /) -> Def[[X], Def[Theta, Y]]: ...

```

### Generic classes and protocols

```console
unpy examples/generics.pyi --diff
```

```diff
+++ -
@@ -1,17 +1,25 @@
- from typing import Protocol, overload
+ from typing import Generic, Protocol, overload
+ from typing_extensions import TypeVar
+
+ T_contra = TypeVar("T_contra", contravariant=True)
+ T_co = TypeVar("T_co", covariant=True)
+ T = TypeVar("T", infer_variance=True)
+ D = TypeVar("D")
+ NameT = TypeVar("NameT", infer_variance=True, bound=str)
+ QualNameT = TypeVar("QualNameT", infer_variance=True, bound=str, default=NameT)

  class Boring: ...

- class CanGetItem[T_contra, T_co](Protocol):
+ class CanGetItem(Protocol[T_contra, T_co]):
      def __getitem__(self, k: T_contra, /) -> T_co: ...

- class Stack[T]:
+ class Stack(Generic[T]):
      def push(self, value: T, /) -> None: ...
      @overload
      def pop(self, /) -> T: ...
      @overload
-     def pop[D](self, default: D, /) -> T | D: ...
+     def pop(self, default: D, /) -> T | D: ...

- class Named[NameT: str, QualNameT: str = NameT]:
+ class Named(Generic[NameT, QualNameT]):
      __name__: NameT
      __qualname__: QualNameT

```

Note how `TypeVar` is (only) imported from `typing_extensions` here, which wasn't the
case in the previous example. This is a consequence of the `infer_variance` parameter,
which has been added in Python 3.12.

## Project goals

Here's the alpha version of a prototype of a rough sketch of some initial ideas for the
potential goals of `unpy`:

1. Towards the past
    - [x] Get frustrated while [stubbing scipy](https://github.com/jorenham/scipy-stubs)
    - [ ] **[WIP]** Transpile Python 3.13 `.pyi` stubs to Python 3.10 stubs
    - [ ] Tooling for stub-only project integration
    - [ ] Use this in [`scipy-stubs`](https://github.com/jorenham/scipy-stubs)
    - [ ] Gradually introduce this into [`numpy`](https://github.com/numpy/numpy)
    - [ ]
2. Towards the future
    - [ ] Beyond Python: $\text{Unpy} \supset \text{Python}$
    - [ ] Language support & tooling for *all* `.py` projects
3. Towards each other
    - [ ] Unified typechecking: Fast, reasonable, and language-agnostic

## Roadmap

### Tooling

- Language support
    - [x] `.pyi` => `.pyi`
    - [ ] `.py` => `.py`
- Conversion
    - [x] stdin => stdout
    - [x] module => module
    - [ ] package => package
    - [ ] project => project (including the `pyproject.toml`)
- Configuration
    - [x] Unified diffs with `--diff`
    - [ ] Configuration options in `pyproject.toml` as `[tools.unpy]`
    - [ ] ...
- Integration
    - [ ] File watcher
    - [ ] Pre-commit
    - [ ] LSP
    - [ ] UV
    - [ ] VSCode extension
    - [ ] (based)mypy plugin
    - [ ] Project build tools
    - [ ] Configurable type-checker integration
    - [ ] Configurable formatter integration, e.g. `ruff format`
- Performance
    - [ ] Limit conversion to changed files

### Stub backporting

- Python 3.13 => 3.12
    - [x] [PEP 742][PEP742]: `typing.TypeIs` => `typing_extensions.TypeIs`
    - [x] [PEP 705][PEP705]: `typing.ReadOnly` => `typing_extensions.ReadOnly`
    - [x] [PEP 702][PEP702]: `warnings.deprecated` => `typing_extensions.deprecated`
    - [x] [PEP 696][PEP696]: Backport [PEP 695][PEP695] type signatures i.f.f. it
    includes a type parameter with default
    - [x] [PEP 696][PEP696]: `typing.NoDefault` => `typing_extensions.NoDefault`
    - [ ] `asyncio.QueueShutDown` => `builtins.Exception`
    - [ ] `pathlib.UnsupportedOperation` => `builtins.NotImplementedError`
    - [ ] `queue.ShutDown` => `builtins.Exception`
    - [ ] `re.PatternError` => `re.error`
    - [x] `types.CapsuleType` => `typing_extensions.CapsuleType`
    - [ ] `typing.{ClassVar,Final}` => `typing_extensions.{ClassVar,Final}` when nested
    (python/cpython#89547)
- Python 3.12 => 3.11
    - [x] [PEP 698][PEP698]: `typing.override` => `typing_extensions.override`
    - [x] [PEP 695][PEP695]: Backport `type _` aliases
    - [x] [PEP 695][PEP695]: Backport generic functions
    - [x] [PEP 695][PEP695]: Backport generic classes and protocols
    - [x] [PEP 695][PEP695]: `typing.TypeAliasType` => `typing_extensions.TypeAliasType`
    - [x] [PEP 688][PEP688]: `collections.abc.Buffer` => `typing_extensions.Buffer`
    - [ ] [PEP 688][PEP688]: `inspect.BufferFlags` => `int` (#57)
    - [ ] `calendar.Day` => `1 | ... | 6` and `calendar.Month` => `1 | 2 | ... | 12`
    - [ ] `csv.QUOTE_STRINGS` => `4` and `csv.QUOTE_NOTNULL` => `5`
    - [ ] Backport subclasses of `pathlib.{PurePath,Path}` (currently disallowed)
- Python 3.11 => 3.10
    - [x] [PEP 681][PEP681]: `typing.dataclass_transform` =>
    `typing_extensions.dataclass_transform`
    - [x] [PEP 675][PEP675]: `typing.LiteralString` => `typing_extensions.LiteralString`
    - [x] [PEP 673][PEP673]: `typing.Self` => `typing_extensions.Self`
    - [x] [PEP 655][PEP655]: `typing.[Not]Required` => `typing_extensions.[Not]Required`
    - [ ] [PEP 654][PEP654]: backport exception groups ([`exceptiongroup`][PEP654-IMPL])
    - [ ] [PEP 646][PEP646]: `*Ts` => `typing_extensions.Unpack[Ts]`
    - [ ] Remove `typing.Any` when used as base class
    - [ ] Backport new `enum` members: `StrEnum`, `EnumCheck`, `ReprEnum`,
    `FlagBoundary`, `property`, `member`, `nonmember`, `global_enum`, `show_flag_values`
    - [ ] Backport subclasses of `asyncio.TaskGroup`
- Generated `TypeVar`s
    - [ ] Prefix extracted `TypeVar`s names with `_`
    - [x] De-duplicate extracted typevar-likes with same name if equivalent
    - [ ] Rename extracted typevar-likes with same name if not equivalent
    - [ ] Infer variance of `typing_extensions.TypeVar(..., infer_variance=True)` whose
      name does not end with `{}_contra` (contravariant) or `{}_co` (covariant)

### Simplification and refactoring

- Type parameters
    - [x] Convert `default=Any` with `bound=T` to `default=T`
    - [x] Remove `bound=Any` and `bound=object`
- Annotations
    - [ ] Transform `self` parameters to be positional-only
    - [ ] Use `None` as the default return type
    - [ ] De-duplicate and flatten unions and literals
    - [ ] `type[S] | type[T]` => `type[S | T]`

### Beyond Python

- [ ] Bare `Literal`s (as implemented in [basedmypy][BMP-BARE])
- [ ] Type-mappings, which would remove the need for most overloads
- [ ] Intersection types (as implemented in [basedmypy][BMP-ISEC])
- [ ] Reusable method signature definitions
- [ ] Higher-kinded types (see python/typing#548)
- [ ] Inline callable types
- [ ] Annotating side-effects: exceptions, warnings, stdout, stderr, etc.
- [ ] Declarative operator overloading syntax
- [ ] Literal type unpacking

### Analysis

- [ ] Unified linting, type-checking, and stubtesting
- [ ] Error messages for humans
- [ ] ???

[PEP646]: https://peps.python.org/pep-0646/
[PEP654]: https://peps.python.org/pep-0654/
[PEP654-IMPL]: https://github.com/agronholm/exceptiongroup
[PEP655]: https://peps.python.org/pep-0655/
[PEP673]: https://peps.python.org/pep-0673/
[PEP675]: https://peps.python.org/pep-0675/
[PEP681]: https://peps.python.org/pep-0681/
[PEP688]: https://peps.python.org/pep-0688/
[PEP695]: https://peps.python.org/pep-0695/
[PEP696]: https://peps.python.org/pep-0696/
[PEP698]: https://peps.python.org/pep-0698/
[PEP702]: https://peps.python.org/pep-0702/
[PEP705]: https://peps.python.org/pep-0705/
[PEP742]: https://peps.python.org/pep-0705/
[BMP-BARE]: https://github.com/KotlinIsland/basedmypy#bare-literals
[BMP-ISEC]: https://github.com/KotlinIsland/basedmypy#intersection-types
