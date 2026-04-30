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

from typing import Any

import jsonschema  # type: ignore[import-untyped]


class ValidationError(Exception):
    """Raised when a dict fails JSON schema validation.

    Attributes:
        errors: List of serialized ``jsonschema`` errors. Each entry has
            ``message``, ``path``, ``schema_path``, and ``validator`` keys.
    """

    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__(f"{len(errors)} validation error(s): {errors}")


def _serialize_errors(errors: list[jsonschema.ValidationError]) -> list[dict[str, Any]]:
    return [
        {
            "message": e.message,
            "path": list(e.absolute_path),
            "schema_path": list(e.absolute_schema_path),
            "validator": e.validator,
        }
        for e in errors
    ]


def _validate(instance: dict[str, Any], schema: dict[str, Any]) -> None:
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
    _validate(formdata, rjsf_schema)
    flat_keys = set(params_schema.get("properties", {}).keys())
    out: dict[str, Any] = {}
    for k, v in formdata.items():
        if k in flat_keys:
            out[k] = v
        else:
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
    _validate(params, params_schema)
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
