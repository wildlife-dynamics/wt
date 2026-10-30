"""One spelling per meaning for a workflow's run parameters.

Producers write the same configuration differently: a default left out or spelled
out, an untouched multi-select as ``[]`` or ``null``. :func:`canonical_params`
projects params onto the workflow's own params JSON schema so every producer's
output for one meaning comes out the same. Compiled workflows apply it at DAG
entry, which is what makes their step-cache keys agree across producers without
task authors doing anything.

The rules are versioned. A compiled package pins the version current when it was
emitted, so changing a rule means adding a version, never editing one: an installed
upgrade must not change what an already-compiled workflow runs.
"""

from __future__ import annotations

import copy
import warnings
from typing import Any

import jsonschema

LATEST_RULES = 1

_MISSING = object()


def canonical_params(
    params: dict[str, Any], params_schema: dict[str, Any], rules: int = LATEST_RULES
) -> dict[str, Any]:
    """Project `params` onto `params_schema` under rules version `rules`.

    Rules (version 1), applied recursively:

    - a key the schema forbids (``additionalProperties: false``) is dropped;
    - a missing property takes its schema default, unless that default is null:
      then it stays absent and the task's own default applies (pydantic emits
      ``"default": null`` beside a non-null type for hidden optionals, so
      filling it in would no longer validate);
    - an empty value (``None``, ``[]``, ``""``) of a property that is not
      required is treated as missing, when its default is itself null or empty:
      a form can't tell such a value from an untouched one, so it can't mean
      anything else. A non-empty default is kept distinct, since clearing it is
      something the user can express. An empty object is not empty in this
      sense: ``{}`` for an optional object picks the object, defaults and all;
    - a missing top-level (task) section without a default is treated as ``{}``,
      as the DAG does;
    - inside ``anyOf``/``oneOf`` only the one branch the value matches is
      canonicalised; anything else is left as given.

    Idempotent, and never raises: params it can't make sense of come back as given.

    Examples:
        >>> schema = {
        ...     "type": "object",
        ...     "properties": {
        ...         "get_events": {
        ...             "type": "object",
        ...             "properties": {
        ...                 "event_types": {"type": "array", "items": {"type": "string"}},
        ...                 "event_states": {"type": "array", "default": None},
        ...                 "include_null_geometry": {"type": "boolean", "default": True},
        ...             },
        ...             "required": ["event_types"],
        ...         }
        ...     },
        ... }
        >>> from_template = {"get_events": {"event_types": []}}
        >>> from_form = {"get_events": {"event_types": [], "event_states": []}}
        >>> canonical_params(from_template, schema) == canonical_params(from_form, schema)
        True
        >>> canonical_params(from_form, schema)
        {'get_events': {'event_types': [], 'include_null_geometry': True}}
    """
    if rules != 1:
        warnings.warn(
            f"canonical_params rules version {rules} is newer than this wt-contracts "
            "supports; running with params as given.",
            stacklevel=2,
        )
        return params
    try:
        defs = params_schema.get("$defs", {})
        sections: dict[str, Any] = {
            name: {}
            for name, sub in params_schema.get("properties", {}).items()
            if name not in params
            and _deref(sub, defs).get("type") == "object"
            and "default" not in _deref(sub, defs)
        }
        canonical: dict[str, Any] = _object({**params, **sections}, params_schema, defs)
        return canonical
    except Exception:  # noqa: BLE001  # a schema shape we can't follow: run as given
        return params


def _object(value: Any, schema: dict[str, Any], defs: dict[str, Any]) -> Any:  # noqa: ANN401
    schema = _deref(schema, defs)
    if not isinstance(value, dict):
        return value
    props: dict[str, Any] = schema.get("properties", {})
    required = set(schema.get("required", ()))
    out: dict[str, Any] = {}
    for name, sub in props.items():
        resolved = _deref(sub, defs)
        given = value.get(name, _MISSING)
        if given is not _MISSING and not (
            name not in required and _is_empty(given) and _empty_default(resolved)
        ):
            out[name] = _canon(given, sub, defs)
        elif resolved.get("default") is not None:
            out[name] = copy.deepcopy(resolved["default"])
        # Otherwise absent, so the task's own default applies.
    if schema.get("additionalProperties", True) is not False:
        out |= {k: v for k, v in value.items() if k not in props}
    return out


def _canon(value: Any, schema: dict[str, Any], defs: dict[str, Any]) -> Any:  # noqa: ANN401
    schema = _deref(schema, defs)
    branches = schema.get("anyOf") or schema.get("oneOf")
    if branches:
        matching = [b for b in branches if _matches(value, b, defs)]
        return _canon(value, matching[0], defs) if len(matching) == 1 else value
    if schema.get("type") == "object" or "properties" in schema:
        return _object(value, schema, defs)
    if schema.get("type") == "array" and isinstance(value, list) and "items" in schema:
        return [_canon(v, schema["items"], defs) for v in value]
    return value


def _deref(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    # Local refs only, which is all pydantic emits; siblings (e.g. a default
    # beside the $ref) win over the definition's own keys.
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
        return schema
    target = defs[ref.removeprefix("#/$defs/")]
    siblings = {k: v for k, v in schema.items() if k != "$ref"}
    return {**_deref(target, defs), **siblings}


def _matches(value: Any, branch: dict[str, Any], defs: dict[str, Any]) -> bool:  # noqa: ANN401
    return jsonschema.Draft202012Validator({**branch, "$defs": defs}).is_valid(value)


def _is_empty(value: Any) -> bool:  # noqa: ANN401
    return value is None or (isinstance(value, (list, str)) and not value)


def _empty_default(schema: dict[str, Any]) -> bool:
    return "default" not in schema or _is_empty(schema["default"])
