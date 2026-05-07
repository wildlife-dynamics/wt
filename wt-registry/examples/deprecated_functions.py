#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "wt-registry",
# ]
# ///
"""Example: Deprecated Functions.

This example demonstrates how to mark functions as deprecated
and provide migration messages to users.

Setup: uv sync

Run with: uv run python examples/deprecated_functions.py
"""

from wt_registry import register


@register(
    title="Process Data V2",
    description="Process data using the new optimized algorithm",
    tags=["processing"],
)
def process_data_v2(data: list[int]) -> list[int]:
    """Process data with improved performance."""
    return [x * 2 for x in data if x > 0]


@register(
    title="Process Data (Old)",
    description="Legacy data processing function",
    tags=["processing"],
    deprecated=True,
    deprecation_message="Use process_data_v2() instead for better performance",
)
def process_data(data: list[int]) -> list[int]:
    """Old data processing function - deprecated."""
    return [x * 2 for x in data]


@register(
    title="Calculate Total V2",
    description="Calculate total with tax and shipping",
    tags=["calculation"],
)
def calculate_total_v2(subtotal: float, tax_rate: float, shipping: float) -> float:
    """Calculate total including tax and shipping."""
    return subtotal * (1 + tax_rate) + shipping


@register(
    title="Calculate Total (Legacy)",
    description="Legacy total calculation - does not include shipping",
    tags=["calculation"],
    deprecated=True,
    deprecation_message="Use calculate_total_v2() which includes shipping costs",
)
def calculate_total(subtotal: float, tax_rate: float) -> float:
    """Old calculate total - deprecated."""
    return subtotal * (1 + tax_rate)


@register(
    title="Send Email V2",
    description="Send email with HTML support and attachments",
    tags=["communication"],
)
def send_email_v2(to: str, subject: str, body: str, html: bool = False) -> bool:
    """Send email with modern features."""
    # Implementation would go here
    return True


@register(
    title="Send Email (Deprecated)",
    description="Legacy email sending function - text only",
    deprecated=True,
    deprecation_message="Use send_email_v2() for HTML support and better reliability",
)
def send_email(to: str, subject: str, body: str) -> bool:
    """Old email function - deprecated."""
    # Implementation would go here
    return True


if __name__ == "__main__":
    import sys

    from wt_registry.cli import main

    print("Notice how deprecated functions are clearly marked:\n")
    sys.argv = ["example", "--format", "pretty"]
    main()
