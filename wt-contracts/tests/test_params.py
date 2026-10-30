"""Tests for canonical_params: one spelling per meaning for a workflow's run params."""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

import pytest

from wt_contracts.formdata import validate
from wt_contracts.params import LATEST_RULES, canonical_params

# A real compiled workflow's params schema: pydantic's anyOf/null unions, $defs
# and nested task groups, rather than a hand-written approximation of them.
EVENTS_MAP = json.loads((pathlib.Path(__file__).parent / "data/events_map_params.json").read_text())


def _schema(**props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": {"step": {"type": "object", **props}}}


def test_an_untouched_multi_select_means_its_null_default():
    schema = _schema(properties={"states": {"type": "array", "default": None}})
    assert canonical_params({"step": {"states": []}}, schema) == canonical_params(
        {"step": {}}, schema
    )


def test_a_required_empty_value_is_kept():
    schema = _schema(properties={"types": {"type": "array"}}, required=["types"])
    assert canonical_params({"step": {"types": []}}, schema) == {"step": {"types": []}}


def test_clearing_a_non_empty_default_is_kept_distinct():
    # The form can express "I removed the defaults", so [] must not become ["a"].
    schema = _schema(properties={"cols": {"type": "array", "default": ["a"]}})
    assert canonical_params({"step": {"cols": []}}, schema) == {"step": {"cols": []}}


def test_a_missing_task_section_reads_as_an_empty_one():
    # The DAG hands a task `params.get(id) or {}`, so the two already mean the same.
    schema = _schema(properties={"n": {"type": "integer", "default": 3}})
    assert canonical_params({}, schema) == canonical_params({"step": {}}, schema)


def test_an_empty_optional_object_is_kept_apart_from_none():
    schema = _schema(
        properties={
            "opt": {
                "anyOf": [{"type": "object", "properties": {}}, {"type": "null"}],
                "default": None,
            }
        }
    )
    assert canonical_params({"step": {"opt": {}}}, schema) != canonical_params(
        {"step": {"opt": None}}, schema
    )


def test_missing_properties_take_their_defaults():
    schema = _schema(properties={"n": {"type": "integer", "default": 3}})
    assert canonical_params({"step": {}}, schema) == {"step": {"n": 3}}


def test_a_property_without_a_default_stays_absent():
    schema = _schema(properties={"n": {"type": "integer"}})
    assert canonical_params({"step": {}}, schema) == {"step": {}}


def test_keys_the_schema_forbids_are_dropped_and_others_kept():
    closed = _schema(properties={}, additionalProperties=False)
    open_ = _schema(properties={})
    assert canonical_params({"step": {"extra": 1}}, closed) == {"step": {}}
    assert canonical_params({"step": {"extra": 1}}, open_) == {"step": {"extra": 1}}


def test_a_default_beside_a_ref_wins():
    schema = {
        "type": "object",
        "$defs": {"Opts": {"type": "object", "properties": {"k": {"type": "integer"}}}},
        "properties": {"step": {"$ref": "#/$defs/Opts", "default": {"k": 1}}},
    }
    assert canonical_params({}, schema) == {"step": {"k": 1}}


def test_only_the_matching_union_branch_is_canonicalised():
    schema = _schema(
        properties={
            "opt": {
                "anyOf": [
                    {"type": "object", "properties": {"x": {"type": "integer", "default": 0}}},
                    {"type": "null"},
                ],
                "default": None,
            }
        }
    )
    assert canonical_params({"step": {"opt": {}}}, schema) == {"step": {"opt": {"x": 0}}}
    # None is the null default: unset, so absent.
    assert canonical_params({"step": {"opt": None}}, schema) == {"step": {}}


def test_items_of_an_array_of_objects_are_canonicalised():
    item = {"type": "object", "properties": {"opacity": {"type": "number", "default": 1.0}}}
    schema = _schema(properties={"maps": {"type": "array", "items": item}})
    assert canonical_params({"step": {"maps": [{}]}}, schema) == {
        "step": {"maps": [{"opacity": 1.0}]}
    }


def test_template_and_form_shapes_of_the_real_schema_agree():
    from_template = {"get_events_data": {"event_types": ["fire_rep"]}}
    from_form = {
        "get_events_data": {
            "event_types": ["fire_rep"],
            "event_states": [],
            "include_null_geometry": True,
            "force_point_geometry": True,
        }
    }
    assert canonical_params(from_template, EVENTS_MAP) == canonical_params(from_form, EVENTS_MAP)


def test_canonical_params_still_validate_against_the_real_schema():
    params = {
        "workflow_details": {"name": "n", "description": ""},
        "er_client_name": {"data_source": {"name": "mep_dev"}},
        "time_range": {"since": "2015-01-01T00:00:00", "until": "2015-12-31T23:59:59"},
        "get_events_data": {"event_types": [], "event_states": []},
    }
    validate(canonical_params(params, EVENTS_MAP), EVENTS_MAP)


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"get_events_data": {"event_types": [], "event_states": []}},
        {"filter_events": {"filter_point_coords": [{"x": 1.0, "y": 2.0}]}},
        {"base_map_defs": {"base_maps": [{"url": "https://t/{z}/{x}/{y}"}]}},
    ],
)
def test_canonicalising_twice_changes_nothing(params):
    once = canonical_params(params, EVENTS_MAP)
    assert canonical_params(copy.deepcopy(once), EVENTS_MAP) == once


def test_the_input_is_not_mutated():
    params = {"get_events_data": {"event_types": [], "event_states": []}}
    before = copy.deepcopy(params)
    canonical_params(params, EVENTS_MAP)
    assert params == before


def test_a_schema_it_cannot_follow_returns_the_params_as_given():
    broken = {"type": "object", "properties": {"step": {"$ref": "#/$defs/Missing"}}}
    params = {"step": {"a": 1}}
    assert canonical_params(params, broken) is params


def test_an_unknown_rules_version_runs_as_given():
    params = {"step": {}}
    with pytest.warns(UserWarning, match="rules version"):
        assert canonical_params(params, _schema(), rules=LATEST_RULES + 1) is params
