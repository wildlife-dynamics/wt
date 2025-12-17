"""Tests for Pydantic validation functionality."""

import pytest
from pydantic import ValidationError

from wt_task import task


def test_validate_parses_string_to_int():
    """Test validate parses string inputs to ints."""

    @task
    def add(a: int, b: int) -> int:
        return a + b

    # Without validation, strings are passed through
    result = add("1", "2")  # type: ignore[arg-type]
    assert result == "12"  # String concatenation

    # With validation, strings are parsed to ints
    result = add.validate().call("1", "2")  # type: ignore[arg-type]
    assert result == 3
    assert isinstance(result, int)


def test_validate_parses_string_to_float():
    """Test validate parses string inputs to floats."""

    @task
    def divide(a: float, b: float) -> float:
        return a / b

    result = divide.validate().call("10.0", "2.0")  # type: ignore[arg-type]
    assert result == 5.0
    assert isinstance(result, float)


def test_validate_with_complex_types():
    """Test validate with complex types like lists."""

    @task
    def sum_list(items: list[int]) -> int:
        return sum(items)

    # Pydantic doesn't automatically parse JSON strings to lists
    # Pass actual list instead
    result = sum_list.validate().call([1, 2, 3])
    assert result == 6


def test_validate_raises_on_invalid_input():
    """Test validate raises ValidationError for invalid input."""

    @task
    def add(a: int, b: int) -> int:
        return a + b

    validated_task = add.validate()

    with pytest.raises(ValidationError):
        validated_task.call("not_a_number", "2")  # type: ignore[arg-type]


def test_validate_with_defaults():
    """Test validate with default parameter values."""

    @task
    def greet(name: str, greeting: str = "Hello") -> str:
        return f"{greeting}, {name}!"

    result = greet.validate().call(name="Alice")
    assert result == "Hello, Alice!"


def test_validate_with_partial():
    """Test validate combined with partial."""

    @task
    def multiply(a: int, b: int) -> int:
        return a * b

    result = multiply.validate().partial(a="10").call(b="2")  # type: ignore[arg-type]
    assert result == 20


def test_validate_with_map():
    """Test validate combined with map."""

    @task
    def square(x: int) -> int:
        return x * x

    results = square.validate().map("x", ["1", "2", "3"])  # type: ignore[list-item]
    assert results == [1, 4, 9]


def test_validate_with_mapvalues():
    """Test validate combined with mapvalues."""

    @task
    def double(x: int) -> int:
        return x * 2

    results = double.validate().mapvalues("x", [("a", "5"), ("b", "10")])  # type: ignore[list-item]
    assert results == [("a", 10), ("b", 20)]


def test_validate_return_value():
    """Test that validate also validates return values."""

    @task
    def get_value() -> int:
        return "not an int"  # type: ignore[return-value]

    with pytest.raises(ValidationError):
        get_value.validate().call()


def test_validate_preserves_none():
    """Test validate correctly handles None values."""

    @task
    def maybe_add(a: int, b: int | None = None) -> int:
        if b is None:
            return a
        return a + b

    result = maybe_add.validate().call(a=5)
    assert result == 5

    result = maybe_add.validate().call(a=5, b=3)
    assert result == 8


def test_validate_with_bool():
    """Test validate with boolean types."""

    @task
    def negate(value: bool) -> bool:
        return not value

    # String "true" should be parsed to True
    result = negate.validate().call("true")  # type: ignore[arg-type]
    assert result is False

    # String "false" should be parsed to False
    result = negate.validate().call("false")  # type: ignore[arg-type]
    assert result is True


def test_validate_chaining():
    """Test chaining validate with other methods."""

    @task
    def add_three(a: int, b: int, c: int) -> int:
        return a + b + c

    # Need to validate first, then partial with strings
    result = (
        add_three
        .validate()
        .partial(a="1", b="2")  # type: ignore[arg-type]
        .call(c="3")  # type: ignore[arg-type]
    )
    assert result == 6


def test_validate_idempotent():
    """Test that calling validate multiple times is safe."""

    @task
    def add(a: int, b: int) -> int:
        return a + b

    result = add.validate().validate().call("1", "2")  # type: ignore[arg-type]
    assert result == 3
