"""End-to-end: execute a generated DAG twice and check what actually re-runs.

These build a real importable package from the compiler's own output and run it
through the real `wt-task` runtime, because the thing worth proving is that the
emitted code and the runtime agree — not that each half works in isolation.
"""

import json
import sys
import warnings
from pathlib import Path

import pytest
from wt_contracts import declared_structure
from wt_task.cache import REPORT_NAME, CacheMismatchWarning, put_cache_report

# Private, but the fixture has to invalidate what the runtime memoizes per process.
from wt_task.cache._key import _packages_distributions, distribution_fingerprint
from wt_task.cache._store import LocalStore

from wt_compiler import spec as wt_spec
from wt_compiler.compiler import DagCompiler

TASKS_MODULE = '''
"""Task library for the end-to-end cache tests.

Plain functions: the generated DAG imports each by name and wraps it with
`task(...)`, so `@register` plays no part at run time.
"""
import hashlib
import json
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel
from wt_contracts import Cacheable, CodecRef
from wt_task.cache import JSON, Codec

LOG = Path(__file__).parent / "calls.jsonl"

# An `Annotated` alias, the way a task library declares a codec for a type it
# owns. `ROWS` is resolved by import path, against this installed distribution.
ROWS = JSON
Rows = Annotated[dict[str, Any], CodecRef("e2e_tasks:ROWS")]


def summary_codec(cls):
    """The class-parameterized form: the structure names the class, not the codec."""
    return Codec(
        codec_id="e2e.summary/v1",
        media_type="application/json",
        types=(cls,),
        encode=lambda v: v.model_dump_json().encode(),
        decode=cls.model_validate_json,
        digest=lambda v: hashlib.sha256(v.model_dump_json().encode()).hexdigest(),
        accepts_subclasses=False,
    )


class Summary(BaseModel, Cacheable):
    __wt_codec__ = "e2e_tasks:summary_codec"

    label: str
    total: int


def _log(name, value):
    with LOG.open("a") as f:
        f.write(json.dumps({"task": name, "value": value}) + "\\n")


def calls(task=None):
    if not LOG.exists():
        return []
    entries = [json.loads(line) for line in LOG.read_text().splitlines()]
    return [e for e in entries if task is None or e["task"] == task]


def reset():
    LOG.unlink(missing_ok=True)


def read_source(payload: int) -> Rows:
    _log("read_source", payload)
    return {"rows": [1, 2, 3], "payload": payload}


def read_stable(payload: int) -> Rows:
    """Re-reads on every key change but always returns the same data."""
    _log("read_stable", payload)
    return {"rows": [1, 2, 3]}


def transform(data: dict, factor: int) -> Rows:
    _log("transform", factor)
    return {"rows": [r * factor for r in data["rows"]]}


def relabel(data: dict, tag: str) -> Rows:
    """A mid-DAG step whose key moves with `tag` but whose output never does."""
    _log("relabel", tag)
    return {"rows": data["rows"]}


def stamp(payload: int) -> Rows:
    """Tagged `no-cache`: never served, but always returns the same thing."""
    _log("stamp", payload)
    return {"rows": [1, 2, 3]}


def wobble() -> Rows:
    """Nondeterministic for fixed inputs — what verify mode exists to find."""
    counter = LOG.parent / "wobble.count"
    n = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(n))
    _log("wobble", n)
    return {"rows": [n]}


def explode(data: dict) -> Rows:
    _log("explode", None)
    raise ValueError("boom")


def summarise(data: dict, label: str) -> Summary:
    _log("summarise", label)
    return Summary(label=label, total=sum(data["rows"]))
'''

METADATA_MODULE = '''
"""Stub of the compiler-generated metadata module."""


def load_params_schema():
    return {"type": "object", "properties": {}}
'''


