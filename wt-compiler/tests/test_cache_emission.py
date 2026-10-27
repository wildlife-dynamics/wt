"""Tests for `--with-caching`: what the compiler emits, and what it leaves alone."""

import json
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rattler import MatchSpec

from wt_compiler import spec as wt_spec
from wt_compiler.cli import main
from wt_compiler.compiler import DagCompiler
from wt_compiler.discovery import discover_tasks_from_requirements


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


@pytest.fixture
def declared_spec(demo_spec):
    """The same spec with every task's return type declaring a codec."""
    for name in ("get_events", "chart", "persist"):
        wt_spec.known_tasks[name]["demo.tasks"].declares_codec = True
    return demo_spec


# --- the flag is genuinely opt-in ------------------------------------------


def test_caching_is_off_by_default(demo_spec):
    assert DagCompiler(spec=demo_spec).caching_enabled is False


def test_without_the_flag_nothing_about_the_dag_changes(demo_spec):
    # The regression guarantee: existing workflows recompile byte-identically,
    # so no downstream repo needs a version bump to adopt this.
    dag = DagCompiler(spec=demo_spec).render_dag("sequential")
    assert ".cached(" not in dag
    assert "CacheSpec" not in dag
    assert "run_scope" not in dag


def test_new_properties_stay_out_of_the_serialized_spec(demo_spec):
    # `Spec.sha256` hashes the dumped model, so a computed field here would move
    # every existing workflow's fingerprint.
    dumped = demo_spec.model_dump()["workflow"][0]
    assert not {"cache_upstream_inputs", "cache_env", "cache_fixed_inputs"} & set(dumped)
    assert not {
        "signature",
        "is_cacheable",
        "declares_codec",
        "cache_declaration_error",
    } & set(dumped["known_task"])


def test_the_spec_fingerprint_is_unchanged_by_a_cache_declaration(demo_spec):
    before = demo_spec.sha256
    wt_spec.known_tasks["chart"]["demo.tasks"].declares_codec = True
    wt_spec.known_tasks["chart"]["demo.tasks"].cache_declaration_error = "nope"
    assert demo_spec.sha256 == before


# --- what gets emitted -----------------------------------------------------


@pytest.fixture
def cached_dag(demo_spec):
    return DagCompiler(spec=demo_spec, caching="report").render_dag("sequential")


def test_every_step_is_wrapped(cached_dag):
    assert cached_dag.count(".cached(") == 3


def test_emitted_dag_is_valid_python(cached_dag):
    compile(cached_dag, "dag.py", "exec")


def test_run_scope_wraps_the_dag_body(cached_dag):
    # The run's parameters go in once, here, rather than into every step.
    assert "with run_scope(params=params):" in cached_dag
    assert "return _main(params, validate_params_schema)" in cached_dag


def test_dependencies_are_emitted_as_upstream_task_ids(cached_dag):
    assert 'upstream_inputs={"data": ["events"]}' in cached_dag
    assert 'upstream_inputs={"text": ["figure"]}' in cached_dag


def test_env_bound_args_are_read_at_runtime(cached_dag):
    # The spec names the variable; the runtime reads its value when it builds
    # the key, so a per-run results directory still moves it.
    assert 'env=["WT_RESULTS"]' in cached_dag


def test_every_step_is_servable_unless_its_author_opted_out(cached_dag):
    # The default is not spelled out; only the exception is.
    assert "servable=" not in cached_dag


def test_runtime_params_reach_the_key(cached_dag):
    # Not per step any more: `run_scope` carries the whole run's parameters,
    # and the runtime looks up this step's by its task-instance id.
    assert "with run_scope(params=params):" in cached_dag
    assert "params=" not in _first_cached_call(cached_dag)
    # Still bound as arguments, which is a separate job.
    assert 'params.get("events")' in cached_dag


def test_mocked_io_dag_is_not_cached(demo_spec):
    # Mocked tasks return canned fixtures; caching them would store the fixture
    # under an identity that claims to describe real work.
    dag = DagCompiler(spec=demo_spec, caching="report").render_dag("sequential", mock_io=True)
    assert "create_func_magicmock" in dag  # the io task really is mocked
    assert dag.count(".cached(") == 2  # the two non-io steps only


