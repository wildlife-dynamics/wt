#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "wt-registry",
# ]
# ///
"""Example: Pretty Output Format.

This example demonstrates the human-readable pretty output format,
showing how metadata like tags and descriptions are displayed.

Setup: uv sync

Run with: uv run python examples/cli_pretty_output.py
"""

from wt_registry import register


@register(
    title="Calculate Mean",
    description="Calculate the arithmetic mean of a list of numbers",
    tags=["statistics", "math", "analysis"],
)
def calculate_mean(values: list[float]) -> float:
    """Calculate and return the mean of the given values."""
    return sum(values) / len(values)


@register(
    title="Calculate Median",
    description="Calculate the median value of a sorted list of numbers",
    tags=["statistics", "math", "analysis"],
)
def calculate_median(values: list[float]) -> float:
    """Calculate and return the median of the given values."""
    sorted_values = sorted(values)
    n = len(sorted_values)
    mid = n // 2
    if n % 2 == 0:
        return (sorted_values[mid - 1] + sorted_values[mid]) / 2
    return sorted_values[mid]


@register(
    title="Format Currency",
    description="Format a number as a currency string with dollar sign and two decimal places",
    tags=["formatting", "display"],
)
def format_currency(amount: float) -> str:
    """Format amount as a currency string."""
    return f"${amount:.2f}"


if __name__ == "__main__":
    # Invoke CLI to show registered functions in pretty format
    import sys

    from wt_registry.cli import main

    sys.argv = ["example", "--format", "pretty"]
    main()
