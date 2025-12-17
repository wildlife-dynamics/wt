"""Error handling utilities for task execution.

This module provides exception types and decorators for wrapping task errors
with additional context like task instance IDs.
"""

from functools import wraps
from typing import Any, Callable


class TaskInstanceError(Exception):
    """Exception raised when a task instance fails.

    This exception wraps the original exception and adds the task instance ID
    for better debugging context in workflow DAGs.

    Attributes:
        task_instance_id: Unique identifier for the task instance
        exc: Original exception that was raised

    Examples:
        >>> try:
        ...     raise ValueError("Something went wrong")
        ... except ValueError as e:
        ...     raise TaskInstanceError("task-1", e) from e
        Traceback (most recent call last):
        ...
        wt_task.exceptions.TaskInstanceError: Task instance 'task-1' raised ValueError('Something went wrong')
    """

    def __init__(self, task_instance_id: str, exc: Exception) -> None:
        """Initialize exception with task instance ID and original exception.

        Args:
            task_instance_id: Unique identifier for the task instance
            exc: Original exception that was raised
        """
        self.task_instance_id = task_instance_id
        self.exc = exc
        super().__init__(str(self))

    def __str__(self) -> str:
        """Return string representation of the error.

        Returns:
            Formatted error message with task instance ID and original exception
        """
        return (
            f"Task instance '{self.task_instance_id}' raised "
            f"{self.exc.__class__.__name__}('{self.exc}')"
        )


def handle_errors(func: Callable[..., Any], *, task_instance_id: str) -> Callable[..., Any]:
    """Wrap a function to catch exceptions and raise TaskInstanceError.

    For a given function, catch any exceptions and raise a TaskInstanceError
    including the given `task_instance_id`. In the context of executing a
    workflow DAG, in which every `@task` invocation has a unique
    `task_instance_id`, this ensures that any exceptions raised by a task
    are surfaced with the correct context for debugging.

    Args:
        func: Function to wrap
        task_instance_id: Unique identifier for this task instance

    Returns:
        Wrapped function that catches exceptions and adds task instance context

    Examples:
        >>> def f(a: int) -> int:
        ...     if not isinstance(a, int):
        ...         raise ValueError("a must be an int")
        ...     return a + 1
        >>> f(1)
        2
        >>> f("1")
        Traceback (most recent call last):
        ...
        ValueError: a must be an int
        >>> handle_errors(f, task_instance_id="task-1")(1)
        2
        >>> handle_errors(f, task_instance_id="task-1")("1")
        Traceback (most recent call last):
        ...
        wt_task.exceptions.TaskInstanceError: Task instance 'task-1' raised ValueError('a must be an int')
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            raise TaskInstanceError(task_instance_id, e) from e

    return wrapper
