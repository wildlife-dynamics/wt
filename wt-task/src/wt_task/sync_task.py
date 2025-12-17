"""Synchronous task implementation.

This module provides the SyncTask class for synchronous task execution.
"""

from __future__ import annotations

import inspect
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Callable, ParamSpec, TypeVar, cast, overload

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

try:
    from opentelemetry import trace

    TRACING_AVAILABLE = True
except ImportError:
    TRACING_AVAILABLE = False

from .base import K, V, R, P, _Task
from .executors import SyncExecutor, mapvalues_wrapper
from .executors.python import PythonExecutor
from .skip import SkipSentinel

# Helper functions


def _get_defaults(func: Callable[..., Any]) -> dict[str, Any]:
    """Extract default values from function signature.

    Args:
        func: Function to inspect

    Returns:
        Dictionary mapping parameter names to their default values
    """
    return {
        k: v.default
        for k, v in inspect.signature(func).parameters.items()
        if v.default is not inspect.Parameter.empty
    }


def _create_kwargs_iterable(
    argnames: str | Sequence[str],
    argvalues: Sequence[V] | Sequence[tuple[V, ...]] | SkipSentinel,
    defaults: dict[str, Any],
) -> list[dict[str, V | Any]]:
    """Create an iterable of kwargs dicts for map operations.

    Args:
        argnames: Single argument name or sequence of names
        argvalues: Values to map over (single values or tuples)
        defaults: Default parameter values from function signature

    Returns:
        List of kwargs dictionaries for each function call
    """
    if isinstance(argnames, str):
        argnames = [argnames]
    if isinstance(argvalues, SkipSentinel):
        return [defaults | {argname: argvalues for argname in argnames}]
    # Handle empty list
    if not argvalues:
        return []
    # For mypy, ensure argvalues is a list of tuples, regardless of input
    argvalues_list: list[tuple[Any, ...]] = (
        [(v,) for v in argvalues]
        if not isinstance(argvalues[0], tuple)
        else cast(list[tuple[Any, ...]], argvalues)
    )
    assert all(
        len(v) == len(argnames) for v in argvalues_list
    ), "All values in `argvalues` must have the same length as `argnames`."
    return [
        defaults | {argnames[i]: argvalues_list[j][i] for i in range(len(argnames))}
        for j in range(len(argvalues_list))
    ]


def _create_mapvalues_kwargs_iterable(
    argnames: str | Sequence[str],
    argvalues: Sequence[tuple[K, V]] | SkipSentinel,
    defaults: dict[str, Any],
) -> list[tuple[K, dict[str, Any]]] | list[tuple[None, dict[str, Any]]]:
    """Create an iterable of (key, kwargs) tuples for mapvalues operations.

    Args:
        argnames: Single argument name or sequence of names
        argvalues: Key-value pairs to map over
        defaults: Default parameter values from function signature

    Returns:
        List of (key, kwargs) tuples for each function call
    """
    if isinstance(argnames, str):
        argnames = [argnames]
    if isinstance(argvalues, SkipSentinel):
        return [
            (
                None,
                defaults | {argname: argvalues for argname in argnames},
            )
        ]
    kwargs_iterable: list[tuple[K, dict[str, Any]]] = []
    for argvalue in argvalues:
        key = argvalue[0]
        values = [argvalue[1]] if len(argnames) == 1 else cast(list[Any], argvalue[1])

        if len(values) != len(argnames):
            raise ValueError(
                f"Length of argvalue {values} must match length of argnames {argnames}."
            )
        kwargs = defaults | {argnames[i]: values[i] for i in range(len(argnames))}
        kwargs_iterable.append((key, kwargs))

    return kwargs_iterable


def _wrap_for_mapvalues(func: Callable[P, R]) -> Callable[[tuple[K, V]], tuple[K, R]]:
    """Wrap function for mapvalues operation.

    Args:
        func: Function to wrap

    Returns:
        Wrapped function that accepts (key, kwargs) and returns (key, result)
    """
    import functools

    wrapper: mapvalues_wrapper[K, V, R] = mapvalues_wrapper(func)
    functools.update_wrapper(wrapper, func)
    return wrapper


