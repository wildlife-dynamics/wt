"""Custom exceptions for wt-registry."""


class RegistryError(Exception):
    """
    Base exception for all wt-registry errors.

    All custom exceptions in wt-registry inherit from this class,
    making it easy to catch any registry-related error.

    Examples:
        >>> try:
        ...     raise RegistryError("Something went wrong")
        ... except RegistryError as e:
        ...     print(f"Caught: {e}")
        Caught: Something went wrong
    """

    pass


class ValidationError(RegistryError):
    """
    Raised when function signature validation fails.

    This error is raised when a function being registered does not meet
    the type annotation requirements (e.g., missing parameter types,
    missing return type, async functions, or classes).

    Examples:
        >>> raise ValidationError("Function missing type annotations")
        Traceback (most recent call last):
            ...
        wt_registry.exceptions.ValidationError: Function missing type annotations
    """

    pass


class DuplicateRegistrationError(RegistryError):
    """
    Raised when attempting to register a function that is already registered.

    Each function can only be registered once. The fully qualified name
    (module.function) must be unique across the entire registry.

    Examples:
        >>> raise DuplicateRegistrationError("Function mymodule.myfunc already registered")
        Traceback (most recent call last):
            ...
        wt_registry.exceptions.DuplicateRegistrationError: Function mymodule.myfunc already registered
    """

    pass


class SchemaGenerationError(RegistryError):
    """
    Raised when JSON schema generation fails.

    This error occurs when Pydantic's TypeAdapter cannot generate a valid
    JSON schema from the function's type annotations, typically due to
    unsupported or complex type hints.

    Examples:
        >>> raise SchemaGenerationError("Failed to generate schema for complex type")
        Traceback (most recent call last):
            ...
        wt_registry.exceptions.SchemaGenerationError: Failed to generate schema for complex type
    """

    pass
