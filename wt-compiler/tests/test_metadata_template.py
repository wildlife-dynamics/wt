"""Tests for the rendered pkg/metadata.jinja2 template.

Two flavors of test live here:

* Schema-matrix tests exec the rendered module in a throwaway namespace with
  ``load_params_schema`` stubbed, which keeps the many ``$ref``-resolution
  cases cheap.
* End-to-end tests write a real package (``metadata.py`` + the ``params.json``
  / ``rjsf.json`` it bundles) to ``tmp_path`` and import it, exercising the
  ``importlib.resources`` loaders and the ``wt_contracts`` delegations the way
  a compiled workflow package does.
"""

from __future__ import annotations

import importlib
import itertools
import json
import pathlib
import sys
from typing import TYPE_CHECKING, Any

import pytest
from jinja2 import Environment, FileSystemLoader
from wt_contracts import ValidationError

if TYPE_CHECKING:
    from types import ModuleType

TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent.parent / "src" / "wt_compiler" / "templates"

_PKG_COUNTER = itertools.count()


def _render_metadata() -> str:
    """Render pkg/metadata.jinja2 with a placeholder file header."""
    env = Environment(  # noqa: S701  # rendering Python code, not HTML
        loader=FileSystemLoader(TEMPLATES_DIR),
        keep_trailing_newline=True,
    )
    return env.get_template("pkg/metadata.jinja2").render(file_header="# auto-generated")


def _exec_metadata(params_schema: dict[str, Any]) -> dict[str, Any]:
    """Exec the rendered metadata module with ``load_params_schema`` stubbed."""
    namespace: dict[str, Any] = {}
    exec(_render_metadata(), namespace)  # noqa: S102  # executing generated code under test
    namespace["load_params_schema"] = lambda: params_schema
    return namespace


def _get_data_connection_property_names(params_schema: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = _exec_metadata(params_schema)[
        "get_data_connection_property_names"
    ]()
    return result


def _import_metadata(
    tmp_path: pathlib.Path,
    params_schema: dict[str, Any],
    rjsf_schema: dict[str, Any],
) -> ModuleType:
    """Write and import a workflow-shaped package bundling both schemas."""
    name = f"generated_pkg_{next(_PKG_COUNTER)}"
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "metadata.py").write_text(_render_metadata())
    (pkg / "params.json").write_text(json.dumps(params_schema))
    (pkg / "rjsf.json").write_text(json.dumps(rjsf_schema))

    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        return importlib.import_module(f"{name}.metadata")
    finally:
        sys.path.remove(str(tmp_path))


# ---------------------------------------------------------------------------
# Schemas mirroring a compiled workflow: two tasks, one of them task-grouped
# ---------------------------------------------------------------------------

ER_CONNECTION_DEF = {
    "type": "object",
    "title": "EarthRangerConnection",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}

GET_EVENTS_PROPS = {
    "type": "object",
    "title": "Get Events",
    "properties": {
        "client": {"$ref": "#/$defs/EarthRangerConnection"},
        "since": {"type": "string"},
    },
    "required": ["client", "since"],
}

DRAW_MAP_PROPS = {
    "type": "object",
    "title": "Draw Map",
    "properties": {"style": {"type": "string"}},
    "required": ["style"],
}

PARAMS_SCHEMA: dict[str, Any] = {
    "properties": {"get_events": GET_EVENTS_PROPS, "draw_map": DRAW_MAP_PROPS},
    "$defs": {"EarthRangerConnection": ER_CONNECTION_DEF},
    "uiSchema": {"ui:order": ["get_events", "draw_map"]},
    "additionalProperties": False,
}

RJSF_SCHEMA: dict[str, Any] = {
    "properties": {
        "Data": {
            "type": "object",
            "description": "Pull events from EarthRanger",
            "ecoscope:task_group": True,
            "properties": {"get_events": GET_EVENTS_PROPS},
        },
        "draw_map": DRAW_MAP_PROPS,
    },
    "$defs": {"EarthRangerConnection": ER_CONNECTION_DEF},
    "uiSchema": {"ui:order": ["Data", "draw_map"]},
    "additionalProperties": False,
}

PARAMS: dict[str, Any] = {
    "get_events": {"client": {"name": "er-prod"}, "since": "2026-01-01"},
    "draw_map": {"style": "dark"},
}

FORMDATA: dict[str, Any] = {
    "Data": {"get_events": {"client": {"name": "er-prod"}, "since": "2026-01-01"}},
    "draw_map": {"style": "dark"},
}


@pytest.fixture
def metadata(tmp_path: pathlib.Path) -> ModuleType:
    return _import_metadata(tmp_path, PARAMS_SCHEMA, RJSF_SCHEMA)


