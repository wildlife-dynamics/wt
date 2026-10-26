"""Tests for the shared subprocess invoker mechanics."""

import asyncio
import contextlib
import os
import signal
import sys
from pathlib import Path

import pytest
from rattler import MatchSpec

from wt_invokers import CompiledPackageInvoker, LocalSubprocessInvoker, _subprocess
from wt_invokers.exceptions import InvocationTimeoutError

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
    returncode = await invoker.wait(timeout=30)

    assert returncode == 3
    assert invoker.run_state == {}  # cleared by the lifecycle...
    assert (
        "could not import obstore" in invoker.last_log_tail
    )  # ...but the tail survives


async def _start(invoker: _EchoInvoker, tmp_path: Path) -> None:
    await invoker.run(
        workflow_run_id="r1",
        config_text="{}",
        results_url=(tmp_path / "results").as_uri(),
        execution_mode="sequential",
        mock_io=True,
    )


@pytest.mark.asyncio
async def test_child_output_is_forwarded_to_stderr(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    invoker = _echo_invoker("print('hello from the workflow')", tmp_path)
    await _start(invoker, tmp_path)
    await invoker.wait(timeout=30)

    assert "hello from the workflow" in capfd.readouterr().err


@pytest.mark.asyncio
async def test_timeout_terminates_the_child(tmp_path: Path) -> None:
    """A timed-out run must not be left running (it once ran for 10h51m)."""
    script = "import time; print('started', flush=True); time.sleep(60)"
    invoker = _echo_invoker(script, tmp_path)
    await _start(invoker, tmp_path)
    process = invoker.run_state["process"]

    with pytest.raises(InvocationTimeoutError):
        await invoker.wait(timeout=1)

    assert process.poll() is not None
    assert process.returncode == -signal.SIGTERM
    assert "started" in invoker.last_log_tail


@pytest.mark.asyncio
async def test_child_ignoring_sigterm_is_killed_after_grace(tmp_path: Path) -> None:
    script = (
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('ready', flush=True); time.sleep(60)"
    )
    invoker = _echo_invoker(script, tmp_path)
    invoker.terminate_grace_seconds = 0.5
    await _start(invoker, tmp_path)
    process = invoker.run_state["process"]
    # Let the child install its handler before the timeout fires.
    await asyncio.sleep(0.5)

    with pytest.raises(InvocationTimeoutError):
        await invoker.wait(timeout=0.5)

    assert process.returncode == -signal.SIGKILL


def _alive(pid: int) -> bool:
    """True if ``pid`` exists and isn't a zombie awaiting reaping."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


async def _wait_until_dead(pid: int, within: float = 5.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + within
    while loop.time() < deadline:
        if not _alive(pid):
            return True
        await asyncio.sleep(0.05)
    return False


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
@pytest.mark.asyncio
async def test_timeout_kills_the_workflow_behind_a_wrapper(tmp_path: Path) -> None:
    """The child may be a `pixi run` wrapper; its workflow must not be orphaned.

    The grandchild ignores SIGTERM (e.g. stuck in a C call), so only a
    group-wide SIGKILL stops it.
    """
    pid_file = tmp_path / "grandchild.pid"
    grandchild = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    script = (
        "import subprocess, sys, time; "
        f"p = subprocess.Popen([sys.executable, '-c', {grandchild!r}]); "
        f"open({str(pid_file)!r}, 'w').write(str(p.pid)); "
        "print('ready', flush=True); p.wait()"
    )
    invoker = _echo_invoker(script, tmp_path)
    invoker.terminate_grace_seconds = 0.5
    await _start(invoker, tmp_path)
    process = invoker.run_state["process"]
    try:
        await asyncio.sleep(1)
        grandchild_pid = int(pid_file.read_text())

        with pytest.raises(InvocationTimeoutError):
            await asyncio.wait_for(invoker.wait(timeout=0.5), timeout=15)

        assert await _wait_until_dead(grandchild_pid)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)


@pytest.mark.asyncio
async def test_grandchild_holding_stdout_does_not_hang_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A background worker that inherits stdout and outlives the child must not block wait()."""
    monkeypatch.setattr(_subprocess, "DRAIN_JOIN_TIMEOUT_SECONDS", 0.5)
    script = (
        "import subprocess, sys; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "print('done', flush=True)"
    )
    invoker = _echo_invoker(script, tmp_path)
    await _start(invoker, tmp_path)
    process = invoker.run_state["process"]
    try:
        returncode = await asyncio.wait_for(invoker.wait(timeout=30), timeout=10)

        assert returncode == 0
        assert "done" in invoker.last_log_tail
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)


@pytest.mark.asyncio
async def test_cancelling_the_waiter_stops_the_child(tmp_path: Path) -> None:
    invoker = _echo_invoker("import time; time.sleep(60)", tmp_path)
    await _start(invoker, tmp_path)
    process = invoker.run_state["process"]

    waiter = asyncio.create_task(invoker.wait(timeout=60))
    await asyncio.sleep(0.5)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    assert process.poll() is not None


@pytest.mark.asyncio
async def test_concurrent_waits_do_not_serialize(tmp_path: Path) -> None:
    """Waiting must not block the event loop, or one run stalls every other."""
    invokers = [_echo_invoker("import time; time.sleep(1)", tmp_path) for _ in range(3)]
    for invoker in invokers:
        await _start(invoker, tmp_path)

    loop = asyncio.get_running_loop()
    started = loop.time()
    await asyncio.gather(*(invoker.wait(timeout=30) for invoker in invokers))

    assert loop.time() - started < 2.5


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


def test_terminate_grace_env_var_supplies_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WT_INVOKERS__SUBPROCESS__TERMINATE_GRACE_SECONDS", "30")
    assert _echo_invoker("pass", tmp_path).terminate_grace_seconds == 30.0
