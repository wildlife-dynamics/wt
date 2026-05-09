"""Skip sentinel and conditional execution logic.

This module provides utilities for conditionally skipping task execution based
on argument values. The SkipSentinel is returned when a task is skipped.
"""

from collections.abc import Callable
from functools import wraps
from typing import Any

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.functional_validators import BeforeValidator
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema as cs


class SkipSentinel:
    """Sentinel value returned when a task execution is skipped.

    This class is used as a return value when a task's execution is conditionally
    skipped based on skipif conditions. It can be used in Pydantic validators
    to provide fallback values when dependencies are skipped.

    Examples:
        >>> sentinel = SkipSentinel()
        >>> repr(sentinel)
        '<SkipSentinel>'
        >>> isinstance(SKIP_SENTINEL, SkipSentinel)
        True
    """

    def __repr__(self) -> str:
        """Return string representation.

        Returns:
            String representation of the sentinel
        """
        return "<SkipSentinel>"

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: type, handler: GetCoreSchemaHandler
    ) -> cs.CoreSchema:
        """Return a Pydantic core schema that matches instances of this class."""
        return cs.is_instance_schema(cls)

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: cs.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        """Map this sentinel to JSON Schema null since it represents an absent value."""
        return {"type": "null", "title": "SkipSentinel"}


SKIP_SENTINEL = SkipSentinel()
"""Global skip sentinel instance."""

SkippedDependencyFallback = BeforeValidator
"""Type alias for Pydantic validators that handle skipped dependencies."""


def unpack_listlike(
    argvalues: list[Any] | tuple[Any, ...],
    unpack_depth: int = 0,
) -> list[Any]:
    """Unpack list-like objects in the argument values.

    This function recursively unpacks nested lists and tuples up to the specified
    depth. This is useful for checking skip conditions on nested data structures.

    Args:
        argvalues: List of argument values to unpack
        unpack_depth: Depth of unpacking (0 means no unpacking)

    Returns:
        List of unpacked argument values

    Examples:
        >>> argvalues = [1, 2, [3, 4], (5, 6)]
        >>> unpack_listlike(argvalues, 1)
        [1, 2, 3, 4, 5, 6]
        >>> unpack_listlike(argvalues, 0)
        [1, 2, [3, 4], (5, 6)]
        >>> argvalues = [1, 2, [3, [4, 5]], (5, 6)]
        >>> unpack_listlike(argvalues, 1)
        [1, 2, 3, [4, 5], 5, 6]
        >>> unpack_listlike(argvalues, 2)
        [1, 2, 3, 4, 5, 5, 6]
    """
    unpacked: list[Any] = []
    for arg in argvalues:
        if isinstance(arg, list | tuple) and unpack_depth > 0:
            unpacked.extend(unpack_listlike(arg, unpack_depth - 1))
        else:
            unpacked.append(arg)
    return unpacked


def skipif(
    func: Callable[..., Any],
    conditions: list[Callable[..., bool]],
    unpack_depth: int = 1,
) -> Callable[..., Any]:
    """Wrap a function to skip execution if conditions are met.

    This wrapper checks if any of the provided conditions return True when
    evaluated against the function's arguments. If so, the function is skipped
    and SKIP_SENTINEL is returned instead.

    Args:
        func: The function to be wrapped
        conditions: A list of conditions (functions) to check against the arguments
        unpack_depth: The depth of unpacking for list-like objects in the arguments

    Returns:
        A wrapped function that skips execution if any condition is met

    Examples:
        >>> from typing import Any
        >>> def f(obj: Any) -> Any:
        ...     print("Function called!")
        ...     return obj
        >>> def any_is_int(*args: Any) -> bool:
        ...     return any(isinstance(arg, int) for arg in args)
        >>> skipif(f, [any_is_int], unpack_depth=1)("1")
        Function called!
        '1'
        >>> result = skipif(f, [any_is_int], unpack_depth=1)(1)
        >>> isinstance(result, SkipSentinel)
        True
        >>> skipif(f, [any_is_int], unpack_depth=0)([1, 2])
        Function called!
        [1, 2]
        >>> result = skipif(f, [any_is_int], unpack_depth=1)([1, 2])
        >>> isinstance(result, SkipSentinel)
        True
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401  # generic wrapper passes args through
        argvalues = list(args) + list(kwargs.values())
        to_evaluate = unpack_listlike(argvalues, unpack_depth)
        if any(condition(*to_evaluate) for condition in conditions):
            return SKIP_SENTINEL
        return func(*args, **kwargs)

    return wrapper
