#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "wt-registry",
# ]
# ///
"""
Example: Functions from Multiple Modules

This example demonstrates how the registry works with functions
from different modules, showing fully qualified names (FQN).

Setup: uv sync

Run with: uv run python examples/multiple_modules.py
"""

import json

from wt_registry import register


# Simulate "utils" module functions
@register(
    title="Utils: Format Text",
    description="Format text with proper spacing and capitalization",
    tags=["utils", "formatting"],
)
def format_text(text: str) -> str:
    """Format text from utils module."""
    return " ".join(text.split()).capitalize()


@register(
    title="Utils: Parse JSON",
    description="Parse JSON string into Python dictionary",
    tags=["utils", "parsing"],
)
def parse_json(json_str: str) -> dict[str, any]:
    """Parse JSON from utils module."""
    return json.loads(json_str)


# Simulate "helpers" module functions
@register(
    title="Helpers: Format Text",
    description="Format text with HTML escaping (different from utils version)",
    tags=["helpers", "formatting"],
)
def format_text_safe(text: str) -> str:
    """Format text from helpers module - note same name but different module."""
    return text.replace("<", "&lt;").replace(">", "&gt;")


@register(
    title="Helpers: Build URL",
    description="Build a URL from components",
    tags=["helpers", "web"],
)
def build_url(base: str, path: str, params: dict[str, str] | None = None) -> str:
    """Build URL from helpers module."""
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{query}"
    return url


# Simulate "api" module functions
@register(
    title="API: Fetch Data",
    description="Fetch data from API endpoint",
    tags=["api", "http"],
)
def fetch_data(endpoint: str) -> dict[str, any]:
    """Fetch data from API."""
    # Simulated API call
    return {"status": "success", "endpoint": endpoint}


if __name__ == "__main__":
    import sys

    from wt_registry.cli import main

    print("=== All Functions (notice different fully qualified names) ===\n")
    sys.argv = ["example", "--format", "pretty"]
    main()

    print("\n\n=== Filter for functions named 'format_text' or 'format_text_safe' ===")
    print("(Shows how to work with functions that have similar names)\n")
    sys.argv = [
        "example",
        "--function",
        "format_text",
        "--function",
        "format_text_safe",
        "--format",
        "pretty",
    ]
    main()
