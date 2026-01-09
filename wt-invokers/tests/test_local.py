"""Tests for LocalSubprocessInvoker.

This module tests the LocalSubprocessInvoker implementation, including
process management, timeout handling, and environment variable configuration.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from rattler import MatchSpec

from wt_invokers.exceptions import InvocationTimeoutError
from wt_invokers.local import LocalSubprocessInvoker


def test_local_invoker_initialization() -> None:
    """Test LocalSubprocessInvoker initialization."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    assert invoker.matchspec == matchspec
    assert invoker._process is None


def test_local_invoker_with_custom_cwd() -> None:
    """Test LocalSubprocessInvoker with custom working directory."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    cwd = "/custom/path"
    invoker = LocalSubprocessInvoker(matchspec=matchspec, cwd=cwd)

    assert invoker.cwd == cwd


def test_local_invoker_with_env_cwd() -> None:
    """Test LocalSubprocessInvoker with CWD from environment."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    cwd = "/env/path"

    with patch.dict(os.environ, {"WT_INVOKERS__LOCAL_SUBPROCESS_INVOKER__CWD": cwd}):
        invoker = LocalSubprocessInvoker(matchspec=matchspec)
        assert invoker.cwd == cwd


def test_entrypoint_property() -> None:
    """Test entrypoint property returns correct command."""
    matchspec = MatchSpec("my-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    assert invoker.entrypoint == "pixi run -e default my-workflow"


@pytest.mark.asyncio
async def test_is_installed_returns_true() -> None:
    """Test is_installed returns True when workflow is available."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    with patch.object(subprocess, "call", return_value=0):
        result = await invoker.is_installed()
        assert result is True


@pytest.mark.asyncio
async def test_is_installed_returns_false() -> None:
    """Test is_installed returns False when workflow is not available."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    with patch.object(subprocess, "call", return_value=1):
        result = await invoker.is_installed()
        assert result is False


@pytest.mark.asyncio
async def test_install_raises_not_implemented() -> None:
    """Test install raises NotImplementedError."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    with pytest.raises(
        NotImplementedError,
        match="Dynamic installation of workflows is not yet supported",
    ):
        await invoker.install()


@pytest.mark.asyncio
async def test_run_creates_results_directory() -> None:
    """Test run creates results directory for file:// URLs."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    with tempfile.TemporaryDirectory() as tmpdir:
        results_url = f"file://{tmpdir}/results/output"
        mock_process = MagicMock()

        with patch.object(subprocess, "Popen", return_value=mock_process):
            await invoker.run(
                workflow_run_id="test-run",
                config_text="param: value",
                results_url=results_url,
                execution_mode="sequential",
                mock_io=False,
            )

            # Check that results directory was created
            assert Path(tmpdir, "results", "output").exists()


@pytest.mark.asyncio
async def test_run_sets_environment_variables() -> None:
    """Test run sets correct environment variables."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    mock_process = MagicMock()
    results_url = "file:///tmp/results"
    extra_env = {"CUSTOM_VAR": "custom_value"}

    with (
        patch.object(subprocess, "Popen", return_value=mock_process) as mock_popen,
        tempfile.TemporaryDirectory(),
    ):
        await invoker.run(
            workflow_run_id="test-run",
            config_text="param: value",
            results_url=results_url,
            execution_mode="sequential",
            mock_io=False,
            extra_env=extra_env,
        )

        # Check that Popen was called with correct environment
        call_kwargs = mock_popen.call_args[1]
        env = call_kwargs["env"]

        assert "WT_RESULTS" in env
        assert env["WT_RESULTS"] == results_url
        assert env["CUSTOM_VAR"] == "custom_value"


@pytest.mark.asyncio
async def test_run_with_lithops_config() -> None:
    """Test run with lithops configuration."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    mock_process = MagicMock()
    lithops_config = "lithops:\n  backend: aws"

    with (
        patch.object(subprocess, "Popen", return_value=mock_process) as mock_popen,
        tempfile.TemporaryDirectory(),
    ):
        await invoker.run(
            workflow_run_id="test-run",
            config_text="param: value",
            results_url="file:///tmp/results",
            execution_mode="sequential",
            mock_io=False,
            lithops_config_text=lithops_config,
        )

        # Check that environment has lithops config file
        call_kwargs = mock_popen.call_args[1]
        env = call_kwargs["env"]

        assert "LITHOPS_CONFIG_FILE" in env
        assert Path(env["LITHOPS_CONFIG_FILE"]).exists()


@pytest.mark.asyncio
async def test_run_builds_correct_command() -> None:
    """Test run builds correct command line."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    mock_process = MagicMock()

    with (
        patch.object(subprocess, "Popen", return_value=mock_process) as mock_popen,
        tempfile.TemporaryDirectory(),
    ):
        await invoker.run(
            workflow_run_id="test-run",
            config_text="param: value",
            results_url="file:///tmp/results",
            execution_mode="sequential",
            mock_io=True,
            otel_exporter="http://localhost:4318",
        )

        # Check command construction
        cmd = mock_popen.call_args[0][0]

        assert "pixi" in cmd
        assert "run" in cmd
        assert "test-workflow" in cmd
        assert "--config-file" in cmd
        assert "--execution-mode" in cmd
        assert "sequential" in cmd
        assert "--mock-io" in cmd
        assert "--otel-exporter" in cmd
        assert "http://localhost:4318" in cmd


def test_is_waitable_property() -> None:
    """Test is_waitable property returns True."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    assert invoker.is_waitable is True


@pytest.mark.asyncio
async def test_wait_without_run_raises_error() -> None:
    """Test wait raises error if run was not called."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    with pytest.raises(RuntimeError, match="Process not started. Call run\\(\\) first"):
        await invoker.wait()


@pytest.mark.asyncio
async def test_wait_returns_exit_code() -> None:
    """Test wait returns process exit code."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    mock_process = MagicMock()
    mock_process.wait.return_value = 0
    invoker._process = mock_process

    exit_code = await invoker.wait()

    assert exit_code == 0
    mock_process.wait.assert_called_once_with(timeout=None)


@pytest.mark.asyncio
async def test_wait_with_timeout() -> None:
    """Test wait with timeout parameter."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    mock_process = MagicMock()
    mock_process.wait.return_value = 0
    invoker._process = mock_process

    await invoker.wait(timeout=30.0)

    mock_process.wait.assert_called_once_with(timeout=30.0)


@pytest.mark.asyncio
async def test_wait_timeout_raises_invocation_timeout_error() -> None:
    """Test wait raises InvocationTimeoutError on timeout."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    mock_process = MagicMock()
    mock_process.wait.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=10)
    invoker._process = mock_process

    with pytest.raises(InvocationTimeoutError):
        await invoker.wait(timeout=10.0, error_msg="Workflow timed out")


