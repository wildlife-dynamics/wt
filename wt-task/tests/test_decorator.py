"""Tests for the task decorator."""

import pytest

from wt_task import SyncTask, task


def test_task_decorator_without_args():
    """Test @task decorator without arguments."""

    @task
    def add(a: int, b: int) -> int:
        return a + b

    assert isinstance(add, SyncTask)
    assert add(1, 2) == 3
    assert add.call(1, 2) == 3


def test_task_decorator_with_args():
    """Test @task decorator with arguments."""

    @task(description="Add two numbers", tags=["math", "arithmetic"])
    def add(a: int, b: int) -> int:
        return a + b

    assert isinstance(add, SyncTask)
    assert add.description == "Add two numbers"
    assert add.tags == ["math", "arithmetic"]
    assert add(1, 2) == 3


def test_task_as_wrapper():
    """Test task as wrapper function (used in generated code)."""

    def multiply(a: int, b: int) -> int:
        return a * b

    wrapped = task(multiply)
    assert isinstance(wrapped, SyncTask)
    assert wrapped(2, 3) == 6


def test_task_with_no_args_has_empty_tags():
    """Test that task without tags has empty list."""

    @task
    def func() -> int:
        return 42

    assert func.tags == []
    assert func.description is None


def test_task_with_only_description():
    """Test task with only description."""

    @task(description="Test function")
    def func() -> int:
        return 42

    assert func.description == "Test function"
    assert func.tags == []


def test_task_with_only_tags():
    """Test task with only tags."""

    @task(tags=["test"])
    def func() -> int:
        return 42

    assert func.tags == ["test"]
    assert func.description is None


def test_task_instance_id_initially_none():
    """Test that task_instance_id is initially None."""

    @task
    def func() -> int:
        return 42

    assert func.task_instance_id is None


def test_set_task_instance_id():
    """Test setting task_instance_id."""

    @task
    def func() -> int:
        return 42

    task_with_id = func.set_task_instance_id("task-1")
    assert task_with_id.task_instance_id == "task-1"
    assert func.task_instance_id is None  # Original unchanged


def test_task_preserves_function_behavior():
    """Test that task preserves the function's behavior."""

    @task
    def complex_func(x: int, y: int = 10) -> int:
        """A function with default args."""
        return x + y

    assert complex_func(5) == 15
    assert complex_func(5, 20) == 25
    assert complex_func.call(x=5, y=20) == 25