def _build_spec(
    source_payload="${{ env.SOURCE_PAYLOAD }}",
    factor=2,
    label="Report",
    source_task="read_source",
):
    import e2e_tasks  # noqa: PLC0415  # only importable once the fixture extends sys.path

    for name, tags in (
        ("read_source", [wt_spec.TaskTag.io]),
        ("read_stable", [wt_spec.TaskTag.io]),
        ("stamp", [wt_spec.TaskTag.no_cache]),
        ("relabel", []),
        ("wobble", []),
        ("transform", []),
        ("explode", []),
        ("summarise", []),
    ):
        wt_spec.known_tasks[name] = {
            "e2e_tasks": wt_spec.KnownTask(
                importable_reference=f"e2e_tasks.{name}",
                tags=tags,
                json_schema={"properties": {}},
                # What wt-registry would have put on the wire. Resolved from the
                # real functions so the refs the DAG carries really do import.
                declares_codec=declared_structure(getattr(e2e_tasks, name)) is not None,
            )
        }
    return wt_spec.Spec.model_validate(
        {
            "id": "e2e",
            "requirements": [{"name": "python", "version": ">=3.10"}],
            "workflow": [
                {
                    "id": "source",
                    "task": source_task,
                    # `None` means "leave it unbound", so the value arrives as a
                    # runtime param instead; binding both would be a duplicate kwarg.
                    "partial": ({} if source_payload is None else {"payload": source_payload}),
                },
                {
                    "id": "shaped",
                    "task": "transform",
                    "partial": {
                        "data": "${{ workflow.source.return }}",
                        "factor": factor,
                    },
                },
                {
                    "id": "report",
                    "task": "summarise",
                    "partial": {
                        "data": "${{ workflow.shaped.return }}",
                        "label": label,
                    },
                },
            ],
        }
    )


def _build_failing_spec():
    """Three steps whose middle one raises, so the last never runs."""
    _build_spec()  # registers the known tasks
    return wt_spec.Spec.model_validate(
        {
            "id": "e2e_failing",
            "requirements": [{"name": "python", "version": ">=3.10"}],
            "workflow": [
                {"id": "source", "task": "read_source", "partial": {"payload": 1}},
                {
                    "id": "broken",
                    "task": "explode",
                    "partial": {"data": "${{ workflow.source.return }}"},
                },
                {
                    "id": "report",
                    "task": "summarise",
                    "partial": {"data": "${{ workflow.broken.return }}", "label": "Report"},
                },
            ],
        }
    )


def _build_renamed_spec():
    """The same three steps as `_build_spec`, under different ids."""
    _build_spec()  # registers the known tasks
    return wt_spec.Spec.model_validate(
        {
            "id": "e2e_renamed",
            "requirements": [{"name": "python", "version": ">=3.10"}],
            "workflow": [
                {
                    "id": "fetched",
                    "task": "read_source",
                    "partial": {"payload": "${{ env.SOURCE_PAYLOAD }}"},
                },
                {
                    "id": "reshaped",
                    "task": "transform",
                    "partial": {"data": "${{ workflow.fetched.return }}", "factor": 2},
                },
                {
                    "id": "written",
                    "task": "summarise",
                    "partial": {"data": "${{ workflow.reshaped.return }}", "label": "Report"},
                },
            ],
        }
    )


def _build_relabel_spec(tag="first"):
    """A four-step DAG whose middle step ignores one of its own arguments."""
    _build_spec()  # registers the known tasks
    return wt_spec.Spec.model_validate(
        {
            "id": "e2e_relabel",
            "requirements": [{"name": "python", "version": ">=3.10"}],
            "workflow": [
                {"id": "source", "task": "read_source", "partial": {"payload": 1}},
                {
                    "id": "tagged",
                    "task": "relabel",
                    "partial": {"data": "${{ workflow.source.return }}", "tag": tag},
                },
                {
                    "id": "shaped",
                    "task": "transform",
                    "partial": {"data": "${{ workflow.tagged.return }}", "factor": 2},
                },
                {
                    "id": "report",
                    "task": "summarise",
                    "partial": {"data": "${{ workflow.shaped.return }}", "label": "Report"},
                },
            ],
        }
    )


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    """Build, install and return a runnable generated workflow package."""
    monkeypatch.setenv("WT_CACHE__STORE", str(tmp_path / "cache"))
    monkeypatch.setenv("SOURCE_PAYLOAD", "1")
    monkeypatch.delenv("WT_CACHE__EPOCH", raising=False)
    # An io step with no scope is never served; most tests here want it to be.
    monkeypatch.setenv("WT_CACHE__SCOPE", "tenant-a")
    monkeypatch.delenv("WT_CACHE__VERIFY", raising=False)
    monkeypatch.syspath_prepend(str(tmp_path))

    (tmp_path / "e2e_tasks.py").write_text(TASKS_MODULE)
    # The cache pins a step to the version of the distribution providing its
    # task, and refuses to cache when it cannot resolve one. A loose module on
    # sys.path belongs to no distribution, so the fixture library ships as a
    # real (if minimal) installed one.
    dist_info = tmp_path / "e2e_tasks-1.0.0.dist-info"
    dist_info.mkdir(exist_ok=True)
    (dist_info / "METADATA").write_text("Metadata-Version: 2.1\nName: e2e-tasks\nVersion: 1.0.0\n")
    (dist_info / "top_level.txt").write_text("e2e_tasks\n")
    _packages_distributions.cache_clear()
    distribution_fingerprint.cache_clear()

    # Each test gets its own tmp_path, so a module cached from a previous test
    # would log into the wrong directory and every assertion would read zero calls.
    sys.modules.pop("e2e_tasks", None)

    def build(spec, cache=True, name="generated"):
        pkg = tmp_path / name
        (pkg / "dags").mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "metadata.py").write_text(METADATA_MODULE)
        (pkg / "dags" / "__init__.py").write_text("")
        compiler = DagCompiler(spec=spec, caching="report" if cache else "off")
        dag = compiler.render_dag("sequential")
        (pkg / "dags" / "run_sequential.py").write_text(dag)
        (pkg / "dispatch.py").write_text(compiler.ruffrender("pkg/dispatch.jinja2"))
        (pkg / "response.py").write_text(compiler.ruffrender("pkg/response.jinja2"))
        for mod in [m for m in sys.modules if m.startswith(name)]:
            del sys.modules[mod]
        module = __import__(f"{name}.dags.run_sequential", fromlist=["main"])
        return module.main, dag

    return build