def test_the_async_dag_is_generated_without_caching(demo_spec):
    # An async method hands back a future, which has no stored form.
    dag = DagCompiler(spec=demo_spec, caching="report").render_dag("async")
    assert ".cached(" not in dag
    assert "run_scope" not in dag
    assert "CacheSpec" not in dag


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
    return DagCompiler(spec=spec, caching="report").render_dag("sequential")


def test_an_opted_out_task_is_still_wrapped(optout_dag):
    # Omitting `.cached(...)` would leave the step unrecorded in run state,
    # which reads as uncacheable and poisons everything below it — the opposite
    # of what the author asked for.
    assert optout_dag.count(".cached(") == 2
    assert optout_dag.split("figure = (")[0].count("servable=False") == 1


def test_only_the_opted_out_task_is_unservable(optout_dag):
    assert optout_dag.count("servable=False") == 1


async def _discover(entry: dict, tmp_path: Path) -> wt_spec.KnownTask:
    """Run one registry entry through discovery, with the environment build mocked out."""
    (tmp_path / "env" / "bin").mkdir(parents=True)
    (tmp_path / "env" / "bin" / "wt-registry").touch()
    record = MagicMock()
    record.name.normalized = "wt-registry"
    record.channel = "https://conda.anaconda.org/conda-forge/"
    output = {"entries": {"pkg.tasks.typo": entry}, "version": "1.0.0"}
    with (
        patch("wt_compiler.discovery.tempfile.TemporaryDirectory") as tmpdir,
        patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock) as create,
        patch("wt_compiler.discovery.subprocess.run") as run,
    ):
        tmpdir.return_value.__enter__ = MagicMock(return_value=str(tmp_path))
        tmpdir.return_value.__exit__ = MagicMock(return_value=False)
        create.return_value = [record]
        run.return_value = MagicMock(stdout=json.dumps(output), returncode=0)
        result = await discover_tasks_from_requirements([MatchSpec("pkg>=1.0.0")])
    return result.tasks["typo"]["pkg.tasks"]


def _entry(**extra: object) -> dict:
    return {
        "metadata": {"title": "T", "description": "t", "tags": ["no-cahce"]},
        "module_path": "pkg.tasks._typo",
        "public_module_path": "pkg.tasks",
        "function_name": "typo",
        "import_statement": "from pkg.tasks import typo as typo",
        "json_schema": {"properties": {}},
        **extra,
    }


@pytest.mark.asyncio
async def test_an_unknown_tag_string_is_silently_dropped(tmp_path):
    # Pinned because it is the sharp edge the verify mode exists to catch: a
    # misspelled `no-cahce` caches anyway, with no error and no warning.
    known = await _discover(_entry(), tmp_path)
    assert known.tags == []
    assert known.is_cacheable


@pytest.mark.asyncio
async def test_discovery_carries_the_cache_declaration_and_its_error(tmp_path):
    known = await _discover(_entry(declares_codec=True), tmp_path)
    assert known.declares_codec
    assert known.cache_declaration_error is None

    known = await _discover(_entry(cache_declaration_error="excludes field x"), tmp_path / "bad")
    assert not known.declares_codec
    assert known.cache_declaration_error == "excludes field x"


# --- the identity pieces ---------------------------------------------------


def test_signature_hash_is_stable_for_the_same_task():
    kwargs = {"importable_reference": "m.f", "json_schema": {"properties": {"a": {}}}}
    assert wt_spec.KnownTask(**kwargs).signature == wt_spec.KnownTask(**kwargs).signature


def test_signature_hash_moves_when_the_signature_changes():
    # A distribution version only moves on release; a signature change within a
    # release still has to invalidate.
    a = wt_spec.KnownTask(importable_reference="m.f", json_schema={"properties": {"a": {}}})
    b = wt_spec.KnownTask(
        importable_reference="m.f", json_schema={"properties": {"a": {}, "b": {}}}
    )
    assert a.signature != b.signature


def test_signature_hash_distinguishes_different_functions():
    schema = {"properties": {"a": {}}}
    assert (
        wt_spec.KnownTask(importable_reference="m.f", json_schema=schema).signature
        != wt_spec.KnownTask(importable_reference="m.g", json_schema=schema).signature
    )


