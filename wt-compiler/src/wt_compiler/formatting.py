"""Code formatting utilities using ruff."""

import functools
import subprocess
import sys
from collections.abc import Callable
from typing import Any


def ruff_formatted(returns_str_func: Callable[..., str]) -> Callable[..., str]:
    """Decorator to format the output of a function that returns a string with ruff.

    This decorator:
    1. Runs the wrapped function to get unformatted code
    2. Formats the code with `ruff format`
    3. Lints and fixes imports with `ruff check --fix`

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
    def wrapper(*args: Any, **kwargs: Any) -> str:
        unformatted = returns_str_func(*args, **kwargs)
        # Format with ruff
        # https://github.com/astral-sh/ruff/issues/8401#issuecomment-1788806462
        formatted = subprocess.check_output(
            [sys.executable, "-m", "ruff", "format", "-s", "-"],
            input=unformatted,
            encoding="utf-8",
        )
        # Lint and fix imports
        linted = subprocess.check_output(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--fix",
                "--extend-select",
                "B006,I",
                "--exit-zero",
                "-s",
                "-",
            ],
            input=formatted,
            encoding="utf-8",
        )
        return linted

    return wrapper
