<h1 align="center">pythoff</h1>

<p align="center">
    Backports Python 3.13 typing stubs to earlier Python versions
</p>

<p align="center">
    <a href="https://pypi.org/project/pythoff/">
        <img
            alt="pythoff - PyPI"
            src="https://img.shields.io/pypi/v/pythoff?style=flat&color=olive"
        />
    </a>
    <a href="https://github.com/jorenham/pythoff">
        <img
            alt="pythoff - Python Versions"
            src="https://img.shields.io/pypi/pyversions/pythoff?style=flat"
        />
    </a>
    <a href="https://github.com/jorenham/pythoff">
        <img
            alt="pythoff - license"
            src="https://img.shields.io/github/license/jorenham/pythoff?style=flat"
        />
    </a>
</p>
<p align="center">
    <a href="https://github.com/jorenham/pythoff/actions?query=workflow%3ACI">
        <img
            alt="pythoff - CI"
            src="https://github.com/jorenham/pythoff/workflows/CI/badge.svg"
        />
    </a>
    <!-- TODO -->
    <a href="https://github.com/pre-commit/pre-commit">
        <img
            alt="pythoff - pre-commit"
            src="https://img.shields.io/badge/pre--commit-enabled-teal?logo=pre-commit"
        />
    </a>
    <!-- <a href="https://github.com/KotlinIsland/basedmypy">
        <img
            alt="pythoff - basedmypy"
            src="https://img.shields.io/badge/basedmypy-checked-fd9002"
        />
    </a> -->
    <a href="https://detachhead.github.io/basedpyright">
        <img
            alt="pythoff - basedpyright"
            src="https://img.shields.io/badge/basedpyright-checked-42b983"
        />
    </a>
    <a href="https://github.com/astral-sh/ruff">
        <img
            alt="pythoff - ruff"
            src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json"
        />
    </a>
</p>

---

> ![IMPORTANT]
> This project is in the early stages of development;
> You probably shouldn't use it in production.
>
## Installation

The `pythoff` package is available as on PyPI, and can be installed with e.g.

```shell
pip install pythoff
```

## Usage

```plain
Usage: pythoff [OPTIONS] FILE_IN [FILE_OUT]

Arguments:
  FILE_IN     [required]
  [FILE_OUT]  [default: -]

Options:
  --install-completion [bash|zsh|fish|powershell|pwsh]
                                  Install completion for the specified shell.
  --show-completion [bash|zsh|fish|powershell|pwsh]
                                  Show completion for the specified shell, to
                                  copy it or customize the installation.
  --help
```

## Features / Wishlist

- [x] Remove redundant `Any` and `object` type-parameter bounds
- [x] Replace `Any` type-parameter defaults with the upper-bound or `object`
- [ ] Replace `collections.abc` and `typing` imports with `typing_extensions` backports.
- [x] Add additional `typing[_extensions]` imports for e.g. `TypeVar` and `TypeAlias`.
- [x] Backport PEP-695 `type {}` aliases to `{}: TypeAlias` (or use
`{} = TypeAliasType('{}', ...)`) if the LHS and RHS order differs).
- [x] Backport PEP-695 classes and protocols to `Generic` and `Protocol`
- [x] Backport PEP-695 generic functions
- [x] Transform PEP-696 `T = {}` type param defaults to `TypeVar("T", default={})`.
- [ ] Rename / de-duplicate typevar-like definitions
- [ ] Infer variance of (all) `Generic` and `Protocol` type params (currently
`infer_variance=True` is used if there's no `{}_co` or `{}_contra` suffix)
- [ ] Transform `*Ts` to `Unpack[Ts]` (`TypeVarTuple`)
- [x] Transform `**Tss` to `Tss` (`ParamSpec`)
- [ ] Reuse e.g. `import typing` or `import typing as tp` if present
- [ ] Detect re-exported imports from `typing` or `typing_extensions` of other modules
