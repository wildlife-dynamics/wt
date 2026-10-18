"""Tests for the shared subprocess invoker mechanics."""

import asyncio
import sys
from pathlib import Path

import pytest
from rattler import MatchSpec

from wt_invokers import CompiledPackageInvoker, LocalSubprocessInvoker

BUILD = "wt-demo-workflow==0.2.0=a1b2c3d4e5f60718"


class _EchoInvoker(CompiledPackageInvoker):
    """Runs a real child process that we control, instead of a workflow CLI."""

    script: str = ""

    def _entrypoint_argv(self) -> list[str]:
        return [sys.executable, "-c", self.script, "--"]

    def _run_env_overrides(self) -> dict[str, str]:
        return {}


def _echo_invoker(script: str, tmp_path: Path) -> _EchoInvoker:
    inv = _EchoInvoker(matchspec=MatchSpec(BUILD), release_dir=tmp_path)
    inv.script = script
    return inv


@pytest.mark.asyncio
async def test_large_child_output_does_not_deadlock(tmp_path: Path) -> None:
    """A chatty workflow must not hang the invoker.

    With stdout on a pipe nobody drains, a child writing past the ~64KB pipe
    buffer blocks forever and wait() never returns.
    """
    script = (
        "import sys; sys.stdout.write('x' * 2_000_000); sys.stderr.write('y' * 500_000)"
    )
    invoker = _echo_invoker(script, tmp_path)

    await invoker.run(
        workflow_run_id="r1",
        config_text="{}",
        results_url=(tmp_path / "results").as_uri(),
        execution_mode="sequential",
        mock_io=True,
    )
    returncode = await asyncio.wait_for(invoker.wait(timeout=30), timeout=60)

    assert returncode == 0


@pytest.mark.asyncio
async def test_log_tail_survives_wait(tmp_path: Path) -> None:
    """The failure tail is readable after wait(), which clears run_state."""
    script = "import sys; print('boom: could not import obstore'); sys.exit(3)"
    invoker = _echo_invoker(script, tmp_path)

    await invoker.run(
        workflow_run_id="r1",
        config_text="{}",
        results_url=(tmp_path / "results").as_uri(),
        execution_mode="sequential",
        mock_io=True,
    )
    log_path = invoker.last_log_path
    assert log_path is not None
    returncode = await invoker.wait(timeout=30)

    assert returncode == 3
    assert invoker.run_state == {}  # cleared by the lifecycle...
    assert (
        "could not import obstore" in invoker.last_log_tail
    )  # ...but the tail survives
    assert not Path(log_path).exists()  # noqa: ASYNC240  # local stat in a test; not a blocking concern


@pytest.mark.asyncio
async def test_results_dir_is_created_for_file_urls(tmp_path: Path) -> None:
    results = tmp_path / "nested" / "results"
    invoker = _echo_invoker("pass", tmp_path)

    await invoker.run(
        workflow_run_id="r1",
        config_text="{}",
        results_url=results.as_uri(),
        execution_mode="sequential",
        mock_io=True,
    )
    await invoker.wait(timeout=30)

    assert results.is_dir()


class TestLocalSubprocessPixiEnv:
    """pixi_env is what makes N pre-solved environments addressable."""

    def test_defaults_to_the_default_environment(self):
        invoker = LocalSubprocessInvoker(matchspec=MatchSpec("my-workflow>=1.0.0"))
        assert invoker.entrypoint == "pixi run -e default my-workflow"

    def test_named_environment(self):
        invoker = LocalSubprocessInvoker(
            matchspec=MatchSpec("ecoscope-workflows-events-workflow==1.2.0"),
            pixi_env="events",
        )
        assert invoker._entrypoint_argv() == [
            "pixi",
            "run",
            "-e",
            "events",
            "ecoscope-workflows-events-workflow",
        ]

    def test_manifest_path_is_threaded_through(self):
        invoker = LocalSubprocessInvoker(
            matchspec=MatchSpec("my-workflow>=1.0.0"),
            pixi_env="patrols",
            manifest_path=Path("/app/pixi.toml"),
        )
        assert invoker.entrypoint == (
            "pixi run --manifest-path /app/pixi.toml -e patrols my-workflow"
        )

    def test_env_var_supplies_the_default(self, monkeypatch):
        monkeypatch.setenv(
            "WT_INVOKERS__LOCAL_SUBPROCESS_INVOKER__PIXI_ENV", "subject-tracking"
        )
        invoker = LocalSubprocessInvoker(matchspec=MatchSpec("my-workflow>=1.0.0"))
        assert invoker.pixi_env == "subject-tracking"
