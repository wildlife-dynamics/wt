"""Tests for `--with-caching`: what the compiler emits, and what it leaves alone."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wt_compiler import spec as wt_spec
from wt_compiler.cli import main
from wt_compiler.compiler import DagCompiler


@pytest.fixture
def demo_spec():
    for name, tags in (("get_events", [wt_spec.TaskTag.io]), ("chart", []), ("persist", [])):
        wt_spec.known_tasks[name] = {
            "demo.tasks": wt_spec.KnownTask(
                importable_reference=f"demo.tasks.{name}",
                tags=tags,
                json_schema={"properties": {"x": {"type": "integer"}}},
            )
        }
    return wt_spec.Spec.model_validate(
        {
            "id": "demo",
            "requirements": [{"name": "python", "version": ">=3.10"}],
            "workflow": [
                {"id": "events", "task": "get_events", "partial": {"kind": "immobility"}},
                {
                    "id": "figure",
                    "task": "chart",
                    "partial": {"data": "${{ workflow.events.return }}", "title": "Events"},
                },
                {
                    "id": "saved",
                    "task": "persist",
                    "partial": {
                        "text": "${{ workflow.figure.return }}",
                        "root_path": "${{ env.WT_RESULTS }}",
                    },
                },
            ],
        }
    )


# --- the flag is genuinely opt-in ------------------------------------------


def test_caching_is_off_by_default(demo_spec):
    assert DagCompiler(spec=demo_spec).cache is False


def test_without_the_flag_nothing_about_the_dag_changes(demo_spec):
    # The regression guarantee: existing workflows recompile byte-identically,
    # so no downstream repo needs a version bump to adopt this.
    dag = DagCompiler(spec=demo_spec, cache=False).render_dag("sequential")
    assert ".cached(" not in dag
    assert "CacheSpec" not in dag
    assert "run_scope" not in dag


def test_new_properties_stay_out_of_the_serialized_spec(demo_spec):
    # `Spec.sha256` hashes the dumped model, so a computed field here would move
    # every existing workflow's fingerprint.
    dumped = demo_spec.model_dump()["workflow"][0]
    assert not {"cache_deps", "cache_env", "cache_static"} & set(dumped)
    assert not {"recipe_hash", "is_source"} & set(dumped["known_task"])


# --- what gets emitted -----------------------------------------------------


@pytest.fixture
def cached_dag(demo_spec):
    return DagCompiler(spec=demo_spec, cache=True).render_dag("sequential")


def test_every_step_is_wrapped(cached_dag):
    assert cached_dag.count(".cached(") == 3


def test_emitted_dag_is_valid_python(cached_dag):
    compile(cached_dag, "dag.py", "exec")


def test_run_scope_wraps_the_dag_body(cached_dag):
    assert "with run_scope():" in cached_dag
    assert "return _main(params, validate_params_schema)" in cached_dag


def test_dependencies_are_emitted_as_upstream_task_ids(cached_dag):
    assert 'deps={"data": ["events"]}' in cached_dag
    assert 'deps={"text": ["figure"]}' in cached_dag


def test_env_bound_args_are_read_at_runtime(cached_dag):
    # A per-run results directory must move the key, so the *value* goes in.
    assert '"WT_RESULTS": os.environ.get("WT_RESULTS", "")' in cached_dag


def test_io_tagged_task_is_marked_a_source(cached_dag):
    events_block = cached_dag.split("figure = (")[0]
    assert "source=True" in events_block
    assert cached_dag.count("source=False") == 2


def test_runtime_params_reach_the_key(cached_dag):
    assert 'params=(params.get("events") or {})' in cached_dag


def test_mocked_io_dag_is_not_cached(demo_spec):
    # Mocked tasks return canned fixtures; caching them would store the fixture
    # under an identity that claims to describe real work.
    dag = DagCompiler(spec=demo_spec, cache=True).render_dag("sequential", mock_io=True)
    assert "create_func_magicmock" in dag  # the io task really is mocked
    assert dag.count(".cached(") == 2  # the two non-io steps only


def test_async_dag_also_emits_cache_specs(demo_spec):
    dag = DagCompiler(spec=demo_spec, cache=True).render_dag("async")
    assert ".cached(" in dag


# --- the identity pieces ---------------------------------------------------


def test_recipe_hash_is_stable_for_the_same_task():
    kwargs = {"importable_reference": "m.f", "json_schema": {"properties": {"a": {}}}}
    assert wt_spec.KnownTask(**kwargs).recipe_hash == wt_spec.KnownTask(**kwargs).recipe_hash


def test_recipe_hash_moves_when_the_signature_changes():
    # A distribution version only moves on release; a signature change within a
    # release still has to invalidate.
    a = wt_spec.KnownTask(importable_reference="m.f", json_schema={"properties": {"a": {}}})
    b = wt_spec.KnownTask(
        importable_reference="m.f", json_schema={"properties": {"a": {}, "b": {}}}
    )
    assert a.recipe_hash != b.recipe_hash


def test_recipe_hash_distinguishes_different_functions():
    schema = {"properties": {"a": {}}}
    assert (
        wt_spec.KnownTask(importable_reference="m.f", json_schema=schema).recipe_hash
        != wt_spec.KnownTask(importable_reference="m.g", json_schema=schema).recipe_hash
    )


def test_is_source_follows_the_io_tag():
    assert wt_spec.KnownTask(importable_reference="m.f", tags=[wt_spec.TaskTag.io]).is_source
    assert not wt_spec.KnownTask(importable_reference="m.f").is_source


def test_cache_static_moves_with_a_literal_argument(demo_spec):
    wt_spec.known_tasks["chart"] = wt_spec.known_tasks["chart"]
    a = wt_spec.TaskInstance(id="x", task="chart", partial={"title": "A"})
    b = wt_spec.TaskInstance(id="x", task="chart", partial={"title": "B"})
    assert a.cache_static != b.cache_static


def test_cache_static_is_stable_for_identical_bindings():
    a = wt_spec.TaskInstance(id="x", task="chart", partial={"title": "A"})
    b = wt_spec.TaskInstance(id="x", task="chart", partial={"title": "A"})
    assert a.cache_static == b.cache_static


def test_cache_deps_omits_args_with_no_upstream():
    t = wt_spec.TaskInstance(
        id="x", task="chart", partial={"data": "${{ workflow.up.return }}", "title": "A"}
    )
    assert t.cache_deps == {"data": ["up"]}


def test_cache_deps_collects_several_upstreams_for_one_arg():
    t = wt_spec.TaskInstance(
        id="x",
        task="chart",
        partial={"widgets": ["${{ workflow.a.return }}", "${{ workflow.b.return }}"]},
    )
    assert t.cache_deps == {"widgets": ["a", "b"]}


def test_cache_env_lists_referenced_variables():
    t = wt_spec.TaskInstance(
        id="x", task="chart", partial={"root": "${{ env.WT_RESULTS }}", "title": "A"}
    )
    assert t.cache_env == ["WT_RESULTS"]


def test_cache_env_is_empty_without_env_references():
    assert wt_spec.TaskInstance(id="x", task="chart", partial={"title": "A"}).cache_env == []


# --- the CLI flag ----------------------------------------------------------


@pytest.mark.parametrize(("argv_extra", "expected"), [([], False), (["--with-caching"], True)])
def test_cli_flag_reaches_the_compiler(tmp_path: Path, argv_extra, expected):
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text("id: test_workflow\n")
    artifacts = MagicMock()
    artifacts.release_dir = tmp_path / "out"

    argv = ["wt-compiler", "compile", "--spec", str(spec_file), *argv_extra]
    with (
        patch.object(sys, "argv", argv),
        patch(
            "wt_compiler.cli.compile_workflow_from_yaml", return_value=artifacts
        ) as compile_workflow,
    ):
        main()

    assert compile_workflow.call_args.kwargs["cache"] is expected
