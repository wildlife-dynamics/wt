"""Tests for skip functionality."""

import pytest

from wt_task import SKIP_SENTINEL, SkipSentinel, task, unpack_listlike


def test_skip_sentinel_repr():
    """Test SkipSentinel string representation."""
    sentinel = SkipSentinel()
    assert repr(sentinel) == "<SkipSentinel>"
    assert repr(SKIP_SENTINEL) == "<SkipSentinel>"


def test_unpack_listlike_depth_0():
    """Test unpack_listlike with depth 0 (no unpacking)."""
    argvalues = [1, 2, [3, 4], (5, 6)]
    result = unpack_listlike(argvalues, 0)
    assert result == [1, 2, [3, 4], (5, 6)]


def test_unpack_listlike_depth_1():
    """Test unpack_listlike with depth 1."""
    argvalues = [1, 2, [3, 4], (5, 6)]
    result = unpack_listlike(argvalues, 1)
    assert result == [1, 2, 3, 4, 5, 6]


def test_unpack_listlike_depth_2():
    """Test unpack_listlike with nested structures at depth 2."""
    argvalues = [1, 2, [3, [4, 5]], (6, 7)]
    result = unpack_listlike(argvalues, 1)
    assert result == [1, 2, 3, [4, 5], 6, 7]

    result = unpack_listlike(argvalues, 2)
    assert result == [1, 2, 3, 4, 5, 6, 7]


def test_skipif_basic():
    """Test skipif with basic condition."""

    @task
    def process(x: int) -> int:
        return x * 2

    def is_negative(x: int) -> bool:
        return x < 0

    conditional_task = process.skipif([is_negative])

    # Positive number should execute
    result = conditional_task.call(5)
    assert result == 10

    # Negative number should skip
    result = conditional_task.call(-5)
    assert isinstance(result, SkipSentinel)


def test_skipif_multiple_conditions():
    """Test skipif with multiple conditions."""

    @task
    def process(x: int) -> int:
        return x * 2

    def is_negative(x: int) -> bool:
        return x < 0

    def is_zero(x: int) -> bool:
        return x == 0

    conditional_task = process.skipif([is_negative, is_zero])

    # Positive number should execute
    assert conditional_task.call(5) == 10

    # Negative should skip
    result = conditional_task.call(-5)
    assert isinstance(result, SkipSentinel)

    # Zero should skip
    result = conditional_task.call(0)
    assert isinstance(result, SkipSentinel)


def test_skipif_with_unpack_depth():
    """Test skipif with unpack_depth parameter."""

    @task
    def process(items: list[int]) -> int:
        return sum(items)

    def contains_negative(*args: int) -> bool:
        return any(x < 0 for x in args if isinstance(x, int))

    # With unpack_depth=0, list is not unpacked, so condition checks the list itself
    task_no_unpack = process.skipif([contains_negative], unpack_depth=0)
    result = task_no_unpack.call([1, -2, 3])
    # List object itself doesn't match, so it executes
    assert result == 2

    # With unpack_depth=1, list is unpacked before checking condition
    task_with_unpack = process.skipif([contains_negative], unpack_depth=1)
    result = task_with_unpack.call([1, -2, 3])
    # Now -2 is detected, so execution is skipped
    assert isinstance(result, SkipSentinel)


def test_skipif_preserves_function_info():
    """Test that skipif preserves function metadata."""

    @task
    def my_function(x: int) -> int:
        """My docstring."""
        return x * 2

    def always_false(*args) -> bool:  # type: ignore[no-untyped-def]
        return False

    conditional_task = my_function.skipif([always_false])
    # Function should still work and have same behavior when not skipped
    assert conditional_task.call(5) == 10


def test_skipif_with_kwargs():
    """Test skipif with keyword arguments."""

    @task
    def add(a: int, b: int) -> int:
        return a + b

    def any_negative(*args: int) -> bool:
        return any(x < 0 for x in args if isinstance(x, int))

    conditional_task = add.skipif([any_negative], unpack_depth=0)

    # Both positive
    assert conditional_task.call(a=5, b=10) == 15

    # One negative
    result = conditional_task.call(a=-5, b=10)
    assert isinstance(result, SkipSentinel)


def test_skipif_chaining():
    """Test chaining skipif with other operations."""

    @task
    def multiply(x: int, factor: int) -> int:
        return x * factor

    def is_negative(x: int) -> bool:
        return x < 0

    result = (
        multiply
        .partial(factor=2)
        .skipif([is_negative])
        .call(x=10)
    )
    assert result == 20

    result = (
        multiply
        .partial(factor=2)
        .skipif([is_negative])
        .call(x=-10)
    )
    assert isinstance(result, SkipSentinel)
