"""Local subprocess invoker implementation.

This module provides a LocalSubprocessInvoker that runs workflows as local
subprocesses using pixi environments.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

from ._subprocess import SubprocessInvokerBase


@dataclass
class LocalSubprocessInvoker(SubprocessInvokerBase):
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
        return " ".join(self._entrypoint_argv())

    def _entrypoint_argv(self) -> list[str]:
        """Return ``pixi run -e default <workflow-name>``.

        Raises:
            ValueError: If the matchspec has no package name.
        """
        name = self.matchspec.name
        if name is None:
            raise ValueError("MatchSpec must have a package name")
        return ["pixi", "run", "-e", "default", name.normalized]

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
        cmd = [*self._entrypoint_argv(), "--help"]
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
            >>> # NotImplementedError
        """
        raise NotImplementedError(
            "Dynamic installation of workflows is not yet supported."
        )

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
            self._entrypoint_argv() + command,
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
