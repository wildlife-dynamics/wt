"""Tracing decorator for task functions.

This module provides a decorator that adds OpenTelemetry tracing spans to
function execution.
"""

from functools import wraps
from typing import Any, Callable, TypeVar

try:
    from opentelemetry import trace

    TRACING_AVAILABLE = True
except ImportError:
    TRACING_AVAILABLE = False

F = TypeVar("F", bound=Callable[..., Any])


def with_tracing(func: F) -> F:
    """Wrap a function to create a tracing span on execution.

    This decorator creates an OpenTelemetry span when the function is called,
    capturing the function name and module as span attributes. If OpenTelemetry
    is not installed, the function is returned unchanged.

    Args:
        func: Function to wrap with tracing

    Returns:
        Wrapped function that creates a tracing span

    Examples:
        >>> @with_tracing
        ... def my_function(x: int) -> int:
        ...     return x * 2
        >>> result = my_function(5)  # Creates a tracing span
        >>> result
        10
    """
    if not TRACING_AVAILABLE:
        return func

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        span_kws = {
            "name": func.__name__,
            "attributes": {
                "func.__module__": func.__module__,
                "func.__name__": func.__name__,
            },
        }
        tracer = trace.get_tracer(__name__)
        return tracer.start_as_current_span(**span_kws)(func)(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
