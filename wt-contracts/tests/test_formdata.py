"""Tests for wt_contracts.formdata."""

import json
from typing import ClassVar

import jsonschema
import pytest

from wt_contracts.formdata import (
    ValidationError,
    ValidationErrorItem,
    _serialize_errors,
    formdata_to_params,
    params_to_formdata,
    validate,
)

PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        "fetch_data": {
            "type": "object",
            "properties": {
                "since": {"type": "string"},
            },
            "required": ["since"],
        },
        "summarize": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
        "render": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
            },
        },
    },
}

# Hierarchical (formdata) schema groups fetch_data + summarize under "Data"
RJSF_SCHEMA = {
    "type": "object",
    "properties": {
        "Data": {
            "type": "object",
            "ecoscope:task_group": True,
            "properties": {
                "fetch_data": PARAMS_SCHEMA["properties"]["fetch_data"],
                "summarize": PARAMS_SCHEMA["properties"]["summarize"],
            },
        },
        "render": PARAMS_SCHEMA["properties"]["render"],
    },
}

VALID_PARAMS = {
    "fetch_data": {"since": "2024-01-01"},
    "summarize": {"name": "team-A"},
    "render": {"title": "Report"},
}

VALID_FORMDATA = {
    "Data": {
        "fetch_data": {"since": "2024-01-01"},
        "summarize": {"name": "team-A"},
    },
    "render": {"title": "Report"},
}


class TestFormdataToParams:
    def test_round_trip_groups_to_flat(self):
        assert formdata_to_params(VALID_FORMDATA, RJSF_SCHEMA, PARAMS_SCHEMA) == VALID_PARAMS

    def test_flat_only_passthrough(self):
        flat_rjsf = {
            "type": "object",
            "properties": {"render": PARAMS_SCHEMA["properties"]["render"]},
        }
        flat_params = {
            "type": "object",
            "properties": {"render": PARAMS_SCHEMA["properties"]["render"]},
        }
        formdata = {"render": {"title": "Hi"}}
        assert formdata_to_params(formdata, flat_rjsf, flat_params) == formdata

    def test_invalid_formdata_raises(self):
        bad = {"Data": {"fetch_data": {"since": 42}}, "render": {"title": "ok"}}
        with pytest.raises(ValidationError) as exc_info:
            formdata_to_params(bad, RJSF_SCHEMA, PARAMS_SCHEMA)
        errors = exc_info.value.errors
        assert errors
        assert isinstance(errors[0], dict)
        assert "message" in errors[0]
        assert "path" in errors[0]
        assert "input" in errors[0]


class TestFormdataInvariant:
    """Pin the two-level group invariant of ``formdata_to_params``.

    The rjsf schema model is strictly two-level: a top-level key is either a
    flat task ID or a group of flat task IDs. Groups never contain groups.
    Inner-key membership is guaranteed by the preceding ``validate()`` call,
    so ``formdata_to_params`` does not need to (and does not) recurse.
    """

    def test_grouped_formdata_inner_keys_flatten_one_level(self):
        formdata = {
            "Data": {
                "fetch_data": {"since": "2024-01-01"},
                "summarize": {"name": "team-A"},
            },
            "render": {"title": "Report"},
        }
        flat = formdata_to_params(formdata, RJSF_SCHEMA, PARAMS_SCHEMA)
        # All inner keys land at the top level; group name "Data" disappears.
        assert set(flat.keys()) == {"fetch_data", "summarize", "render"}
        assert flat["fetch_data"] == {"since": "2024-01-01"}
        assert flat["summarize"] == {"name": "team-A"}


