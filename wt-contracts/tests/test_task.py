"""Tests for task protocol."""

from collections.abc import Callable, Sequence
from typing import Any

from wt_contracts.task import TaskProtocol


class MockSyncTask:
    """Mock implementation of TaskProtocol for testing.

    This demonstrates that a class implementing the required methods
    satisfies the TaskProtocol.
    """

    def __init__(self, func: Callable[..., Any]) -> None:
        self.func = func
        self.bound_kwargs: dict[str, Any] = {}

    def partial(self, **kwargs: Any) -> "MockSyncTask":
        """Bind keyword arguments."""
        new_task = MockSyncTask(self.func)
        new_task.bound_kwargs = {**self.bound_kwargs, **kwargs}
        return new_task

    def call(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the function."""
        all_kwargs = {**self.bound_kwargs, **kwargs}
        return self.func(*args, **all_kwargs)

    def map(self, argname: str, argvalues: Sequence[Any], **kwargs: Any) -> Sequence[Any]:
        """Map over a sequence of values."""
        results = []
        for value in argvalues:
            all_kwargs = {**self.bound_kwargs, **kwargs, argname: value}
            results.append(self.func(**all_kwargs))
        return results

    def mapvalues(
        self, argname: str, argvalues: Sequence[tuple[Any, Any]], **kwargs: Any
    ) -> Sequence[tuple[Any, Any]]:
        """Map over key-value pairs."""
        results = []
        for key, value in argvalues:
            all_kwargs = {**self.bound_kwargs, **kwargs, argname: value}
            result = self.func(**all_kwargs)
            results.append((key, result))
        return results

    def validate(self) -> "MockSyncTask":
        """Validate configuration."""
        # Mock validation - just return self
        return self

    def skipif(self, condition: Callable[..., bool]) -> "MockSyncTask":
        """Add skip condition."""
        # Mock skipif - just return self
        return self

    def set_executor(self, executor: Any) -> "MockSyncTask":
        """Set executor."""
        # Mock executor setting - just return self
        return self


def test_mock_task_conforms_to_protocol() -> None:
    """Test that MockSyncTask conforms to TaskProtocol."""

    def add(x: int, y: int) -> int:
        return x + y

    task: TaskProtocol[..., int] = MockSyncTask(add)

    # Test that we can call protocol methods
    result = task.call(x=1, y=2)
    assert result == 3


def test_protocol_partial() -> None:
    """Test partial application through protocol."""

    def multiply(x: int, y: int) -> int:
        return x * y

    task: TaskProtocol[..., int] = MockSyncTask(multiply)

    # Apply partial
    partial_task = task.partial(y=3)
    result = partial_task.call(x=4)

    assert result == 12


def test_protocol_map() -> None:
    """Test map through protocol."""

    def square(x: int) -> int:
        return x * x

    task: TaskProtocol[..., int] = MockSyncTask(square)

    # Map over values
    results = task.map("x", [1, 2, 3, 4])

    assert results == [1, 4, 9, 16]


def test_protocol_map_with_fixed_args() -> None:
    """Test map with additional fixed arguments."""

    def power(x: int, n: int) -> int:
        return x**n

    task: TaskProtocol[..., int] = MockSyncTask(power)

    # Map over x with fixed n=3
    results = task.map("x", [2, 3, 4], n=3)

    assert results == [8, 27, 64]


def test_protocol_mapvalues() -> None:
    """Test mapvalues preserves keys."""

    def double(x: int) -> int:
        return x * 2

    task: TaskProtocol[..., int] = MockSyncTask(double)

    # Map over key-value pairs
    input_pairs = [("a", 1), ("b", 2), ("c", 3)]
    results = task.mapvalues("x", input_pairs)

    assert results == [("a", 2), ("b", 4), ("c", 6)]


def test_protocol_validate() -> None:
    """Test validate returns self for chaining."""

    def identity(x: int) -> int:
        return x

    task: TaskProtocol[..., int] = MockSyncTask(identity)

    validated_task = task.validate()

    # Should return self for chaining
    assert isinstance(validated_task, MockSyncTask)

    # Should still work
    result = validated_task.call(x=42)
    assert result == 42


def test_protocol_skipif() -> None:
    """Test skipif returns self for chaining."""

    def process(x: int) -> int:
        return x + 1

    task: TaskProtocol[..., int] = MockSyncTask(process)

    conditional_task = task.skipif(lambda: False)

    # Should return self for chaining
    assert isinstance(conditional_task, MockSyncTask)

    # Should still work
    result = conditional_task.call(x=10)
    assert result == 11


def test_protocol_set_executor() -> None:
    """Test set_executor returns self for chaining."""

    def compute(x: int) -> int:
        return x * 2

    task: TaskProtocol[..., int] = MockSyncTask(compute)

    # Mock executor
    executor = object()
    task_with_executor = task.set_executor(executor)

    # Should return self for chaining
    assert isinstance(task_with_executor, MockSyncTask)

    # Should still work
    result = task_with_executor.call(x=5)
    assert result == 10


def test_protocol_method_chaining() -> None:
    """Test chaining multiple protocol methods."""

    def calculate(x: int, y: int) -> int:
        return x + y

    task: TaskProtocol[..., int] = MockSyncTask(calculate)

    # Chain multiple methods
    result = task.partial(y=10).validate().call(x=5)

    assert result == 15


def test_protocol_with_different_types() -> None:
    """Test protocol works with different type parameters."""

    # String function
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    str_task: TaskProtocol[..., str] = MockSyncTask(greet)
    greeting = str_task.call(name="Alice")
    assert greeting == "Hello, Alice!"

    # Float function
    def divide(x: float, y: float) -> float:
        return x / y

    float_task: TaskProtocol[..., float] = MockSyncTask(divide)
    quotient = float_task.call(x=10.0, y=2.0)
    assert quotient == 5.0


class NonConformingTask:
    """A class that doesn't implement all required methods."""

    def partial(self, **kwargs: Any) -> "NonConformingTask":
        return self

    # Missing other required methods


def test_protocol_structural_typing() -> None:
    """Test that protocol uses structural typing, not nominal."""

    # MockSyncTask should satisfy protocol without explicit inheritance
    def func(x: int) -> int:
        return x

    task = MockSyncTask(func)

    # This should type-check (mypy would verify)
    def use_task(t: TaskProtocol[..., int]) -> int:
        return t.call(x=42)

    result = use_task(task)
    assert result == 42


def test_protocol_covariance() -> None:
    """Test that return type is covariant."""

    # A task returning int can be used where TaskProtocol[..., int] is expected
    def get_number() -> int:
        return 42

    task: TaskProtocol[[], int] = MockSyncTask(get_number)
    result = task.call()
    assert result == 42
