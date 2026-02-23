"""Tests for exception classes."""

import pytest

from wt_registry.exceptions import (
    DuplicateRegistrationError,
    RegistryError,
    SchemaGenerationError,
    ValidationError,
)


def test_registry_error_base_exception() -> None:
    """Test that RegistryError is the base exception."""
    error = RegistryError("test message")
    assert isinstance(error, Exception)
    assert str(error) == "test message"


def test_validation_error_inherits_from_registry_error() -> None:
    """Test that ValidationError inherits from RegistryError."""
    error = ValidationError("validation failed")
    assert isinstance(error, RegistryError)
    assert isinstance(error, Exception)
    assert str(error) == "validation failed"


def test_duplicate_registration_error_inherits_from_registry_error() -> None:
    """Test that DuplicateRegistrationError inherits from RegistryError."""
    error = DuplicateRegistrationError("already registered")
    assert isinstance(error, RegistryError)
    assert isinstance(error, Exception)
    assert str(error) == "already registered"


def test_schema_generation_error_inherits_from_registry_error() -> None:
    """Test that SchemaGenerationError inherits from RegistryError."""
    error = SchemaGenerationError("schema generation failed")
    assert isinstance(error, RegistryError)
    assert isinstance(error, Exception)
    assert str(error) == "schema generation failed"


def test_catch_all_registry_errors() -> None:
    """Test that all custom exceptions can be caught by RegistryError."""
    errors = [
        ValidationError("validation"),
        DuplicateRegistrationError("duplicate"),
        SchemaGenerationError("schema"),
    ]

    for error in errors:
        with pytest.raises(RegistryError):
            raise error


def test_validation_error_can_be_raised() -> None:
    """Test that ValidationError can be raised and caught."""
    with pytest.raises(ValidationError) as exc_info:
        raise ValidationError("Function has no type hints")
    assert str(exc_info.value) == "Function has no type hints"


def test_duplicate_registration_error_can_be_raised() -> None:
    """Test that DuplicateRegistrationError can be raised and caught."""
    with pytest.raises(DuplicateRegistrationError) as exc_info:
        raise DuplicateRegistrationError("mymodule.myfunc already registered")
    assert "mymodule.myfunc" in str(exc_info.value)


def test_schema_generation_error_can_be_raised() -> None:
    """Test that SchemaGenerationError can be raised and caught."""
    with pytest.raises(SchemaGenerationError) as exc_info:
        raise SchemaGenerationError("Cannot generate schema for complex type")
    assert "complex type" in str(exc_info.value)
