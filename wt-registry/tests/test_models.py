"""Tests for Pydantic models."""

from typing import Annotated

import pytest
from pydantic import Field
from pydantic import ValidationError as PydanticValidationError

from wt_registry.models import RegistryEntry, RegistryMetadata


def test_registry_metadata_minimal() -> None:
    """Test creating RegistryMetadata with minimal required fields."""
    metadata = RegistryMetadata(
        title="Test Function", description="A test function for unit testing"
    )

    assert metadata.title == "Test Function"
    assert metadata.description == "A test function for unit testing"
    assert metadata.tags == []
    assert metadata.deprecated is False
    assert metadata.deprecation_message is None


def test_registry_metadata_with_tags() -> None:
    """Test creating RegistryMetadata with tags."""
    metadata = RegistryMetadata(
        title="Database Query",
        description="Execute a database query",
        tags=["database", "io", "query"],
    )

    assert metadata.tags == ["database", "io", "query"]


def test_registry_metadata_with_deprecation() -> None:
    """Test creating RegistryMetadata with deprecation info."""
    metadata = RegistryMetadata(
        title="Old Function",
        description="Legacy function",
        deprecated=True,
        deprecation_message="Use new_function instead for better performance",
    )

    assert metadata.deprecated is True
    assert metadata.deprecation_message == "Use new_function instead for better performance"


def test_registry_metadata_all_fields() -> None:
    """Test creating RegistryMetadata with all fields populated."""
    metadata = RegistryMetadata(
        title="Complete Example",
        description="Example with all fields",
        tags=["example", "test"],
        deprecated=True,
        deprecation_message="Deprecated",
    )

    assert metadata.title == "Complete Example"
    assert metadata.description == "Example with all fields"
    assert metadata.tags == ["example", "test"]
    assert metadata.deprecated is True
    assert metadata.deprecation_message == "Deprecated"


def test_registry_metadata_title_defaults_to_none() -> None:
    """Test that RegistryMetadata title defaults to None when not provided."""
    metadata = RegistryMetadata(description="Has description")
    assert metadata.title is None
    assert metadata.description == "Has description"


def test_registry_metadata_description_defaults_to_none() -> None:
    """Test that RegistryMetadata description defaults to None."""
    metadata = RegistryMetadata(title="Has title")
    assert metadata.title == "Has title"
    assert metadata.description is None


def test_registry_metadata_minimal_creation() -> None:
    """Test that RegistryMetadata can be created with no arguments."""
    metadata = RegistryMetadata()
    assert metadata.title is None
    assert metadata.description is None
    assert metadata.tags == []
    assert metadata.deprecated is False
    assert metadata.deprecation_message is None


def test_registry_metadata_serialization() -> None:
    """Test that RegistryMetadata can be serialized to dict."""
    metadata = RegistryMetadata(
        title="Serialize Test",
        description="Test serialization",
        tags=["test"],
        deprecated=True,
        deprecation_message="Use v2",
    )

    data = metadata.model_dump()
    assert data["title"] == "Serialize Test"
    assert data["description"] == "Test serialization"
    assert data["tags"] == ["test"]
    assert data["deprecated"] is True
    assert data["deprecation_message"] == "Use v2"


def test_registry_entry_minimal() -> None:
    """Test creating RegistryEntry with minimal fields."""
    metadata = RegistryMetadata(title="Test", description="Test function")

    def sample_func(x: int) -> str:
        return str(x)

    entry = RegistryEntry(
        metadata=metadata,
        module_path="myapp.tasks",
        function_name="test_func",
    )
    entry._func_ref = sample_func

    assert entry.metadata == metadata
    assert entry.module_path == "myapp.tasks"
    assert entry.function_name == "test_func"
    # json_schema is generated lazily
    assert isinstance(entry.json_schema, dict)


def test_registry_entry_fully_qualified_name() -> None:
    """Test the fully_qualified_name computed property."""
    metadata = RegistryMetadata(title="Test", description="Test")
    entry = RegistryEntry(
        metadata=metadata,
        module_path="mypackage.submodule.tasks",
        function_name="process_data",
    )

    assert entry.fully_qualified_name == "mypackage.submodule.tasks.process_data"


def test_registry_entry_import_statement() -> None:
    """Test the import_statement computed property."""
    metadata = RegistryMetadata(title="Test", description="Test")
    entry = RegistryEntry(
        metadata=metadata,
        module_path="mypackage.utils",
        function_name="helper_function",
    )

    assert entry.import_statement == "from mypackage.utils import helper_function"


