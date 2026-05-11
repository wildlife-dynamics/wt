"""JSON schema utilities for React JSON Schema Form integration."""
# ruff: noqa: N801, N815  # class/field names mirror JSON Schema spec (oneOf, uiSchema, additionalProperties)

import copy
from typing import Any, Literal

from pydantic import BaseModel, Field, model_serializer


def find_referenced_defs(json_schema: dict[str, Any]) -> set[str]:
    """Recursively search through a JSON schema and return referenced definitions.

    Finds all $ref references in the schema and returns the set of definition names.

    Args:
        json_schema: A JSON schema dictionary with $defs

    Returns:
        Set of referenced definition names

    Examples:
        >>> schema = {
        ...     "properties": {
        ...         "field1": {"$ref": "#/$defs/MyModel"},
        ...         "field2": {"type": "string"}
        ...     },
        ...     "$defs": {
        ...         "MyModel": {
        ...             "properties": {
        ...                 "nested": {"$ref": "#/$defs/NestedModel"}
        ...             }
        ...         },
        ...         "NestedModel": {
        ...             "properties": {"value": {"type": "int"}}
        ...         }
        ...     }
        ... }
        >>> refs = find_referenced_defs(schema)
        >>> "MyModel" in refs
        True
        >>> "NestedModel" in refs
        True
    """

    def _find_refs(obj: Any, refs: set[str]) -> None:  # noqa: ANN401  # walks arbitrary JSON
        if isinstance(obj, dict):
            if "$ref" in obj:
                assert isinstance(obj["$ref"], str)  # noqa: S101  # type narrowing for mypy
                ref = obj["$ref"].removeprefix("#/$defs/")
                refs.add(ref)
                if json_schema["$defs"][ref].get("properties"):
                    _find_refs(json_schema["$defs"][ref]["properties"], refs)
            else:
                for v in obj.values():
                    _find_refs(v, refs)
        elif isinstance(obj, list):
            for item in obj:
                _find_refs(item, refs)
        else:
            return

    properties_refs: set[str] = set()
    _find_refs(json_schema["properties"], properties_refs)

    return properties_refs


class oneOf(BaseModel):
    """Model representing the oneOf field in a JSON schema.

    Args:
        const: The value that will appear in the form data
        title: The user-facing name that will appear in the input widget
    """

    const: Any
    title: str


class RJSFFilterProperty(BaseModel):
    """Model representing properties of a React JSON Schema Form filter.

    This model is used to generate the `properties` field for a filter schema.

    Args:
        type: The type of the filter property
        title: The title of the filter property
        oneOf: The possible values for the filter property
        default: The default value for the filter property
    """

    type: str
    title: str
    oneOf: list[oneOf]
    default: str


class RJSFFilterUiSchema(BaseModel):
    """Model representing the UI schema of a React JSON Schema Form filter.

    This model is used to generate the `uiSchema` field for a filter schema.

    Args:
        title: The title of the filter
        help: The help text for the filter
        widget: The widget type (default: "select")
    """

    title: str
    help: str | None = None
    widget: Literal["select"] = "select"

    @model_serializer
    def ser_model(self) -> dict[str, Any]:
        """Serialize to RJSF uiSchema format."""
        return {
            "ui:title": self.title,
            "ui:widget": self.widget,
        } | ({"ui:help": self.help} if self.help else {})


class RJSFFilter(BaseModel):
    """Model representing a React JSON Schema Form filter."""

    property: RJSFFilterProperty
    uiSchema: RJSFFilterUiSchema


class ReactJSONSchemaFormFilters(BaseModel):
    """Collection of RJSF filters."""

    options: dict[str, RJSFFilter]

    @property
    def _schema(self) -> dict[str, Any]:
        """Generate the complete filter schema."""
        return {
            "type": "object",
            "properties": {opt: rjsf.property.model_dump() for opt, rjsf in self.options.items()},
            "uiSchema": {opt: rjsf.uiSchema.model_dump() for opt, rjsf in self.options.items()},
        }

    @model_serializer
    def ser_model(self) -> dict[str, Any]:
        """Serialize to RJSF format."""
        return {"schema": self._schema}


class ReactJSONSchemaFormConfiguration(BaseModel):
    """Complete React JSON Schema Form configuration.

    Args:
        title: The form title
        properties: The form properties (JSON schema)
        definitions: The JSON schema definitions ($defs)
        uiSchema: The UI schema for the form
        additionalProperties: Whether additional properties are allowed
    """

    title: str | None
    properties: dict[str, Any]
    definitions: dict[str, Any] = Field(alias="$defs", default_factory=dict)
    uiSchema: dict[str, Any]
    additionalProperties: bool = False


