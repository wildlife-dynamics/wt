"""Tests for `--with-caching`: what the compiler emits, and what it leaves alone."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from wt_contracts.registry import RegistryOutput

from wt_compiler import spec as wt_spec
from wt_compiler.cli import main
from wt_compiler.compiler import DagCompiler
from wt_compiler.discovery import _registry_output_to_known_tasks


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


JSON_STRUCTURE = {"k": "ref", "ref": "wt_task.cache:JSON", "type": None}


@pytest.fixture
def declared_spec(demo_spec):
    """The same spec with every task's return type declaring a codec."""
    for name in ("get_events", "chart", "persist"):
        wt_spec.known_tasks[name]["demo.tasks"].cache_structure = dict(JSON_STRUCTURE)
    return demo_spec


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
    assert not {
        "recipe_hash",
        "is_cacheable",
        "cache_structure",
        "cache_structure_error",
    } & set(dumped["known_task"])


def test_the_spec_fingerprint_is_unchanged_by_a_declared_structure(demo_spec):
    before = demo_spec.sha256
    wt_spec.known_tasks["chart"]["demo.tasks"].cache_structure = {"k": "json"}
    wt_spec.known_tasks["chart"]["demo.tasks"].cache_structure_error = "nope"
    assert demo_spec.sha256 == before


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


def test_every_step_is_servable_unless_its_author_opted_out(cached_dag):
    assert cached_dag.count("servable=True") == 3
    assert "servable=False" not in cached_dag


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


# --- opting out ------------------------------------------------------------


@pytest.fixture
def optout_dag():
    for name, tags in (("now", [wt_spec.TaskTag.no_cache]), ("chart", [])):
        wt_spec.known_tasks[name] = {
            "demo.tasks": wt_spec.KnownTask(
                importable_reference=f"demo.tasks.{name}",
                tags=tags,
                json_schema={"properties": {}},
            )
        }
    spec = wt_spec.Spec.model_validate(
        {
            "id": "optout",
            "requirements": [{"name": "python", "version": ">=3.10"}],
            "workflow": [
                {"id": "stamp", "task": "now"},
                {
                    "id": "figure",
                    "task": "chart",
                    "partial": {"data": "${{ workflow.stamp.return }}"},
                },
            ],
        }
    )
    return DagCompiler(spec=spec, cache=True).render_dag("sequential")


def test_an_opted_out_task_is_still_wrapped(optout_dag):
    # Omitting `.cached(...)` would leave the step unrecorded in run state,
    # which reads as uncacheable and poisons everything below it — the opposite
    # of what the author asked for.
    assert optout_dag.count(".cached(") == 2
    assert optout_dag.split("figure = (")[0].count("servable=False") == 1


def test_only_the_opted_out_task_is_unservable(optout_dag):
    assert optout_dag.count("servable=False") == 1
    assert optout_dag.count("servable=True") == 1


def test_an_unknown_tag_string_is_silently_dropped():
    # Pinned because it is the sharp edge the verify mode exists to catch: a
    # misspelled `no-cahce` caches anyway, with no error and no warning.
    entries = {
        "pkg.tasks.typo": {
            "metadata": {"title": "T", "description": "t", "tags": ["no-cahce"]},
            "module_path": "pkg.tasks._typo",
            "public_module_path": "pkg.tasks",
            "function_name": "typo",
            "import_statement": "from pkg.tasks import typo as typo",
            "json_schema": {"properties": {}},
        }
    }
    out = RegistryOutput.model_validate({"entries": entries, "version": "1.0.0"})
    known = _registry_output_to_known_tasks(out)["typo"]["pkg.tasks"]
    assert known.tags == []
    assert known.is_cacheable


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


def test_is_cacheable_follows_the_no_cache_tag():
    tagged = wt_spec.KnownTask(importable_reference="m.f", tags=[wt_spec.TaskTag.no_cache])
    assert not tagged.is_cacheable
    assert wt_spec.KnownTask(importable_reference="m.f").is_cacheable
    # The cache reads exactly one tag — its own. `io` means "mock me in tests".
    assert wt_spec.KnownTask(importable_reference="m.f", tags=[wt_spec.TaskTag.io]).is_cacheable


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


# --- the declared structure reaches the DAG --------------------------------


def test_the_declared_structure_and_method_are_emitted(declared_spec):
    dag = DagCompiler(spec=declared_spec, cache=True).render_dag("sequential")
    assert dag.count('"ref": "wt_task.cache:JSON"') == 3
    assert dag.count('method="call"') == 3


