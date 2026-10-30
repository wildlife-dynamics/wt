"""Shared mechanics for invokers that run a workflow as a local subprocess.

``LocalSubprocessInvoker`` and ``CompiledPackageInvoker`` differ only in the
argv that reaches the workflow CLI and in the environment they add around it;
everything else -- results directory, config temp file, otel flags, process
launch, waiting -- is identical. That common body lives here, parameterised by
:meth:`SubprocessInvokerBase._entrypoint_argv` and
:meth:`SubprocessInvokerBase._run_env_overrides`.

Child output is drained continuously and forwarded to this process's stderr,
so it reaches the host's log collector (Cloud Logging on Cloud Run). An
undrained ``PIPE`` deadlocks once the child writes past the ~64KB pipe buffer.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from abc import abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import TimeoutExpired
from typing import IO, Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from .abstract import AbstractInvoker
from .exceptions import InvocationTimeoutError

LOG_TAIL_MAX_BYTES = 8192
# Bounds the post-exit drain: a grandchild that inherited stdout and outlives the
# child would otherwise hold the pipe open and block wait() indefinitely.
DRAIN_JOIN_TIMEOUT_SECONDS = 5.0


def _forward(chunk: bytes) -> None:
    out = getattr(sys.stderr, "buffer", None)
    if out is not None:
        out.write(chunk)
        out.flush()
    else:
        sys.stderr.write(chunk.decode(errors="replace"))
        sys.stderr.flush()


def _signal_group(pgid: int, sig: int) -> bool:
    """Send ``sig`` to a process group; return False if the group is gone."""
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return False
    return True


@dataclass
class SubprocessInvokerBase(AbstractInvoker):
    """Base for invokers that launch the workflow CLI as a child process.

    Attributes:
        cwd: Optional working directory for the workflow subprocess.
        terminate_grace_seconds: How long a timed-out or cancelled child gets
            between SIGTERM and SIGKILL. Must exceed the generated CLI's span
            flush timeout (5s), so a terminated run still exports its spans.

    Environment Variables:
        WT_INVOKERS__SUBPROCESS__TERMINATE_GRACE_SECONDS: Default for
            ``terminate_grace_seconds`` (10).
    """

    cwd: str | None = None
    terminate_grace_seconds: float = field(
        default_factory=lambda: float(
            os.environ.get("WT_INVOKERS__SUBPROCESS__TERMINATE_GRACE_SECONDS", "10")
        )
    )
    _last_log_tail: str = field(default="", init=False, repr=False)

    @abstractmethod
    def _entrypoint_argv(self) -> list[str]:
        """Return the argv that invokes the workflow CLI, before its subcommand."""

    def _run_env_overrides(self) -> dict[str, str]:
        """Return extra environment variables for the subprocess (default: none)."""
        return {}

    @property
    def last_log_tail(self) -> str:
        """Tail of the most recent finished run's combined stdout/stderr.

        Survives ``wait()``, which clears ``run_state``.
        """
        return self._last_log_tail

    async def _run(
        self,
        workflow_run_id: str,  # noqa: ARG002  # interface compatibility
        config_text: str,
        results_url: str,
        execution_mode: str,
        mock_io: bool,
        otel_exporter: str | None = None,
        otel_console_exporter_dst: str | None = None,
        extra_env: dict[str, str] | None = None,
        lithops_config_text: str | None = None,
        **kwargs: Any,  # noqa: ARG002, ANN401  # interface passthrough
    ) -> None:
        """Launch the workflow CLI as a subprocess.

        Args:
            workflow_run_id: Unique identifier for this workflow run (unused here).
            config_text: YAML configuration text for the workflow.
            results_url: URL where workflow results should be stored.
            execution_mode: Execution mode (e.g. ``"sequential"``).
            mock_io: Whether to mock I/O with third-party services.
            otel_exporter: Optional OpenTelemetry exporter backend.
            otel_console_exporter_dst: Optional console exporter destination.
            extra_env: Optional extra environment variables to pass.
            lithops_config_text: Optional Lithops configuration text.
            **kwargs: Additional arguments (ignored).
        """
        parsed_results_url = urlparse(results_url)
        if parsed_results_url.scheme in ("file", ""):
            Path(url2pathname(parsed_results_url.path)).mkdir(  # noqa: ASYNC240  # local mkdir; fast metadata op
                parents=True, exist_ok=True
            )

        run_env = dict(extra_env or {})
        run_env[self.results_env_var] = results_url

        with (
            tempfile.NamedTemporaryFile(
                mode="w", delete=False, suffix=".yaml"
            ) as config_tmpfile,
            tempfile.NamedTemporaryFile(
                mode="w", delete=False, suffix=".yaml"
            ) as lithops_tmpfile,
        ):
            if lithops_config_text:
                lithops_tmpfile.write(lithops_config_text)
                lithops_tmpfile.flush()
                run_env["LITHOPS_CONFIG_FILE"] = lithops_tmpfile.name

            config_tmpfile.write(config_text)
            config_tmpfile.flush()

            cmd = [
                *self._entrypoint_argv(),
                "run",
                "--config-file",
                config_tmpfile.name,
                "--execution-mode",
                execution_mode,
                "--mock-io" if mock_io else "--no-mock-io",
            ]
            if otel_exporter:
                cmd += ["--otel-exporter", otel_exporter]
            if otel_console_exporter_dst:
                cmd += ["--otel-console-exporter-dst", otel_console_exporter_dst]

            env = os.environ.copy() | run_env | self._run_env_overrides()

            self._last_log_tail = ""
            process = subprocess.Popen(  # noqa: ASYNC220, S603  # subprocess is intentional; cmd is built from a configured entrypoint
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                cwd=self.cwd,
                # Own process group, so _stop reaches the workflow behind a
                # `pixi run` wrapper, which doesn't forward SIGKILL.
                start_new_session=True,
            )
            tail = bytearray()
            drain = threading.Thread(
                target=self._drain,
                args=(process.stdout, tail),
                name="wt-invokers-drain",
                daemon=True,
            )
            drain.start()
            self.run_state["process"] = process
            self.run_state["drain"] = drain
            self.run_state["tail"] = tail

    @staticmethod
    def _drain(stream: IO[bytes], tail: bytearray) -> None:
        with stream:
            for chunk in iter(lambda: stream.read1(65536), b""):  # type: ignore[attr-defined]
                # A broken stderr must not stop draining, or the child blocks.
                with contextlib.suppress(OSError, ValueError):
                    _forward(chunk)
                tail.extend(chunk)
                del tail[:-LOG_TAIL_MAX_BYTES]

    @property
    def is_waitable(self) -> bool:
        """Return True: the workflow runs as a waitable local subprocess."""
        return True

    async def _wait(
        self,
        timeout: float | None = None,  # noqa: ASYNC109  # mirrors abstract _wait signature
        error_msg: str | None = None,
    ) -> int:
        """Wait for the workflow subprocess and return its exit code.

        The blocking wait runs on a worker thread, so concurrent runs on one
        event loop don't serialize. A child that times out, or whose waiter is
        cancelled, is terminated and then killed here, before
        ``AbstractInvoker.wait`` clears ``run_state`` and drops the handle.

        Args:
            timeout: Optional timeout in seconds.
            error_msg: Optional error message to use if the timeout is reached.

        Returns:
            Exit code of the workflow subprocess.

        Raises:
            RuntimeError: If the process was not started.
            InvocationTimeoutError: If the timeout is reached.
        """
        process: subprocess.Popen[bytes] | None = self.run_state.get("process")
        if process is None:
            raise RuntimeError("Process not started. Call run() first.")
        try:
            returncode = await asyncio.to_thread(process.wait, timeout=timeout)
        except TimeoutExpired as e:
            await asyncio.to_thread(self._stop, process)
            await self._finish_drain()
            raise InvocationTimeoutError(error_msg or str(e)) from e
        except asyncio.CancelledError:
            await asyncio.to_thread(self._stop, process)
            raise
        await self._finish_drain()
        return returncode

    def _stop(self, process: subprocess.Popen[bytes]) -> None:
        # The child leads its own group (start_new_session), so pgid == pid.
        pgid = process.pid
        if not _signal_group(pgid, signal.SIGTERM):
            return
        deadline = time.monotonic() + self.terminate_grace_seconds
        while time.monotonic() < deadline:
            # Reap the leader: its zombie would keep the group signalable.
            process.poll()
            if not _signal_group(pgid, 0):
                break
            time.sleep(0.05)
        else:
            _signal_group(pgid, signal.SIGKILL)
        process.wait()

    async def _finish_drain(self) -> None:
        drain: threading.Thread | None = self.run_state.get("drain")
        if drain is not None:
            await asyncio.to_thread(drain.join, DRAIN_JOIN_TIMEOUT_SECONDS)
        tail: bytearray = self.run_state.get("tail", bytearray())
        self._last_log_tail = bytes(tail).decode(errors="replace").strip()
