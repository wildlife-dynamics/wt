"""The @register decorator for registering functions."""

from collections.abc import Callable
from typing import Any, TypeVar

from wt_registry.models import RegistryEntry, RegistryMetadata
from wt_registry.registry import register_entry

# Type variable for the decorated function
F = TypeVar("F", bound=Callable[..., Any])


def _snake_to_title(name: str) -> str:
    """Convert snake_case function name to Title Case.

    Args:
        name: Function name in snake_case

    Returns:
        Title Case version of the name

    Examples:
        >>> _snake_to_title("get_patrol_observations")
        'Get Patrol Observations'
        >>> _snake_to_title("calculate_mean")
        'Calculate Mean'
    """
    return name.replace("_", " ").title()


def register(
    *,
    title: str | None = None,
    description: str = "",
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

    If title is not provided, it is auto-generated from the function name
    by converting snake_case to Title Case (e.g., "get_events" -> "Get Events").

    Args:
        title: Human-readable title for the function. If None, auto-generated
            from the function name.
        description: Detailed description of what the function does. Defaults
            to empty string.
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
        Minimal registration (title auto-generated from function name):

        >>> from wt_registry.decorator import register
        >>> from wt_registry.registry import get_registry, clear_registry
        >>> clear_registry()  # Start fresh
        >>> @register()
        ... def get_patrol_observations(x: int) -> str:
        ...     return str(x)
        >>> entry = list(get_registry().values())[0]
        >>> entry.metadata.title
        'Get Patrol Observations'
        >>> entry.metadata.description
        ''

        With explicit title and description:

        >>> @register(
        ...     title="Add Numbers",
        ...     description="Add two integers together"
        ... )
        ... def add(a: int, b: int) -> int:
        ...     return a + b
        >>> entry = list(get_registry().values())[-1]
        >>> entry.metadata.title
        'Add Numbers'

        With tags only (title auto-generated):

        >>> @register(tags=["io"])
        ... def fetch_data(url: str) -> dict:
        ...     return {}
        >>> entry = list(get_registry().values())[-1]
        >>> entry.metadata.title
        'Fetch Data'
        >>> entry.metadata.tags
        ['io']

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

        # 2. Auto-generate title from function name if not provided
        effective_title = title if title is not None else _snake_to_title(func.__name__)

        # 3. Create registry entry with metadata and function reference
        # NO validation or schema generation at this point (lazy)
        metadata = RegistryMetadata(
            title=effective_title,
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

        # 4. Register in global registry
        register_entry(entry)

        # 5. Return original function unchanged
        return func

    return decorator
