"""Tests for registry contracts."""

import json

import pytest
from pydantic import ValidationError

from wt_contracts.registry import RegistryEntry, RegistryMetadata, RegistryOutput


class TestRegistryMetadata:
    """Tests for RegistryMetadata model."""

    def test_minimal_metadata(self) -> None:
        """Test creating metadata with only required fields."""
        metadata = RegistryMetadata(
            title="Test Function", description="A test function"
        )

        assert metadata.title == "Test Function"
        assert metadata.description == "A test function"
        assert metadata.tags == []
        assert metadata.deprecated is False
        assert metadata.deprecation_message is None

    def test_full_metadata(self) -> None:
        """Test creating metadata with all fields."""
        metadata = RegistryMetadata(
            title="Calculate Mean",
            description="Calculate arithmetic mean",
            tags=["statistics", "math"],
            deprecated=True,
            deprecation_message="Use calculate_mean_v2 instead",
        )

        assert metadata.title == "Calculate Mean"
        assert metadata.description == "Calculate arithmetic mean"
        assert metadata.tags == ["statistics", "math"]
        assert metadata.deprecated is True
        assert metadata.deprecation_message == "Use calculate_mean_v2 instead"

    def test_metadata_serialization(self) -> None:
        """Test JSON serialization and deserialization."""
        metadata = RegistryMetadata(
            title="Test", description="Test desc", tags=["tag1", "tag2"]
        )

        # Serialize to JSON
        json_str = metadata.model_dump_json()
        data = json.loads(json_str)

        # Verify structure
        assert data["title"] == "Test"
        assert data["description"] == "Test desc"
        assert data["tags"] == ["tag1", "tag2"]
        assert data["deprecated"] is False

        # Deserialize back
        metadata2 = RegistryMetadata.model_validate_json(json_str)
        assert metadata2.title == metadata.title
        assert metadata2.tags == metadata.tags

    def test_metadata_validation_error(self) -> None:
        """Test validation fails with missing required fields."""
        with pytest.raises(ValidationError) as exc_info:
            RegistryMetadata(title="Test")  # Missing description

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("description",)
        assert errors[0]["type"] == "missing"


class TestRegistryEntry:
    """Tests for RegistryEntry model."""

    def test_minimal_entry(self) -> None:
        """Test creating entry with minimal data."""
        entry = RegistryEntry(
            metadata=RegistryMetadata(title="Test", description="Test func"),
            module_path="mypackage.tasks",
            function_name="test_func",
            import_statement="from mypackage.tasks import test_func",
            json_schema={"type": "object", "properties": {}},
        )

        assert entry.function_name == "test_func"
        assert entry.module_path == "mypackage.tasks"
        assert entry.metadata.title == "Test"

    def test_entry_with_complex_schema(self) -> None:
        """Test entry with complex JSON schema."""
        schema = {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "First number"},
                "y": {"type": "integer", "description": "Second number"},
            },
            "required": ["x", "y"],
            "return": {"type": "integer", "description": "Sum of x and y"},
        }

        entry = RegistryEntry(
            metadata=RegistryMetadata(
                title="Add Numbers", description="Add two integers"
            ),
            module_path="math_utils",
            function_name="add",
            import_statement="from math_utils import add",
            json_schema=schema,
        )

        assert entry.json_schema["properties"]["x"]["type"] == "integer"
        assert "return" in entry.json_schema

    def test_entry_serialization_roundtrip(self) -> None:
        """Test complete serialization roundtrip."""
        entry = RegistryEntry(
            metadata=RegistryMetadata(
                title="Process Data",
                description="Process input data",
                tags=["data", "processing"],
            ),
            module_path="data.processors",
            function_name="process",
            import_statement="from data.processors import process",
            json_schema={
                "type": "object",
                "properties": {"data": {"type": "array"}},
            },
        )

        # Serialize
        json_str = entry.model_dump_json()

        # Deserialize
        entry2 = RegistryEntry.model_validate_json(json_str)

        # Verify
        assert entry2.function_name == entry.function_name
        assert entry2.module_path == entry.module_path
        assert entry2.metadata.title == entry.metadata.title
        assert entry2.metadata.tags == entry.metadata.tags

    def test_entry_validation_error(self) -> None:
        """Test validation fails with invalid data."""
        with pytest.raises(ValidationError):
            RegistryEntry(
                metadata="invalid",  # type: ignore[arg-type]  # Should be RegistryMetadata
                module_path="pkg",
                function_name="func",
                import_statement="import",
                json_schema={},
            )


