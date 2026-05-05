"""Schema-driven conversion between flat ``params`` and grouped ``formdata`` dicts.

Workflow specs may organize tasks into named groups for the React JSON Schema
Form (RJSF) UI, but the executable DAG always consumes a flat mapping of
``task_id -> task_args``. This module provides the two conversion helpers
(``formdata_to_params``, ``params_to_formdata``) that translate between the
two shapes, plus a :class:`ValidationError` wrapper around
``jsonschema.Draft202012Validator``.

The conversion is purely structural: top-level keys in ``params_schema``
identify direct (flat) tasks, while any other top-level key in ``rjsf_schema``
is treated as a task group whose nested ``properties`` enumerate its tasks.
The helpers do not read RJSF custom keywords (e.g. ``ecoscope:task_group``);
group membership is inferred from schema structure alone.
"""

from typing import Any, TypedDict

import jsonschema
from pydantic import BaseModel, Field


class ValidationErrorItemDict(TypedDict):
    """JSON-serializable shape of a single jsonschema validation error.

    This is the wire shape emitted by :func:`_serialize_errors` and carried in
    :attr:`ValidationError.errors`. The :class:`ValidationErrorItem` Pydantic
    model below mirrors this shape for FastAPI/OpenAPI declarations. Field
    semantics and a worked example are documented on
    :class:`ValidationErrorItem`.
    """

    message: str
    path: list[str | int]
    schema_path: list[str | int]
    validator: str | None
    input: Any


class ValidationErrorItem(BaseModel):
    """One serialized jsonschema validation error, as carried in 422 responses.

    Each field corresponds 1:1 with the same key on
    :class:`ValidationErrorItemDict` (the wire dict produced by
    :func:`_serialize_errors`); see the ``Field(description=...)`` entries
    below for per-field semantics that also flow through to OpenAPI.
    """

    message: str = Field(description="Human-readable description of why validation failed.")
    path: list[str | int] = Field(
        description=(
            "Location of the failing instance, as a sequence of object keys / "
            "array indices from the root of the validated document."
        )
    )
    schema_path: list[str | int] = Field(
        description=(
            "Location of the failed keyword inside the JSON schema, as a "
            "sequence of keys / indices from the schema root."
        )
    )
    validator: str | None = Field(
        description=(
            "Name of the JSON Schema keyword that produced the error "
            "(e.g. ``type``, ``required``, ``enum``). May be ``None`` when "
            "jsonschema cannot attribute the failure to a specific keyword."
        )
    )
    input: Any = Field(description="The failing value from the validated document at ``path``.")


class ValidationErrorResponse(BaseModel):
    """422 response body shape for endpoints that surface jsonschema errors."""

    detail: list[ValidationErrorItem] = Field(
        description=(
            "List of jsonschema validation errors describing why the request body was rejected."
        )
    )


class ValidationError(Exception):
    """Raised when a dict fails JSON schema validation.

    Attributes:
        errors: List of serialized ``jsonschema`` errors. Each entry has
            ``message``, ``path``, ``schema_path``, ``validator``, and
            ``input`` keys (see :class:`ValidationErrorItemDict`).
    """

    def __init__(self, errors: list[ValidationErrorItemDict]):
        self.errors = errors
        super().__init__(f"{len(errors)} validation error(s): {errors}")


def _serialize_errors(
    errors: list[jsonschema.ValidationError],
) -> list[ValidationErrorItemDict]:
    return [
        {
            "message": e.message,
            "path": list(e.absolute_path),
            "schema_path": list(e.absolute_schema_path),
            # jsonschema's e.validator is `str | Unset`; coerce Unset to None for the wire shape.
            "validator": e.validator if isinstance(e.validator, str) else None,
            "input": e.instance,
        }
        for e in errors
    ]


