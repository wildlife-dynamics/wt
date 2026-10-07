"""End-to-end: execute a generated DAG twice and check what actually re-runs.

These build a real importable package from the compiler's own output and run it
through the real `wt-task` runtime, because the thing worth proving is that the
emitted code and the runtime agree — not that each half works in isolation.
"""

import sys
from pathlib import Path

import pytest

# Private, but the fixture has to invalidate what the runtime memoizes per process.
from wt_task.cache._key import _packages_distributions, distribution_version

from wt_compiler import spec as wt_spec
from wt_compiler.compiler import DagCompiler

TASKS_MODULE = '''
"""Task library for the end-to-end cache tests.

Plain functions: the generated DAG imports each by name and wraps it with
`task(...)`, so `@register` plays no part at run time.
"""
import json
from pathlib import Path

LOG = Path(__file__).parent / "calls.jsonl"


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


def read_source(payload: int) -> dict:
    _log("read_source", payload)
    return {"rows": [1, 2, 3], "payload": payload}


def read_stable(payload: int) -> dict:
    """Re-reads on every key change but always returns the same data."""
    _log("read_stable", payload)
    return {"rows": [1, 2, 3]}


def transform(data: dict, factor: int) -> dict:
    _log("transform", factor)
    return {"rows": [r * factor for r in data["rows"]]}


def summarise(data: dict, label: str) -> dict:
    _log("summarise", label)
    return {"label": label, "total": sum(data["rows"])}
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
    for name, tags in (
        ("read_source", [wt_spec.TaskTag.io]),
        ("read_stable", [wt_spec.TaskTag.io]),
        ("transform", []),
        ("summarise", []),
    ):
        wt_spec.known_tasks[name] = {
            "e2e_tasks": wt_spec.KnownTask(
                importable_reference=f"e2e_tasks.{name}",
                tags=tags,
                json_schema={"properties": {}},
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


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    """Build, install and return a runnable generated workflow package."""
    monkeypatch.setenv("WT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("SOURCE_PAYLOAD", "1")
    monkeypatch.delenv("WT_CACHE_EPOCH", raising=False)
    monkeypatch.delenv("WT_CACHE_SCOPE", raising=False)
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
    distribution_version.cache_clear()

    # Each test gets its own tmp_path, so a module cached from a previous test
    # would log into the wrong directory and every assertion would read zero calls.
    sys.modules.pop("e2e_tasks", None)

    def build(spec, cache=True, name="generated"):
        pkg = tmp_path / name
        (pkg / "dags").mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "metadata.py").write_text(METADATA_MODULE)
        (pkg / "dags" / "__init__.py").write_text("")
        dag = DagCompiler(spec=spec, cache=cache).render_dag("sequential")
        (pkg / "dags" / "run_sequential.py").write_text(dag)
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

    assert [c["task"] for c in tasks.calls()] == ["read_source", "transform", "summarise"]


# --- source behaviour -------------------------------------------------------


def test_source_rereading_unchanged_data_cuts_off_recomputation(workflow, tasks, monkeypatch):
    """Early cutoff: the source re-runs, but its unchanged output stops there."""
    main, _ = workflow(_build_spec(source_task="read_stable"))
    run(main)
    tasks.reset()

    # The source's own key moves, so it re-executes — but it returns the same
    # data, so nothing below it has anything new to work from.
    monkeypatch.setenv("SOURCE_PAYLOAD", "2")
    main2, _ = workflow(_build_spec(source_task="read_stable"), name="generated2")
    run(main2)

    assert [c["task"] for c in tasks.calls()] == ["read_stable"]


# --- inert without a store --------------------------------------------------


def test_everything_runs_every_time_without_a_cache_url(workflow, tasks, monkeypatch):
    monkeypatch.delenv("WT_CACHE")
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


@pytest.mark.parametrize("var", ["WT_CACHE_EPOCH", "WT_CACHE_SCOPE"])
def test_epoch_and_scope_invalidate_everything(workflow, tasks, monkeypatch, var):
    main, _ = workflow(_build_spec())
    run(main)
    tasks.reset()

    monkeypatch.setenv(var, "changed")
    run(main)
    assert len(tasks.calls()) == 3


def test_payloads_are_shared_by_content(workflow, tasks, tmp_path):
    """Two keys producing the same value point at one stored payload."""
    main, _ = workflow(_build_spec())
    run(main)
    main2, _ = workflow(_build_spec(label="Other"), name="generated2")
    run(main2)

    cache = tmp_path / "cache"
    keys = list((cache / "keys").rglob("*"))
    payloads = [p for p in (cache / "cas").rglob("*") if p.is_file()]
    # Four keys (three steps, plus the relabelled report) but the two upstream
    # steps contributed one payload each, not two.
    assert len(keys) == 4
    assert len(payloads) == 4


def test_generated_package_imports_cleanly(workflow):
    _, dag = workflow(_build_spec())
    assert "from wt_task.cache import CacheSpec, run_scope" in dag
    compile(dag, "run_sequential.py", "exec")


def test_log_path_is_inside_the_tmp_dir(tasks, tmp_path: Path):
    assert Path(tasks.LOG).parent == tmp_path
