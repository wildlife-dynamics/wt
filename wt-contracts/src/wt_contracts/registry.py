"""Registry contracts for wt-registry CLI output.

This module defines the Pydantic schemas that wt-registry CLI outputs and
wt-compiler consumes for task discovery. These contracts ensure type-safe
communication across package boundaries.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RegistryMetadata(BaseModel):
    """Metadata for a registered function.

    Attributes:
        title: Human-readable title for the function
        description: Detailed description of what the function does
        tags: List of categorization tags (e.g., ["statistics", "dataframe"])
        deprecated: Whether this function is deprecated
        deprecation_message: Optional message explaining the deprecation

    Examples:
        >>> metadata = RegistryMetadata(
        ...     title="Calculate Mean",
        ...     description="Calculate arithmetic mean of values",
        ...     tags=["statistics", "math"],
        ...     deprecated=False
        ... )
        >>> metadata.title
        'Calculate Mean'
        >>> metadata.tags
        ['statistics', 'math']
    """

    title: str = Field(..., description="Human-readable title")
    description: str = Field(..., description="Detailed description")
    tags: list[str] = Field(default_factory=list, description="Categorization tags")
    deprecated: bool = Field(default=False, description="Whether function is deprecated")
    deprecation_message: str | None = Field(
        default=None, description="Optional deprecation message"
    )


class RegistryEntry(BaseModel):
    """Complete registry entry from CLI output.

    Represents a single function discovered by wt-registry CLI. Contains all
    information needed by wt-compiler to generate imports and validate schemas.

    Attributes:
        metadata: Function metadata (title, description, tags, etc.)
        module_path: Python module path (e.g., "mypackage.tasks")
        function_name: Function name (e.g., "calculate_stats")
        import_statement: Complete import statement
                          (e.g., "from mypackage.tasks import calculate_stats")
        json_schema: JSON Schema for function signature (parameters + return type)

    Examples:
        >>> entry = RegistryEntry(
        ...     metadata=RegistryMetadata(
        ...         title="Add Numbers",
        ...         description="Add two integers",
        ...     ),
        ...     module_path="mypackage.tasks",
        ...     function_name="add",
        ...     import_statement="from mypackage.tasks import add",
        ...     json_schema={
        ...         "type": "object",
        ...         "properties": {
        ...             "a": {"type": "integer"},
        ...             "b": {"type": "integer"}
        ...         },
        ...         "required": ["a", "b"],
        ...         "return": {"type": "integer"}
        ...     }
        ... )
        >>> entry.function_name
        'add'
        >>> entry.module_path
        'mypackage.tasks'
    """

    metadata: RegistryMetadata = Field(..., description="Function metadata")
    module_path: str = Field(..., description="Python module path")
    function_name: str = Field(..., description="Function name")
    import_statement: str = Field(..., description="Complete import statement")
    json_schema: dict[str, object] = Field(..., description="JSON Schema for signature")


class RegistryOutput(BaseModel):
    """Top-level schema for wt-registry CLI JSON output.

    The CLI outputs this format when called with `wt-registry --format json`.
    wt-compiler parses and validates against this schema.

    Attributes:
        entries: Mapping from fully-qualified name (FQN) to registry entry
                 FQN format: "{module_path}.{function_name}"
        version: Schema version for compatibility tracking

    Examples:
        >>> output = RegistryOutput(
        ...     entries={
        ...         "mypackage.tasks.add": RegistryEntry(
        ...             metadata=RegistryMetadata(
        ...                 title="Add Numbers",
        ...                 description="Add two integers"
        ...             ),
        ...             module_path="mypackage.tasks",
        ...             function_name="add",
        ...             import_statement="from mypackage.tasks import add",
        ...             json_schema={"type": "object", "properties": {}}
        ...         )
        ...     },
        ...     version="1.0.0"
        ... )
        >>> "mypackage.tasks.add" in output.entries
        True
        >>> output.version
        '1.0.0'
    """

    entries: dict[str, RegistryEntry] = Field(..., description="Mapping from FQN to registry entry")
    version: str = Field(default="1.0.0", description="Schema version")
