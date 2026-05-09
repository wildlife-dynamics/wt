"""Function signature validation utilities."""

import inspect
from collections.abc import Callable
from typing import Any

from wt_registry.exceptions import ValidationError


def validate_function_signature(func: Callable[..., Any]) -> None:
    """Validate that a function has complete type annotations.

    This function ensures that:
    - The function is not async (async functions are not supported)
    - The function is not a class (only functions can be registered)
    - All parameters have type annotations
    - The return type is annotated

    Args:
        func: The function to validate

    Raises:
        ValidationError: If the function signature does not meet requirements

    Examples:
        Valid function passes without error:

        >>> def valid_func(x: int, y: str) -> bool:
        ...     return True
        >>> validate_function_signature(valid_func)

        Async function raises ValidationError:

        >>> async def async_func(x: int) -> str:
        ...     return "test"
        >>> validate_function_signature(async_func)  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
            ...
        wt_registry.exceptions.ValidationError: Async functions are not supported...

        Untyped parameter raises ValidationError:

        >>> def untyped_param(x, y: int) -> str:
        ...     return "test"
        >>> validate_function_signature(untyped_param)  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
            ...
        wt_registry.exceptions.ValidationError: Function...has untyped parameters: x...

        Missing return type raises ValidationError:

        >>> def no_return(x: int):
        ...     pass
        >>> validate_function_signature(no_return)  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
            ...
        wt_registry.exceptions.ValidationError: Function...has no return type annotation...
    """
    # Get fully qualified name for error messages
    fqn = f"{func.__module__}.{func.__qualname__}"

    # Check it's not an async function
    if inspect.iscoroutinefunction(func):
        raise ValidationError(
            f"Async functions are not supported: {fqn}. "
            f"Only synchronous functions can be registered."
        )

    # Check it's not a class
    if inspect.isclass(func):
        raise ValidationError(
            f"Classes are not supported: {fqn}. Only functions can be registered."
        )

    # Get signature
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError) as e:
        raise ValidationError(f"Cannot inspect signature of {fqn}: {e}") from e

    # Check all parameters have annotations
    untyped_params = []
    for param_name, param in sig.parameters.items():
        if param.annotation is inspect.Parameter.empty:
            untyped_params.append(param_name)

    if untyped_params:
        raise ValidationError(
            f"Function {fqn} has untyped parameters: {', '.join(untyped_params)}. "
            f"All parameters must have type annotations."
        )

    # Check return type is annotated
    if sig.return_annotation is inspect.Signature.empty:
        raise ValidationError(
            f"Function {fqn} has no return type annotation. Return type must be annotated."
        )
