"""Task decorator and wrapper function.

This module provides the `task` function which works both as a decorator and
as a wrapper function for creating SyncTask instances.
"""

from typing import Callable, ParamSpec, TypeVar, overload

from .sync_task import SyncTask

P = ParamSpec("P")
R = TypeVar("R")
K = TypeVar("K")
V = TypeVar("V")


@overload  # @task style (no parentheses)
def task(
    func: Callable[P, R],
    *,
    tags: list[str] | None = None,
    description: str | None = None,
) -> SyncTask[P, R, K, V]: ...


@overload  # @task(...) style (with parentheses)
def task(
    *,
    tags: list[str] | None = None,
    description: str | None = None,
) -> Callable[[Callable[P, R]], SyncTask[P, R, K, V]]: ...


def task(
    func: Callable[P, R] | None = None,
    *,
    description: str | None = None,
    tags: list[str] | None = None,
) -> Callable[[Callable[P, R]], SyncTask[P, R, K, V]] | SyncTask[P, R, K, V]:
    """Decorator and wrapper for task functions.

    This function serves dual purposes:
    1. As a decorator: @task or @task(description="...", tags=[...])
    2. As a wrapper: task(registered_func) in generated code

    The decorator creates a SyncTask instance that wraps the function and
    provides execution methods (call, map, mapvalues) and transformation
    methods (partial, validate, with_tracing, etc.).

    Args:
        func: Function to wrap (None when used as @task(...) with parentheses)
        description: Optional description of the task
        tags: Optional list of tags for categorization

    Returns:
        Either a SyncTask (when func is provided) or a decorator function
        (when func is None)

    Examples:
        Usage as decorator without parentheses:

        >>> @task
        ... def add(a: int, b: int) -> int:
        ...     return a + b
        >>> add(1, 2)
        3
        >>> add.call(1, 2)
        3

        Usage as decorator with parentheses:

        >>> @task(description="Multiply two numbers", tags=["math"])
        ... def multiply(a: int, b: int) -> int:
        ...     return a * b
        >>> multiply(2, 3)
        6

        Usage as wrapper (in generated code):

        >>> def registered_func(x: int) -> int:
        ...     return x * 2
        >>> task(registered_func).partial(x=5).call()
        10

        Method chaining:

        >>> @task
        ... def divide(a: int, b: int) -> float:
        ...     return a / b
        >>> result = (
        ...     divide
        ...     .partial(b=2)
        ...     .validate()
        ...     .set_task_instance_id("div-1")
        ...     .handle_errors()
        ...     .call(a=10)
        ... )
        >>> result
        5.0
    """

    def wrapper(
        func: Callable[P, R],
    ) -> SyncTask[P, R, K, V]:
        return SyncTask(
            func,
            tags=tags or [],
            description=description,
            # `task_instance_id` is deliberately unsettable via the decorator;
            # the compiler will set it later via `SyncTask.set_task_instance_id`
            task_instance_id=None,
        )

    if func:
        return wrapper(func)  # @task style (no parentheses)
    return wrapper  # @task(...) style (with parentheses)


# Type alias for convenience
Task = SyncTask
