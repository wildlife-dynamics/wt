"""Asynchronous task implementation.

This module provides the AsyncTask class for asynchronous task execution that
returns Future objects.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

try:
    from opentelemetry import trace

    TRACING_AVAILABLE = True
except ImportError:
    TRACING_AVAILABLE = False

from .base import K, P, R, V, _Task
from .executors import AsyncExecutor, Future, FutureSequence
from .sync_task import (
    _create_kwargs_iterable,
    _create_mapvalues_kwargs_iterable,
    _get_defaults,
    _wrap_for_mapvalues,
)


@dataclass(frozen=True)
class AsyncTask(_Task[P, R, K, V]):
    """Asynchronous task implementation.

    This class wraps a function and provides methods for asynchronous execution
    that return Future objects. The futures can be gathered later to retrieve
    the actual results. This is useful for parallel or distributed execution.

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
        executor: Async executor for running the task

    Examples:
        >>> from wt_task import task
        >>> from wt_task.executors import AsyncExecutor, Future
        >>> # AsyncTask is typically created via set_executor with an async executor
        >>> # Examples here are conceptual as we'd need a concrete AsyncExecutor
    """

    executor: AsyncExecutor[P, R]

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Future[R]:
        """Execute the task asynchronously.

        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Future representing the pending result
        """
        defaults = _get_defaults(self.func)
        return self.executor.call(self.func, *args, **defaults | kwargs)

    def call(self, *args: P.args, **kwargs: P.kwargs) -> Future[R]:
        """Execute the task asynchronously (alias for __call__).

        This method is an alias for `__call__` that provides more readable
        method chaining syntax.

        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Future representing the pending result
        """
        if TRACING_AVAILABLE:
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span(
                self.task_instance_id or "",
                attributes={"method": "call"},
            ):
                return self(*args, **kwargs)
        else:
            return self(*args, **kwargs)

    def map(
        self,
        argnames: str | Sequence[str],
        argvalues: Sequence[V] | Sequence[tuple[V, ...]],
    ) -> FutureSequence[R]:
        """Map the task function over an iterable asynchronously.

        Execute the task multiple times in parallel, once for each element in
        argvalues. Returns a FutureSequence that can be gathered later.

        Args:
            argnames: Single argument name or sequence of names
            argvalues: Sequence of values or tuples to map over

        Returns:
            FutureSequence representing the pending results
        """
        defaults = _get_defaults(self.func)
        kwargs_iterable = _create_kwargs_iterable(argnames, argvalues, defaults)

        if TRACING_AVAILABLE:
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span(
                self.task_instance_id or "",
                attributes={
                    "ncalls": str(len(kwargs_iterable)),
                    "method": "map",
                },
            ):
                return self.executor.map(self.func, kwargs_iterable)
        else:
            return self.executor.map(self.func, kwargs_iterable)

    def mapvalues(
        self, argnames: str | Sequence[str], argvalues: Sequence[tuple[K, V]]
    ) -> FutureSequence[tuple[K, R]]:
        """Map the task function over key-value pairs asynchronously.

        Execute the task multiple times in parallel, once for each (key, value)
        pair. Returns a FutureSequence of (key, result) tuples that can be
        gathered later.

        Args:
            argnames: Single argument name or sequence of names
            argvalues: Sequence of (key, value) tuples

        Returns:
            FutureSequence of (key, result) tuples
        """
        defaults = _get_defaults(self.func)
        kwargs_iterable = _create_mapvalues_kwargs_iterable(argnames, argvalues, defaults)

        if TRACING_AVAILABLE:
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span(
                self.task_instance_id or "",
                attributes={
                    "ncalls": str(len(kwargs_iterable)),
                    "method": "mapvalues",
                },
            ):
                return self.executor.map(_wrap_for_mapvalues(self.func), kwargs_iterable)  # type: ignore[return-value, arg-type]
        else:
            return self.executor.map(_wrap_for_mapvalues(self.func), kwargs_iterable)  # type: ignore[return-value, arg-type]