class TestParamsToFormdata:
    def test_flat_to_grouped(self):
        assert params_to_formdata(VALID_PARAMS, RJSF_SCHEMA, PARAMS_SCHEMA) == VALID_FORMDATA

    def test_direct_task_without_nested_properties_passes_through(self):
        # A direct (ungrouped) rjsf entry with no ``properties`` dict is NOT
        # detected as a group, so it lands at the top level via the
        # direct-task branch (``k in rjsf_props and k not in task_groups``).
        rjsf = {
            "type": "object",
            "properties": {
                "grouped": {
                    "type": "object",
                    "properties": {"inner_task": {"type": "object"}},
                },
                "noop_task": {"type": "object"},  # no nested "properties"
            },
        }
        params_schema = {
            "type": "object",
            "properties": {
                "inner_task": {"type": "object"},
                "noop_task": {"type": "object"},
            },
        }
        params = {"inner_task": {}, "noop_task": {}}
        assert params_to_formdata(params, rjsf, params_schema) == {
            "noop_task": {},
            "grouped": {"inner_task": {}},
        }

    def test_invalid_params_raises(self):
        bad = {"fetch_data": {"since": 42}, "summarize": {"name": "x"}, "render": {}}
        with pytest.raises(ValidationError):
            params_to_formdata(bad, RJSF_SCHEMA, PARAMS_SCHEMA)

    def test_round_trip_idempotent(self):
        formdata = params_to_formdata(VALID_PARAMS, RJSF_SCHEMA, PARAMS_SCHEMA)
        params = formdata_to_params(formdata, RJSF_SCHEMA, PARAMS_SCHEMA)
        assert params == VALID_PARAMS

    def test_unknown_key_raises(self):
        # missing param key in rjsf -> KeyError before validation, but params
        # validation will also catch it via additionalProperties depending on schema.
        # Here PARAMS_SCHEMA doesn't restrict, so we expect KeyError when looking
        # up the group.
        params = {
            "render": {"title": "ok"},
            "fetch_data": {"since": "x"},
            "summarize": {"name": "y"},
            "unknown_task": {},
        }
        with pytest.raises(KeyError):
            params_to_formdata(params, RJSF_SCHEMA, PARAMS_SCHEMA)


class TestValidationErrorShape:
    """Lock down the ValidationError.errors serialization contract.

    wt-runner surfaces these entries directly in 422 response bodies, so the
    shape and JSON-safety of every entry must remain stable.
    """

    EXPECTED_KEYS: ClassVar[set[str]] = {"message", "path", "schema_path", "validator", "input"}

    def _trigger_errors(self) -> list[dict]:
        bad = {"fetch_data": {"since": 42}, "summarize": {"name": 7}, "render": {}}
        with pytest.raises(ValidationError) as exc_info:
            validate(bad, PARAMS_SCHEMA)
        return exc_info.value.errors

    def test_errors_is_non_empty_list_of_dicts(self):
        errors = self._trigger_errors()
        assert isinstance(errors, list)
        assert errors, "expected at least one validation error"
        assert all(isinstance(e, dict) for e in errors)

    def test_each_entry_has_exact_keys_and_types(self):
        errors = self._trigger_errors()
        for entry in errors:
            assert set(entry.keys()) == self.EXPECTED_KEYS
            assert isinstance(entry["message"], str)
            assert isinstance(entry["path"], list)
            assert isinstance(entry["schema_path"], list)
            assert entry["validator"] is None or isinstance(entry["validator"], str)

    def test_input_carries_failing_instance(self):
        errors = self._trigger_errors()
        # The failing values in ``bad`` were 42 and 7; both should appear as
        # ``input`` on at least one error entry.
        inputs = [entry["input"] for entry in errors]
        assert 42 in inputs
        assert 7 in inputs

    def test_path_components_are_json_primitives(self):
        # FastAPI serializes the response body to JSON, so each path
        # component must be a JSON-safe primitive (str/int).
        errors = self._trigger_errors()
        for entry in errors:
            for component in entry["path"]:
                assert isinstance(component, (str, int))
            for component in entry["schema_path"]:
                assert isinstance(component, (str, int))

    def test_errors_round_trip_through_json(self):
        errors = self._trigger_errors()
        # Should be losslessly JSON-serializable as-is.
        round_tripped = json.loads(json.dumps(errors))
        assert round_tripped == errors

    def test_serialized_errors_validate_against_pydantic_model(self):
        # Catches drift between ValidationErrorItemDict and ValidationErrorItem.
        errors = self._trigger_errors()
        for entry in errors:
            ValidationErrorItem(**entry)


