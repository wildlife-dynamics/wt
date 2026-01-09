"""Tests for map functionality."""

from wt_task import SKIP_SENTINEL, task


def test_map_single_arg():
    """Test mapping over a single argument."""

    @task
    def square(x: int) -> int:
        return x * x

    results = square.map("x", [1, 2, 3, 4])
    assert results == [1, 4, 9, 16]


def test_map_multiple_args():
    """Test mapping over multiple arguments with tuples."""

    @task
    def add(a: int, b: int) -> int:
        return a + b

    results = add.map(["a", "b"], [(1, 2), (3, 4), (5, 6)])
    assert results == [3, 7, 11]


def test_map_with_partial():
    """Test map combined with partial."""

    @task
    def multiply(a: int, b: int) -> int:
        return a * b

    results = multiply.partial(a=10).map("b", [1, 2, 3])
    assert results == [10, 20, 30]


def test_map_with_string_argname():
    """Test map with string argument name."""

    @task
    def double(x: int) -> int:
        return x * 2

    results = double.map("x", [5, 10, 15])
    assert results == [10, 20, 30]


def test_map_with_sequence_argnames():
    """Test map with sequence of argument names."""

    @task
    def concat(a: str, b: str) -> str:
        return a + b

    results = concat.map(["a", "b"], [("hello", " world"), ("foo", "bar")])
    assert results == ["hello world", "foobar"]


def test_map_with_defaults():
    """Test map with function having default values."""

    @task
    def greet(name: str, greeting: str = "Hello") -> str:
        return f"{greeting}, {name}!"

    results = greet.map("name", ["Alice", "Bob"])
    assert results == ["Hello, Alice!", "Hello, Bob!"]


def test_map_empty_list():
    """Test map with empty list."""

    @task
    def square(x: int) -> int:
        return x * x

    results = square.map("x", [])
    assert results == []


def test_map_with_skip_sentinel():
    """Test map with SkipSentinel."""

    @task
    def process(x: int) -> int:
        return x * 2

    results = process.map("x", SKIP_SENTINEL)
    assert len(results) == 1
    assert isinstance(results[0], type(SKIP_SENTINEL))


def test_map_preserves_order():
    """Test that map preserves input order."""

    @task
    def identity(x: int) -> int:
        return x

    inputs = [5, 1, 9, 3, 7]
    results = identity.map("x", inputs)
    assert results == inputs


def test_map_with_complex_types():
    """Test map with complex types."""

    @task
    def get_length(items: list[int]) -> int:
        return len(items)

    results = get_length.map("items", [[1, 2], [3, 4, 5], [6]])
    assert results == [2, 3, 1]


def test_map_three_args():
    """Test map with three arguments."""

    @task
    def add_three(a: int, b: int, c: int) -> int:
        return a + b + c

    results = add_three.map(["a", "b", "c"], [(1, 2, 3), (4, 5, 6)])
    assert results == [6, 15]


def test_map_with_partial_multiple_fixed():
    """Test map with multiple fixed arguments via partial."""

    @task
    def add_three(a: int, b: int, c: int) -> int:
        return a + b + c

    results = add_three.partial(a=1, b=2).map("c", [3, 4, 5])
    assert results == [6, 7, 8]
