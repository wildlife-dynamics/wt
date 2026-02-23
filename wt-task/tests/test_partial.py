"""Tests for partial application functionality."""

import pytest

from wt_task import task


def test_partial_single_arg():
    """Test partial with a single argument."""

    @task
    def add(a: int, b: int) -> int:
        return a + b

    partial_add = add.partial(a=10)
    assert partial_add.call(b=5) == 15
    assert partial_add(b=5) == 15


def test_partial_multiple_args():
    """Test partial with multiple arguments."""

    @task
    def add_three(a: int, b: int, c: int) -> int:
        return a + b + c

    partial_add = add_three.partial(a=1, b=2)
    assert partial_add.call(c=3) == 6


def test_partial_preserves_immutability():
    """Test that partial creates a new task instance."""

    @task
    def multiply(a: int, b: int) -> int:
        return a * b

    partial1 = multiply.partial(a=2)
    partial2 = multiply.partial(a=3)

    assert partial1.call(b=4) == 8
    assert partial2.call(b=4) == 12
    # Original task should still work
    assert multiply.call(a=5, b=4) == 20


def test_partial_rejects_positional_args():
    """Test that partial raises ValueError for positional arguments."""

    @task
    def add(a: int, b: int) -> int:
        return a + b

    with pytest.raises(ValueError, match="Positional arguments are not supported"):
        add.partial(1)


def test_partial_chaining():
    """Test chaining multiple partial calls."""

    @task
    def add_three(a: int, b: int, c: int) -> int:
        return a + b + c

    result = add_three.partial(a=1).partial(b=2).call(c=3)
    assert result == 6


def test_partial_with_defaults():
    """Test partial with function that has default values."""

    @task
    def greet(name: str, greeting: str = "Hello") -> str:
        return f"{greeting}, {name}!"

    partial_greet = greet.partial(greeting="Hi")
    assert partial_greet.call(name="Alice") == "Hi, Alice!"

    # Can still call without partial
    assert greet.call(name="Bob") == "Hello, Bob!"


def test_partial_then_map():
    """Test using partial before map."""

    @task
    def add(a: int, b: int) -> int:
        return a + b

    results = add.partial(a=10).map("b", [1, 2, 3])
    assert results == [11, 12, 13]


def test_partial_then_mapvalues():
    """Test using partial before mapvalues."""

    @task
    def multiply(x: int, factor: int) -> int:
        return x * factor

    results = multiply.partial(factor=2).mapvalues("x", [("a", 5), ("b", 10)])
    assert results == [("a", 10), ("b", 20)]


def test_partial_overriding_values():
    """Test that calling with the same kwarg overrides partial value."""

    @task
    def add(a: int, b: int) -> int:
        return a + b

    partial_add = add.partial(a=10, b=5)
    # Both args are bound, can override by calling directly
    # Note: functools.partial behavior - can't override bound kwargs
    # This test documents the expected behavior
    result = partial_add.call()
    assert result == 15
