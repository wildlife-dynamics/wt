"""Code formatting utilities using ruff."""

import functools
import subprocess
import sys
import tempfile
from collections.abc import Callable
from typing import Any

# Generated code must format identically wherever the compiler runs, which takes
# two guards. ``--isolated`` plus the explicit values below stop ruff resolving
# config from the CWD; the reverse-integration suite's line length was silently
# rewrapping every generated file. ``--isolated`` doesn't stop isort inferring
# first-party modules from the filesystem, so ruff also runs from an empty
# directory (``_NEUTRAL_CWD``): a nearby ``conftest.py`` otherwise splits the
# generated ``from conftest import ...`` into its own import group, which is what
# drifted that same harness.
#
# py310 matches the generated package's ``requires-python``; 88 is ruff's default.
_LINE_LENGTH = "88"
_TARGET_VERSION = "py310"

# Empty directory used as the CWD for every ruff subprocess so that ruff's
# filesystem-based first-party detection has nothing to latch onto. Kept for the
# process lifetime and removed at interpreter exit by the TemporaryDirectory
# finalizer. ``sys.executable -m ruff`` resolves the interpreter's ruff
# independent of CWD, so running from here is safe.
_neutral_cwd = tempfile.TemporaryDirectory(prefix="wt-compiler-ruff-")
_NEUTRAL_CWD = _neutral_cwd.name

# Added on top of ruff's defaults, which generated code rides as-is. Those are wide as
# of 0.16 (~400 rules), so the exact ``ruff==0.16.6`` pin in pyproject.toml -- not this
# string -- is what holds generated output still; of the three, only ``I`` is additive.
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