# ---------------------------------------------------------------------------
# Schema loaders
# ---------------------------------------------------------------------------


def test_load_params_schema(metadata: ModuleType) -> None:
    assert metadata.load_params_schema() == PARAMS_SCHEMA


def test_load_rjsf_schema(metadata: ModuleType) -> None:
    assert metadata.load_rjsf_schema() == RJSF_SCHEMA


def test_loaders_read_distinct_bundled_files(metadata: ModuleType) -> None:
    assert metadata.load_params_schema() != metadata.load_rjsf_schema()
    assert "Data" in metadata.load_rjsf_schema()["properties"]
    assert "Data" not in metadata.load_params_schema()["properties"]


# ---------------------------------------------------------------------------
# formdata <-> params conversion (delegated to wt_contracts)
# ---------------------------------------------------------------------------


def test_formdata_to_params_flattens_task_groups(metadata: ModuleType) -> None:
    assert metadata.formdata_to_params(FORMDATA) == PARAMS


def test_params_to_formdata_nests_task_groups(metadata: ModuleType) -> None:
    assert metadata.params_to_formdata(PARAMS) == FORMDATA


def test_round_trip(metadata: ModuleType) -> None:
    assert metadata.formdata_to_params(metadata.params_to_formdata(PARAMS)) == PARAMS
    assert metadata.params_to_formdata(metadata.formdata_to_params(FORMDATA)) == FORMDATA


def test_formdata_to_params_rejects_invalid_formdata(metadata: ModuleType) -> None:
    with pytest.raises(ValidationError):
        metadata.formdata_to_params({"Data": {"get_events": {"since": 42}}})


def test_params_to_formdata_rejects_invalid_params(metadata: ModuleType) -> None:
    with pytest.raises(ValidationError):
        metadata.params_to_formdata({"get_events": {"client": "not-an-object"}})


def test_formdata_to_params_rejects_flat_params_as_formdata(metadata: ModuleType) -> None:
    # top-level "get_events" isn't a key of the grouped rjsf schema
    with pytest.raises(ValidationError):
        metadata.formdata_to_params(PARAMS)


# ---------------------------------------------------------------------------
# get_data_connection_property_names
# ---------------------------------------------------------------------------


def test_data_connection_property_names_end_to_end(metadata: ModuleType) -> None:
    assert metadata.get_data_connection_property_names() == {"EarthRanger": ["get_events"]}


def test_direct_ref_to_connection() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "get_events": {"properties": {"client": {"$ref": "#/$defs/EarthRangerConnection"}}},
        },
        "$defs": {"EarthRangerConnection": {"type": "object"}},
    }
    assert _get_data_connection_property_names(schema) == {"EarthRanger": ["get_events"]}


def test_connection_nested_in_defs() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "get_events": {"properties": {"config": {"$ref": "#/$defs/EventsConfig"}}},
        },
        "$defs": {
            "EventsConfig": {
                "properties": {"client": {"$ref": "#/$defs/EarthRangerConnection"}},
            },
            "EarthRangerConnection": {"type": "object"},
        },
    }
    assert _get_data_connection_property_names(schema) == {"EarthRanger": ["get_events"]}


def test_connection_nested_multiple_levels_deep() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "get_events": {"properties": {"outer": {"$ref": "#/$defs/Outer"}}},
        },
        "$defs": {
            "Outer": {"properties": {"inner": {"$ref": "#/$defs/Inner"}}},
            "Inner": {"properties": {"client": {"$ref": "#/$defs/EarthRangerConnection"}}},
            "EarthRangerConnection": {"type": "object"},
        },
    }
    assert _get_data_connection_property_names(schema) == {"EarthRanger": ["get_events"]}


def test_connection_behind_anyof() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "get_events": {
                "properties": {
                    "client": {
                        "anyOf": [{"$ref": "#/$defs/EarthRangerConnection"}, {"type": "null"}]
                    },
                },
            },
        },
        "$defs": {"EarthRangerConnection": {"type": "object"}},
    }
    assert _get_data_connection_property_names(schema) == {"EarthRanger": ["get_events"]}


def test_connection_behind_array_items() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "get_events": {
                "properties": {"clients": {"type": "array", "items": {"$ref": "#/$defs/Config"}}},
            },
        },
        "$defs": {
            "Config": {"properties": {"client": {"$ref": "#/$defs/EarthRangerConnection"}}},
            "EarthRangerConnection": {"type": "object"},
        },
    }
    assert _get_data_connection_property_names(schema) == {"EarthRanger": ["get_events"]}


