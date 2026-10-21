"""Tests for CompiledPackageInvoker (run a pre-built compiled package)."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rattler import MatchSpec

from wt_invokers import CompiledPackageInvoker

RELEASE_DIR = Path("/build/wt-demo-workflow")
# name==version=build -- the build string is the compile's content hash.
BUILD = "wt-demo-workflow==0.2.0=a1b2c3d4e5f60718"


def _invoker(**kw) -> CompiledPackageInvoker:
    kw.setdefault("matchspec", MatchSpec(BUILD))
    kw.setdefault("release_dir", RELEASE_DIR)
    return CompiledPackageInvoker(**kw)


class TestBuildIdentity:
    """The matchspec carries release name, version and content hash."""

    def test_package_name_derived_from_matchspec(self):
        assert _invoker().package_name == "wt_demo_workflow"

    def test_version_and_build_round_trip_through_the_string_form(self):
        ms = MatchSpec(BUILD)
        assert ms.name.normalized == "wt-demo-workflow"
        assert str(ms.version) == "==0.2.0"
        assert ms.build == "a1b2c3d4e5f60718"
        # str() is how a build identity crosses a process boundary.
        assert str(MatchSpec(str(ms))) == str(ms)

    def test_version_less_build_is_addressable(self):
        ms = MatchSpec("wt-demo-workflow=*=a1b2c3d4e5f60718")
        assert ms.build == "a1b2c3d4e5f60718"
        assert CompiledPackageInvoker(matchspec=ms).package_name == "wt_demo_workflow"

    def test_published_matchspec_without_a_build_also_works(self):
        invoker = _invoker(
            matchspec=MatchSpec("ecoscope-workflows-events-workflow==1.2.0")
        )
        assert invoker.package_name == "ecoscope_workflows_events_workflow"


def test_is_waitable() -> None:
    assert _invoker().is_waitable is True


@pytest.mark.asyncio
async def test_is_installed_requires_release_dir() -> None:
    assert (
        await CompiledPackageInvoker(matchspec=MatchSpec(BUILD)).is_installed() is False
    )
    assert await _invoker().is_installed() is True


@pytest.mark.asyncio
async def test_install_is_noop() -> None:
    invoker = _invoker()
    await invoker.install()  # must not raise
    assert await invoker.is_installed() is True


@pytest.mark.asyncio
async def test_run_without_release_dir_raises() -> None:
    invoker = CompiledPackageInvoker(matchspec=MatchSpec(BUILD))
    with pytest.raises(ValueError, match="release_dir"):
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
    assert cmd[cmd.index("--otel-exporter") + 1] == "console"
    assert cmd[cmd.index("--otel-console-exporter-dst") + 1] == "stdout"


@pytest.mark.asyncio
async def test_run_in_named_pixi_env() -> None:
    invoker = _invoker(pixi_env="dynamic")
    with patch.object(subprocess, "Popen", return_value=MagicMock()) as popen:
        await invoker.run(
            workflow_run_id="r1",
            config_text="{}",
            results_url="file:///tmp/results",
            execution_mode="sequential",
            mock_io=True,
        )
    cmd = popen.call_args[0][0]
    assert cmd[:6] == ["pixi", "run", "-e", "dynamic", "python", "-m"]
    assert cmd[6] == "wt_demo_workflow.cli"


@pytest.mark.asyncio
async def test_run_in_named_pixi_env_with_manifest() -> None:
    invoker = _invoker(pixi_env="events", manifest_path=Path("/app/pixi.toml"))
    with patch.object(subprocess, "Popen", return_value=MagicMock()) as popen:
        await invoker.run(
            workflow_run_id="r1",
            config_text="{}",
            results_url="file:///tmp/results",
            execution_mode="sequential",
            mock_io=False,
        )
    cmd = popen.call_args[0][0]
    assert cmd[:6] == [
        "pixi",
        "run",
        "--manifest-path",
        "/app/pixi.toml",
        "-e",
        "events",
    ]


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