def test_is_cacheable_follows_the_no_cache_tag():
    tagged = wt_spec.KnownTask(importable_reference="m.f", tags=[wt_spec.TaskTag.no_cache])
    assert not tagged.is_cacheable
    assert wt_spec.KnownTask(importable_reference="m.f").is_cacheable
    # The cache reads exactly one tag — its own. `io` means "mock me in tests".
    assert wt_spec.KnownTask(importable_reference="m.f", tags=[wt_spec.TaskTag.io]).is_cacheable


def test_cache_fixed_inputs_moves_with_a_literal_argument(demo_spec):
    wt_spec.known_tasks["chart"] = wt_spec.known_tasks["chart"]
    a = wt_spec.TaskInstance(id="x", task="chart", partial={"title": "A"})
    b = wt_spec.TaskInstance(id="x", task="chart", partial={"title": "B"})
    assert a.cache_fixed_inputs != b.cache_fixed_inputs


def test_cache_fixed_inputs_is_stable_for_identical_bindings():
    a = wt_spec.TaskInstance(id="x", task="chart", partial={"title": "A"})
    b = wt_spec.TaskInstance(id="x", task="chart", partial={"title": "A"})
    assert a.cache_fixed_inputs == b.cache_fixed_inputs


def test_cache_fixed_inputs_moves_with_the_skipif_conditions(demo_spec):
    # The conditions decide whether the step returns the skip sentinel, so a
    # binding without them must not be served one stored by a binding with them.
    for name in ("is_empty", "never"):
        wt_spec.known_tasks[name] = {
            "demo.conditions": wt_spec.KnownTask(importable_reference=f"demo.conditions.{name}")
        }

    def fixed(skipif):
        return wt_spec.TaskInstance(
            id="x", task="chart", partial={"title": "A"}, skipif=skipif
        ).cache_fixed_inputs

    keys = [
        fixed(None),
        fixed({"conditions": ["is_empty"]}),
        fixed({"conditions": ["never"]}),
        fixed({"conditions": ["is_empty"], "unpack_depth": 2}),
    ]
    assert len(set(keys)) == len(keys)
    assert fixed({"conditions": ["is_empty"]}) == keys[1]


def test_cache_upstream_inputs_omits_args_with_no_upstream():
    t = wt_spec.TaskInstance(
        id="x", task="chart", partial={"data": "${{ workflow.up.return }}", "title": "A"}
    )
    assert t.cache_upstream_inputs == {"data": ["up"]}


def test_cache_upstream_inputs_collects_several_upstreams_for_one_arg():
    t = wt_spec.TaskInstance(
        id="x",
        task="chart",
        partial={"widgets": ["${{ workflow.a.return }}", "${{ workflow.b.return }}"]},
    )
    assert t.cache_upstream_inputs == {"widgets": ["a", "b"]}


def test_cache_env_lists_referenced_variables():
    t = wt_spec.TaskInstance(
        id="x", task="chart", partial={"root": "${{ env.WT_RESULTS }}", "title": "A"}
    )
    assert t.cache_env == ["WT_RESULTS"]


def test_cache_env_is_empty_without_env_references():
    assert wt_spec.TaskInstance(id="x", task="chart", partial={"title": "A"}).cache_env == []


# --- keys do not depend on what a spec names its steps ---------------------


REF_A = "${{ workflow.alpha.return }}"
REF_B = "${{ workflow.beta.return }}"


def static(**partial):
    return wt_spec.TaskInstance(id="x", task="chart", partial=partial).cache_fixed_inputs


def test_renaming_an_upstream_step_does_not_move_the_key():
    # The upstream's *output* is already in the key, as a digest under
    # `inputs`; its id is an artifact of how one spec was written.
    assert static(data=REF_A) == static(data=REF_B)


def test_the_steps_own_id_does_not_reach_its_static_hash():
    a = wt_spec.TaskInstance(id="first", task="chart", partial={"data": REF_A})
    b = wt_spec.TaskInstance(id="second", task="chart", partial={"data": REF_A})
    assert a.cache_fixed_inputs == b.cache_fixed_inputs