def test_multiple_properties_share_a_connection() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "get_events": {"properties": {"client": {"$ref": "#/$defs/EarthRangerConnection"}}},
            "get_subjects": {"properties": {"config": {"$ref": "#/$defs/SubjectsConfig"}}},
        },
        "$defs": {
            "SubjectsConfig": {"properties": {"client": {"$ref": "#/$defs/EarthRangerConnection"}}},
            "EarthRangerConnection": {"type": "object"},
        },
    }
    assert _get_data_connection_property_names(schema) == {
        "EarthRanger": ["get_events", "get_subjects"],
    }


def test_multiple_connection_types_for_one_property() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "sync": {
                "properties": {
                    "source": {"$ref": "#/$defs/EarthRangerConnection"},
                    "dest": {"$ref": "#/$defs/SmartConnection"},
                },
            },
        },
        "$defs": {
            "EarthRangerConnection": {"type": "object"},
            "SmartConnection": {"type": "object"},
        },
    }
    assert _get_data_connection_property_names(schema) == {
        "EarthRanger": ["sync"],
        "Smart": ["sync"],
    }


def test_property_appears_once_when_connection_referenced_twice() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "get_events": {
                "properties": {
                    "client": {"$ref": "#/$defs/EarthRangerConnection"},
                    "config": {"$ref": "#/$defs/EventsConfig"},
                },
            },
        },
        "$defs": {
            "EventsConfig": {"properties": {"client": {"$ref": "#/$defs/EarthRangerConnection"}}},
            "EarthRangerConnection": {"type": "object"},
        },
    }
    assert _get_data_connection_property_names(schema) == {"EarthRanger": ["get_events"]}


def test_self_referential_def_terminates() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "get_events": {"properties": {"node": {"$ref": "#/$defs/Node"}}},
        },
        "$defs": {
            "Node": {
                "properties": {
                    "child": {"$ref": "#/$defs/Node"},
                    "client": {"$ref": "#/$defs/EarthRangerConnection"},
                },
            },
            "EarthRangerConnection": {"type": "object"},
        },
    }
    assert _get_data_connection_property_names(schema) == {"EarthRanger": ["get_events"]}


def test_mutually_recursive_defs_terminate() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "get_events": {"properties": {"a": {"$ref": "#/$defs/A"}}},
        },
        "$defs": {
            "A": {"properties": {"b": {"$ref": "#/$defs/B"}}},
            "B": {
                "properties": {
                    "a": {"$ref": "#/$defs/A"},
                    "client": {"$ref": "#/$defs/EarthRangerConnection"},
                },
            },
            "EarthRangerConnection": {"type": "object"},
        },
    }
    assert _get_data_connection_property_names(schema) == {"EarthRanger": ["get_events"]}


def test_missing_def_is_tolerated() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "get_events": {"properties": {"config": {"$ref": "#/$defs/NotInDefs"}}},
        },
        "$defs": {},
    }
    assert _get_data_connection_property_names(schema) == {}


def test_schema_without_defs_block() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "get_events": {"properties": {"client": {"$ref": "#/$defs/EarthRangerConnection"}}},
        },
    }
    assert _get_data_connection_property_names(schema) == {"EarthRanger": ["get_events"]}


def test_no_connections_returns_empty() -> None:
    schema: dict[str, Any] = {
        "properties": {"get_events": {"properties": {"since": {"type": "string"}}}},
    }
    assert _get_data_connection_property_names(schema) == {}


def test_property_without_properties_is_skipped() -> None:
    schema: dict[str, Any] = {
        "properties": {"flag": {"type": "boolean"}},
        "$defs": {},
    }
    assert _get_data_connection_property_names(schema) == {}


def test_def_named_exactly_connection_is_not_a_connection_key() -> None:
    # stripping the suffix would leave an empty key, so it's walked as an ordinary def
    schema: dict[str, Any] = {
        "properties": {
            "get_events": {"properties": {"base": {"$ref": "#/$defs/Connection"}}},
        },
        "$defs": {"Connection": {"type": "object"}},
    }
    assert _get_data_connection_property_names(schema) == {}


def test_def_named_exactly_connection_is_walked_for_nested_connections() -> None:
    schema: dict[str, Any] = {
        "properties": {
            "get_events": {"properties": {"base": {"$ref": "#/$defs/Connection"}}},
        },
        "$defs": {
            "Connection": {"properties": {"client": {"$ref": "#/$defs/EarthRangerConnection"}}},
            "EarthRangerConnection": {"type": "object"},
        },
    }
    assert _get_data_connection_property_names(schema) == {"EarthRanger": ["get_events"]}
