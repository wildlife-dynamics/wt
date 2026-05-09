"""JSON schema generation with proper Field() metadata surfacing.

Workaround for https://github.com/pydantic/pydantic/issues/9404 where
Pydantic's default TypeAdapter.json_schema() does not surface descriptions,
titles, defaults, or json_schema_extra from Annotated[T, Field(...)] types.
"""

from collections.abc import Callable
from inspect import signature
from typing import Any, Literal, get_args

from pydantic import BaseModel, TypeAdapter
from pydantic.fields import FieldInfo
from pydantic.json_schema import GenerateJsonSchema
from pydantic_core import PydanticUndefined


# Workaround for https://github.com/pydantic/pydantic/issues/9404
class SurfacesDescriptionSchema(GenerateJsonSchema):
    """Custom JSON schema generator that surfaces field descriptions.

    This is a workaround for Pydantic issue #9404 where field descriptions
    from Annotated types are not properly surfaced in the JSON schema.
    """

    def generate(
        self,
        schema: Any,  # noqa: ANN401  # Pydantic CoreSchema is dynamic
        mode: Literal["validation", "serialization"] = "validation",
    ) -> dict[str, Any]:
        """Generate JSON schema with proper field descriptions."""
        json_schema = super().generate(schema, mode=mode)
        if "schema" in schema:
            schema = schema["schema"]
        if "function" in schema and "properties" in json_schema:
            for p in json_schema["properties"].copy():
                annotation_args = get_args(signature(schema["function"]).parameters[p].annotation)
                if any(isinstance(arg, FieldInfo) for arg in annotation_args):
                    field_info: FieldInfo = next(
                        arg for arg in annotation_args if isinstance(arg, FieldInfo)
                    )
                    if isinstance(field_info.default, BaseModel):
                        json_schema["properties"][p]["default"] = field_info.default.model_dump()
                    elif field_info.default is not PydanticUndefined:
                        json_schema["properties"][p]["default"] = field_info.default
                    if field_info.description is not None:
                        json_schema["properties"][p]["description"] = field_info.description
                    if field_info.title is not None:
                        json_schema["properties"][p]["title"] = field_info.title
                    if field_info.json_schema_extra:
                        match field_info.json_schema_extra:
                            case dict():
                                json_schema["properties"][p] |= field_info.json_schema_extra
                            case func if callable(func):
                                field_info.json_schema_extra(json_schema["properties"][p])
                    if field_info.exclude:
                        del json_schema["properties"][p]
        return json_schema


def jsonschema_from_task_func(func: Callable[..., Any]) -> dict[str, Any]:
    """Generate a JSON schema from the type annotations of a task function.

    Uses SurfacesDescriptionSchema to ensure that Field() metadata
    (descriptions, titles, defaults, json_schema_extra) is properly
    surfaced in the generated schema.

    Args:
        func: The function to generate a schema for

    Returns:
        A JSON schema dictionary

    Examples:
        >>> def example_func(x: int, y: str = "default") -> bool:
        ...     return True
        >>> schema = jsonschema_from_task_func(example_func)
        >>> "properties" in schema
        True
        >>> "x" in schema["properties"]
        True
    """
    ta: TypeAdapter[Callable[..., Any]] = TypeAdapter(
        func, config={"arbitrary_types_allowed": True}
    )
    return ta.json_schema(
        # NOTE: SurfacesDescriptionSchema is a workaround for
        # https://github.com/pydantic/pydantic/issues/9404
        # Once that issue is closed, we can remove SurfacesDescriptionSchema
        # and use the default schema_generator.
        schema_generator=SurfacesDescriptionSchema,
        # mode="serialization" is required for `AdvancedField`s to be
        # correctly excluded from the schema for nested models
        mode="serialization",
    )
