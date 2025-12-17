"""Tests for exception handling functionality."""

import pytest

from wt_task import TaskInstanceError, task


def test_task_instance_error_creation():
    """Test creating TaskInstanceError."""
    original_error = ValueError("Something went wrong")
    error = TaskInstanceError("task-1", original_error)

    assert error.task_instance_id == "task-1"
    assert error.exc is original_error
    assert str(error) == "Task instance 'task-1' raised ValueError('Something went wrong')"


def test_task_instance_error_with_different_exception_types():
    """Test TaskInstanceError with different exception types."""
    errors = [
        ValueError("value error"),
        TypeError("type error"),
        RuntimeError("runtime error"),
        KeyError("key error"),
    ]

    for exc in errors:
        error = TaskInstanceError("task-test", exc)
        assert error.task_instance_id == "task-test"
        assert error.exc is exc
        assert exc.__class__.__name__ in str(error)


def test_handle_errors_with_success():
    """Test handle_errors when function succeeds."""

    @task
    def divide(a: int, b: int) -> float:
        return a / b

    task_with_id = divide.set_task_instance_id("div-1")
    result = task_with_id.handle_errors().call(10, 2)
    assert result == 5.0


def test_handle_errors_with_failure():
    """Test handle_errors when function raises exception."""

    @task
    def divide(a: int, b: int) -> float:
        return a / b

    task_with_id = divide.set_task_instance_id("div-1")

    with pytest.raises(TaskInstanceError) as exc_info:
        task_with_id.handle_errors().call(10, 0)

    error = exc_info.value
    assert error.task_instance_id == "div-1"
    assert isinstance(error.exc, ZeroDivisionError)
    assert "Task instance 'div-1' raised ZeroDivisionError" in str(error)


def test_handle_errors_preserves_original_exception():
    """Test that handle_errors preserves original exception info."""

    @task
    def fail_with_message() -> None:
        raise ValueError("Custom error message")

    task_with_id = fail_with_message.set_task_instance_id("fail-1")

    with pytest.raises(TaskInstanceError) as exc_info:
        task_with_id.handle_errors().call()

    error = exc_info.value
    assert isinstance(error.exc, ValueError)
    assert str(error.exc) == "Custom error message"


def test_handle_errors_without_task_instance_id():
    """Test handle_errors warns when task_instance_id is not set."""

    @task
    def func() -> int:
        raise ValueError("error")

    with pytest.warns(UserWarning, match="Task instance ID is unset"):
        task_with_handler = func.handle_errors()

    with pytest.raises(TaskInstanceError) as exc_info:
        task_with_handler.call()

    # Task instance ID should be empty string
    assert exc_info.value.task_instance_id == ""


def test_handle_errors_chaining():
    """Test chaining handle_errors with other methods."""

    @task
    def multiply(x: int, factor: int) -> int:
        if x < 0:
            raise ValueError("x must be positive")
        return x * factor

    result = (
        multiply
        .partial(factor=2)
        .set_task_instance_id("mult-1")
        .handle_errors()
        .call(x=5)
    )
    assert result == 10

    with pytest.raises(TaskInstanceError) as exc_info:
        (
            multiply
            .partial(factor=2)
            .set_task_instance_id("mult-2")
            .handle_errors()
            .call(x=-5)
        )

    assert exc_info.value.task_instance_id == "mult-2"


def test_handle_errors_with_map():
    """Test handle_errors with map (errors should propagate)."""

    @task
    def inverse(x: int) -> float:
        return 1.0 / x

    task_with_handler = (
        inverse
        .set_task_instance_id("inv-1")
        .handle_errors()
    )

    # Successful map
    results = task_with_handler.map("x", [1, 2, 4])
    assert results == [1.0, 0.5, 0.25]

    # Map with error should raise
    with pytest.raises(TaskInstanceError):
        task_with_handler.map("x", [1, 0, 4])  # 0 will cause ZeroDivisionError


def test_exception_chain_preserved():
    """Test that exception chaining is preserved."""

    @task
    def func() -> None:
        raise ValueError("Original error")

    task_with_id = func.set_task_instance_id("test-1")

    with pytest.raises(TaskInstanceError) as exc_info:
        task_with_id.handle_errors().call()

    # Check that the exception chain is preserved
    assert exc_info.value.__cause__ is exc_info.value.exc
    assert isinstance(exc_info.value.__cause__, ValueError)