@pytest.mark.asyncio
async def test_check_output_success() -> None:
    """Test check_output returns stdout on success."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    mock_process = Mock()
    mock_process.communicate.return_value = ("success output\n", "")
    mock_process.returncode = 0

    with patch.object(subprocess, "Popen", return_value=mock_process):
        output = await invoker.check_output(["--version"])

        assert output == "success output"


@pytest.mark.asyncio
async def test_check_output_failure() -> None:
    """Test check_output raises error on command failure."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    mock_process = Mock()
    mock_process.communicate.return_value = ("", "error message")
    mock_process.returncode = 1

    with patch.object(subprocess, "Popen", return_value=mock_process):
        with pytest.raises(RuntimeError, match="Command failed with error"):
            await invoker.check_output(["--invalid"])


@pytest.mark.asyncio
async def test_check_output_with_stdin() -> None:
    """Test check_output with stdin input."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = LocalSubprocessInvoker(matchspec=matchspec)

    mock_process = Mock()
    mock_process.communicate.return_value = ("processed input", "")
    mock_process.returncode = 0

    with patch.object(subprocess, "Popen", return_value=mock_process) as mock_popen:
        await invoker.check_output(["process"], stdin="input data")

        # Verify communicate was called with stdin
        mock_process.communicate.assert_called_once_with("input data")
