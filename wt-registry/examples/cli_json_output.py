#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "wt-registry",
# ]
# ///
"""Example: JSON Output Format.

This example demonstrates how to output the registry as JSON,
which is useful for programmatic processing and integration.

Setup: uv sync

Run with: uv run python examples/cli_json_output.py
"""

from wt_registry import register


@register(
    title="Calculate Square",
    description="Calculate the square of a number",
    tags=["math"],
)
def square(n: int) -> int:
    """Calculate n squared."""
    return n * n


@register(
    title="Calculate Cube",
    description="Calculate the cube of a number",
    tags=["math"],
)
def cube(n: int) -> int:
    """Calculate n cubed."""
    return n * n * n


@register(
    title="Is Even",
    description="Check if a number is even",
    tags=["logic", "math"],
)
def is_even(n: int) -> bool:
    """Return True if n is even, False otherwise."""
    return n % 2 == 0


if __name__ == "__main__":
    # Invoke CLI to show registered functions in JSON format
    import sys

    from wt_registry.cli import main

    sys.argv = ["example", "--format", "json"]
    main()
