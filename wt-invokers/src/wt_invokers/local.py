"""Local subprocess invoker implementation.

This module provides a LocalSubprocessInvoker that runs workflows as local
subprocesses using pixi environments.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from .abstract import AbstractInvoker
from .exceptions import InvocationTimeoutError


@dataclass
class LocalSubprocessInvoker(AbstractInvoker):
    r"""Invoker that runs workflows in local subprocesses.

    This invoker executes workflows using pixi environments on the local
    machine. It's ideal for development, testing, and small-scale deployments.

    Attributes:
        matchspec: Rattler MatchSpec specifying the workflow package
        cwd: Optional working directory for subprocess execution

    Environment Variables:
        WT_INVOKERS__LOCAL_SUBPROCESS_INVOKER__CWD: Default working directory

    Examples:
        Creating and using a local subprocess invoker:

        >>> import asyncio
        >>> from rattler import MatchSpec
        >>> invoker = LocalSubprocessInvoker(
        ...     matchspec=MatchSpec("my-workflow>=1.0.0"),
        ...     cwd="/path/to/project"
        ... )
        >>> # Check if installed
        >>> # asyncio.run(invoker.is_installed())
        >>> # True

        Running a workflow:

        >>> invoker = LocalSubprocessInvoker(
        ...     matchspec=MatchSpec("my-workflow>=1.0.0")
        ... )
        >>> config = "param1: value1\\nparam2: value2"
        >>> # asyncio.run(invoker.run(
        >>> #     workflow_run_id="run-123",
        >>> #     config_text=config,
        >>> #     results_url="file:///tmp/results",
        >>> #     execution_mode="sequential",
        >>> #     mock_io=False
        >>> # ))
        >>> # exit_code = asyncio.run(invoker.wait(timeout=300))
    """

    cwd: str | None = field(
        default_factory=lambda: os.environ.get(
            "WT_INVOKERS__LOCAL_SUBPROCESS_INVOKER__CWD"
        )
    )

    @property
    def entrypoint(self) -> str:
        """Get the entrypoint command for the workflow.

        Returns:
            Command string to invoke the workflow via pixi

        Examples:
            Getting the entrypoint:

            >>> from rattler import MatchSpec
            >>> invoker = LocalSubprocessInvoker(
            ...     matchspec=MatchSpec("my-workflow>=1.0.0")
            ... )
            >>> invoker.entrypoint
            'pixi run -e default my-workflow'
        """
        name = self.matchspec.name
        if name is None:
            raise ValueError("MatchSpec must have a package name")
        return f"pixi run -e default {name.normalized}"

    async def is_installed(self) -> bool:
        """Check if the workflow is installed.

        Returns:
            True if the workflow is available, False otherwise

        Examples:
            Checking if a workflow is installed:

            >>> import asyncio
            >>> from rattler import MatchSpec
            >>> invoker = LocalSubprocessInvoker(
            ...     matchspec=MatchSpec("my-workflow>=1.0.0")
            ... )
            >>> # asyncio.run(invoker.is_installed())
            >>> # True
        """
        cmd = f"{self.entrypoint} --help".split()
        returncode = subprocess.call(  # noqa: ASYNC221, S603  # blocking is intentional in this helper; cmd is built from a configured entrypoint
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
        )
        return returncode == 0

    async def install(self) -> None:
        """Install the workflow.

        Raises:
            NotImplementedError: Dynamic installation is not yet supported

        Examples:
            Attempting to install:

            >>> import asyncio
            >>> from rattler import MatchSpec
            >>> invoker = LocalSubprocessInvoker(
            ...     matchspec=MatchSpec("my-workflow>=1.0.0")
            ... )
            >>> # asyncio.run(invoker.install())
            >>> # NotImplementedError: Dynamic installation not yet supported.
        """
        raise NotImplementedError(
            "Dynamic installation of workflows is not yet supported."
        )

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
        """Invoke the workflow in a subprocess.

        Args:
            workflow_run_id: Unique identifier for this workflow run
            config_text: YAML configuration text for the workflow
            results_url: URL where workflow results should be stored
            execution_mode: Execution mode (e.g., "sequential", "parallel")
            mock_io: Whether to mock I/O operations
            otel_exporter: Optional OpenTelemetry exporter endpoint
            otel_console_exporter_dst: Optional console exporter destination
            extra_env: Optional extra environment variables to pass
            lithops_config_text: Optional Lithops configuration text
            **kwargs: Additional arguments (ignored by this implementation)

        Examples:
            Running a workflow:

            >>> import asyncio
            >>> from rattler import MatchSpec
            >>> invoker = LocalSubprocessInvoker(
            ...     matchspec=MatchSpec("my-workflow>=1.0.0")
            ... )
            >>> config = '''
            ... param1: value1
            ... param2: 42
            ... '''
            >>> # asyncio.run(invoker.run(
            >>> #     workflow_run_id="run-123",
            >>> #     config_text=config,
            >>> #     results_url="file:///tmp/results",
            >>> #     execution_mode="sequential",
            >>> #     mock_io=False,
            >>> #     extra_env={"DEBUG": "1"}
            >>> # ))
        """
        # Create results directory if using file:// URL
        parse_results_url = urlparse(results_url)
        if parse_results_url.scheme in ("file", ""):
            Path(url2pathname(parse_results_url.path)).mkdir(  # noqa: ASYNC240  # local mkdir; fast metadata op
                parents=True, exist_ok=True
            )

        # Setup environment variables
        if extra_env is None:
            extra_env = {}
        extra_env[self.results_env_var] = results_url

        # Create temporary config files
        with (
            tempfile.NamedTemporaryFile(
                mode="w", delete=False, suffix=".yaml"
            ) as config_tmpfile,
            tempfile.NamedTemporaryFile(
                mode="w", delete=False, suffix=".yaml"
            ) as lithops_tmpfile,
        ):
            # Write lithops config if provided
            if lithops_config_text:
                lithops_tmpfile.write(lithops_config_text)
                lithops_tmpfile.flush()
                extra_env["LITHOPS_CONFIG_FILE"] = lithops_tmpfile.name

            # Write workflow config
            config_tmpfile.write(config_text)
            config_tmpfile.flush()

            # Build command
            otel_exp_arg = f" --otel-exporter {otel_exporter}" if otel_exporter else ""
            otel_dst_arg = (
                f" --otel-console-exporter-dst {otel_console_exporter_dst}"
                if otel_console_exporter_dst
                else ""
            )
            cmd = (
                f"{self.entrypoint} run "
                f"--config-file {config_tmpfile.name} "
                f"--execution-mode {execution_mode} "
                f"{('--mock-io' if mock_io else '--no-mock-io')}"
                f"{otel_exp_arg}{otel_dst_arg}"
            ).split()

            # Merge environment variables
            env = os.environ.copy() | (extra_env or {})

            self.run_state["process"] = subprocess.Popen(  # noqa: ASYNC220, S603  # subprocess is intentional; cmd is built from a configured entrypoint
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=self.cwd,
            )

    @property
    def is_waitable(self) -> bool:
        """Check if the invoker supports waiting for completion.

        Returns:
            True (local subprocesses are always waitable)

        Examples:
            Checking if waitable:

            >>> from rattler import MatchSpec
            >>> invoker = LocalSubprocessInvoker(
            ...     matchspec=MatchSpec("my-workflow>=1.0.0")
            ... )
            >>> invoker.is_waitable
            True
        """
        return True

    async def _wait(
        self,
        timeout: float | None = None,  # noqa: ASYNC109  # mirrors abstract _wait signature
        error_msg: str | None = None,
    ) -> int:
        """Wait for the subprocess to finish and return the exit code.

        Args:
            timeout: Optional timeout in seconds
            error_msg: Optional error message to use if timeout occurs

        Returns:
            Exit code of the workflow (0 for success)

        Raises:
            RuntimeError: If process not started
            InvocationTimeoutError: If timeout is reached

        Examples:
            Waiting for completion:

            >>> import asyncio
            >>> from rattler import MatchSpec
            >>> invoker = LocalSubprocessInvoker(
            ...     matchspec=MatchSpec("my-workflow>=1.0.0")
            ... )
            >>> # asyncio.run(invoker.run(...))
            >>> # exit_code = asyncio.run(invoker.wait(timeout=300))
            >>> # exit_code
            >>> # 0
        """
        process: subprocess.Popen[bytes] | None = self.run_state.get("process")
        if process is None:
            raise RuntimeError("Process not started. Call run() first.")
        try:
            return process.wait(timeout=timeout)
        except TimeoutExpired as e:
            raise InvocationTimeoutError(error_msg or str(e)) from e

    async def check_output(self, command: list[str], stdin: str | None = None) -> str:
        """Get the output of a subprocess command.

        This is a utility method for running one-off commands in the workflow
        environment and capturing their output.

        Args:
            command: List of command arguments to pass to the workflow entrypoint
            stdin: Optional stdin input for the command

        Returns:
            Stripped stdout from the command

        Raises:
            RuntimeError: If the command fails (non-zero exit code)

        Examples:
            Running a command and capturing output:

            >>> import asyncio
            >>> from rattler import MatchSpec
            >>> invoker = LocalSubprocessInvoker(
            ...     matchspec=MatchSpec("my-workflow>=1.0.0")
            ... )
            >>> # output = asyncio.run(invoker.check_output(["--version"]))
            >>> # output
            >>> # '1.2.3'
        """
        p = subprocess.Popen(  # noqa: ASYNC220, S603  # subprocess is intentional; cmd is built from a configured entrypoint
            self.entrypoint.split() + command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            cwd=self.cwd,
        )
        out, err = p.communicate(stdin)
        if p.returncode != 0:
            raise RuntimeError(f"Command failed with error: {err}")
        return out.strip()
