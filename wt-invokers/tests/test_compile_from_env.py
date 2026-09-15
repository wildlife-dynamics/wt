"""Tests for CompileFromEnvInvoker (compile-from-env, run-in-current-env)."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wt_invokers import CompileFromEnvInvoker

BUILD = (Path("/build/wt-demo-workflow"), "wt_demo_workflow")


def _invoker(**kw) -> CompileFromEnvInvoker:
    return CompileFromEnvInvoker(spec_path="spec.yaml", **kw)


def test_is_waitable() -> None:
    assert _invoker().is_waitable is True


@pytest.mark.asyncio
async def test_is_installed_reflects_build_cache() -> None:
    invoker = _invoker()
    assert await invoker.is_installed() is False
    invoker._release_dir = Path("/build/wt-demo-workflow")
    assert await invoker.is_installed() is True


@pytest.mark.asyncio
async def test_ensure_built_requires_spec_path() -> None:
    invoker = CompileFromEnvInvoker()  # no spec_path
    with pytest.raises(ValueError, match="spec_path"):
        invoker._ensure_built()


@pytest.mark.asyncio
async def test_install_delegates_to_build() -> None:
    invoker = _invoker()
    with patch.object(invoker, "_ensure_built", return_value=BUILD) as built:
        await invoker.install()
    built.assert_called_once()


@pytest.mark.asyncio
async def test_run_builds_correct_command() -> None:
    invoker = _invoker()
    mock_process = MagicMock()
    with (
        patch.object(invoker, "_ensure_built", return_value=BUILD),
        patch.object(subprocess, "Popen", return_value=mock_process) as popen,
    ):
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
    assert cmd[1] == "-m"
    assert cmd[2] == "wt_demo_workflow.cli"
    assert "run" in cmd
    assert "--config-file" in cmd
    assert "--execution-mode" in cmd
    assert "sequential" in cmd
    assert "--no-mock-io" in cmd  # mock_io=False
    assert "--otel-exporter" in cmd
    assert "console" in cmd
    assert "--otel-console-exporter-dst" in cmd


@pytest.mark.asyncio
async def test_run_mock_io_flag() -> None:
    invoker = _invoker()
    with (
        patch.object(invoker, "_ensure_built", return_value=BUILD),
        patch.object(subprocess, "Popen", return_value=MagicMock()) as popen,
    ):
        await invoker.run(
            workflow_run_id="r1",
            config_text="{}",
            results_url="file:///tmp/results",
            execution_mode="sequential",
            mock_io=True,
        )
    cmd = popen.call_args[0][0]
    assert "--mock-io" in cmd
    assert "--no-mock-io" not in cmd


@pytest.mark.asyncio
async def test_run_sets_pythonpath_and_results_env() -> None:
    invoker = _invoker()
    with (
        patch.object(invoker, "_ensure_built", return_value=BUILD),
        patch.object(subprocess, "Popen", return_value=MagicMock()) as popen,
    ):
        await invoker.run(
            workflow_run_id="r1",
            config_text="{}",
            results_url="file:///tmp/results",
            execution_mode="sequential",
            mock_io=False,
            extra_env={"CUSTOM": "1"},
        )
    env = popen.call_args.kwargs["env"]
    assert env["PYTHONPATH"].split(":")[0] == str(BUILD[0])
    assert env["WT_RESULTS"] == "file:///tmp/results"
    assert env["CUSTOM"] == "1"


@pytest.mark.asyncio
async def test_run_respects_custom_results_env_var() -> None:
    invoker = _invoker(results_env_var="MY_RESULTS")
    with (
        patch.object(invoker, "_ensure_built", return_value=BUILD),
        patch.object(subprocess, "Popen", return_value=MagicMock()) as popen,
    ):
        await invoker.run(
            workflow_run_id="r1",
            config_text="{}",
            results_url="file:///tmp/results",
            execution_mode="sequential",
            mock_io=False,
        )
    env = popen.call_args.kwargs["env"]
    assert env["MY_RESULTS"] == "file:///tmp/results"


@pytest.mark.asyncio
async def test_wait_returns_exit_code() -> None:
    invoker = _invoker()
    mock_process = MagicMock()
    mock_process.wait.return_value = 0
    invoker.run_state["process"] = mock_process
    invoker._is_running = True
    assert await invoker.wait() == 0


@pytest.mark.asyncio
async def test_wait_without_process_raises() -> None:
    invoker = _invoker()
    invoker._is_running = True
    with pytest.raises(RuntimeError, match="Process not started"):
        await invoker.wait()