@dataclass(frozen=True)
class SyncTask(_Task[P, R, K, V]):
    """Synchronous task implementation.

    This class wraps a function and provides methods for synchronous execution
    including calling, mapping over iterables, and mapping over key-value pairs.
    Methods can be chained with `partial` to set arguments, `validate` to enable
    Pydantic validation, and other transformation methods.

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
        executor: Executor for running the task (default: PythonExecutor)

    Examples:
        Basic usage:

        >>> from wt_task import task
        >>> @task
        ... def add(a: int, b: int) -> int:
        ...     return a + b
        >>> add(1, 2)
        3
        >>> add.call(1, 2)
        3

        Partial application and mapping:

        >>> add.partial(a=1)(b=2)
        3
        >>> add.partial(a=1).call(b=2)
        3
        >>> add.partial(a=1).map("b", [2, 3])
        [3, 4]

        Mapvalues operation:

        >>> add.partial(a=1).mapvalues("b", [("x", 2), ("y", 3)])
        [('x', 3), ('y', 4)]

        Validation:

        >>> add.validate().call("1", "2")  # coerce input values to ints
        3
        >>> add.validate().partial(a="1").map("b", ["2", "3"])
        [3, 4]
    """

    executor: SyncExecutor[P, R] = field(default_factory=PythonExecutor)  # type: ignore[assignment]

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        """Execute the task with given arguments.

        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result of function execution
        """
        return self.executor.call(self.func, *args, **kwargs)

    def call(self, *args: P.args, **kwargs: P.kwargs) -> R:
        """Execute the task (alias for __call__ for readable chaining).

        This method is an alias for `__call__` that provides more readable
        method chaining syntax.

        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result of function execution

        Examples:
            >>> from wt_task import task
            >>> @task
            ... def add(a: int, b: int) -> int:
            ...     return a + b
            >>> add(1, 2)
            3
            >>> add.call(1, 2)
            3
            >>> add.partial(a=1)(b=2)  # this works but is less readable
            3
            >>> add.partial(a=1).call(b=2)  # this is more readable
            3
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

    @overload
    def map(
        self,
        argnames: str | Sequence[str],
        argvalues: SkipSentinel,
    ) -> Sequence[SkipSentinel]: ...

    @overload
    def map(
        self,
        argnames: str | Sequence[str],
        argvalues: Sequence[Any] | Sequence[tuple[Any, ...]],
    ) -> Sequence[R]: ...

    def map(
        self,
        argnames: str | Sequence[str],
        argvalues: Sequence[Any] | Sequence[tuple[Any, ...]] | SkipSentinel,
    ) -> Sequence[R | SkipSentinel]:
        """Map the task function over an iterable of argument values.

        Execute the task multiple times, once for each element in argvalues.
        Each element can be a single value (if argnames is a single string) or
        a tuple of values (if argnames is a sequence). To set constant arguments,
        chain with `partial`.

        Args:
            argnames: Single argument name or sequence of names
            argvalues: Sequence of values or tuples to map over

        Returns:
            Sequence of results, one per input value

        Examples:
            Single argument:

            >>> from wt_task import task
            >>> @task
            ... def square(x: int) -> int:
            ...     return x * x
            >>> square.map("x", [1, 2, 3])
            [1, 4, 9]

            Multiple arguments:

            >>> @task
            ... def add(a: int, b: int) -> int:
            ...     return a + b
            >>> add.map(["a", "b"], [(1, 2), (3, 4), (5, 6)])
            [3, 7, 11]

            With partial:

            >>> add.partial(a=1).map("b", [2, 3, 4])
            [3, 4, 5]
        """
        # Special handling for SkipSentinel - return it directly without executing
        if isinstance(argvalues, SkipSentinel):
            return [argvalues]

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
                return self.executor.map(lambda kw: self.func(**kw), kwargs_iterable)  # type: ignore[arg-type, call-arg]
        else:
            return self.executor.map(lambda kw: self.func(**kw), kwargs_iterable)  # type: ignore[arg-type, call-arg]

    @overload
    def mapvalues(
        self,
        argnames: str | Sequence[str],
        argvalues: SkipSentinel,
    ) -> Sequence[tuple[None, SkipSentinel]]: ...

    @overload
    def mapvalues(
        self,
        argnames: str | Sequence[str],
        argvalues: Sequence[tuple[K, V]],
    ) -> Sequence[tuple[K, R]]: ...

    def mapvalues(
        self,
        argnames: str | Sequence[str],
        argvalues: Sequence[tuple[K, V]] | SkipSentinel,
    ) -> Sequence[tuple[K, R]] | Sequence[tuple[None, SkipSentinel]]:
        """Map the task function over key-value pairs, preserving keys.

        Execute the task multiple times, once for each (key, value) pair in
        argvalues. The keys are passed through unchanged while the values are
        transformed by the task function. This is similar to pyspark.RDD.mapValues.

        Args:
            argnames: Single argument name or sequence of names
            argvalues: Sequence of (key, value) tuples

        Returns:
            Sequence of (key, result) tuples with keys preserved

        Examples:
            Single argument:

            >>> from wt_task import task
            >>> @task
            ... def length(s: str) -> int:
            ...     return len(s)
            >>> length.mapvalues("s", [("a", "hello"), ("b", "world")])
            [('a', 5), ('b', 5)]

            With partial:

            >>> @task
            ... def multiply(x: int, factor: int) -> int:
            ...     return x * factor
            >>> multiply.partial(factor=2).mapvalues("x", [("a", 5), ("b", 10)])
            [('a', 10), ('b', 20)]
        """
        # Special handling for SkipSentinel - return it with None key
        if isinstance(argvalues, SkipSentinel):
            return [(None, argvalues)]  # type: ignore[list-item]

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
                return self.executor.map(_wrap_for_mapvalues(self.func), kwargs_iterable)
        else:
            return self.executor.map(_wrap_for_mapvalues(self.func), kwargs_iterable)