def _capture_first_error(schema: dict, instance: object) -> dict:
    """Run :func:`validate` and return the first wire-shape error entry."""
    with pytest.raises(ValidationError) as exc_info:
        validate(instance, schema)
    return exc_info.value.errors[0]


class TestValidationErrorValidatorVocabulary:
    """Pin the full vocabulary of ``validator`` strings the 422 path can emit.

    Each parametrize entry below is a literal record: feed ``bad_value`` against
    a schema whose only constraint on ``x`` is ``subschema``, and see exactly
    what wire-shape ``validator`` / ``message`` / ``input`` come back. These
    tests double as developer documentation: a reader can scan the cases and
    learn the error shape for every Draft 2020-12 keyword.

    The Draft 2020-12 keyword set is frozen by spec (see
    ``Draft202012Validator.VALIDATORS``), so the 36 cases here will not drift.
    Keywords that delegate error attribution to inner keywords (e.g. ``allOf``,
    ``properties``, ``$ref``) are marked ``xfail`` with a reason describing
    where the error actually surfaces.
    """

    @pytest.mark.parametrize(
        ("subschema", "bad_value", "expected"),
        [
            # Surfacing keywords: e.validator equals the keyword itself ----------
            pytest.param(
                {"type": "integer"},
                "old",
                {
                    "validator": "type",
                    "message": "'old' is not of type 'integer'",
                    "input": "old",
                },
                id="type",
            ),
            pytest.param(
                {"enum": ["red", "blue"]},
                "green",
                {
                    "validator": "enum",
                    "message": "'green' is not one of ['red', 'blue']",
                    "input": "green",
                },
                id="enum",
            ),
            pytest.param(
                {"const": "exact"},
                "wrong",
                {
                    "validator": "const",
                    "message": "'exact' was expected",
                    "input": "wrong",
                },
                id="const",
            ),
            pytest.param(
                {"type": "object", "required": ["a"]},
                {},
                {
                    "validator": "required",
                    "message": "'a' is a required property",
                    "input": {},
                },
                id="required",
            ),
            pytest.param(
                {"type": "object", "additionalProperties": False},
                {"extra": 1},
                {
                    "validator": "additionalProperties",
                    "message": "Additional properties are not allowed ('extra' was unexpected)",
                    "input": {"extra": 1},
                },
                id="additionalProperties",
            ),
            pytest.param(
                {"anyOf": [{"type": "integer"}, {"type": "boolean"}]},
                "str",
                {
                    "validator": "anyOf",
                    "message": "'str' is not valid under any of the given schemas",
                    "input": "str",
                },
                id="anyOf",
            ),
            pytest.param(
                {"oneOf": [{"type": "integer"}, {"minimum": 0}]},
                1,
                {
                    "validator": "oneOf",
                    "message": "1 is valid under each of {'minimum': 0}, {'type': 'integer'}",
                    "input": 1,
                },
                id="oneOf",
            ),
            pytest.param(
                {"not": {"type": "integer"}},
                1,
                {
                    "validator": "not",
                    "message": "1 should not be valid under {'type': 'integer'}",
                    "input": 1,
                },
                id="not",
            ),
            pytest.param(
                {"type": "array", "contains": {"type": "integer"}},
                ["a", "b"],
                {
                    "validator": "contains",
                    "message": "['a', 'b'] does not contain items matching the given schema",
                    "input": ["a", "b"],
                },
                id="contains",
            ),
            pytest.param(
                {"type": "object", "dependentRequired": {"a": ["b"]}},
                {"a": 1},
                {
                    "validator": "dependentRequired",
                    "message": "'b' is a dependency of 'a'",
                    "input": {"a": 1},
                },
                id="dependentRequired",
            ),
            pytest.param(
                {"minimum": 5},
                4,
                {
                    "validator": "minimum",
                    "message": "4 is less than the minimum of 5",
                    "input": 4,
                },
                id="minimum",
            ),
            pytest.param(
                {"maximum": 5},
                6,
                {
                    "validator": "maximum",
                    "message": "6 is greater than the maximum of 5",
                    "input": 6,
                },
                id="maximum",
            ),
            pytest.param(
                {"exclusiveMinimum": 5},
                5,
                {
                    "validator": "exclusiveMinimum",
                    "message": "5 is less than or equal to the minimum of 5",
                    "input": 5,
                },
                id="exclusiveMinimum",
            ),
            pytest.param(
                {"exclusiveMaximum": 5},
                5,
                {
                    "validator": "exclusiveMaximum",
                    "message": "5 is greater than or equal to the maximum of 5",
                    "input": 5,
                },
                id="exclusiveMaximum",
            ),
            pytest.param(
                {"multipleOf": 3},
                5,
                {
                    "validator": "multipleOf",
                    "message": "5 is not a multiple of 3",
                    "input": 5,
                },
                id="multipleOf",
            ),
            pytest.param(
                {"type": "string", "minLength": 2},
                "a",
                {
                    "validator": "minLength",
                    "message": "'a' is too short",
                    "input": "a",
                },
                id="minLength",
            ),
            pytest.param(
                {"type": "string", "maxLength": 2},
                "abc",
                {
                    "validator": "maxLength",
                    "message": "'abc' is too long",
                    "input": "abc",
                },
                id="maxLength",
            ),
            pytest.param(
                {"type": "string", "pattern": "^a"},
                "b",
                {
                    "validator": "pattern",
                    "message": "'b' does not match '^a'",
                    "input": "b",
                },
                id="pattern",
            ),
            pytest.param(
                {"type": "array", "minItems": 2},
                [1],
                {
                    "validator": "minItems",
                    "message": "[1] is too short",
                    "input": [1],
                },
                id="minItems",
            ),
            pytest.param(
                {"type": "array", "maxItems": 1},
                [1, 2],
                {
                    "validator": "maxItems",
                    "message": "[1, 2] is too long",
                    "input": [1, 2],
                },
                id="maxItems",
            ),
            pytest.param(
                {"type": "array", "uniqueItems": True},
                [1, 1],
                {
                    "validator": "uniqueItems",
                    "message": "[1, 1] has non-unique elements",
                    "input": [1, 1],
                },
                id="uniqueItems",
            ),
            pytest.param(
                {"type": "object", "minProperties": 2},
                {"a": 1},
                {
                    "validator": "minProperties",
                    "message": "{'a': 1} does not have enough properties",
                    "input": {"a": 1},
                },
                id="minProperties",
            ),
            pytest.param(
                {"type": "object", "maxProperties": 1},
                {"a": 1, "b": 2},
                {
                    "validator": "maxProperties",
                    "message": "{'a': 1, 'b': 2} has too many properties",
                    "input": {"a": 1, "b": 2},
                },
                id="maxProperties",
            ),
            pytest.param(
                {
                    "type": "array",
                    "prefixItems": [{"type": "integer"}],
                    "unevaluatedItems": False,
                },
                [1, 2],
                {
                    "validator": "unevaluatedItems",
                    "message": "Unevaluated items are not allowed (2 was unexpected)",
                    "input": [1, 2],
                },
                id="unevaluatedItems",
            ),
            pytest.param(
                {
                    "type": "object",
                    "properties": {"a": {}},
                    "unevaluatedProperties": False,
                },
                {"b": 1},
                {
                    "validator": "unevaluatedProperties",
                    "message": "Unevaluated properties are not allowed ('b' was unexpected)",
                    "input": {"b": 1},
                },
                id="unevaluatedProperties",
            ),
            # Delegating / non-surfacing keywords: error attribution moves to the
            # resolved inner keyword, so e.validator never equals the outer
            # keyword name. Each xfail reason documents where the failure
            # actually surfaces in the wire shape.
            pytest.param(
                {"$ref": "#/$defs/posint"},
                "old",
                {
                    "validator": "$ref",
                    "message": "<delegates to resolved inner schema>",
                    "input": "old",
                },
                marks=pytest.mark.xfail(
                    reason=(
                        "$ref is a structural applicator: errors are attributed to the "
                        "resolved inner keyword (e.g. 'type'), not '$ref'. The wrapper "
                        "schema also has no $defs, so resolution would itself raise."
                    ),
                ),
                id="$ref",
            ),
            pytest.param(
                {"$dynamicRef": "#nope"},
                "old",
                {
                    "validator": "$dynamicRef",
                    "message": "<delegates to resolved dynamic anchor>",
                    "input": "old",
                },
                marks=pytest.mark.xfail(
                    reason=(
                        "$dynamicRef is a structural applicator for dynamic schema "
                        "composition; it never surfaces directly in validation errors."
                    ),
                ),
                id="$dynamicRef",
            ),
            pytest.param(
                {"allOf": [{"type": "integer"}, {"minimum": 10}]},
                "str",
                {
                    "validator": "allOf",
                    "message": "<delegates to first failing inner subschema>",
                    "input": "str",
                },
                marks=pytest.mark.xfail(
                    reason=(
                        "allOf delegates: surfaces as the first failing inner "
                        "keyword (here 'type')."
                    ),
                ),
                id="allOf",
            ),
            pytest.param(
                {"type": "object", "dependentSchemas": {"a": {"required": ["b"]}}},
                {"a": 1},
                {
                    "validator": "dependentSchemas",
                    "message": "<delegates to inner subschema>",
                    "input": {"a": 1},
                },
                marks=pytest.mark.xfail(
                    reason=(
                        "dependentSchemas delegates: surfaces as the failing inner "
                        "keyword (here 'required')."
                    ),
                ),
                id="dependentSchemas",
            ),
            pytest.param(
                {"if": {"type": "integer"}, "then": {"minimum": 100}},
                1,
                {
                    "validator": "if",
                    "message": "<delegates to then/else branch>",
                    "input": 1,
                },
                marks=pytest.mark.xfail(
                    reason=(
                        "if/then/else delegates: surfaces as the failing keyword in "
                        "then/else (here 'minimum')."
                    ),
                ),
                id="if",
            ),
            pytest.param(
                {"type": "array", "items": {"type": "integer"}},
                ["a"],
                {
                    "validator": "items",
                    "message": "<delegates to per-item subschema>",
                    "input": ["a"],
                },
                marks=pytest.mark.xfail(
                    reason=(
                        "items delegates: surfaces as the failing inner keyword on "
                        "the offending element (here 'type')."
                    ),
                ),
                id="items",
            ),
            pytest.param(
                {"type": "array", "prefixItems": [{"type": "integer"}]},
                ["a"],
                {
                    "validator": "prefixItems",
                    "message": "<delegates to positional subschema>",
                    "input": ["a"],
                },
                marks=pytest.mark.xfail(
                    reason=(
                        "prefixItems delegates: surfaces as the failing inner "
                        "keyword (here 'type')."
                    ),
                ),
                id="prefixItems",
            ),
            pytest.param(
                {"type": "object", "properties": {"a": {"type": "integer"}}},
                {"a": "x"},
                {
                    "validator": "properties",
                    "message": "<delegates to per-property subschema>",
                    "input": {"a": "x"},
                },
                marks=pytest.mark.xfail(
                    reason=(
                        "properties delegates: surfaces as the failing inner keyword "
                        "(here 'type') with path extended by the property name."
                    ),
                ),
                id="properties",
            ),
            pytest.param(
                {"type": "object", "patternProperties": {"^a": {"type": "integer"}}},
                {"abc": "x"},
                {
                    "validator": "patternProperties",
                    "message": "<delegates to matching subschema>",
                    "input": {"abc": "x"},
                },
                marks=pytest.mark.xfail(
                    reason=(
                        "patternProperties delegates: surfaces as the failing inner "
                        "keyword (here 'type')."
                    ),
                ),
                id="patternProperties",
            ),
            pytest.param(
                {"type": "object", "propertyNames": {"pattern": "^a"}},
                {"b": 1},
                {
                    "validator": "propertyNames",
                    "message": "<delegates to property-name subschema>",
                    "input": {"b": 1},
                },
                marks=pytest.mark.xfail(
                    reason=(
                        "propertyNames delegates: surfaces as the failing inner "
                        "keyword on the offending key (here 'pattern')."
                    ),
                ),
                id="propertyNames",
            ),
            pytest.param(
                {"type": "string", "format": "ipv4"},
                "abc",
                {
                    "validator": "format",
                    "message": "<format is annotation-only without a format_checker>",
                    "input": "abc",
                },
                marks=pytest.mark.xfail(
                    reason=(
                        "format is annotation-only by default in Draft 2020-12; validate() "
                        "constructs Draft202012Validator without a format_checker, so format "
                        "violations never raise."
                    ),
                ),
                id="format",
            ),
        ],
    )
    def test_keyword_surfaces_in_wire_shape(
        self, subschema: dict, bad_value: object, expected: dict
    ) -> None:
        err = _capture_first_error({"properties": {"x": subschema}}, {"x": bad_value})
        assert err["path"] == ["x"]
        assert {k: err[k] for k in expected} == expected

    def test_synthetic_type_from_non_dict_guard(self) -> None:
        """Cross-reference: the non-dict guard at validate() also emits ``validator: "type"``.

        This case is exercised exhaustively in
        :class:`TestValidateNonDictInstance` (one entry per non-dict primitive);
        it is named here so the vocabulary class reads as complete.
        """
        with pytest.raises(ValidationError) as exc_info:
            validate(42, {"properties": {}})
        assert exc_info.value.errors[0]["validator"] == "type"

    def test_unset_validator_coerced_to_none(self) -> None:
        """A jsonschema ValidationError with no ``validator=`` defaults to the ``Unset``
        sentinel; ``_serialize_errors`` must coerce that to JSON ``None``.
        """
        err = jsonschema.ValidationError("synthesized")
        assert not isinstance(err.validator, str)  # confirm default is the Unset sentinel
        [wire] = _serialize_errors([err])
        assert wire == {
            "message": "synthesized",
            "path": [],
            "schema_path": [],
            "validator": None,
            "input": err.instance,
        }


