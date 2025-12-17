"""Abstract base class for workflow invokers.

This module defines the AbstractInvoker interface that all workflow invokers
must implement. Invokers are responsible for installing and running workflows
in different execution environments (local subprocess, cloud batch, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from rattler import MatchSpec


@dataclass
class AbstractInvoker(ABC):
    """Abstract base class for all workflow invokers.

    Invokers are responsible for installing and executing workflows specified
    by a rattler MatchSpec. Different implementations provide execution in
    various environments (local subprocess, cloud platforms, etc.).

    Attributes:
        matchspec: Rattler MatchSpec specifying the workflow package to invoke

    Examples:
        Implementing a custom invoker:

        >>> from dataclasses import dataclass
        >>> @dataclass
        ... class MyInvoker(AbstractInvoker):
        ...     async def is_installed(self) -> bool:
        ...         # Check if workflow is available
        ...         return True
        ...     async def install(self) -> None:
        ...         # Install the workflow
        ...         pass
        ...     async def run(
        ...         self,
        ...         workflow_run_id: str,
        ...         config_text: str,
        ...         results_url: str,
        ...         execution_mode: str,
        ...         mock_io: bool,
        ...         **kwargs
        ...     ) -> None:
        ...         # Execute the workflow
        ...         pass
        ...     async def wait(
        ...         self,
        ...         timeout: float | None = None,
        ...         error_msg: str | None = None
        ...     ) -> int:
        ...         return 0
        ...     @property
        ...     def is_waitable(self) -> bool:
        ...         return False
    """

    matchspec: MatchSpec

    @abstractmethod
    async def is_installed(self) -> bool:
        """Check if the workflow is installed and available.

        Returns:
            True if the workflow is installed, False otherwise

        Examples:
            Checking if a workflow is installed:

            >>> import asyncio
            >>> from rattler import MatchSpec
            >>> # invoker = MyInvoker(matchspec=MatchSpec("my-workflow>=1.0.0"))
            >>> # asyncio.run(invoker.is_installed())
            >>> # True
        """
        pass

    @abstractmethod
    async def install(self) -> None:
        """Install the workflow using the given matchspec.

        Raises:
            NotImplementedError: If dynamic installation is not supported
            InstallationError: If installation fails

        Examples:
            Installing a workflow:

            >>> import asyncio
            >>> from rattler import MatchSpec
            >>> # invoker = MyInvoker(matchspec=MatchSpec("my-workflow>=1.0.0"))
            >>> # asyncio.run(invoker.install())
        """
        pass

    @abstractmethod
    async def run(
        self,
        workflow_run_id: str,
        config_text: str,
        results_url: str,
        execution_mode: str,
        mock_io: bool,
        otel_exporter: str | None = None,
        otel_console_exporter_dst: str | None = None,
        extra_env: dict[str, str] | None = None,
        lithops_config_text: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Invoke the workflow with the given arguments.

        Args:
            workflow_run_id: Unique identifier for this workflow run
            config_text: YAML or JSON configuration text for the workflow
            results_url: URL where workflow results should be stored
            execution_mode: Execution mode (e.g., "sequential", "parallel")
            mock_io: Whether to mock I/O operations
            otel_exporter: Optional OpenTelemetry exporter endpoint
            otel_console_exporter_dst: Optional console exporter destination
            extra_env: Optional extra environment variables to pass
            lithops_config_text: Optional Lithops configuration text
            **kwargs: Additional invoker-specific arguments

        Raises:
            RuntimeError: If workflow invocation fails

        Examples:
            Running a workflow:

            >>> import asyncio
            >>> from rattler import MatchSpec
            >>> # invoker = MyInvoker(matchspec=MatchSpec("my-workflow>=1.0.0"))
            >>> # config = "param1: value1\\nparam2: value2"
            >>> # asyncio.run(invoker.run(
            >>> #     workflow_run_id="run-123",
            >>> #     config_text=config,
            >>> #     results_url="s3://bucket/results",
            >>> #     execution_mode="sequential",
            >>> #     mock_io=False
            >>> # ))
        """
        pass

    @abstractmethod
    async def wait(
        self,
        timeout: float | None = None,
        error_msg: str | None = None,
    ) -> int:
        """Wait for the invoker to finish and return the exit code.

        Args:
            timeout: Optional timeout in seconds. If None, wait indefinitely.
            error_msg: Optional error message to use if timeout occurs

        Returns:
            Exit code of the workflow (0 for success, non-zero for failure)

        Raises:
            RuntimeError: If process not started or already finished
            InvocationTimeoutError: If timeout is reached

        Examples:
            Waiting for workflow completion:

            >>> import asyncio
            >>> from rattler import MatchSpec
            >>> # invoker = MyInvoker(matchspec=MatchSpec("my-workflow>=1.0.0"))
            >>> # asyncio.run(invoker.run(...))
            >>> # exit_code = asyncio.run(invoker.wait(timeout=300))
            >>> # exit_code
            >>> # 0
        """
        pass

    @property
    @abstractmethod
    def is_waitable(self) -> bool:
        """Check if the invoker supports waiting for completion.

        Some invokers (e.g., cloud batch jobs) may submit work asynchronously
        and not support waiting for completion within the same process.

        Returns:
            True if wait() can be called, False otherwise

        Examples:
            Checking if invoker is waitable:

            >>> from rattler import MatchSpec
            >>> # invoker = MyInvoker(matchspec=MatchSpec("my-workflow>=1.0.0"))
            >>> # invoker.is_waitable
            >>> # False
        """
        pass
