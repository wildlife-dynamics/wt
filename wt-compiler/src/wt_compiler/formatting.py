"""Code formatting utilities using ruff."""

import functools
import subprocess
import sys
import tempfile
from collections.abc import Callable
from typing import Any

# Generated-code formatting is pinned so output is byte-for-byte reproducible
# regardless of where the compiler runs. Two ambient influences are neutralized:
#
# 1. Config discovery. Every ruff invocation passes ``--isolated`` (ignore any
#    ``pyproject.toml``/``ruff.toml`` found by walking up from the CWD) plus an
#    explicit line length, target version, and rule set. Without this, ruff
#    resolves config from the CWD, so the same spec compiled from different
#    directories produced different formatting (e.g. the reverse-integration
#    suite, whose config sets a different line length, silently rewrapped every
#    generated file).
#
# 2. isort first-party detection. ``--isolated`` ignores config *files* but ruff
#    still infers first-party modules from the filesystem around the CWD. If the
#    CWD (or its ``src/``) contains, say, a ``conftest.py``, ruff classifies the
#    generated ``from conftest import ...`` as first-party and splits it into its
#    own import group. The reverse-integration harness has exactly such a
#    ``src/conftest.py``, which drifted its recompiled output from the release
#    pipeline's. Running ruff from an empty neutral directory (``_NEUTRAL_CWD``)
#    removes any such filesystem signal.
#
# The values below match the generated package's declared environment
# (``requires-python = ">=3.10"``) and ruff's default line length.
_LINE_LENGTH = "88"
_TARGET_VERSION = "py310"

# Empty directory used as the CWD for every ruff subprocess so that ruff's
# filesystem-based first-party detection has nothing to latch onto. Kept for the
# process lifetime and removed at interpreter exit by the TemporaryDirectory
# finalizer. ``sys.executable -m ruff`` resolves the interpreter's ruff
# independent of CWD, so running from here is safe.
_neutral_cwd = tempfile.TemporaryDirectory(prefix="wt-compiler-ruff-")
_NEUTRAL_CWD = _neutral_cwd.name

# Rules applied to generated code, extending ruff's built-in defaults
# (``E4``/``E7``/``E9``/``F``). ``UP`` (pyupgrade) modernizes type syntax
# (``Optional[X]`` -> ``X | None``, ``typing.Coroutine`` -> ``collections.abc``)
# for the pinned target version; ``I`` sorts imports; ``B006`` flags mutable
# default arguments.
_EXTEND_SELECT = "B006,I,UP"


def ruff_formatted(returns_str_func: Callable[..., str]) -> Callable[..., str]:
    r"""Decorator to format the output of a function that returns a string with ruff.

    This decorator:
    1. Runs the wrapped function to get unformatted code
    2. Formats the code with `ruff format`
    3. Lints and fixes imports with `ruff check --fix`

    All ruff invocations run with `--isolated`, a pinned line length, target
    version, and rule set, and from an empty neutral working directory, so the
    formatted output depends on neither config discovered from the current
    working directory nor ruff's filesystem-based first-party detection.

    Args:
        returns_str_func: A function that returns a string of Python code

    Returns:
        A wrapped function that returns formatted Python code

    Examples:
        >>> @ruff_formatted
        ... def generate_code() -> str:
        ...     return "import os\\nimport sys\\n\\ndef foo():\\n    pass"
        >>> # code = generate_code()  # doctest: +SKIP
        >>> # "import os" in code  # doctest: +SKIP
        True
    """

    @functools.wraps(returns_str_func)
    def wrapper(*args: Any, **kwargs: Any) -> str:  # noqa: ANN401  # generic decorator passthrough
        unformatted = returns_str_func(*args, **kwargs)
        # Format with ruff
        # https://github.com/astral-sh/ruff/issues/8401#issuecomment-1788806462
        formatted = subprocess.check_output(  # noqa: S603  # cmd is a fixed ruff invocation
            [
                sys.executable,
                "-m",
                "ruff",
                "format",
                "--isolated",
                "--line-length",
                _LINE_LENGTH,
                "--target-version",
                _TARGET_VERSION,
                "-s",
                "-",
            ],
            input=unformatted,
            encoding="utf-8",
            cwd=_NEUTRAL_CWD,
        )
        # Lint and fix imports
        return subprocess.check_output(  # noqa: S603  # cmd is a fixed ruff invocation
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--fix",
                "--isolated",
                "--line-length",
                _LINE_LENGTH,
                "--target-version",
                _TARGET_VERSION,
                "--extend-select",
                _EXTEND_SELECT,
                "--exit-zero",
                "-s",
                "-",
            ],
            input=formatted,
            encoding="utf-8",
            cwd=_NEUTRAL_CWD,
        )

    return wrapper