class TestRegistryOutput:
    """Tests for RegistryOutput model."""

    def test_empty_registry(self) -> None:
        """Test creating empty registry output."""
        output = RegistryOutput(entries={})

        assert output.entries == {}
        assert output.version == "1.0.0"

    def test_registry_with_entries(self) -> None:
        """Test creating registry with multiple entries."""
        entry1 = RegistryEntry(
            metadata=RegistryMetadata(title="Func1", description="First function"),
            module_path="pkg.tasks",
            function_name="func1",
            import_statement="from pkg.tasks import func1",
            json_schema={},
        )

        entry2 = RegistryEntry(
            metadata=RegistryMetadata(title="Func2", description="Second function"),
            module_path="pkg.tasks",
            function_name="func2",
            import_statement="from pkg.tasks import func2",
            json_schema={},
        )

        output = RegistryOutput(
            entries={"pkg.tasks.func1": entry1, "pkg.tasks.func2": entry2}
        )

        assert len(output.entries) == 2
        assert "pkg.tasks.func1" in output.entries
        assert "pkg.tasks.func2" in output.entries
        assert output.entries["pkg.tasks.func1"].function_name == "func1"

    def test_registry_output_complete_roundtrip(self) -> None:
        """Test complete CLI output format roundtrip."""
        # Simulate CLI output
        cli_data = {
            "version": "1.0.0",
            "entries": {
                "mylib.calculate_mean": {
                    "metadata": {
                        "title": "Calculate Mean",
                        "description": "Calculate arithmetic mean of values",
                        "tags": ["statistics", "math"],
                        "deprecated": False,
                        "deprecation_message": None,
                    },
                    "module_path": "mylib.stats",
                    "function_name": "calculate_mean",
                    "import_statement": "from mylib.stats import calculate_mean",
                    "json_schema": {
                        "type": "object",
                        "properties": {
                            "values": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "List of numbers",
                            }
                        },
                        "required": ["values"],
                        "return": {"type": "number"},
                    },
                }
            },
        }

        # Parse as if from CLI output
        json_str = json.dumps(cli_data)
        output = RegistryOutput.model_validate_json(json_str)

        # Verify structure
        assert output.version == "1.0.0"
        assert "mylib.calculate_mean" in output.entries

        entry = output.entries["mylib.calculate_mean"]
        assert entry.metadata.title == "Calculate Mean"
        assert entry.metadata.tags == ["statistics", "math"]
        assert entry.function_name == "calculate_mean"
        assert entry.module_path == "mylib.stats"
        assert "values" in entry.json_schema["properties"]

        # Serialize back
        output_json = output.model_dump_json()
        output2 = RegistryOutput.model_validate_json(output_json)

        # Verify roundtrip
        assert output2.entries.keys() == output.entries.keys()

    def test_custom_version(self) -> None:
        """Test registry with custom version."""
        output = RegistryOutput(entries={}, version="2.0.0")

        assert output.version == "2.0.0"

    def test_registry_output_validation(self) -> None:
        """Test that registry validates entry structure."""
        # Valid entry
        valid_data = {
            "entries": {
                "pkg.func": {
                    "metadata": {"title": "Test", "description": "Test func"},
                    "module_path": "pkg",
                    "function_name": "func",
                    "import_statement": "from pkg import func",
                    "json_schema": {},
                }
            }
        }

        output = RegistryOutput.model_validate(valid_data)
        assert "pkg.func" in output.entries

        # Invalid entry (missing required field)
        invalid_data = {
            "entries": {
                "pkg.func": {
                    "metadata": {"title": "Test", "description": "Test func"},
                    # Missing module_path
                    "function_name": "func",
                    "import_statement": "from pkg import func",
                    "json_schema": {},
                }
            }
        }

        with pytest.raises(ValidationError):
            RegistryOutput.model_validate(invalid_data)
