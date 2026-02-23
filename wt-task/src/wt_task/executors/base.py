"""Abstract executor interfaces for task execution.

This module defines the abstract base classes for synchronous and asynchronous
task execution, along with Future types for async results.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from typing import Generic, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")


class SyncExecutor(ABC, Generic[P, R]):
    """Abstract base class for synchronous task executors.

    Synchronous executors execute tasks immediately and return results directly.
    Examples include the PythonExecutor which runs tasks in the current thread.

    Type parameters:
        P: Parameter specification for the function
        R: Return type of the function

    Examples:
        >>> class MyExecutor(SyncExecutor):
        ...     def call(self, func, *args, **kwargs):
        ...         return func(*args, **kwargs)
        ...     def map(self, func, iterable):
        ...         return list(map(func, iterable))
    """

    @abstractmethod
    def call(self, func: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
        """Execute a function with given arguments.

        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result of function execution
        """
        ...

    @abstractmethod
    def map(self, func: Callable[..., R], iterable: Iterable[T]) -> Sequence[R]:
        """Map a function over an iterable.

        Args:
            func: Function to apply to each element
            iterable: Iterable of input values

        Returns:
            Sequence of results
        """
        ...


class Future(ABC, Generic[R]):
    """Abstract base class for async execution results.

    A Future represents a value that may not be available yet. Calling gather()
    blocks until the result is ready.

    Type parameters:
        R: Return type of the future value

    Examples:
        >>> class MyFuture(Future):
        ...     def __init__(self, value):
        ...         self._value = value
        ...     def gather(self):
        ...         return self._value
    """

    @abstractmethod
    def gather(self, *args, **kwargs) -> R:  # type: ignore[no-untyped-def]
        """Block until result is available and return it.

        Args:
            *args: Implementation-specific arguments
            **kwargs: Implementation-specific keyword arguments

        Returns:
            The future's value
        """
        ...


class FutureSequence(ABC, Generic[R]):
    """Abstract base class for sequences of async execution results.

    A FutureSequence represents multiple values that may not be available yet.
    Calling gather() blocks until all results are ready.

    Type parameters:
        R: Return type of the future values

    Examples:
        >>> class MyFutureSequence(FutureSequence):
        ...     def __init__(self, values):
        ...         self._values = values
        ...     def gather(self):
        ...         return self._values
    """

    @abstractmethod
    def gather(self, *args, **kwargs) -> Sequence[R]:  # type: ignore[no-untyped-def]
        """Block until all results are available and return them.

        Args:
            *args: Implementation-specific arguments
            **kwargs: Implementation-specific keyword arguments

        Returns:
            Sequence of future values
        """
        ...


class AsyncExecutor(ABC, Generic[P, R]):
    """Abstract base class for asynchronous task executors.

    Asynchronous executors return Future objects that can be gathered later.
    Examples include the LithopsExecutor for serverless execution.

    Type parameters:
        P: Parameter specification for the function
        R: Return type of the function

    Examples:
        >>> class MyAsyncExecutor(AsyncExecutor):
        ...     def call(self, func, *args, **kwargs):
        ...         # Return a Future that will execute func later
        ...         ...
        ...     def map(self, func, iterable):
        ...         # Return a FutureSequence for parallel execution
        ...         ...
    """

    @abstractmethod
    def call(
        self,
        func: Callable[P, R],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> Future[R]:
        """Execute a function asynchronously.

        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Future representing the pending result
        """
        ...

    @abstractmethod
    def map(
        self,
        func: Callable[..., R],
        iterable: Iterable[T],
    ) -> FutureSequence[R]:
        """Map a function over an iterable asynchronously.

        Args:
            func: Function to apply to each element
            iterable: Iterable of input values

        Returns:
            FutureSequence representing the pending results
        """
        ...


class mapvalues_wrapper(Generic[K, V, R]):
    """Wrapper for mapvalues operations that preserves keys.

    This wrapper takes a function that accepts keyword arguments and wraps it
    to accept (key, kwargs) tuples, returning (key, result) tuples. This enables
    the mapvalues operation which preserves keys while transforming values.

    Type parameters:
        K: Key type
        V: Value type (kwargs dict)
        R: Result type

    Examples:
        >>> def my_func(x: int, y: int) -> int:
        ...     return x + y
        >>> wrapper = mapvalues_wrapper(my_func)
        >>> wrapper(("key1", {"x": 1, "y": 2}))
        ('key1', 3)
    """

    def __init__(self, func: Callable[..., R]) -> None:
        """Initialize wrapper with function.

        Args:
            func: Function to wrap
        """
        self.func = func

    def __call__(self, kv: tuple[K, V]) -> tuple[K, R]:
        """Apply function to value, preserving key.

        Args:
            kv: Tuple of (key, kwargs_dict)

        Returns:
            Tuple of (key, result)
        """
        key, argvalue = kv
        return key, self.func(**argvalue)  # type: ignore[arg-type]
