"""Tests for wt_registry.jsonschema - JSON schema generation with Field() metadata."""

from typing import Annotated

import pytest

from pydantic import Field

from wt_registry.jsonschema import jsonschema_from_task_func


class TestJsonSchemaFromTaskFunc:
    """Tests for jsonschema_from_task_func."""

    def test_simple_function(self) -> None:
        """Test schema generation from a simple function."""

        def simple_func(x: int, y: str) -> bool:
            return True

        schema = jsonschema_from_task_func(simple_func)
        assert "properties" in schema
        assert "x" in schema["properties"]
        assert "y" in schema["properties"]

    def test_function_with_defaults(self) -> None:
        """Test schema generation with default values."""

        def func_with_defaults(x: int, y: str = "default") -> int:
            return x

        schema = jsonschema_from_task_func(func_with_defaults)
        assert schema["properties"]["y"].get("default") == "default"
        assert "x" in schema.get("required", [])
        assert "y" not in schema.get("required", [])

    def test_annotated_field_description(self) -> None:
        """Test that Field(description=...) is surfaced in schema."""

        def func(
            x: Annotated[int, Field(description="An integer value")],
        ) -> bool:
            return True

        schema = jsonschema_from_task_func(func)
        assert schema["properties"]["x"]["description"] == "An integer value"

    def test_annotated_field_title(self) -> None:
        """Test that Field(title=...) is surfaced in schema."""

        def func(
            x: Annotated[int, Field(title="Custom Title")],
        ) -> bool:
            return True

        schema = jsonschema_from_task_func(func)
        assert schema["properties"]["x"]["title"] == "Custom Title"

    def test_annotated_field_description_and_title(self) -> None:
        """Test that both description and title are surfaced."""

        def func(
            x: Annotated[int, Field(description="An integer", title="My Int")],
            y: Annotated[str, Field(description="A string", title="My Str")],
        ) -> bool:
            return True

        schema = jsonschema_from_task_func(func)
        assert schema["properties"]["x"]["description"] == "An integer"
        assert schema["properties"]["x"]["title"] == "My Int"
        assert schema["properties"]["y"]["description"] == "A string"
        assert schema["properties"]["y"]["title"] == "My Str"

    def test_annotated_field_default(self) -> None:
        """Test that Field(default=...) is surfaced in schema."""

        def func(
            x: Annotated[int, Field(default=42, description="Has default")],
        ) -> int:
            return x

        schema = jsonschema_from_task_func(func)
        assert schema["properties"]["x"]["default"] == 42
        assert schema["properties"]["x"]["description"] == "Has default"

    def test_annotated_field_json_schema_extra_dict(self) -> None:
        """Test that json_schema_extra dict attributes (e.g. ecoscope:advanced) are surfaced."""

        def func(
            x: Annotated[
                int,
                Field(
                    description="Advanced param",
                    json_schema_extra={"ecoscope:advanced": True},
                ),
            ],
        ) -> int:
            return x

        schema = jsonschema_from_task_func(func)
        assert schema["properties"]["x"]["ecoscope:advanced"] is True
        assert schema["properties"]["x"]["description"] == "Advanced param"

    def test_annotated_field_json_schema_extra_callable(self) -> None:
        """Test that callable json_schema_extra is invoked."""

        def add_custom(schema: dict) -> None:
            schema["custom_key"] = "custom_value"

        def func(
            x: Annotated[int, Field(json_schema_extra=add_custom)],
        ) -> int:
            return x

        schema = jsonschema_from_task_func(func)
        assert schema["properties"]["x"]["custom_key"] == "custom_value"

    def test_annotated_field_exclude(self) -> None:
        """Test that Field(exclude=True) removes the field from schema."""

        def func(
            x: Annotated[int, Field(description="Visible")],
            y: Annotated[str, Field(exclude=True)],
        ) -> bool:
            return True

        schema = jsonschema_from_task_func(func)
        assert "x" in schema["properties"]
        assert "y" not in schema["properties"]

    def test_mixed_annotated_and_plain(self) -> None:
        """Test function with both Annotated and plain parameters."""

        def func(
            x: Annotated[int, Field(description="Annotated param")],
            y: str,
        ) -> bool:
            return True

        schema = jsonschema_from_task_func(func)
        assert schema["properties"]["x"]["description"] == "Annotated param"
        assert "y" in schema["properties"]