@pytest.fixture
def tasks(workflow, tmp_path):  # `workflow` must run first: it extends sys.path
    import e2e_tasks  # noqa: PLC0415  # only importable once the fixture extends sys.path

    e2e_tasks.reset()
    return e2e_tasks


def run(main, **params):
    return main(params, validate_params_schema=False)


# --- the headline invariant -------------------------------------------------


def test_second_run_executes_nothing_and_returns_the_same_result(workflow, tasks):
    main, _ = workflow(_build_spec())

    first = run(main)
    assert len(tasks.calls()) == 3

    second = run(main)
    assert len(tasks.calls()) == 3  # nothing re-executed
    assert second == first


def test_hit_equals_miss(workflow, tasks):
    """A cached result must be indistinguishable from a recomputed one."""
    main, _ = workflow(_build_spec())
    cold = run(main)

    tasks.reset()
    warm = run(main)
    assert warm == cold
    assert tasks.calls() == []


# --- only what changed re-runs ---------------------------------------------


def test_changing_the_tail_reruns_only_the_tail(workflow, tasks):
    main, _ = workflow(_build_spec())
    run(main)
    tasks.reset()

    # A new label changes `report`'s binding and nothing upstream.
    main2, _ = workflow(_build_spec(label="Different"), name="generated2")
    run(main2)

    assert [c["task"] for c in tasks.calls()] == ["summarise"]


def test_changing_the_middle_reruns_the_middle_and_below(workflow, tasks):
    main, _ = workflow(_build_spec())
    run(main)
    tasks.reset()

    main2, _ = workflow(_build_spec(factor=10), name="generated2")
    run(main2)

    # The source is untouched; everything downstream of the change re-runs.
    assert [c["task"] for c in tasks.calls()] == ["transform", "summarise"]


def test_runtime_params_invalidate_the_step_that_receives_them(workflow, tasks):
    main, _ = workflow(_build_spec(source_payload=None))
    run(main, source={"payload": 1})
    tasks.reset()
    run(main, source={"payload": 2})

    # `summarise` is absent because content promotion cuts off there: the new
    # payload changes `read_source`'s output, but `transform` reads only `rows`
    # and so reproduces exactly what it produced last time.
    assert [c["task"] for c in tasks.calls()] == ["read_source", "transform"]


# --- early cutoff, for any step ---------------------------------------------


def test_a_source_rereading_unchanged_data_cuts_off_recomputation(workflow, tasks, monkeypatch):
    """The source re-runs, but its unchanged output stops there."""
    main, _ = workflow(_build_spec(source_task="read_stable"))
    run(main)
    tasks.reset()

    # The source's own key moves, so it re-executes — but it returns the same
    # data, so nothing below it has anything new to work from.
    monkeypatch.setenv("SOURCE_PAYLOAD", "2")
    main2, _ = workflow(_build_spec(source_task="read_stable"), name="generated2")
    run(main2)

    assert [c["task"] for c in tasks.calls()] == ["read_stable"]


