"""Shared mechanics for invokers that run a workflow as a local subprocess.

``LocalSubprocessInvoker`` and ``CompiledPackageInvoker`` differ only in the
argv that reaches the workflow CLI and in the environment they add around it;
everything else -- results directory, config temp file, otel flags, process
launch, waiting -- is identical. That common body lives here, parameterised by
:meth:`SubprocessInvokerBase._entrypoint_argv` and
:meth:`SubprocessInvokerBase._run_env_overrides`.

Child output goes to a log file rather than a pipe. ``Popen(stdout=PIPE)``
followed by ``wait()`` deadlocks once the child writes past the pipe buffer
(~64KB), which a chatty workflow does; nothing in this package ever drained
those pipes.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
from abc import abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from .abstract import AbstractInvoker
from .exceptions import InvocationTimeoutError

LOG_TAIL_MAX_BYTES = 8192


@dataclass
class SubprocessInvokerBase(AbstractInvoker):
    """Base for invokers that launch the workflow CLI as a child process.

    Attributes:
        cwd: Optional working directory for the workflow subprocess.
    """

    cwd: str | None = None
    _last_log_path: str | None = field(default=None, init=False, repr=False)
    _last_log_tail: str = field(default="", init=False, repr=False)

    @abstractmethod
    def _entrypoint_argv(self) -> list[str]:
        """Return the argv that invokes the workflow CLI, before its subcommand."""

    def _run_env_overrides(self) -> dict[str, str]:
        """Return extra environment variables for the subprocess (default: none)."""
        return {}

    @property
    def last_log_path(self) -> str | None:
        """Path to the most recent run's log file, if it still exists.

        Survives ``wait()``, which clears ``run_state``.
        """
        return self._last_log_path

    @property
    def last_log_tail(self) -> str:
        """Tail of the most recent finished run's combined stdout/stderr."""
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
            Path(
                url2pathname(parsed_results_url.path)
            ).mkdir(  # local mkdir; fast metadata op
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
            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, suffix=".log"
            ) as log_file:
                self._last_log_path = log_file.name
                self.run_state["log_path"] = log_file.name
                self.run_state["process"] = subprocess.Popen(  # noqa: ASYNC220, S603  # subprocess is intentional; cmd is built from a configured entrypoint
                    cmd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=env,
                    cwd=self.cwd,
                )

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
            returncode = process.wait(timeout=timeout)
        except TimeoutExpired as e:
            # The child is still writing; leave the log in place for inspection.
            raise InvocationTimeoutError(error_msg or str(e)) from e
        self._capture_log_tail()
        return returncode

    def _capture_log_tail(self) -> None:
        """Read the tail of the finished run's log, then remove the log file."""
        path = self._last_log_path
        if path is None:
            return
        log_path = Path(path)
        with contextlib.suppress(OSError), log_path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - LOG_TAIL_MAX_BYTES))
            self._last_log_tail = f.read().decode(errors="replace").strip()
        with contextlib.suppress(OSError):
            log_path.unlink()
        self._last_log_path = None