def test_two_specs_differing_only_in_step_ids_agree_step_for_step(demo_spec):
    renamed = wt_spec.Spec.model_validate(
        {
            "id": "demo",
            "requirements": [{"name": "python", "version": ">=3.10"}],
            "workflow": [
                {"id": "fetched", "task": "get_events", "partial": {"kind": "immobility"}},
                {
                    "id": "plotted",
                    "task": "chart",
                    "partial": {
                        "data": "${{ workflow.fetched.return }}",
                        "title": "Events",
                    },
                },
                {
                    "id": "written",
                    "task": "persist",
                    "partial": {
                        "text": "${{ workflow.plotted.return }}",
                        "root_path": "${{ env.WT_RESULTS }}",
                    },
                },
            ],
        }
    )
    assert [t.cache_fixed_inputs for t in renamed.flat_workflow] == [
        t.cache_fixed_inputs for t in demo_spec.flat_workflow
    ]


def test_which_argument_holds_a_reference_still_matters():
    # Dropping references outright rather than marking them would collide
    # these: only `static` records where a reference sits.
    assert static(x=REF_A) != static(y=REF_A)


def test_where_a_reference_sits_in_a_list_still_matters():
    assert static(widgets=[REF_A, "lit"]) != static(widgets=["lit", REF_A])


def test_where_a_reference_sits_in_a_nested_dict_still_matters():
    assert static(opts={"a": REF_A, "b": "lit"}) != static(opts={"a": "lit", "b": REF_A})


def test_two_references_in_one_dict_do_not_collide_when_swapped():
    # `inputs` lists digests in document order, so the hash has to keep that
    # order too — a key-sorted hash would make these two the same step.
    assert static(opts={"a": REF_A, "b": REF_B}) != static(opts={"b": REF_A, "a": REF_B})


def test_a_literal_cannot_be_mistaken_for_a_reference_marker():
    assert static(title="$dep") != static(title=REF_A)


def test_literal_values_still_move_the_key():
    assert static(title="A", data=REF_A) != static(title="B", data=REF_A)


def test_environment_references_are_left_alone():
    # Env names are not workflow-specific, and their values reach the key
    # through `env` at run time.
    assert static(root="${{ env.WT_RESULTS }}") != static(root="${{ env.OTHER }}")


def test_a_mapped_step_over_differently_named_upstreams_agrees():
    def mapped(ref):
        return wt_spec.TaskInstance(
            id="x", task="chart", map={"argnames": "data", "argvalues": ref}
        ).cache_fixed_inputs

    assert mapped(REF_A) == mapped(REF_B)
    # The argname is not an id, and still has to count.
    assert (
        mapped(REF_A)
        != wt_spec.TaskInstance(
            id="x", task="chart", map={"argnames": "other", "argvalues": REF_A}
        ).cache_fixed_inputs
    )


def test_a_mapvalues_step_over_differently_named_upstreams_agrees():
    def mapvalues(ref):
        return wt_spec.TaskInstance(
            id="x", task="chart", mapvalues={"argnames": "data", "argvalues": ref}
        ).cache_fixed_inputs

    assert mapvalues(REF_A) == mapvalues(REF_B)


def test_map_and_mapvalues_do_not_collide():
    bound = {"argnames": "data", "argvalues": REF_A}
    assert (
        wt_spec.TaskInstance(id="x", task="chart", map=bound).cache_fixed_inputs
        != wt_spec.TaskInstance(id="x", task="chart", mapvalues=bound).cache_fixed_inputs
    )


def test_renaming_steps_does_not_change_the_spec_fingerprint_contract(demo_spec):
    # `cache_fixed_inputs` is not serialized, so none of this touches `Spec.sha256`.
    before = demo_spec.sha256
    assert [t.cache_fixed_inputs for t in demo_spec.flat_workflow]
    assert demo_spec.sha256 == before
    dumped = demo_spec.model_dump()["workflow"][1]
    assert "cache_fixed_inputs" not in dumped
    # A renamed spec *is* a different workflow, and still fingerprints as one.
    assert "plotted" not in json.dumps(dumped)


# --- the CLI flag ----------------------------------------------------------


@pytest.mark.parametrize(
    ("argv_extra", "caching"),
    [
        ([], "off"),
        (["--with-caching"], "report"),
        (["--with-caching=strict"], "strict"),
        (["--with-caching", "strict"], "strict"),
    ],
)
def test_cli_flag_reaches_the_compiler(tmp_path: Path, argv_extra, caching):
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

    assert compile_workflow.call_args.kwargs["caching"] == caching