def test_a_mid_dag_pure_step_rerunning_also_cuts_off_recomputation(workflow, tasks):
    """What content promotion buys over the earlier source-only rule."""
    main, _ = workflow(_build_relabel_spec())
    run(main)
    tasks.reset()

    # Only `relabel`'s own literal argument moves, and it ignores that argument.
    main2, _ = workflow(_build_relabel_spec(tag="other"), name="generated2")
    run(main2)

    assert [c["task"] for c in tasks.calls()] == ["relabel"]


# --- keys are independent of what a spec names its steps --------------------


def test_a_workflow_hits_entries_written_by_another_that_named_its_steps_differently(
    workflow, tasks
):
    main, _ = workflow(_build_spec())
    first = run(main)
    tasks.reset()

    renamed, _ = workflow(_build_renamed_spec(), name="renamed")
    assert run(renamed) == first
    assert tasks.calls() == []  # every step served, under different step ids


def test_renaming_steps_adds_no_new_entries_to_the_store(workflow, tasks, tmp_path):
    main, _ = workflow(_build_spec())
    run(main)
    keys = {p.name for p in (tmp_path / "cache" / "keys").rglob("*") if p.is_file()}

    renamed, _ = workflow(_build_renamed_spec(), name="renamed")
    run(renamed)
    assert {p.name for p in (tmp_path / "cache" / "keys").rglob("*") if p.is_file()} == keys


# --- opting out -------------------------------------------------------------


def test_an_opted_out_step_runs_every_time_without_poisoning_its_subtree(workflow, tasks):
    main, _ = workflow(_build_spec(source_task="stamp"))
    run(main)
    tasks.reset()
    run(main)

    # Opting out is a claim about this task, not about everything below it.
    assert [c["task"] for c in tasks.calls()] == ["stamp"]


# --- verify mode ------------------------------------------------------------


