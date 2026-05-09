#!/usr/bin/env python3
"""Example: Basic Function Registration.

This example demonstrates how to register functions with wt-registry
and view them using the CLI.

Setup (one-time):
    uv sync

Run with:
    uv run python examples/basic_registration.py
"""

from wt_registry import register


@register(
    title="Add Two Numbers",
    description="Calculate the sum of two integers",
    tags=["math", "basic"],
)
def add(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b


@register(
    title="Multiply Two Numbers",
    description="Calculate the product of two integers",
    tags=["math", "basic"],
)
def multiply(x: int, y: int) -> int:
    """Multiply two integers and return the product."""
    return x * y


@register(
    title="Greet User",
    description="Generate a personalized greeting message",
)
def greet(name: str) -> str:
    """Generate a greeting for the given name."""
    return f"Hello, {name}!"


if __name__ == "__main__":
    # Invoke CLI to show registered functions in pretty format
    import sys

    from wt_registry.cli import main

    sys.argv = ["example", "--format", "pretty"]
    main()
