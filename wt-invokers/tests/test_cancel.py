"""Cancelling a run by a marker beside its results."""

from __future__ import annotations

import asyncio
import sys
import time

from rattler import MatchSpec

from wt_invokers import CompiledPackageInvoker
from wt_invokers.cancel import CANCEL_MARKER, cancel_requested, wait_unless_cancelled

PACKAGE = "wt_sleeper_workflow"


def _invoker(tmp_path, seconds: float) -> CompiledPackageInvoker:
    """A compiled package whose CLI just sleeps, run on this interpreter."""
    pkg = tmp_path / "release" / PACKAGE
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "cli.py").write_text(f"import time\n\ntime.sleep({seconds})\n")
    return CompiledPackageInvoker(
        matchspec=MatchSpec("wt-sleeper-workflow==0.0.0"), release_dir=pkg.parent
    )


async def _start(invoker: CompiledPackageInvoker, results) -> None:
    await invoker.run(
        workflow_run_id="run-1",
        config_text="{}",
        results_url=results.as_uri(),
        execution_mode="sequential",
        mock_io=True,
    )


async def test_a_marker_stops_a_running_run(tmp_path):
    invoker = _invoker(tmp_path, seconds=120)
    results = tmp_path / "results"
    await _start(invoker, results)
    process = invoker.run_state["process"]

    async def cancel_soon():
        await asyncio.sleep(1)
        (results / CANCEL_MARKER).write_text("{}")

    started = time.monotonic()
    returncode, _ = await asyncio.gather(
        wait_unless_cancelled(invoker, results.as_uri(), poll_seconds=0.1),
        cancel_soon(),
    )
    assert returncode is None
    assert time.monotonic() - started < 30  # the sleeper would run 120s
    assert process.poll() is not None


async def test_without_a_marker_the_exit_code_comes_back(tmp_path):
    invoker = _invoker(tmp_path, seconds=0.2)
    results = tmp_path / "results"
    await _start(invoker, results)
    assert await wait_unless_cancelled(invoker, results.as_uri(), poll_seconds=0.1) == 0


async def test_a_marker_is_found_by_url_or_path(tmp_path):
    (tmp_path / CANCEL_MARKER).write_text("{}")
    assert await cancel_requested(tmp_path.as_uri()) is True
    assert await cancel_requested(str(tmp_path)) is True


async def test_a_missing_results_dir_is_not_cancelled(tmp_path):
    assert await cancel_requested((tmp_path / "never-created").as_uri()) is False


async def test_without_obstore_a_remote_run_reads_as_not_cancelled(monkeypatch):
    monkeypatch.setitem(sys.modules, "obstore", None)  # import obstore -> ImportError
    assert await cancel_requested("gs://some-bucket/user/run") is False
