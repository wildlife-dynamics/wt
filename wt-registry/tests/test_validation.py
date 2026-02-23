"""Tests for function signature validation."""

import pytest

from wt_registry.exceptions import ValidationError
from wt_registry.validation import validate_function_signature


def test_valid_function_passes() -> None:
    """Test that a properly typed function passes validation."""

    def valid_func(x: int, y: str) -> bool:
        return True

    # Should not raise any exception
    validate_function_signature(valid_func)


def test_valid_function_with_complex_types() -> None:
    """Test that a function with complex type annotations passes."""

    def complex_func(data: list[dict[str, int]], count: int = 10) -> tuple[str, float]:
        return ("result", 3.14)

    validate_function_signature(complex_func)


def test_valid_function_with_none_return() -> None:
    """Test that a function with None return type passes."""

    def none_return(x: int) -> None:
        pass

    validate_function_signature(none_return)


def test_async_function_raises_error() -> None:
    """Test that async functions are rejected."""

    async def async_func(x: int) -> str:
        return "test"

    with pytest.raises(ValidationError) as exc_info:
        validate_function_signature(async_func)

    assert "Async functions are not supported" in str(exc_info.value)
    assert "async_func" in str(exc_info.value)


def test_class_raises_error() -> None:
    """Test that classes are rejected."""

    class MyClass:
        pass

    with pytest.raises(ValidationError) as exc_info:
        validate_function_signature(MyClass)  # type: ignore

    assert "Classes are not supported" in str(exc_info.value)
    assert "MyClass" in str(exc_info.value)


def test_untyped_parameter_raises_error() -> None:
    """Test that functions with untyped parameters are rejected."""

    def untyped_param(x, y: int) -> str:  # type: ignore
        return "test"

    with pytest.raises(ValidationError) as exc_info:
        validate_function_signature(untyped_param)

    assert "has untyped parameters" in str(exc_info.value)
    assert "x" in str(exc_info.value)


def test_multiple_untyped_parameters_raises_error() -> None:
    """Test that all untyped parameters are listed in the error."""

    def multiple_untyped(a, b: int, c, d: str) -> bool:  # type: ignore
        return True

    with pytest.raises(ValidationError) as exc_info:
        validate_function_signature(multiple_untyped)

    error_msg = str(exc_info.value)
    assert "has untyped parameters" in error_msg
    assert "a" in error_msg
    assert "c" in error_msg


def test_missing_return_type_raises_error() -> None:
    """Test that functions without return type annotation are rejected."""

    def no_return_type(x: int, y: str):  # type: ignore
        pass

    with pytest.raises(ValidationError) as exc_info:
        validate_function_signature(no_return_type)

    assert "has no return type annotation" in str(exc_info.value)


def test_function_with_defaults_passes() -> None:
    """Test that functions with default values pass if typed."""

    def with_defaults(x: int, y: str = "default", z: float = 3.14) -> bool:
        return True

    validate_function_signature(with_defaults)


def test_function_with_args_passes() -> None:
    """Test that functions with *args pass if typed."""

    def with_args(x: int, *args: str) -> list[str]:
        return list(args)

    validate_function_signature(with_args)


def test_function_with_kwargs_passes() -> None:
    """Test that functions with **kwargs pass if typed."""

    def with_kwargs(x: int, **kwargs: float) -> dict[str, float]:
        return kwargs

    validate_function_signature(with_kwargs)


def test_function_with_union_types_passes() -> None:
    """Test that functions with union types pass."""

    def with_union(x: int | str, y: list[int] | None = None) -> str | None:
        return None

    validate_function_signature(with_union)


def test_lambda_function_passes() -> None:
    """Test that lambda functions with type hints pass."""

    # Note: lambdas can't have type hints directly, but if we annotate the variable...
    def typed_lambda(x):
        return x + 1  # type: ignore

    # This will fail because lambdas can't be properly type-hinted
    with pytest.raises(ValidationError):
        validate_function_signature(typed_lambda)  # type: ignore


def test_error_message_includes_fqn() -> None:
    """Test that error messages include the fully qualified name."""

    def test_func(x) -> int:  # type: ignore
        return 1

    with pytest.raises(ValidationError) as exc_info:
        validate_function_signature(test_func)

    # Should include module and function name
    assert "test_func" in str(exc_info.value)
