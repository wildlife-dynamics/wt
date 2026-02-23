"""Tests for executor functionality."""

import pytest

from wt_task import PythonExecutor, task
from wt_task.executors import SyncExecutor


def test_python_executor_call():
    """Test PythonExecutor.call method."""
    executor = PythonExecutor()

    def add(a: int, b: int) -> int:
        return a + b

    result = executor.call(add, 5, 10)
    assert result == 15


def test_python_executor_map():
    """Test PythonExecutor.map method."""
    executor = PythonExecutor()

    def square(x: int) -> int:
        return x * x

    inputs = [{"x": 1}, {"x": 2}, {"x": 3}]
    results = executor.map(lambda kw: square(**kw), inputs)
    assert results == [1, 4, 9]


def test_task_default_executor_is_python():
    """Test that tasks use PythonExecutor by default."""

    @task
    def func(x: int) -> int:
        return x * 2

    assert isinstance(func.executor, PythonExecutor)


def test_set_executor_python():
    """Test set_executor with 'python' string."""

    @task
    def func(x: int) -> int:
        return x * 2

    new_task = func.set_executor("python")
    assert isinstance(new_task.executor, PythonExecutor)
    assert new_task.call(5) == 10


def test_set_executor_with_instance():
    """Test set_executor with executor instance."""

    @task
    def func(x: int) -> int:
        return x * 2

    custom_executor = PythonExecutor()
    new_task = func.set_executor(custom_executor)
    assert new_task.executor is custom_executor
    assert new_task.call(5) == 10


def test_set_executor_invalid():
    """Test set_executor with invalid input."""

    @task
    def func(x: int) -> int:
        return x * 2

    with pytest.raises(ValueError, match="Executor must be"):
        func.set_executor("invalid")  # type: ignore[arg-type]


def test_executor_with_map():
    """Test that executor is used in map operations."""

    @task
    def square(x: int) -> int:
        return x * x

    results = square.map("x", [1, 2, 3, 4])
    assert results == [1, 4, 9, 16]


def test_executor_with_mapvalues():
    """Test that executor is used in mapvalues operations."""

    @task
    def double(x: int) -> int:
        return x * 2

    results = double.mapvalues("x", [("a", 1), ("b", 2)])
    assert results == [("a", 2), ("b", 4)]


def test_executor_preserved_with_partial():
    """Test that executor is preserved when using partial."""

    @task
    def add(a: int, b: int) -> int:
        return a + b

    original_executor = add.executor
    partial_task = add.partial(a=10)

    assert isinstance(partial_task.executor, type(original_executor))


def test_executor_preserved_with_validate():
    """Test that executor is preserved when using validate."""

    @task
    def add(a: int, b: int) -> int:
        return a + b

    original_executor = add.executor
    validated_task = add.validate()

    assert isinstance(validated_task.executor, type(original_executor))


def test_custom_executor_implementation():
    """Test with a custom executor implementation."""

    class CountingExecutor(SyncExecutor):  # type: ignore[type-arg]
        def __init__(self):  # type: ignore[no-untyped-def]
            self.call_count = 0
            self.map_count = 0

        def call(self, func, *args, **kwargs):  # type: ignore[no-untyped-def]
            self.call_count += 1
            return func(*args, **kwargs)

        def map(self, func, iterable):  # type: ignore[no-untyped-def]
            self.map_count += 1
            return list(map(func, iterable))

    @task
    def square(x: int) -> int:
        return x * x

    counter = CountingExecutor()
    counting_task = square.set_executor(counter)

    # Test call
    counting_task.call(5)
    assert counter.call_count == 1

    # Test map
    counting_task.map("x", [1, 2, 3])
    assert counter.map_count == 1