def validate(instance: Any, schema: dict[str, Any]) -> None:
    """Validate ``instance`` against ``schema`` using JSON Schema Draft 2020-12.

    Args:
        instance: The value to validate. Callers (e.g. the compiled CLI that
            pipes ``json.loads`` output straight in) may pass non-dict values;
            since wt-compiler-emitted schemas omit a root ``"type": "object"``,
            an explicit ``isinstance`` check guards downstream consumers
            (``formdata_to_params`` / ``params_to_formdata``) that assume a
            mapping.
        schema: The JSON schema to validate against.

    Raises:
        ValidationError: If ``instance`` is not a dict, or does not validate
            against ``schema``. The exception's ``errors`` attribute contains
            a list of serialized validation errors with stable,
            JSON-serializable shape.

    Examples:
        Validating ``{"age": "old"}`` against a schema that requires an
        integer ``age`` raises :class:`ValidationError`; ``e.errors`` is the
        wire ``list[ValidationErrorItemDict]`` and round-trips cleanly through
        :class:`ValidationErrorItem`:

        >>> import json
        >>> from wt_contracts import ValidationError, ValidationErrorItem, validate
        >>> try:
        ...     validate({"age": "old"}, {"properties": {"age": {"type": "integer"}}})
        ... except ValidationError as e:
        ...     err = e.errors[0]
        >>> print(json.dumps(err, indent=2))
        {
          "message": "'old' is not of type 'integer'",
          "path": [
            "age"
          ],
          "schema_path": [
            "properties",
            "age",
            "type"
          ],
          "validator": "type",
          "input": "old"
        }
        >>> item = ValidationErrorItem(**err)
        >>> item.model_dump() == err
        True
    """
    if not isinstance(instance, dict):
        raise ValidationError(
            [
                {
                    "message": f"{instance!r} is not of type 'object'",
                    "path": [],
                    "schema_path": ["type"],
                    "validator": "type",
                    "input": instance,
                }
            ]
        )
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    if errors:
        raise ValidationError(_serialize_errors(errors))


def formdata_to_params(
    formdata: dict[str, Any],
    rjsf_schema: dict[str, Any],
    params_schema: dict[str, Any],
) -> dict[str, Any]:
    """Flatten grouped ``formdata`` into the flat ``params`` shape.

    ``formdata`` is validated against ``rjsf_schema``. Top-level keys present
    in ``params_schema["properties"]`` are direct task IDs and are copied as-is;
    every other top-level key is treated as a task group whose nested values
    are merged into the result.

    Args:
        formdata: User-supplied form data (possibly grouped).
        rjsf_schema: JSON schema describing ``formdata`` (with task groups).
        params_schema: JSON schema describing the flat params shape.

    Returns:
        Flat ``{task_id: task_args}`` dict.

    Raises:
        ValidationError: If ``formdata`` does not validate against ``rjsf_schema``.
    """
    validate(formdata, rjsf_schema)
    flat_keys = set(params_schema.get("properties", {}).keys())
    out: dict[str, Any] = {}
    for k, v in formdata.items():
        if k in flat_keys:
            out[k] = v
        else:
            # rjsf schema groups are flat: inner keys are validated as task IDs
            # by the preceding validate() call, so no recursion is needed.
            for inner_k, inner_v in v.items():
                out[inner_k] = inner_v
    return out


def params_to_formdata(
    params: dict[str, Any],
    rjsf_schema: dict[str, Any],
    params_schema: dict[str, Any],
) -> dict[str, Any]:
    """Group flat ``params`` into the nested ``formdata`` shape.

    ``params`` is validated against ``params_schema``. Each key is then placed
    either directly on the result (if the same key exists at the top level of
    ``rjsf_schema``) or nested inside the task group whose ``properties``
    contain the key.

    Args:
        params: Flat ``{task_id: task_args}`` dict.
        rjsf_schema: JSON schema describing the grouped formdata shape.
        params_schema: JSON schema describing the flat params shape.

    Returns:
        Possibly-grouped formdata dict.

    Raises:
        ValidationError: If ``params`` does not validate against ``params_schema``.
        KeyError: If a key in ``params`` cannot be located in ``rjsf_schema``.
    """
    validate(params, params_schema)
    rjsf_props: dict[str, Any] = rjsf_schema.get("properties", {})
    task_groups: dict[str, list[str]] = {}
    for name, sub in rjsf_props.items():
        if isinstance(sub, dict) and isinstance(sub.get("properties"), dict):
            task_groups[name] = list(sub["properties"].keys())

    out: dict[str, Any] = {}
    for k, v in params.items():
        if k in rjsf_props and k not in task_groups:
            out[k] = v
            continue
        if k in rjsf_props and k in task_groups:
            # k is itself a group name in rjsf -- shouldn't happen for flat params,
            # but if so, treat it as direct.
            out[k] = v
            continue
        # find the group that lists k as a member
        owning_group = next((g for g, members in task_groups.items() if k in members), None)
        if owning_group is None:
            raise KeyError(f"Key {k!r} is not present in rjsf schema's flat or grouped properties.")
        out.setdefault(owning_group, {})[k] = v
    return out
