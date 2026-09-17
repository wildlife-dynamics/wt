"""Tests for CompiledPackageInvoker (run a pre-built compiled package)."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wt_invokers import CompiledPackageInvoker

RELEASE_DIR = Path("/build/wt-demo-workflow")
PACKAGE = "wt_demo_workflow"


def _invoker(**kw) -> CompiledPackageInvoker:
    return CompiledPackageInvoker(release_dir=RELEASE_DIR, package_name=PACKAGE, **kw)


def test_is_waitable() -> None:
    assert _invoker().is_waitable is True


@pytest.mark.asyncio
async def test_is_installed_requires_both_fields() -> None:
    assert await CompiledPackageInvoker().is_installed() is False
    assert await CompiledPackageInvoker(release_dir=RELEASE_DIR).is_installed() is False
    assert await _invoker().is_installed() is True


@pytest.mark.asyncio
async def test_install_is_noop() -> None:
    invoker = _invoker()
    await invoker.install()  # must not raise
    assert await invoker.is_installed() is True


@pytest.mark.asyncio
async def test_run_without_package_raises() -> None:
    invoker = CompiledPackageInvoker()  # no release_dir/package_name
    with pytest.raises(ValueError, match="release_dir and package_name"):
        await invoker.run(
            workflow_run_id="r1",
            config_text="{}",
            results_url="file:///tmp/results",
            execution_mode="sequential",
            mock_io=False,
        )


@pytest.mark.asyncio
async def test_run_builds_correct_command() -> None:
    invoker = _invoker()
    with patch.object(subprocess, "Popen", return_value=MagicMock()) as popen:
        await invoker.run(
            workflow_run_id="r1",
            config_text='{"total": {"a": 1, "b": 2}}',
            results_url="file:///tmp/results",
            execution_mode="sequential",
            mock_io=False,
            otel_exporter="console",
            otel_console_exporter_dst="stdout",
        )
    cmd = popen.call_args[0][0]
    assert cmd[0] == sys.executable
    assert cmd[1:3] == ["-m", "wt_demo_workflow.cli"]
    assert "run" in cmd
    assert "--no-mock-io" in cmd
    assert "--otel-exporter" in cmd
    assert "console" in cmd


@pytest.mark.asyncio
async def test_run_sets_pythonpath_and_results_env() -> None:
    invoker = _invoker()
    with patch.object(subprocess, "Popen", return_value=MagicMock()) as popen:
        await invoker.run(
            workflow_run_id="r1",
            config_text="{}",
            results_url="file:///tmp/results",
            execution_mode="sequential",
            mock_io=True,
            extra_env={"CUSTOM": "1"},
        )
    cmd = popen.call_args[0][0]
    assert "--mock-io" in cmd
    env = popen.call_args.kwargs["env"]
    assert env["PYTHONPATH"].split(":")[0] == str(RELEASE_DIR)
    assert env["WT_RESULTS"] == "file:///tmp/results"
    assert env["CUSTOM"] == "1"


@pytest.mark.asyncio
async def test_run_respects_custom_results_env_var() -> None:
    invoker = _invoker(results_env_var="MY_RESULTS")
    with patch.object(subprocess, "Popen", return_value=MagicMock()) as popen:
        await invoker.run(
            workflow_run_id="r1",
            config_text="{}",
            results_url="file:///tmp/results",
            execution_mode="sequential",
            mock_io=False,
        )
    assert popen.call_args.kwargs["env"]["MY_RESULTS"] == "file:///tmp/results"


@pytest.mark.asyncio
async def test_wait_returns_exit_code() -> None:
    invoker = _invoker()
    proc = MagicMock()
    proc.wait.return_value = 0
    invoker.run_state["process"] = proc
    invoker._is_running = True
    assert await invoker.wait() == 0


@pytest.mark.asyncio
async def test_wait_without_process_raises() -> None:
    invoker = _invoker()
    invoker._is_running = True
    with pytest.raises(RuntimeError, match="Process not started"):
        await invoker.wait()
