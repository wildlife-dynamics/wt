"""Tests for global registry functions."""

import json

import pytest

from wt_registry.exceptions import DuplicateRegistrationError
from wt_registry.models import RegistryEntry, RegistryMetadata
from wt_registry.registry import clear_registry, get_registry, register_entry, to_json


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    """Clear the registry before each test for isolation."""
    clear_registry()


def test_register_entry_adds_to_registry() -> None:
    """Test that register_entry adds an entry to the registry."""
    metadata = RegistryMetadata(title="Test", description="Test function")
    entry = RegistryEntry(
        metadata=metadata,
        module_path="test.module",
        function_name="test_func",
        json_schema={},
    )

    register_entry(entry)
    registry = get_registry()

    assert len(registry) == 1
    assert "test.module.test_func" in registry


def test_register_entry_duplicate_raises_error() -> None:
    """Test that registering the same function twice raises DuplicateRegistrationError."""
    metadata = RegistryMetadata(title="Test", description="Test function")
    entry = RegistryEntry(
        metadata=metadata,
        module_path="test.module",
        function_name="duplicate_func",
        json_schema={},
    )

    register_entry(entry)

    with pytest.raises(DuplicateRegistrationError) as exc_info:
        register_entry(entry)

    assert "test.module.duplicate_func" in str(exc_info.value)
    assert "already registered" in str(exc_info.value)


def test_register_multiple_entries() -> None:
    """Test registering multiple different entries."""
    entries = [
        RegistryEntry(
            metadata=RegistryMetadata(title=f"Func{i}", description=f"Function {i}"),
            module_path="test.module",
            function_name=f"func_{i}",
            json_schema={},
        )
        for i in range(5)
    ]

    for entry in entries:
        register_entry(entry)

    registry = get_registry()
    assert len(registry) == 5
    for i in range(5):
        assert f"test.module.func_{i}" in registry


def test_get_registry_returns_immutable_view() -> None:
    """Test that get_registry returns an immutable MappingProxyType."""
    metadata = RegistryMetadata(title="Test", description="Test")
    entry = RegistryEntry(
        metadata=metadata, module_path="test", function_name="func", json_schema={}
    )
    register_entry(entry)

    registry = get_registry()

    # Should not be able to modify the registry directly
    with pytest.raises(TypeError):
        registry["new.func"] = entry  # type: ignore


def test_get_registry_reflects_additions() -> None:
    """Test that get_registry reflects new additions to the registry."""
    registry1 = get_registry()
    assert len(registry1) == 0

    metadata = RegistryMetadata(title="Test", description="Test")
    entry = RegistryEntry(
        metadata=metadata, module_path="test", function_name="func", json_schema={}
    )
    register_entry(entry)

    registry2 = get_registry()
    assert len(registry2) == 1
    assert "test.func" in registry2


def test_clear_registry_removes_all_entries() -> None:
    """Test that clear_registry removes all entries."""
    # Add multiple entries
    for i in range(3):
        metadata = RegistryMetadata(title=f"Func{i}", description=f"Function {i}")
        entry = RegistryEntry(
            metadata=metadata, module_path="test", function_name=f"func_{i}", json_schema={}
        )
        register_entry(entry)

    assert len(get_registry()) == 3

    clear_registry()
    assert len(get_registry()) == 0


def test_to_json_empty_registry() -> None:
    """Test to_json with an empty registry."""
    json_str = to_json()
    data = json.loads(json_str)

    assert data == {}


def test_to_json_single_entry() -> None:
    """Test to_json with a single entry."""
    metadata = RegistryMetadata(
        title="JSON Test",
        description="Test JSON serialization",
        tags=["test", "json"],
    )

    def json_func(x: int) -> dict[str, int]:
        return {"x": x}

    entry = RegistryEntry(
        metadata=metadata,
        module_path="test.json",
        function_name="json_func",
    )
    entry._func_ref = json_func
    register_entry(entry)

    json_str = to_json()
    data = json.loads(json_str)

    assert "test.json.json_func" in data
    assert data["test.json.json_func"]["metadata"]["title"] == "JSON Test"
    assert data["test.json.json_func"]["metadata"]["tags"] == ["test", "json"]
    assert data["test.json.json_func"]["module_path"] == "test.json"
    assert data["test.json.json_func"]["function_name"] == "json_func"
    # json_schema is generated lazily and included in JSON output
    assert "json_schema" in data["test.json.json_func"]
    assert isinstance(data["test.json.json_func"]["json_schema"], dict)