def test_an_undeclared_return_type_emits_a_null_structure(demo_spec):
    dag = DagCompiler(spec=demo_spec, cache=True).render_dag("sequential")
    assert dag.count("structure=None") == 3


def test_a_mapped_step_emits_its_method(declared_spec):
    spec = wt_spec.Spec.model_validate(
        {
            "id": "mapped",
            "requirements": [{"name": "python", "version": ">=3.10"}],
            "workflow": [
                {"id": "events", "task": "get_events", "partial": {"kind": "immobility"}},
                {
                    "id": "figures",
                    "task": "chart",
                    "map": {
                        "argnames": "data",
                        "argvalues": "${{ workflow.events.return }}",
                    },
                },
            ],
        }
    )
    dag = DagCompiler(spec=spec, cache=True).render_dag("sequential")
    assert 'method="map"' in dag
    assert 'method="call"' in dag


def test_only_io_tagged_steps_are_scoped(declared_spec):
    # A derived step is a pure function of its input digests, so folding a
    # per-request scope into its key would make a fresh token a cold run.
    dag = DagCompiler(spec=declared_spec, cache=True).render_dag("sequential")
    assert dag.count("scoped=True") == 1
    assert dag.count("scoped=False") == 2


# --- the compile-time report -----------------------------------------------


def test_every_step_is_cacheable_when_every_return_type_declares_one(declared_spec):
    rows = DagCompiler(spec=declared_spec, cache=True).cache_report()
    assert [r.status for r in rows] == ["cacheable"] * 3


def test_an_undeclared_return_type_propagates_down_the_report(declared_spec):
    wt_spec.known_tasks["chart"]["demo.tasks"].cache_structure = None
    rows = {
        r.task_instance_id: r for r in DagCompiler(spec=declared_spec, cache=True).cache_report()
    }

    assert rows["events"].status == "cacheable"
    assert rows["figure"].status == "uncacheable"
    assert rows["figure"].reason == "return type has no codec"
    assert rows["saved"].status == "uncacheable"
    assert rows["saved"].reason == "upstream figure uncacheable"


def test_a_no_cache_task_is_unservable_and_does_not_block_its_dependents(declared_spec):
    wt_spec.known_tasks["get_events"]["demo.tasks"].tags = [wt_spec.TaskTag.no_cache]
    rows = {
        r.task_instance_id: r for r in DagCompiler(spec=declared_spec, cache=True).cache_report()
    }
    assert (rows["events"].status, rows["events"].reason) == ("unservable", "no-cache tag")
    assert rows["figure"].status == "cacheable"


def test_a_bad_declaration_is_reported_and_blocks_a_caching_compile(declared_spec):
    wt_spec.known_tasks["chart"]["demo.tasks"].cache_structure = None
    wt_spec.known_tasks["chart"]["demo.tasks"].cache_structure_error = "excludes field help_text"

    compiler = DagCompiler(spec=declared_spec, cache=True)
    rows = {r.task_instance_id: r for r in compiler.cache_report()}
    assert rows["figure"].reason == "excludes field help_text"

    with pytest.raises(ValueError, match="help_text"):
        compiler._check_cache_declarations()
    # Without the flag it is data, not an error: one bad declaration in a task
    # library must not break every non-caching compile against it.
    assert ".cached(" not in DagCompiler(spec=declared_spec, cache=False).render_dag("sequential")


def test_the_report_is_logged_under_the_flag(declared_spec, caplog):
    wt_spec.known_tasks["chart"]["demo.tasks"].cache_structure = None
    with caplog.at_level("INFO"):
        DagCompiler(spec=declared_spec, cache=True).log_cache_report()
    assert "figure is uncacheable" in caplog.text
    assert "1 of 3 steps cacheable" in caplog.text


# --- the per-run report in the result envelope -----------------------------


def test_the_envelope_carries_the_run_report_under_the_flag(demo_spec):
    compiler = DagCompiler(spec=demo_spec, cache=True)
    assert "cache: dict[str, Any] | None = None" in compiler.ruffrender("pkg/response.jinja2")
    dispatch = compiler.ruffrender("pkg/dispatch.jinja2", cache=True)
    assert "run_report()" in dispatch


def test_the_dispatcher_is_byte_identical_without_the_flag(demo_spec):
    compiler = DagCompiler(spec=demo_spec, cache=False)
    dispatch = compiler.ruffrender("pkg/dispatch.jinja2", cache=False)
    assert "run_report" not in dispatch
    assert "ResponseModel(result=result)" in dispatch
