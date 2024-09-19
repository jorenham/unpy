<!-- omit in toc -->
# Contributing to `unpy`

First off, thanks for taking the time to contribute! :heart:

All types of contributions are encouraged and valued.
Please make sure to read the relevant section before making your contribution.
It will make it a lot easier for us maintainers and smooth out the experience for all
involved.
The community looks forward to your contributions. :tada:

> [!NOTE]
> And if you like `unpy`, but just don't have time to contribute, that's fine.
> There are other easy ways to support the project and show your appreciation, which we
> would also be very happy about:
>
> - Star the project
> - Share it on social media
> - Refer this project in your project's readme
> - Mention the project at local meetups and tell your friends and colleagues

## I Have a Question

> [!NOTE]
> If you want to ask a question, we assume that you have read the available
> [documentation][DOC].

Before you ask a question, it is best to search for existing [Issues][BUG] that might
help you.
In case you have found a suitable issue and still need clarification, you can write
your question in this issue.
It is also advisable to search the internet for answers first.

If you then still feel the need to ask a question and need clarification, we
recommend the following:

- Open an [Issue][BUG].
- Provide as much context as you can about what you're running into.
- Provide project and platform versions (Python, pyright, ruff, etc), depending on what
seems relevant.

We will then take care of the issue as soon as possible.

## I Want To Contribute

> ### Legal Notice <!-- omit in toc -->
>
> When contributing to this project,
> you must agree that you have authored 100% of the content,
> that you have the necessary rights to the content and that the content you
> contribute may be provided under the project license.

### Reporting Bugs

<!-- omit in toc -->
#### Before Submitting a Bug Report

A good bug report shouldn't leave others needing to chase you up for more information.
Therefore, we ask you to investigate carefully, collect information and describe the
issue in detail in your report.
Please complete the following steps in advance to help us fix any potential bug as fast
as possible.

- Make sure that you are using the latest version.
- Determine if your bug is really a bug and not an error on your side e.g. using
- incompatible environment components/versions (Make sure that you have read the
[docs][DOC]. If you are looking for support, you might want to check
[this section](#i-have-a-question)).
- To see if other users have experienced (and potentially already solved) the same
issue you are having, check if there is not already a bug report existing for your bug
or error in the [bug tracker][BUG].
- Also make sure to search the internet (including Stack Overflow) to see if users
outside of the GitHub community have discussed the issue.
- Collect information about the bug:
    - Stack trace (Traceback)
    - OS, Platform and Version (Windows, Linux, macOS, x86, ARM)
    - Version of the project and platform, (Python, pyright, ruff, etc), depending on
    what seems relevant.
    - Possibly your input and the output
    - Can you reliably reproduce the issue?

<!-- omit in toc -->
#### How Do I Submit a Good Bug Report?

> You must never report security related issues, vulnerabilities or bugs including
sensitive information to the issue tracker, or elsewhere in public.
Instead sensitive bugs must be sent by email to `jhammudoglu<at>gmail<dot>com`.

We use GitHub issues to track bugs and errors.
If you run into an issue with the project:

- Open an [Issue][BUG].
(Since we can't be sure at this point whether it is a bug or not, we ask you not to
talk about a bug yet and not to label the issue.)
- Explain the behavior you would expect and the actual behavior.
- Please provide as much context as possible and describe the
*reproduction steps* that someone else can follow to recreate the issue on their own.
This usually includes your code.
For good bug reports you should isolate the problem and create a reduced test case.
- Provide the information you collected in the previous section.

### Suggesting Enhancements

This section guides you through submitting an enhancement suggestion for
`unpy`, **including completely new features and minor improvements to existing
functionality**.
Following these guidelines will help maintainers and the community to
understand your suggestion and find related suggestions.

<!-- omit in toc -->
#### Before Submitting an Enhancement

- Make sure that you are using the latest version.
- Read the [documentation][DOC] carefully and find out if the functionality is
already covered, maybe by an individual configuration.
- Perform a [search][BUG] to see if the enhancement has already been suggested.
If it has, add a comment to the existing issue instead of opening a new one.
- Find out whether your idea fits with the scope and aims of the project.
It's up to you to make a strong case to convince the project's developers of
the merits of this feature. Keep in mind that we want features that will be
useful to the majority of our users and not just a small subset. If you're
just targeting a minority of users, consider writing an add-on/plugin library.

<!-- omit in toc -->
#### How Do I Submit a Good Enhancement Suggestion?

Enhancement suggestions are tracked as [GitHub issues][BUG].

- Use a **clear and descriptive title** for the issue to identify the suggestion.
- Provide a **step-by-step description of the suggested enhancement** in as many details
as possible.
- **Describe the current behavior** and
**explain which behavior you expected to see instead** and why.
At this point you can also tell which alternatives don't work for you.
- **Explain why this enhancement would be useful** to most `unpy` users.
You may also want to point out the other projects that solved it better and which could
serve as inspiration.

### Your First Code Contribution

Ensure you have [uv](https://github.com/astral-sh/uv) installed.
You can install it with

```shell
uv sync
```

### Testing

`unpy` uses [pytest](https://docs.pytest.org/en/stable/) for unit testing.
These tests can be run with

```shell
uv run pytest
```

### pre-commit

`unpy` uses [pre-commit](https://pre-commit.com/) to ensure that the code is
formatted and typed correctly when committing the changes.
You can install it with

```shell
uv run pre-commit install
```

> [!NOTE]
> Pre-commit doesn't run the tests. This will be run by github actions when
> submitting a pull request. See the next section for more details.

### tox

You can use [tox][TOX] to run all pre-commit hooks and tests on multiple environments
in parallel with

```shell
uv run tox -p all
```

This way you don't have to wait on the CI to report any linter errors or failed tests.
:zap:

### Improving The Documentation

All [documentation] lives in the `README.md`. Please read it carefully before proposing
any changes. Ensure that the markdown is formatted correctly with
[markdownlint][MDLINT].

This guide is based on the **contributing-gen**.
[Make your own](https://github.com/bttger/contributing-gen)!

[BUG]: https://github.com/jorenham/unpy/issues
[DOC]: https://github.com/jorenham/unpy#unpy
[TOX]: https://github.com/tox-dev/tox
[MDLINT]: https://github.com/DavidAnson/markdownlint/
