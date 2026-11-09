"""Tests for the ``/run-from-pubsub`` endpoint, which needs ecoscope-eda-core."""

import base64
import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from ecoscope_eda_core.messages.commands import RunWorkflow, RunWorkflowParams
from fastapi.testclient import TestClient

# `wt_runner.app` is shadowed by the FastAPI instance re-exported from the package.
app_module = importlib.import_module("wt_runner.app")


class FakeInvoker:
    """Records calls instead of running a workflow; writes a result like a real run."""

    def __init__(self, *, waitable: bool = True) -> None:
        self.waitable = waitable
        self.run_calls: list[dict[str, Any]] = []
        self.wait_timeouts: list[float | None] = []

    @property
    def is_waitable(self) -> bool:
        return self.waitable

    async def run(self, **kwargs: Any) -> None:
        self.run_calls.append(kwargs)
        results_dir = Path(kwargs["results_url"].removeprefix("file://"))
        (results_dir / "result.json").write_text(
            json.dumps({"result": {}, "error": None})
        )

    async def wait(self, timeout: float | None = None, error_msg: str = "") -> int:  # noqa: ASYNC109  # mirrors AbstractInvoker.wait
        self.wait_timeouts.append(timeout)
        return 0


@pytest.fixture
def invoker(monkeypatch: pytest.MonkeyPatch) -> FakeInvoker:
    fake = FakeInvoker()

    async def resolve_invoker(**_: Any) -> FakeInvoker:
        return fake

    monkeypatch.setattr(app_module, "resolve_invoker", resolve_invoker)
    return fake


@pytest.fixture
def results_dir(tmp_path: Path) -> Path:
    d = tmp_path / "user" / "workflow_run_1"
    d.mkdir(parents=True)
    return d


def push(results_dir: Path, **invoker_kwargs: Any) -> dict[str, Any]:
    command = RunWorkflow(
        payload=RunWorkflowParams(
            match_spec="some-workflow",
            command="run",
            invoker_kwargs={
                "workflow_run_id": "workflow_run_1",
                "results_url": f"file://{results_dir}/",
                **invoker_kwargs,
            },
        )
    )
    data = base64.b64encode(command.model_dump_json().encode()).decode()
    response = TestClient(app_module.app).post(
        "/run-from-pubsub",
        json={"message": {"data": data, "messageId": "m1"}, "subscription": "s"},
    )
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def test_first_delivery_runs_and_claims(
    invoker: FakeInvoker, results_dir: Path
) -> None:
    body = push(results_dir)

    assert body["status"] == "processed"
    assert len(invoker.run_calls) == 1
    assert (results_dir / "lock.json").exists()


def test_redelivery_after_result_is_skipped(
    invoker: FakeInvoker, results_dir: Path
) -> None:
    push(results_dir)
    body = push(results_dir)

    assert body["status"] == "skipped"
    assert len(invoker.run_calls) == 1


def test_redelivery_while_running_is_skipped(
    invoker: FakeInvoker, results_dir: Path
) -> None:
    # A claim without a result is what an attempt still in progress (or one that died) leaves.
    (results_dir / "lock.json").write_text("{}")

    body = push(results_dir)

    assert body["status"] == "skipped"
    assert invoker.run_calls == []


def test_existing_result_without_claim_is_skipped(
    invoker: FakeInvoker, results_dir: Path
) -> None:
    # Results written before this change have no claim.
    (results_dir / "result.json").write_text(json.dumps({"result": {}, "error": None}))

    body = push(results_dir)

    assert body["status"] == "skipped"
    assert invoker.run_calls == []


def test_wait_timeout_is_capped_below_ack_deadline(
    invoker: FakeInvoker, results_dir: Path
) -> None:
    push(results_dir, timeout=900)

    assert invoker.wait_timeouts == [app_module.PUBSUB_ACK_MAX_TIMEOUT]


def test_wait_timeout_below_cap_is_kept(
    invoker: FakeInvoker, results_dir: Path
) -> None:
    push(results_dir, timeout=60)

    assert invoker.wait_timeouts == [60]
