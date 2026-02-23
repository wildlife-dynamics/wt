"""Tests for mapvalues functionality."""

from wt_task import SKIP_SENTINEL, task


def test_mapvalues_single_arg():
    """Test mapvalues with a single argument."""

    @task
    def length(s: str) -> int:
        return len(s)

    results = length.mapvalues("s", [("a", "hello"), ("b", "world")])
    assert results == [("a", 5), ("b", 5)]


def test_mapvalues_preserves_keys():
    """Test that mapvalues preserves keys."""

    @task
    def square(x: int) -> int:
        return x * x

    results = square.mapvalues("x", [("one", 1), ("two", 2), ("three", 3)])
    assert results == [("one", 1), ("two", 4), ("three", 9)]


def test_mapvalues_with_partial():
    """Test mapvalues combined with partial."""

    @task
    def multiply(x: int, factor: int) -> int:
        return x * factor

    results = multiply.partial(factor=3).mapvalues("x", [("a", 2), ("b", 4)])
    assert results == [("a", 6), ("b", 12)]


def test_mapvalues_with_string_keys():
    """Test mapvalues with string keys."""

    @task
    def upper(s: str) -> str:
        return s.upper()

    results = upper.mapvalues("s", [("first", "hello"), ("second", "world")])
    assert results == [("first", "HELLO"), ("second", "WORLD")]


def test_mapvalues_with_int_keys():
    """Test mapvalues with integer keys."""

    @task
    def double(x: int) -> int:
        return x * 2

    results = double.mapvalues("x", [(1, 10), (2, 20), (3, 30)])
    assert results == [(1, 20), (2, 40), (3, 60)]


def test_mapvalues_empty_list():
    """Test mapvalues with empty list."""

    @task
    def process(x: int) -> int:
        return x * 2

    results = process.mapvalues("x", [])
    assert results == []


def test_mapvalues_with_skip_sentinel():
    """Test mapvalues with SkipSentinel."""

    @task
    def process(x: int) -> int:
        return x * 2

    results = process.mapvalues("x", SKIP_SENTINEL)
    assert len(results) == 1
    assert results[0][0] is None
    assert isinstance(results[0][1], type(SKIP_SENTINEL))


def test_mapvalues_preserves_order():
    """Test that mapvalues preserves input order."""

    @task
    def identity(x: int) -> int:
        return x

    inputs = [("e", 5), ("a", 1), ("d", 4), ("b", 2)]
    results = identity.mapvalues("x", inputs)
    assert results == [("e", 5), ("a", 1), ("d", 4), ("b", 2)]


def test_mapvalues_with_tuple_keys():
    """Test mapvalues with tuple keys."""

    @task
    def add(x: int) -> int:
        return x + 10

    results = add.mapvalues("x", [((1, 2), 5), ((3, 4), 6)])
    assert results == [((1, 2), 15), ((3, 4), 16)]


def test_mapvalues_with_complex_values():
    """Test mapvalues with complex value types."""

    @task
    def sum_list(items: list[int]) -> int:
        return sum(items)

    results = sum_list.mapvalues("items", [("a", [1, 2, 3]), ("b", [4, 5])])
    assert results == [("a", 6), ("b", 9)]


def test_mapvalues_multiple_args_with_partial():
    """Test mapvalues with multiple args where some are fixed via partial."""

    @task
    def weighted_sum(x: int, weight: float) -> float:
        return x * weight

    results = weighted_sum.partial(weight=1.5).mapvalues("x", [("a", 10), ("b", 20)])
    assert results == [("a", 15.0), ("b", 30.0)]


def test_mapvalues_with_defaults():
    """Test mapvalues with function having default values."""

    @task
    def greet(name: str, greeting: str = "Hello") -> str:
        return f"{greeting}, {name}!"

    results = greet.mapvalues("name", [("p1", "Alice"), ("p2", "Bob")])
    assert results == [("p1", "Hello, Alice!"), ("p2", "Hello, Bob!")]