def test_an_unknown_caching_mode_is_rejected(tmp_path: Path, capsys):
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text("id: test_workflow\n")
    argv = ["wt-compiler", "compile", "--spec", str(spec_file), "--with-caching=loose"]
    with patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    assert "invalid choice: 'loose'" in capsys.readouterr().err


# --- the declared structure reaches the DAG --------------------------------


def _cached_calls(dag):
    """Each `.cached(...)` call in a rendered DAG, whitespace-normalised."""
    calls = []
    for start in (i for i in range(len(dag)) if dag.startswith(".cached(", i)):
        depth = 0
        for i in range(dag.index("(", start), len(dag)):
            depth += dag[i] in "(["
            depth -= dag[i] in ")]"
            if depth == 0:
                flat = " ".join(dag[start : i + 1].split())
                # The formatter wraps the longer ones; compare the call, not
                # the line breaks it chose.
                calls.append(flat.replace("( ", "(").replace(" )", ")").replace(",)", ")"))
                break
        else:
            raise AssertionError("unbalanced .cached(")
    return calls


def _first_cached_call(dag):
    return _cached_calls(dag)[0]


def test_a_default_step_is_one_short_cached_call(declared_spec):
    # Everything the runtime can work out for itself stays out of the DAG.
    dag = DagCompiler(spec=declared_spec, caching="report").render_dag("sequential")
    calls = _cached_calls(dag)
    assert len(calls) == 3

    signature = wt_spec.known_tasks["chart"]["demo.tasks"].signature
    fixed = next(t for t in declared_spec.flat_workflow if t.id == "figure").cache_fixed_inputs
    assert calls[1] == (
        f'.cached(CacheSpec(signature="{signature}", fixed_inputs="{fixed}", '
        'upstream_inputs={"data": ["events"]}))'
    )

    for call in calls:
        assert call.startswith('.cached(CacheSpec(signature="')
        for absent in (
            "structure",
            "anchor=",
            "function=",
            "task_instance_id",
            "method=",
            "params=",
        ):
            assert absent not in call


def test_only_io_tagged_steps_are_marked_io(declared_spec):
    # The flag only drives the io rules (TTL, never served unscoped); every
    # step's key carries the scope regardless.
    dag = DagCompiler(spec=declared_spec, caching="report").render_dag("sequential")
    assert len(re.findall(r"\bio=True", dag)) == 1
    assert not re.search(r"\bio=False", dag)


# --- the compile-time report -----------------------------------------------


def test_every_step_is_cacheable_when_every_return_type_declares_one(declared_spec):
    rows = DagCompiler(spec=declared_spec, caching="report").cacheability_report()
    assert [r.status for r in rows] == ["cacheable"] * 3


def test_an_undeclared_return_type_propagates_down_the_report(declared_spec):
    wt_spec.known_tasks["chart"]["demo.tasks"].declares_codec = False
    rows = {
        r.task_instance_id: r
        for r in DagCompiler(spec=declared_spec, caching="report").cacheability_report()
    }

    assert rows["events"].status == "cacheable"
    assert rows["figure"].status == "uncacheable"
    assert rows["figure"].reason == "return type has no codec"
    assert rows["saved"].status == "uncacheable"
    assert rows["saved"].reason == "upstream figure uncacheable"


def test_a_no_cache_task_is_unservable_and_does_not_block_its_dependents(declared_spec):
    wt_spec.known_tasks["get_events"]["demo.tasks"].tags = [wt_spec.TaskTag.no_cache]
    rows = {
        r.task_instance_id: r
        for r in DagCompiler(spec=declared_spec, caching="report").cacheability_report()
    }
    assert (rows["events"].status, rows["events"].reason) == ("unservable", "no-cache tag")
    assert rows["figure"].status == "cacheable"


def _with_a_bad_declaration() -> None:
    wt_spec.known_tasks["chart"]["demo.tasks"].declares_codec = False
    wt_spec.known_tasks["chart"]["demo.tasks"].cache_declaration_error = "excludes field help_text"


class _PastTheGateError(Exception):
    """Raised from `on_progress`, the first thing `compile` does after the cache gate."""


