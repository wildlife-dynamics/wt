"""Simple tasks used in the Getting Started guide and tutorials."""

from wt_registry import register


@register(description="Add two integers.")
def add(a: int, b: int) -> int:
    return a + b


@register(description="Double a number.")
def double(n: int | float) -> int | float:
    return n * 2


@register(description="Split an integer into its individual digits as strings.")
def split_digits(n: int) -> list[str]:
    return list(str(abs(n)))


@register(description="Parse a string as an integer.")
def parse_int(s: str) -> int:
    return int(s)