def test_registry_entry_with_complex_schema() -> None:
    """Test RegistryEntry with complex types generates schema."""
    metadata = RegistryMetadata(
        title="Complex Function", description="Function with complex schema"
    )

    def create_user(name: str, age: int, email: str) -> dict[str, str | int]:
        return {"name": name, "age": age, "email": email}

    entry = RegistryEntry(metadata=metadata, module_path="app.users", function_name="create_user")
    entry._func_ref = create_user

    # Schema is generated lazily
    schema = entry.json_schema
    assert isinstance(schema, dict)
    # Verify it's a valid Pydantic schema (has type or $defs)
    assert "type" in schema or "$defs" in schema


def test_registry_entry_serialization() -> None:
    """Test that RegistryEntry can be serialized to dict."""
    metadata = RegistryMetadata(
        title="Serialize Entry", description="Test entry serialization", tags=["test"]
    )
    entry = RegistryEntry(
        metadata=metadata,
        module_path="test.module",
        function_name="serialize_test",
    )

    data = entry.model_dump()
    assert data["metadata"]["title"] == "Serialize Entry"
    assert data["module_path"] == "test.module"
    assert data["function_name"] == "serialize_test"
    # json_schema is a property, not a field, so it's not included in model_dump
    assert "json_schema" not in data


def test_registry_entry_json_mode_serialization() -> None:
    """Test that RegistryEntry can be serialized in JSON mode."""
    metadata = RegistryMetadata(title="JSON Test", description="Test JSON serialization")
    entry = RegistryEntry(
        metadata=metadata,
        module_path="test.json",
        function_name="json_test",
    )

    data = entry.model_dump(mode="json")
    assert isinstance(data, dict)
    assert data["metadata"]["title"] == "JSON Test"
    assert data["module_path"] == "test.json"


def test_registry_entry_validation_missing_metadata() -> None:
    """Test that RegistryEntry requires metadata field."""
    with pytest.raises(PydanticValidationError) as exc_info:
        RegistryEntry(  # type: ignore
            module_path="test", function_name="func", json_schema={}
        )

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("metadata",) for error in errors)


def test_registry_entry_validation_missing_module_path() -> None:
    """Test that RegistryEntry requires module_path field."""
    metadata = RegistryMetadata(title="Test", description="Test")
    with pytest.raises(PydanticValidationError) as exc_info:
        RegistryEntry(metadata=metadata, function_name="func", json_schema={})  # type: ignore

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("module_path",) for error in errors)


def test_registry_entry_validation_missing_function_name() -> None:
    """Test that RegistryEntry requires function_name field."""
    metadata = RegistryMetadata(title="Test", description="Test")
    with pytest.raises(PydanticValidationError) as exc_info:
        RegistryEntry(metadata=metadata, module_path="test", json_schema={})  # type: ignore

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("function_name",) for error in errors)


def test_registry_entry_validation_missing_func_ref() -> None:
    """Test that accessing json_schema without _func_ref raises AttributeError."""
    metadata = RegistryMetadata(title="Test", description="Test")
    entry = RegistryEntry(metadata=metadata, module_path="test", function_name="func")

    # Accessing json_schema without setting _func_ref should raise AttributeError
    with pytest.raises(AttributeError) as exc_info:
        _ = entry.json_schema

    assert "function reference not set" in str(exc_info.value)


def test_registry_entry_json_schema_surfaces_field_metadata() -> None:
    """Test that RegistryEntry.json_schema surfaces Annotated Field descriptions and titles."""
    metadata = RegistryMetadata(title="Test", description="Test function")

    def func_with_annotations(
        x: Annotated[int, Field(description="An integer", title="X Value")],
        y: Annotated[str, Field(description="A string")],
        z: Annotated[float, Field(default=3.14, json_schema_extra={"ecoscope:advanced": True})],
    ) -> bool:
        return True

    entry = RegistryEntry(
        metadata=metadata,
        module_path="test.module",
        function_name="func_with_annotations",
    )
    entry._func_ref = func_with_annotations

    schema = entry.json_schema
    assert schema["properties"]["x"]["description"] == "An integer"
    assert schema["properties"]["x"]["title"] == "X Value"
    assert schema["properties"]["y"]["description"] == "A string"
    assert schema["properties"]["z"]["default"] == 3.14
    assert schema["properties"]["z"]["ecoscope:advanced"] is True