def _compile_until_past_the_gate(compiler: DagCompiler, tmp_path: Path) -> None:
    def stop(_: str) -> None:
        raise _PastTheGateError

    compiler.compile(
        str(tmp_path / "spec.yaml"), merged_default_feature=MagicMock(), on_progress=stop
    )


def test_a_bad_declaration_is_reported_but_does_not_block_a_caching_compile(
    declared_spec, tmp_path
):
    _with_a_bad_declaration()

    compiler = DagCompiler(spec=declared_spec, caching="report")
    rows = {r.task_instance_id: r for r in compiler.cacheability_report()}
    assert (rows["figure"].status, rows["figure"].reason) == (
        "uncacheable",
        "excludes field help_text",
    )
    with pytest.raises(_PastTheGateError):
        _compile_until_past_the_gate(compiler, tmp_path)


def test_a_bad_declaration_blocks_a_strict_caching_compile(declared_spec, tmp_path):
    _with_a_bad_declaration()

    compiler = DagCompiler(spec=declared_spec, caching="strict")
    with pytest.raises(ValueError, match=r"demo\.tasks\.chart: excludes field help_text"):
        _compile_until_past_the_gate(compiler, tmp_path)


def test_the_report_is_logged_under_the_flag(declared_spec, caplog):
    wt_spec.known_tasks["chart"]["demo.tasks"].declares_codec = False
    with caplog.at_level("INFO"):
        DagCompiler(spec=declared_spec, caching="report").log_cacheability_report()
    assert "figure is uncacheable" in caplog.text
    assert "1 of 3 steps cacheable" in caplog.text
    # Every step gets a line, not only the ones the cache cannot serve, plus the summary.
    assert len([r for r in caplog.records if r.getMessage().startswith("cache: ")]) == 4


# --- the per-run report beside the result envelope -------------------------


def _cli(spec, cache):
    return DagCompiler(spec=spec, caching="report" if cache else "off").ruffrender(
        "pkg/cli.jinja2", release_name="demo", results_env_var="WT_RESULTS", cache=cache
    )


@pytest.mark.parametrize("cache", [True, False])
def test_the_result_envelope_has_no_cache_field(demo_spec, cache):
    compiler = DagCompiler(spec=demo_spec, caching="report" if cache else "off")
    assert "cache" not in compiler.ruffrender("pkg/response.jinja2")
    dispatch = compiler.ruffrender("pkg/dispatch.jinja2")
    assert "run_report" not in dispatch
    assert "ResponseModel(result=result)" in dispatch


def test_the_cli_writes_the_cache_report_under_the_flag(demo_spec):
    cli = _cli(demo_spec, cache=True)
    compile(cli, "cli.py", "exec")
    assert "from wt_task.cache import put_cache_report" in cli
    # Once per tracing branch, each before result.json, so a failed result
    # write still leaves the report behind.
    assert cli.count("put_cache_report(result_store, error=response.error)") == 2
    for branch in cli.split("put_cache_report(result_store, error=response.error)")[1:]:
        assert 'result_store.put("result.json"' in branch.split("put_cache_report")[0]


def test_the_cli_is_unchanged_without_the_flag(demo_spec):
    assert "put_cache_report" not in _cli(demo_spec, cache=False)


# --- what the generated README says ----------------------------------------


def _readme(spec, cache):
    return DagCompiler(spec=spec, caching="report" if cache else "off").plainrender(
        "README.jinja2", fingerprint="", spec_id=spec.id, release_name="demo", cache=cache
    )


def test_the_readme_documents_caching_only_when_it_is_on(demo_spec):
    assert "## Caching" not in _readme(demo_spec, cache=False)
    readme = _readme(demo_spec, cache=True)
    assert "## Caching" in readme
    # The section is a summary; the docs page is where caching is documented.
    assert "docs/content/caching.md" in readme
    assert "cache-report.json" in readme


def test_the_readme_warns_that_an_editable_install_freezes_the_key(demo_spec):
    # The sharpest edge in the whole feature: a dev edits a task in a checkout,
    # the version string does not move, and the warm run serves the old result.
    readme = _readme(demo_spec, cache=True)
    assert "editable install" in readme
    assert "WT_CACHE__EPOCH" in readme
    assert "signature" in readme  # a signature change does still invalidate