def test_to_json_multiple_entries() -> None:
    """Test to_json with multiple entries."""

    def sample_func(x: int) -> str:
        return str(x)

    entries = []
    for i in range(3):
        entry = RegistryEntry(
            metadata=RegistryMetadata(title=f"Func{i}", description=f"Function {i}"),
            module_path="test.module",
            function_name=f"func_{i}",
        )
        entry._func_ref = sample_func
        entries.append(entry)

    for entry in entries:
        register_entry(entry)

    json_str = to_json()
    data = json.loads(json_str)

    assert len(data) == 3
    for i in range(3):
        fqn = f"test.module.func_{i}"
        assert fqn in data
        assert data[fqn]["metadata"]["title"] == f"Func{i}"


def test_to_json_with_deprecated_function() -> None:
    """Test to_json correctly serializes deprecated functions."""
    metadata = RegistryMetadata(
        title="Deprecated Function",
        description="This function is deprecated",
        deprecated=True,
        deprecation_message="Use new_function instead",
    )

    def old_func(x: int) -> int:
        return x

    entry = RegistryEntry(
        metadata=metadata,
        module_path="test.deprecated",
        function_name="old_func",
    )
    entry._func_ref = old_func
    register_entry(entry)

    json_str = to_json()
    data = json.loads(json_str)

    assert data["test.deprecated.old_func"]["metadata"]["deprecated"] is True
    assert (
        data["test.deprecated.old_func"]["metadata"]["deprecation_message"]
        == "Use new_function instead"
    )


def test_to_json_is_valid_json() -> None:
    """Test that to_json produces valid JSON."""
    metadata = RegistryMetadata(title="Valid JSON", description="Test valid JSON output")

    def valid_func(x: int) -> str:
        return str(x)

    entry = RegistryEntry(
        metadata=metadata,
        module_path="test.valid",
        function_name="valid_func",
    )
    entry._func_ref = valid_func
    register_entry(entry)

    json_str = to_json()

    # Should not raise an exception
    data = json.loads(json_str)
    assert isinstance(data, dict)


def test_registry_entry_retrieval() -> None:
    """Test retrieving a specific entry from the registry."""
    metadata = RegistryMetadata(
        title="Retrieve Test",
        description="Test retrieving entry",
        tags=["retrieval"],
    )
    entry = RegistryEntry(
        metadata=metadata,
        module_path="test.retrieve",
        function_name="retrieve_func",
        json_schema={"type": "object"},
    )
    register_entry(entry)

    registry = get_registry()
    retrieved = registry["test.retrieve.retrieve_func"]

    assert retrieved.metadata.title == "Retrieve Test"
    assert retrieved.metadata.description == "Test retrieving entry"
    assert retrieved.metadata.tags == ["retrieval"]
    assert retrieved.module_path == "test.retrieve"
    assert retrieved.function_name == "retrieve_func"


def test_registry_iteration() -> None:
    """Test iterating over registry entries."""
    entries = [
        RegistryEntry(
            metadata=RegistryMetadata(title=f"Func{i}", description=f"Function {i}"),
            module_path="test.iter",
            function_name=f"func_{i}",
            json_schema={},
        )
        for i in range(3)
    ]

    for entry in entries:
        register_entry(entry)

    registry = get_registry()
    fqns = list(registry.keys())

    assert len(fqns) == 3
    assert "test.iter.func_0" in fqns
    assert "test.iter.func_1" in fqns
    assert "test.iter.func_2" in fqns


def test_registry_values_iteration() -> None:
    """Test iterating over registry values."""
    metadata = RegistryMetadata(title="Values Test", description="Test values iteration")
    entry = RegistryEntry(
        metadata=metadata,
        module_path="test.values",
        function_name="values_func",
        json_schema={},
    )
    register_entry(entry)

    registry = get_registry()
    values = list(registry.values())

    assert len(values) == 1
    assert values[0].metadata.title == "Values Test"


def test_registry_items_iteration() -> None:
    """Test iterating over registry items."""
    metadata = RegistryMetadata(title="Items Test", description="Test items iteration")
    entry = RegistryEntry(
        metadata=metadata,
        module_path="test.items",
        function_name="items_func",
        json_schema={},
    )
    register_entry(entry)

    registry = get_registry()
    items = list(registry.items())

    assert len(items) == 1
    fqn, entry_value = items[0]
    assert fqn == "test.items.items_func"
    assert entry_value.metadata.title == "Items Test"
