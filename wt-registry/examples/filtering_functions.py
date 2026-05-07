#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "wt-registry",
# ]
# ///
"""Example: Filtering Functions.

This example demonstrates how to filter the registry by function names,
showing only the functions you're interested in.

Setup: uv sync

Run with: uv run python examples/filtering_functions.py
"""

from wt_registry import register


@register(
    title="Validate Email",
    description="Check if a string is a valid email address",
    tags=["validation"],
)
def validate_email(email: str) -> bool:
    """Return True if email appears to be valid."""
    return "@" in email and "." in email


@register(
    title="Validate URL",
    description="Check if a string is a valid URL",
    tags=["validation"],
)
def validate_url(url: str) -> bool:
    """Return True if URL appears to be valid."""
    return url.startswith(("http://", "https://"))


@register(
    title="Validate Phone",
    description="Check if a string is a valid phone number",
    tags=["validation"],
)
def validate_phone(phone: str) -> bool:
    """Return True if phone number appears to be valid."""
    digits = "".join(c for c in phone if c.isdigit())
    return len(digits) >= 10


@register(
    title="Sanitize Input",
    description="Remove potentially dangerous characters from user input",
    tags=["security", "validation"],
)
def sanitize_input(text: str) -> str:
    """Remove HTML tags and special characters."""
    return "".join(c for c in text if c.isalnum() or c.isspace())


@register(
    title="Capitalize Words",
    description="Capitalize the first letter of each word",
    tags=["formatting"],
)
def capitalize_words(text: str) -> str:
    """Capitalize each word in the text."""
    return " ".join(word.capitalize() for word in text.split())


if __name__ == "__main__":
    import sys

    from wt_registry.cli import main

    print("=== All Functions ===")
    sys.argv = ["example", "--format", "pretty"]
    main()

    print("\n\n=== Filtering for 'validate_email' only ===")
    sys.argv = ["example", "--function", "validate_email", "--format", "pretty"]
    main()

    print("\n\n=== Filtering for multiple validation functions ===")
    sys.argv = [
        "example",
        "--function",
        "validate_email",
        "--function",
        "validate_url",
        "--format",
        "pretty",
    ]
    main()