def _verify_run(main, **params):
    """Run under `WT_CACHE__VERIFY` and return the mismatch messages."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run(main, **params)
    return [str(w.message) for w in caught if issubclass(w.category, CacheMismatchWarning)]


def test_verify_mode_names_the_task_instance_that_did_not_reproduce(workflow, tasks, monkeypatch):
    # Two runs: one to populate the store, then one to compare against it.
    main, _ = workflow(_build_spec(source_payload=None, source_task="wobble"))
    run(main)

    monkeypatch.setenv("WT_CACHE__VERIFY", "1")
    mismatches = _verify_run(main)

    assert len(mismatches) == 1
    assert "'source'" in mismatches[0]
    # The steps below it have no stored entry under their new key, so there is
    # nothing to compare and nothing to report.
    assert "'shaped'" not in mismatches[0]


def test_verify_mode_reports_nothing_for_a_deterministic_dag(workflow, tasks, monkeypatch):
    main, _ = workflow(_build_spec())
    run(main)
    tasks.reset()

    monkeypatch.setenv("WT_CACHE__VERIFY", "1")
    assert _verify_run(main) == []
    assert len(tasks.calls()) == 3  # executed anyway, which is the point


def test_verify_mode_skips_an_opted_out_step(workflow, tasks, monkeypatch):
    # It has no stored entry, having already been declared untrustworthy.
    main, _ = workflow(_build_spec(source_task="stamp"))
    run(main)

    monkeypatch.setenv("WT_CACHE__VERIFY", "1")
    assert _verify_run(main) == []


# --- inert without a store --------------------------------------------------


def test_everything_runs_every_time_without_a_cache_url(workflow, tasks, monkeypatch):
    monkeypatch.delenv("WT_CACHE__STORE")
    main, _ = workflow(_build_spec())
    run(main)
    run(main)
    assert len(tasks.calls()) == 6


def test_an_uncached_build_is_unaffected_by_the_cache_url(workflow, tasks):
    main, dag = workflow(_build_spec(), cache=False)
    assert ".cached(" not in dag
    run(main)
    run(main)
    assert len(tasks.calls()) == 6


# --- invalidation knobs -----------------------------------------------------


def test_the_epoch_invalidates_everything(workflow, tasks, monkeypatch):
    main, _ = workflow(_build_spec())
    run(main)
    tasks.reset()

    monkeypatch.setenv("WT_CACHE__EPOCH", "changed")
    run(main)
    assert len(tasks.calls()) == 3


def test_a_new_scope_is_a_cold_run(workflow, tasks, monkeypatch):
    # Every key carries the scope, so nothing computed for one principal is
    # served to another: the whole workflow reruns.
    main, _ = workflow(_build_spec())
    run(main)
    cold = [c["task"] for c in tasks.calls()]
    tasks.reset()

    monkeypatch.setenv("WT_CACHE__SCOPE", "another-tenant")
    run(main)
    assert [c["task"] for c in tasks.calls()] == cold


def test_with_no_scope_the_source_always_refetches(workflow, tasks, monkeypatch):
    # Unscoped, tenants sharing a connection name would share the source's key,
    # so it is never served; the steps below still hit on identical content.
    monkeypatch.delenv("WT_CACHE__SCOPE")
    main, _ = workflow(_build_spec())
    run(main)
    tasks.reset()

    run(main)
    assert [c["task"] for c in tasks.calls()] == ["read_source"]


def test_payloads_are_shared_by_content(workflow, tasks, tmp_path):
    """Two keys producing the same value point at one stored payload."""
    main, _ = workflow(_build_spec())
    run(main)
    main2, _ = workflow(_build_spec(label="Other"), name="generated2")
    run(main2)

    cache = tmp_path / "cache"
    keys = [p for p in (cache / "keys").rglob("*") if p.is_file()]
    payloads = [p for p in (cache / "content").rglob("*") if p.is_file()]
    # Four keys (three steps, plus the relabelled report) but the two upstream
    # steps contributed one payload each, not two.
    assert len(keys) == 4
    assert len(payloads) == 4
    assert all(p.parent == cache / "keys" for p in keys)  # flat, not sharded


def content_tree(cache):
    root = cache / "content"
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_payloads_are_filed_under_their_root_codec(workflow, tasks, tmp_path):
    main, _ = workflow(_build_spec())
    run(main)

    tree = content_tree(tmp_path / "cache")
    # `Rows` is a JSON alias and `Summary` a `Cacheable` class: one leaf each.
    assert sorted({p.rpartition("/")[0] for p in tree}) == ["e2e.summary/v1", "json/v1"]
    assert len(tree) == 3


# --- the cache report beside result.json ------------------------------------


def run_like_the_cli(name, results):
    """What the generated CLI does with a run: dispatch, then write both files."""
    dispatch = __import__(f"{name}.dispatch", fromlist=["dispatch"]).dispatch
    response = dispatch("sequential", False, {}, validate_params_schema=False)
    store = LocalStore(results)
    put_cache_report(store, error=response.error)
    store.put("result.json", response.model_dump_json().encode("utf-8"))
    return (
        json.loads((results / "result.json").read_text()),
        json.loads((results / REPORT_NAME).read_text()),
    )


def test_a_completed_run_writes_its_report_beside_result_json(workflow, tasks, tmp_path):
    workflow(_build_spec())
    result, report = run_like_the_cli("generated", tmp_path / "results")

    assert set(result) == {"result", "error", "trace"}  # no `cache` field
    assert result["error"] is None
    assert report["status"] == "completed"
    assert report["summary"] == {"miss": 3}
    assert list(report["steps"]) == ["source", "shaped", "report"]
    assert report["settings"]["store"] == {"configured": True, "scheme": "file"}
    assert str(tmp_path) not in json.dumps(report)


def test_a_failed_run_still_writes_how_far_it_got(workflow, tasks, tmp_path):
    workflow(_build_failing_spec())
    result, report = run_like_the_cli("generated", tmp_path / "results")

    assert "boom" in result["error"]
    assert report["status"] == "failed"
    assert report["failed_step"] == "broken"
    assert "ValueError('boom')" in report["error"]
    assert list(report["steps"]) == ["source"]  # recorded before the failure
    assert report["summary"] == {"miss": 1}


def test_generated_package_imports_cleanly(workflow):
    _, dag = workflow(_build_spec())
    assert "from wt_task.cache import CacheSpec, run_scope" in dag
    compile(dag, "run_sequential.py", "exec")


def test_log_path_is_inside_the_tmp_dir(tasks, tmp_path: Path):
    assert Path(tasks.LOG).parent == tmp_path