class TestValidateNonDictInstance:
    """Guard against non-dict instances slipping through to ``.items()`` / ``.get()``.

    wt-compiler emits schemas without a root ``"type": "object"``, so jsonschema
    alone will not reject a non-dict instance. The compiled CLI feeds raw
    ``json.loads`` output into :func:`validate`, so the guard must raise a
    ``ValidationError`` (not crash later inside ``formdata_to_params`` /
    ``params_to_formdata``).
    """

    # Schema modeled on what wt-compiler emits: no root ``type`` keyword.
    SCHEMA_WITHOUT_ROOT_TYPE: ClassVar[dict] = {
        "title": "params",
        "properties": PARAMS_SCHEMA["properties"],
    }

    @pytest.mark.parametrize(
        "instance",
        [
            [],
            ["not", "a", "dict"],
            "string",
            42,
            None,
            True,
        ],
    )
    def test_non_dict_raises_validation_error(self, instance):
        with pytest.raises(ValidationError) as exc_info:
            validate(instance, self.SCHEMA_WITHOUT_ROOT_TYPE)
        errors = exc_info.value.errors
        assert len(errors) == 1
        entry = errors[0]
        assert entry["validator"] == "type"
        assert "is not of type 'object'" in entry["message"]
        assert entry["input"] == instance
        # Shape stays consistent with jsonschema-sourced entries so wt-runner
        # can serialize it through the same 422 envelope.
        ValidationErrorItem(**entry)

    def test_formdata_to_params_rejects_list_instance(self):
        with pytest.raises(ValidationError):
            formdata_to_params([], RJSF_SCHEMA, PARAMS_SCHEMA)  # type: ignore[arg-type]

    def test_params_to_formdata_rejects_string_instance(self):
        with pytest.raises(ValidationError):
            params_to_formdata("oops", RJSF_SCHEMA, PARAMS_SCHEMA)  # type: ignore[arg-type]
