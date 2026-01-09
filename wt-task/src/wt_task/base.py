"""Base task class with shared functionality.

This module defines the _Task base class that provides shared functionality
for SyncTask and AsyncTask implementations.
"""

from __future__ import annotations

import functools
import sys
import warnings
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Generic, Literal, ParamSpec, TypeVar, overload

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from pydantic import validate_call

from .exceptions import handle_errors as handle_errors_fn
from .executors import AsyncExecutor, SyncExecutor
from .executors.python import PythonExecutor
from .skip import skipif as skipif_fn
from .tracing import with_tracing as with_tracing_fn

P = ParamSpec("P")
R = TypeVar("R")
K = TypeVar("K")
V = TypeVar("V")


@dataclass(frozen=True)
class _Task(Generic[P, R, K, V]):
    """Base class for task wrappers providing common functionality.

    This class provides shared methods for task manipulation including partial
    application, validation, tracing, error handling, and conditional skipping.
    Subclasses (SyncTask, AsyncTask) implement the actual execution methods.

    Type parameters:
        P: Parameter specification for the wrapped function
        R: Return type of the wrapped function
        K: Key type for mapvalues operations
        V: Value type for mapvalues operations

    Attributes:
        func: The wrapped function
        tags: List of tags for categorization
        description: Optional description of the task
        task_instance_id: Optional unique identifier for this task instance
    """

    func: Callable[P, R]
    tags: list[str]
    description: str | None
    task_instance_id: str | None

    def set_task_instance_id(self, task_instance_id: str, /) -> Self:
        """Return a new Task with the task_instance_id set.

        Args:
            task_instance_id: Unique identifier for this task instance

        Returns:
            New task with task_instance_id set

        Examples:
            >>> from wt_task import task
            >>> @task
            ... def add(a: int, b: int) -> int:
            ...     return a + b
            >>> task_with_id = add.set_task_instance_id("task-1")
            >>> task_with_id.task_instance_id
            'task-1'
        """
        return replace(self, task_instance_id=task_instance_id)

    def partial(
        self,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> Self:
        """Return a new Task with partial function application.

        This method creates a new task with some arguments bound to fixed values.
        This is useful for mapping a function over an iterable where some of the
        function's arguments are constant across all calls.

        Args:
            *args: Positional arguments (not supported, will raise ValueError)
            **kwargs: Keyword arguments to bind

        Returns:
            New task with arguments partially applied

        Raises:
            ValueError: If positional arguments are provided

        Examples:
            >>> from wt_task import task
            >>> @task
            ... def add(a: int, b: int) -> int:
            ...     return a + b
            >>> add.partial(a=1).call(b=2)
            3
            >>> add.partial(a=1).map("b", [2, 3])
            [3, 4]
            >>> add.partial(a=1).mapvalues("b", [("x", 2), ("y", 3)])
            [('x', 3), ('y', 4)]
        """
        if args:
            raise ValueError("Positional arguments are not supported in `partial`.")
        return replace(self, func=functools.partial(self.func, **kwargs))

    def validate(self) -> Self:
        """Return a new Task with Pydantic validation enabled.

        This method wraps the function with Pydantic's `validate_call`, which
        validates and parses input parameters and return values. This is required
        when input parameters are given as strings that need to be parsed into
        the correct Python type.

        Returns:
            New task with validation enabled

        Examples:
            >>> from wt_task import task
            >>> @task
            ... def add(a: int) -> int:
            ...     return a
            >>> add("1")  # no parsing without validate
            '1'
            >>> add.validate().call("1")  # with validate, input is parsed
            1
        """
        return replace(
            self,
            func=validate_call(  # type: ignore[call-overload]
                self.func,
                validate_return=True,
                config={"arbitrary_types_allowed": True},
            ),
        )

    def with_tracing(self) -> Self:
        """Return a new Task with OpenTelemetry tracing enabled.

        This method wraps the function invocation with the `with_tracing`
        decorator, which creates a tracing span for the function call.

        Returns:
            New task with tracing enabled

        Examples:
            >>> from wt_task import task
            >>> @task
            ... def compute(x: int) -> int:
            ...     return x * 2
            >>> traced_task = compute.with_tracing()
            >>> traced_task.call(5)  # Creates a tracing span
            10
        """
        return replace(self, func=with_tracing_fn(self.func))

    def handle_errors(self) -> Self:
        """Return a new Task with error handling enabled.

        This method wraps the function invocation with error handling that
        catches any exceptions and raises a `TaskInstanceError` with the
        task_instance_id. This ensures that exceptions in workflow DAGs are
        surfaced with the correct context for debugging.

        Returns:
            New task with error handling enabled

        Warnings:
            Warns if task_instance_id is not set

        Examples:
            >>> from wt_task import task
            >>> from wt_task.exceptions import TaskInstanceError
            >>> @task
            ... def divide(a: int, b: int) -> float:
            ...     return a / b
            >>> task_with_id = divide.set_task_instance_id("task-1")
            >>> try:
            ...     task_with_id.handle_errors().call(10, 0)
            ... except TaskInstanceError as e:
            ...     print(str(e))
            Task instance 'task-1' raised ZeroDivisionError('division by zero')
        """
        if not self.task_instance_id:
            warnings.warn(
                "Task instance ID is unset. Wrapped errors will not include task instance IDs in their messages. "
                "Set task instance ID with `set_task_instance_id` method before calling this method.",
                stacklevel=2,
            )
        return replace(
            self,
            func=handle_errors_fn(self.func, task_instance_id=self.task_instance_id or ""),
        )

    def skipif(self, conditions: list[Callable[..., bool]], unpack_depth: int = 1) -> Self:
        """Return a new Task with conditional skipping enabled.

        This method wraps the function with skip logic that checks conditions
        before execution. If any condition returns True, the function is skipped
        and a SkipSentinel is returned.

        Args:
            conditions: List of condition functions that return bool
            unpack_depth: Depth for unpacking nested list-like arguments

        Returns:
            New task with skip conditions applied

        Examples:
            >>> from wt_task import task
            >>> from wt_task.skip import SkipSentinel
            >>> @task
            ... def process(x: int) -> int:
            ...     return x * 2
            >>> def is_negative(x: int) -> bool:
            ...     return x < 0
            >>> conditional_task = process.skipif([is_negative])
            >>> result = conditional_task.call(-5)
            >>> isinstance(result, SkipSentinel)
            True
            >>> conditional_task.call(5)
            10
        """
        return replace(
            self,
            func=skipif_fn(self.func, conditions=conditions, unpack_depth=unpack_depth),
        )

    @overload
    def set_executor(
        self,
        name_or_executor: Literal["python"],
    ) -> SyncTask[P, R, K, V]: ...

    @overload
    def set_executor(
        self,
        name_or_executor: SyncExecutor,  # type: ignore[type-arg]
    ) -> SyncTask[P, R, K, V]: ...

    @overload
    def set_executor(
        self,
        name_or_executor: AsyncExecutor,  # type: ignore[type-arg]
    ) -> AsyncTask[P, R, K, V]: ...

    def set_executor(
        self,
        name_or_executor: Literal["python"] | AsyncExecutor | SyncExecutor,  # type: ignore[type-arg]
    ) -> AsyncTask[P, R, K, V] | SyncTask[P, R, K, V]:
        """Return a new Task with a different executor.

        This method allows changing the executor for a task function after it
        has been defined. Useful for switching between synchronous and
        asynchronous execution or using custom executors.

        Args:
            name_or_executor: Either "python" for PythonExecutor, or an executor instance

        Returns:
            New task with specified executor (SyncTask or AsyncTask depending on executor type)

        Raises:
            ValueError: If name_or_executor is not a valid executor name or instance

        Examples:
            >>> from wt_task import task
            >>> from wt_task.executors import PythonExecutor
            >>> @task
            ... def add(a: int, b: int) -> int:
            ...     return a + b
            >>> type(add.executor).__name__
            'PythonExecutor'
            >>> custom = add.set_executor(PythonExecutor())
            >>> type(custom.executor).__name__
            'PythonExecutor'
        """
        # Import here to avoid circular imports
        from .async_task import AsyncTask
        from .sync_task import SyncTask

        match name_or_executor:
            case "python":
                return SyncTask(
                    self.func,
                    tags=self.tags,
                    description=self.description,
                    task_instance_id=self.task_instance_id,
                    executor=PythonExecutor(),
                )
            case AsyncExecutor():
                return AsyncTask(
                    self.func,
                    tags=self.tags,
                    description=self.description,
                    task_instance_id=self.task_instance_id,
                    executor=name_or_executor,
                )
            case SyncExecutor():
                return SyncTask(
                    self.func,
                    tags=self.tags,
                    description=self.description,
                    task_instance_id=self.task_instance_id,
                    executor=name_or_executor,
                )
            case _:
                raise ValueError(
                    "Executor must be 'python' or an instance of `AsyncExecutor` or "
                    f"`SyncExecutor`, not {name_or_executor}."
                )


# Forward declarations for type checking
if sys.version_info >= (3, 11):
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from .async_task import AsyncTask
        from .sync_task import SyncTask
else:
    # For Python 3.10, we can't use TYPE_CHECKING with forward references in match statements
    # The imports in set_executor will handle the actual classes
    pass
