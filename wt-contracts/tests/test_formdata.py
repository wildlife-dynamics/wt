"""Tests for wt_contracts.formdata."""

import json

import pytest

from wt_contracts.formdata import (
    ValidationError,
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


class TestParamsToFormdata:
    def test_flat_to_grouped(self):
        assert params_to_formdata(VALID_PARAMS, RJSF_SCHEMA, PARAMS_SCHEMA) == VALID_FORMDATA

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

    wt-runner translates these entries into FastAPI 422 responses (each
    error's ``path`` is placed directly into ``loc``), so the shape and
    JSON-safety of every entry must remain stable.
    """

    EXPECTED_KEYS = {"message", "path", "schema_path", "validator"}

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
            assert isinstance(entry["validator"], str)

    def test_path_components_are_json_primitives(self):
        # FastAPI puts ``path`` directly into the response ``loc`` and
        # serializes the response to JSON, so each component must be a
        # JSON-safe primitive (str/int).
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
