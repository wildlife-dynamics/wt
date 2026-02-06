"""Pydantic models for registry metadata and entries."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

# Import shared contract from wt-contracts
from wt_contracts.registry import RegistryMetadata

from wt_registry.exceptions import SchemaGenerationError
from wt_registry.jsonschema import jsonschema_from_task_func
from wt_registry.validation import validate_function_signature

# Re-export for backward compatibility
__all__ = ["RegistryEntry", "RegistryMetadata"]


class RegistryEntry(BaseModel):
    """
    Complete registry entry for a registered function.

    This model represents a complete entry in the global registry, combining
    user-provided metadata with auto-detected information. The JSON schema
    is generated lazily when first accessed.

    Attributes:
        metadata: User-provided metadata from @register decorator
        module_path: Full module path where the function is defined
        function_name: Name of the function (from __qualname__)
        json_schema: JSON schema property (generated lazily on first access)

    Examples:
        Creating a registry entry:

        >>> from wt_registry.models import RegistryMetadata, RegistryEntry
        >>> from wt_registry.registry import clear_registry
        >>> clear_registry()
        >>> def sample_func(x: int) -> str:
        ...     return str(x)
        >>> metadata = RegistryMetadata(
        ...     title="Add Numbers",
        ...     description="Add two integers"
        ... )
        >>> entry = RegistryEntry(
        ...     metadata=metadata,
        ...     module_path="myapp.math",
        ...     function_name="add",
        ...     _func_ref=sample_func
        ... )
        >>> entry.fully_qualified_name
        'myapp.math.add'
        >>> entry.import_statement
        'from myapp.math import add'
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    metadata: RegistryMetadata = Field(..., description="User-provided metadata")
    module_path: str = Field(..., description="Full module path (e.g., 'mypackage.tasks')")
    function_name: str = Field(..., description="Function name (e.g., 'calculate_mean')")
    _func_ref: Any = PrivateAttr(default=None)

    @property
    def json_schema(self) -> dict[str, Any]:
        """
        Generate JSON schema for the function.

        The schema is generated fresh on every access (no caching) by:
        1. Validating the function signature (raises ValidationError if invalid)
        2. Generating the JSON schema using Pydantic TypeAdapter
        3. Returning the result directly

        Since this is only accessed during build/export, regeneration is acceptable.

        Returns:
            The JSON schema dictionary

        Raises:
            ValidationError: If the function signature is invalid
            SchemaGenerationError: If schema generation fails

        Examples:
            Accessing schema triggers validation and generation:

            >>> from wt_registry.registry import clear_registry
            >>> clear_registry()
            >>> def valid_func(x: int, y: str) -> bool:
            ...     return True
            >>> metadata = RegistryMetadata(title="Test", description="Test")
            >>> entry = RegistryEntry(
            ...     metadata=metadata,
            ...     module_path="test",
            ...     function_name="valid_func",
            ... )
            >>> entry._func_ref = valid_func
            >>> schema = entry.json_schema
            >>> isinstance(schema, dict)
            True

            Invalid function raises error on schema access:

            >>> def invalid_func(x) -> bool:  # Missing type annotation
            ...     return True
            >>> entry2 = RegistryEntry(
            ...     metadata=metadata,
            ...     module_path="test",
            ...     function_name="invalid_func",
            ... )
            >>> entry2._func_ref = invalid_func
            >>> entry2.json_schema  # doctest: +IGNORE_EXCEPTION_DETAIL
            Traceback (most recent call last):
                ...
            wt_registry.exceptions.ValidationError: Function...has untyped parameters...
        """
        if self._func_ref is None:
            raise AttributeError(
                f"Cannot generate schema for {self.fully_qualified_name}: "
                "function reference not set. Use @register decorator to register functions."
            )

        # Step 1: Validate function signature
        validate_function_signature(self._func_ref)

        # Step 2: Generate JSON schema using custom generator that surfaces
        # Field() metadata (descriptions, titles, defaults, json_schema_extra)
        try:
            schema = jsonschema_from_task_func(self._func_ref)
        except Exception as e:
            raise SchemaGenerationError(
                f"Failed to generate JSON schema for {self.fully_qualified_name}: {e}"
            ) from e

        # Step 3: Return directly (no caching)
        return schema

    @property
    def fully_qualified_name(self) -> str:
        """
        Generate fully qualified name: 'module_path.function_name'.

        Returns:
            The fully qualified name of the function

        Examples:
            >>> metadata = RegistryMetadata(title="Test", description="Test function")
            >>> def sample_func(x: int) -> str:
            ...     return str(x)
            >>> entry = RegistryEntry(
            ...     metadata=metadata,
            ...     module_path="myapp.tasks",
            ...     function_name="process_data",
            ...     _func_ref=sample_func
            ... )
            >>> entry.fully_qualified_name
            'myapp.tasks.process_data'
        """
        return f"{self.module_path}.{self.function_name}"

    @property
    def import_statement(self) -> str:
        """
        Generate import statement: 'from module_path import function_name'.

        Returns:
            A Python import statement for this function

        Examples:
            >>> metadata = RegistryMetadata(title="Test", description="Test function")
            >>> def sample_func(x: int) -> str:
            ...     return str(x)
            >>> entry = RegistryEntry(
            ...     metadata=metadata,
            ...     module_path="myapp.tasks",
            ...     function_name="process_data",
            ...     _func_ref=sample_func
            ... )
            >>> entry.import_statement
            'from myapp.tasks import process_data'
        """
        return f"from {self.module_path} import {self.function_name}"