def _apply_dict_overrides(
    dotted_key_dict: dict[str, Any], target_dict: dict[str, Any]
) -> dict[str, Any]:
    """Replace the value of arbitrarily nested keys in a dictionary.

    Args:
        dotted_key_dict: A dictionary where keys are dotted paths and values are new values
        target_dict: The dictionary to update

    Returns:
        The updated dictionary

    Examples:
        Simple override:

        >>> _apply_dict_overrides({'a.b': 1}, {'a': {'b': 2}})
        {'a': {'b': 1}}

        Adding new key:

        >>> _apply_dict_overrides({'a.b': 1}, {'a': {'c': 2}})
        {'a': {'c': 2, 'b': 1}}

        Deep nesting:

        >>> _apply_dict_overrides({'a.b.c': 1}, {'a': {'b': {'c': 2}}})
        {'a': {'b': {'c': 1}}}
    """

    def set_nested_value(d: dict[str, Any], keys: list[str], value: Any) -> None:  # noqa: ANN401  # accepts any JSON value
        for key in keys[:-1]:
            d = d.setdefault(key, {})
        d[keys[-1]] = value

    for dotted_key, value in dotted_key_dict.items():
        keys = dotted_key.split(".")
        set_nested_value(target_dict, keys, value)

    return target_dict


class ReactJSONSchemaFormOverrides(BaseModel):
    """Overrides for React JSON Schema Form configuration.

    Allows selective overriding of properties, definitions, and uiSchema
    using dotted key notation (e.g., "a.b.c" to override nested value).

    Args:
        properties: Property overrides using dotted keys
        definitions: Definition ($defs) overrides using dotted keys
        uiSchema: UI schema overrides using dotted keys
    """

    properties: dict[str, Any] = Field(default_factory=dict)
    definitions: dict[str, Any] = Field(alias="$defs", default_factory=dict)
    uiSchema: dict[str, Any] = Field(default_factory=dict)

    def apply_overrides(
        self,
        initial: ReactJSONSchemaFormConfiguration,
    ) -> ReactJSONSchemaFormConfiguration:
        """Construct a new ReactJSONSchemaFormConfiguration with overrides applied.

        Args:
            initial: The initial configuration to override

        Returns:
            A new configuration with overrides applied

        Examples:
            >>> initial = ReactJSONSchemaFormConfiguration(
            ...     title="Test",
            ...     properties={"a": {"b": 1}},
            ...     **{"$defs":{"c": {"d": 2}}},
            ...     uiSchema={"e": {"f": 3}},
            ... )
            >>> overrides = ReactJSONSchemaFormOverrides(
            ...     properties={"a.b": 4},
            ...     **{"$defs":{"c.d": 5}},
            ...     uiSchema={"e.f": 6},
            ... )
            >>> rjsf = overrides.apply_overrides(initial)
            >>> rjsf.title
            'Test'
            >>> rjsf.properties
            {'a': {'b': 4}}
            >>> rjsf.definitions
            {'c': {'d': 5}}
            >>> rjsf.uiSchema
            {'e': {'f': 6}}
            >>> rjsf.additionalProperties
            False
        """
        initial_props = copy.deepcopy(initial.properties)
        initial_defs = copy.deepcopy(initial.definitions)
        initial_uischema = copy.deepcopy(initial.uiSchema)
        return ReactJSONSchemaFormConfiguration(
            title=initial.title,
            properties=_apply_dict_overrides(self.properties, initial_props),
            **{"$defs": _apply_dict_overrides(self.definitions, initial_defs)},
            uiSchema=_apply_dict_overrides(self.uiSchema, initial_uischema),
            additionalProperties=initial.additionalProperties,
        )

    def apply_defs_only(
        self,
        initial: ReactJSONSchemaFormConfiguration,
    ) -> ReactJSONSchemaFormConfiguration:
        """Apply only $defs overrides; leave properties and uiSchema untouched.

        Used for the flat ``params.json`` artifact, whose top-level shape
        differs from the hierarchical ``rjsf.json`` so ``properties.*`` and
        ``uiSchema`` overrides written for the hierarchical layout would
        silently mis-target. ``$defs`` is shared between the two artifacts,
        so its overrides apply cleanly to both.

        Args:
            initial: The initial configuration to override

        Returns:
            A new configuration with only ``$defs`` overrides applied
        """
        initial_defs = copy.deepcopy(initial.definitions)
        return ReactJSONSchemaFormConfiguration(
            title=initial.title,
            properties=initial.properties,
            **{"$defs": _apply_dict_overrides(self.definitions, initial_defs)},
            uiSchema=initial.uiSchema,
            additionalProperties=initial.additionalProperties,
        )
