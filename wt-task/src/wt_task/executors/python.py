"""Python executor for synchronous task execution.

This module provides a simple synchronous executor that runs tasks in the
current thread using standard Python function calls.
"""

from collections.abc import Callable, Iterable, Sequence
from typing import TypeVar

from .base import P, R, SyncExecutor

T = TypeVar("T")


class PythonExecutor(SyncExecutor[P, R]):
    """Synchronous executor that runs tasks in the current thread.

    This is the default executor for tasks. It executes functions directly
    without any parallelization or special handling.

    Examples:
        >>> executor = PythonExecutor()
        >>> def add(a: int, b: int) -> int:
        ...     return a + b
        >>> executor.call(add, 1, 2)
        3
        >>> executor.map(lambda x: x * 2, [1, 2, 3])
        [2, 4, 6]
    """

    def call(self, func: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
        """Execute function with given arguments.

        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result of function execution
        """
        return func(*args, **kwargs)

    def map(self, func: Callable[..., R], iterable: Iterable[T]) -> Sequence[R]:
        """Map function over iterable using built-in map.

        Args:
            func: Function to apply to each element
            iterable: Iterable of input values

        Returns:
            List of results
        """
        mapper = map(func, iterable)
        return list(mapper)
