"""Tests for wt_contracts.formdata."""

import json

import pytest

from wt_contracts.formdata import (
    ValidationError,
    ValidationErrorItem,
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
        assert errors and isinstance(errors[0], dict)
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

    EXPECTED_KEYS = {"message", "path", "schema_path", "validator", "input"}

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


class TestValidateNonDictInstance:
    """Guard against non-dict instances slipping through to ``.items()`` / ``.get()``.

    wt-compiler emits schemas without a root ``"type": "object"``, so jsonschema
    alone will not reject a non-dict instance. The compiled CLI feeds raw
    ``json.loads`` output into :func:`validate`, so the guard must raise a
    ``ValidationError`` (not crash later inside ``formdata_to_params`` /
    ``params_to_formdata``).
    """

    # Schema modeled on what wt-compiler emits: no root ``type`` keyword.
    SCHEMA_WITHOUT_ROOT_TYPE: dict = {
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
