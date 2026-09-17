"""Tests for the wt-compiler-service FastAPI app (builder + runner mocked)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from wt_compiler.discovery import DiscoveryResult

from wt_compiler_service import app as app_module
from wt_compiler_service.app import app
from wt_compiler_service.builder import Build

FAKE_DISCOVERY = DiscoveryResult(tasks={"add": {"pkg.tasks": MagicMock()}}, records=[])

FAKE_BUILD = Build(
    build_id="abc123",
    release_name="wt-demo-workflow",
    package_name="wt_demo_workflow",
    release_dir=Path("/build/abc123/wt-demo-workflow"),
    dag="from x import y\n",
    params_schema={"properties": {}},
    n_tasks=3,
    results_env_var="WT_RESULTS",
    version="0.1.0",
)

RUN_OUTCOME = {
    "results_url": "file:///tmp/results",
    "result": 42,
    "error": None,
    "trace": None,
    "run_ms": 456.7,
    "returncode": 0,
}


@pytest.fixture
def client():
    """A TestClient whose startup warms the registry from a mocked discovery."""
    with (
        patch.object(app_module, "populate_known_tasks_in_process", return_value=FAKE_DISCOVERY),
        TestClient(app) as test_client,
    ):
        yield test_client


def test_health_reports_hot(client):
    body = client.get("/").json()
    assert body["status"] == "hot"
    assert body["n_tasks_registered"] == 1


# --- /compile ---------------------------------------------------------------


def test_compile_requires_exactly_one_input(client):
    assert client.post("/compile", json={}).status_code == 422
    both = {"spec": {"id": "x"}, "spec_yaml": "id: x"}
    assert client.post("/compile", json=both).status_code == 422


def test_compile_returns_build_id_and_dag(client):
    with patch.object(app_module.builder, "build", return_value=(FAKE_BUILD, False)) as build_fn:
        r = client.post("/compile", json={"spec_yaml": "id: demo"})
    assert r.status_code == 200
    body = r.json()
    assert body["build_id"] == "abc123"
    assert body["version"] == "0.1.0"
    assert body["dag"].startswith("from x import y")
    assert body["n_tasks_in_workflow"] == 3
    assert body["cached"] is False
    build_fn.assert_called_once()


def test_compile_error_becomes_400(client):
    with patch.object(app_module.builder, "build", side_effect=ValueError("bad spec")):
        r = client.post("/compile", json={"spec_yaml": "id: demo"})
    assert r.status_code == 400
    assert "bad spec" in r.json()["detail"]


# --- /run -------------------------------------------------------------------


def test_run_requires_exactly_one_input(client):
    assert client.post("/run", json={"params": {}}).status_code == 422  # none
    both = {"build_id": "x", "spec_yaml": "id: d"}
    assert client.post("/run", json=both).status_code == 422  # two


def test_run_by_spec_hot_compiles(client):
    with (
        patch.object(app_module.builder, "build", return_value=(FAKE_BUILD, False)) as build_fn,
        patch.object(app_module.runner, "run_build", new_callable=AsyncMock) as run_fn,
    ):
        run_fn.return_value = RUN_OUTCOME
        r = client.post(
            "/run",
            json={"spec_yaml": "id: demo", "params": {"total": {"a": 40, "b": 2}}, "mock_io": True},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["build_id"] == "abc123"
    assert body["result"] == 42
    assert body["cached"] is False
    build_fn.assert_called_once()
    # run_build receives the build's package + params + mock_io.
    assert run_fn.call_args.args[1] == "wt_demo_workflow"
    assert run_fn.call_args.args[2] == {"total": {"a": 40, "b": 2}}
    assert run_fn.call_args.kwargs["mock_io"] is True


def test_run_by_build_id_skips_compile(client):
    with (
        patch.object(app_module.builder, "get_build", return_value=FAKE_BUILD) as get_fn,
        patch.object(app_module.runner, "run_build", new_callable=AsyncMock) as run_fn,
    ):
        run_fn.return_value = RUN_OUTCOME
        r = client.post("/run", json={"build_id": "abc123", "params": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["build_id"] == "abc123"
    assert body["cached"] is True
    get_fn.assert_called_once_with("abc123")


def test_run_unknown_build_id_is_404(client):
    with patch.object(app_module.builder, "get_build", return_value=None):
        r = client.post("/run", json={"build_id": "nope"})
    assert r.status_code == 404


def test_run_task_failure_is_200_with_error(client):
    outcome = {**RUN_OUTCOME, "result": None, "error": "boom", "trace": "Traceback ..."}
    with (
        patch.object(app_module.builder, "build", return_value=(FAKE_BUILD, False)),
        patch.object(app_module.runner, "run_build", new_callable=AsyncMock) as run_fn,
    ):
        run_fn.return_value = outcome
        r = client.post("/run", json={"spec_yaml": "id: demo"})
    assert r.status_code == 200
    assert r.json()["error"] == "boom"


def test_run_compile_error_becomes_400(client):
    with patch.object(app_module.builder, "build", side_effect=ValueError("bad spec")):
        r = client.post("/run", json={"spec_yaml": "id: demo"})
    assert r.status_code == 400
    assert "bad spec" in r.json()["detail"]
