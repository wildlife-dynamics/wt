"""Tests for jsonschema.py - JSON schema utilities and RJSF support."""

import pytest
from typing import Annotated

from pydantic import Field

from wt_compiler.jsonschema import (
    find_referenced_defs,
    jsonschema_from_task_func,
    _apply_dict_overrides,
    ReactJSONSchemaFormConfiguration,
    ReactJSONSchemaFormOverrides,
)


class TestFindReferencedDefs:
    """Tests for find_referenced_defs function."""

    def test_find_simple_refs(self):
        """Test finding simple $ref references."""
        schema = {
            "properties": {
                "field1": {"$ref": "#/$defs/MyModel"},
                "field2": {"type": "string"},
            },
            "$defs": {
                "MyModel": {"properties": {"value": {"type": "integer"}}},
            },
        }
        refs = find_referenced_defs(schema)
        assert "MyModel" in refs

    def test_find_nested_refs(self):
        """Test finding nested $ref references."""
        schema = {
            "properties": {
                "field1": {"$ref": "#/$defs/MyModel"},
            },
            "$defs": {
                "MyModel": {
                    "properties": {"nested": {"$ref": "#/$defs/NestedModel"}}
                },
                "NestedModel": {"properties": {"value": {"type": "integer"}}},
                "UnusedModel": {"properties": {"unused": {"type": "string"}}},
            },
        }
        refs = find_referenced_defs(schema)
        assert "MyModel" in refs
        assert "NestedModel" in refs
        assert "UnusedModel" not in refs  # Not referenced

    def test_find_refs_in_arrays(self):
        """Test finding $refs in array items."""
        schema = {
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/Item"},
                },
            },
            "$defs": {
                "Item": {"properties": {"name": {"type": "string"}}},
            },
        }
        refs = find_referenced_defs(schema)
        assert "Item" in refs


class TestApplyDictOverrides:
    """Tests for _apply_dict_overrides function."""

    def test_simple_override(self):
        """Test simple one-level override."""
        result = _apply_dict_overrides({"a": 1}, {"a": 2, "b": 3})
        assert result == {"a": 1, "b": 3}

    def test_nested_override(self):
        """Test nested key override with dotted notation."""
        result = _apply_dict_overrides(
            {"a.b": 1}, {"a": {"b": 2, "c": 3}, "d": 4}
        )
        assert result == {"a": {"b": 1, "c": 3}, "d": 4}

    def test_deep_nested_override(self):
        """Test deeply nested override."""
        result = _apply_dict_overrides(
            {"a.b.c": 99}, {"a": {"b": {"c": 1, "d": 2}}}
        )
        assert result == {"a": {"b": {"c": 99, "d": 2}}}

    def test_create_new_key(self):
        """Test creating new nested key."""
        result = _apply_dict_overrides({"a.x": 10}, {"a": {"b": 1}})
        assert result == {"a": {"b": 1, "x": 10}}

    def test_create_deep_path(self):
        """Test creating entirely new nested path."""
        result = _apply_dict_overrides({"x.y.z": 5}, {})
        assert result == {"x": {"y": {"z": 5}}}


class TestJSONSchemaFromTaskFunc:
    """Tests for jsonschema_from_task_func."""

    def test_simple_function(self):
        """Test schema generation from simple function."""

        def simple_func(x: int, y: str) -> bool:
            return True

        schema = jsonschema_from_task_func(simple_func)
        assert "properties" in schema
        assert "x" in schema["properties"]
        assert "y" in schema["properties"]

    def test_function_with_defaults(self):
        """Test schema generation with default values."""

        def func_with_defaults(x: int, y: str = "default") -> int:
            return x

        schema = jsonschema_from_task_func(func_with_defaults)
        assert schema["properties"]["y"].get("default") == "default"
        assert "x" in schema.get("required", [])
        assert "y" not in schema.get("required", [])

    def test_function_with_annotated_field(self):
        """Test schema generation with Annotated[T, Field(...)]."""

        def annotated_func(
            x: Annotated[int, Field(description="An integer", ge=0, le=100)],
            y: Annotated[str, Field(description="A string", max_length=50)],
        ) -> bool:
            return True

        schema = jsonschema_from_task_func(annotated_func)
        assert "x" in schema["properties"]
        assert "y" in schema["properties"]
        # Check that Field metadata is included
        assert "description" in schema["properties"]["x"]
        assert schema["properties"]["x"]["description"] == "An integer"


class TestReactJSONSchemaFormConfiguration:
    """Tests for ReactJSONSchemaFormConfiguration."""

    def test_rjsf_config_creation(self):
        """Test creating RJSF configuration."""
        config = ReactJSONSchemaFormConfiguration(
            title="Test Form",
            properties={"field1": {"type": "string"}},
            uiSchema={"field1": {"ui:widget": "text"}},
        )
        assert config.title == "Test Form"
        assert "field1" in config.properties

    def test_rjsf_config_with_defs(self):
        """Test RJSF configuration with definitions."""
        config = ReactJSONSchemaFormConfiguration(
            title="Test Form",
            properties={"field1": {"$ref": "#/$defs/MyType"}},
            uiSchema={},
            **{"$defs": {"MyType": {"type": "object"}}},
        )
        assert config.definitions["MyType"]["type"] == "object"


class TestReactJSONSchemaFormOverrides:
    """Tests for ReactJSONSchemaFormOverrides."""

    def test_property_override(self):
        """Test overriding properties."""
        overrides = ReactJSONSchemaFormOverrides(
            properties={"task1.x.type": "number"}
        )
        config = ReactJSONSchemaFormConfiguration(
            title="Original",
            properties={"task1": {"x": {"type": "string"}}},
            uiSchema={},
        )
        updated = overrides.apply_overrides(config)
        assert updated.properties["task1"]["x"]["type"] == "number"

    def test_uischema_override(self):
        """Test overriding uiSchema."""
        overrides = ReactJSONSchemaFormOverrides(
            uiSchema={"task1.ui:widget": "textarea"}
        )
        config = ReactJSONSchemaFormConfiguration(
            title="Original",
            properties={"task1": {"type": "string"}},
            uiSchema={"task1": {"ui:widget": "text"}},
        )
        updated = overrides.apply_overrides(config)
        assert updated.uiSchema["task1"]["ui:widget"] == "textarea"

    def test_multiple_overrides(self):
        """Test applying multiple overrides at once."""
        overrides = ReactJSONSchemaFormOverrides(
            properties={"task1.type": "number"},
            uiSchema={"task1.ui:widget": "range"},
        )
        config = ReactJSONSchemaFormConfiguration(
            title="Original",
            properties={"task1": {"type": "string"}},
            uiSchema={},
        )
        updated = overrides.apply_overrides(config)
        assert updated.properties["task1"]["type"] == "number"
        assert updated.uiSchema["task1"]["ui:widget"] == "range"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
