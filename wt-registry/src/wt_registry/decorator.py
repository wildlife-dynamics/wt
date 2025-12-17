"""The @register decorator for registering functions."""

from collections.abc import Callable
from typing import Any, TypeVar

from wt_registry.models import RegistryEntry, RegistryMetadata
from wt_registry.registry import register_entry

# Type variable for the decorated function
F = TypeVar("F", bound=Callable[..., Any])


def register(
    *,
    title: str,
    description: str,
    tags: list[str] | None = None,
    deprecated: bool = False,
    deprecation_message: str | None = None,
) -> Callable[[F], F]:
    """
    Register a function in the global registry with metadata.

    The decorated function must have complete type annotations for all
    parameters and return type. The function is registered immediately
    when the decorator is applied (at import time), and the original
    function is returned unchanged.

    Args:
        title: Human-readable title for the function
        description: Detailed description of what the function does
        tags: Optional list of categorization tags
        deprecated: Whether this function is deprecated (default: False)
        deprecation_message: Optional message explaining the deprecation

    Returns:
        Decorator that registers the function and returns it unchanged

    Raises:
        ValidationError: If the function signature is not fully typed
        DuplicateRegistrationError: If the function is already registered
        SchemaGenerationError: If JSON schema generation fails

    Examples:
        Basic registration:

        >>> from wt_registry.decorator import register
        >>> from wt_registry.registry import get_registry, clear_registry
        >>> clear_registry()  # Start fresh
        >>> @register(
        ...     title="Add Numbers",
        ...     description="Add two integers together"
        ... )
        ... def add(a: int, b: int) -> int:
        ...     return a + b
        >>> registry = get_registry()
        >>> len(registry)
        1
        >>> "add" in str(list(registry.keys())[0])
        True

        With tags:

        >>> @register(
        ...     title="Calculate Mean",
        ...     description="Calculate arithmetic mean",
        ...     tags=["statistics", "math"]
        ... )
        ... def mean(values: list[float]) -> float:
        ...     return sum(values) / len(values)
        >>> entry = list(get_registry().values())[-1]
        >>> entry.metadata.tags
        ['statistics', 'math']

        Deprecated function:

        >>> @register(
        ...     title="Old Function",
        ...     description="Legacy function",
        ...     deprecated=True,
        ...     deprecation_message="Use new_function instead"
        ... )
        ... def old_func(x: int) -> int:
        ...     return x * 2
        >>> entry = list(get_registry().values())[-1]
        >>> entry.metadata.deprecated
        True
    """

    def decorator(func: F) -> F:
        # 1. Extract metadata from function
        module_path = func.__module__
        function_name = func.__qualname__

        # 2. Create registry entry with metadata and function reference
        # NO validation or schema generation at this point (lazy)
        metadata = RegistryMetadata(
            title=title,
            description=description,
            tags=tags or [],
            deprecated=deprecated,
            deprecation_message=deprecation_message,
        )

        entry = RegistryEntry(
            metadata=metadata,
            module_path=module_path,
            function_name=function_name,
        )
        entry._func_ref = func

        # 3. Register in global registry
        register_entry(entry)

        # 4. Return original function unchanged
        return func

    return decorator
