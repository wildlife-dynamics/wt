"""Abstract base class for workflow invokers.

This module defines the AbstractInvoker interface that all workflow invokers
must implement. Invokers are responsible for installing and running workflows
in different execution environments (local subprocess, cloud batch, etc.).

The base class defines a strict ``IDLE -> RUNNING -> IDLE`` lifecycle via the
concrete :meth:`AbstractInvoker.run` and :meth:`AbstractInvoker.wait` methods.
Subclasses implement ``_run``/``_wait`` (and optionally ``_pre_run``/
``_post_run``) rather than overriding ``run``/``wait`` directly. This allows
mixins to compose pre-run and post-run behavior (e.g. environment unpacking,
results archiving) without each invoker having to reimplement the hook plumbing.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from rattler import MatchSpec


@dataclass
class AbstractInvoker(ABC):
    """Abstract base class for all workflow invokers.

    Invokers are responsible for installing and executing workflows specified
    by a rattler MatchSpec. Different implementations provide execution in
    various environments (local subprocess, cloud platforms, etc.).

    The public :meth:`run` and :meth:`wait` methods are concrete wrappers that
    enforce an ``IDLE -> RUNNING -> IDLE`` lifecycle and delegate to the
    abstract ``_run`` / ``_wait`` implementations. Subclasses may override
    ``_pre_run`` and ``_post_run`` (both default to no-ops) for setup and
    cleanup work. Mixins can also override these hooks to contribute
    composable behavior (see :mod:`wt_invokers.mixins`).

    Attributes:
        matchspec: Rattler MatchSpec specifying the workflow package to invoke
        results_env_var: Name of the environment variable used by the workflow
            process to discover its results URL (default ``WT_RESULTS``).

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
        ...     async def _run(
        ...         self,
        ...         workflow_run_id: str,
        ...         config_text: str,
        ...         results_url: str,
        ...         execution_mode: str,
        ...         mock_io: bool,
        ...         **kwargs,
        ...     ) -> None:
        ...         # Execute the workflow
        ...         pass
        ...     async def _wait(
        ...         self,
        ...         timeout: float | None = None,
        ...         error_msg: str | None = None,
        ...     ) -> int:
        ...         return 0
        ...     @property
        ...     def is_waitable(self) -> bool:
        ...         return False
    """

    matchspec: MatchSpec
    results_env_var: str = field(
        default_factory=lambda: os.environ.get(
            "WT_INVOKERS__RESULTS_ENV_VAR", "WT_RESULTS"
        )
    )
    _run_args: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _run_state: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _is_running: bool = field(default=False, init=False, repr=False)

    @property
    def is_running(self) -> bool:
        """Whether the invoker is currently between ``run()`` and ``wait()``."""
        return self._is_running

    @property
    def run_args(self) -> MappingProxyType[str, Any]:
        """Immutable view of the arguments passed to the current ``run()`` call.

        Populated by :meth:`run` and cleared by :meth:`wait`. Hooks
        (``_pre_run``, ``_post_run``) read per-invocation values from here.
        Empty when the invoker is IDLE.
        """
        return MappingProxyType(self._run_args)

    @property
    def run_state(self) -> dict[str, Any]:
        """Mutable dict for per-run derived state shared between hooks.

        Populated by hooks (``_pre_run``, ``_run``) and read by later hooks
        (``_wait``, ``_post_run``). Cleared by :meth:`wait` so the invoker
        returns to a clean IDLE state after each run.
        """
        return self._run_state

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
        """Invoke the workflow, running ``_pre_run`` and then ``_run``.

        Populates :attr:`run_args` with all arguments (including ``kwargs``)
        before invoking the hooks so subclasses and mixins can read
        per-invocation values. Raises :class:`RuntimeError` if called while
        the invoker is already running.

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
            **kwargs: Additional invoker-specific arguments; these are stored
                in ``run_args`` so hooks and mixins can read them.

        Raises:
            RuntimeError: If called while already running.
        """
        if self._is_running:
            raise RuntimeError(
                "run() called while already running -- "
                "wait() must complete before calling run() again"
            )
        self._is_running = True
        self._run_args = {
            "workflow_run_id": workflow_run_id,
            "config_text": config_text,
            "results_url": results_url,
            "execution_mode": execution_mode,
            "mock_io": mock_io,
            "otel_exporter": otel_exporter,
            "otel_console_exporter_dst": otel_console_exporter_dst,
            "extra_env": extra_env,
            "lithops_config_text": lithops_config_text,
            **kwargs,
        }
        try:
            await self._pre_run()
            await self._run(
                workflow_run_id=workflow_run_id,
                config_text=config_text,
                results_url=results_url,
                execution_mode=execution_mode,
                mock_io=mock_io,
                otel_exporter=otel_exporter,
                otel_console_exporter_dst=otel_console_exporter_dst,
                extra_env=extra_env,
                lithops_config_text=lithops_config_text,
                **kwargs,
            )
        except BaseException:
            self._run_args.clear()
            self._run_state.clear()
            self._is_running = False
            raise

        # Non-waitable invokers have no ``wait()`` phase to reset state in, so
        # ``run()`` itself is the whole lifecycle — clear state here so the
        # invoker can be re-run without calling ``wait()`` in between.
        if not self.is_waitable:
            self._run_args.clear()
            self._run_state.clear()
            self._is_running = False

    async def wait(
        self,
        timeout: float | None = None,
        error_msg: str | None = None,
    ) -> int:
        """Wait for the workflow to finish, run ``_post_run``, and return the exit code.

        Outcomes by lifecycle state:

        * Called from IDLE on a **waitable** invoker (never ran, or already
          reset): raises :class:`RuntimeError` immediately. ``_post_run``
          is not invoked. This mirrors the symmetric guard in :meth:`run`.
        * Called on a **non-waitable** invoker: the guard is skipped,
          ``_wait`` is invoked (which by convention returns ``0``), and
          ``_post_run`` runs as usual. Non-waitable invokers clear state
          inside :meth:`run`, so a post-run ``wait()`` is a no-op tail by
          design; rejecting it would break the symmetric API.
        * Workflow succeeds, ``_post_run`` succeeds: returns the workflow
          exit code.
        * Workflow finishes with non-zero exit code, ``_post_run`` succeeds:
          returns that exit code for the caller to inspect.
        * ``_wait`` raises, ``_post_run`` succeeds: ``_wait``'s exception
          propagates; ``_post_run`` still runs; state is reset.
        * Workflow (or ``_wait``) succeeds but ``_post_run`` raises:
          ``_post_run``'s exception propagates and the workflow exit code is
          lost **by design**. Post-run hooks do real work (e.g. results
          upload) whose failure is not secondary to the workflow's exit code.
          Mixins that want their own failures not to affect the return value
          should catch and log them internally.
        * Both ``_wait`` and ``_post_run`` raise: ``_post_run``'s exception
          propagates with ``_wait``'s preserved on ``__context__`` (visible
          in the default traceback as "During handling of the above
          exception, another exception occurred").

        State (:attr:`run_args`, :attr:`run_state`, :attr:`is_running`) is
        always cleared on exit, regardless of which branch the call took.

        Args:
            timeout: Optional timeout in seconds. If None, wait indefinitely.
            error_msg: Optional error message to use if timeout occurs

        Returns:
            Exit code of the workflow (0 for success, non-zero for failure)

        Raises:
            RuntimeError: If called while not running, or if the subclass
                ``_wait`` reports the process was not started
            InvocationTimeoutError: If timeout is reached
        """
        if self.is_waitable and not self._is_running:
            raise RuntimeError(
                "wait() called while not running -- run() must complete first"
            )
        try:
            exit_code = await self._wait(timeout=timeout, error_msg=error_msg)
        finally:
            try:
                await self._post_run()
            finally:
                self._run_args.clear()
                self._run_state.clear()
                self._is_running = False
        return exit_code

    async def _pre_run(self) -> None:  # noqa: B027
        """Pre-run hook. Default is a no-op; mixins may override."""
        pass

    @abstractmethod
    async def _run(
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
        """Concrete per-invoker implementation of the workflow invocation.

        Called by :meth:`run` after :meth:`_pre_run`. Implementations should
        not override :meth:`run` itself; the base ``run`` wrapper manages
        lifecycle state.
        """
        pass

    async def _post_run(self) -> None:  # noqa: B027
        """Post-run hook. Default is a no-op; mixins may override."""
        pass

    @abstractmethod
    async def _wait(
        self,
        timeout: float | None = None,
        error_msg: str | None = None,
    ) -> int:
        """Concrete per-invoker implementation of waiting for completion.

        Called by :meth:`wait`; must return the workflow exit code.
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

    async def check_output(self, command: list[str], stdin: str | None = None) -> str:
        """Get the output of a subprocess command.

        This is a utility method for running one-off commands in the workflow
        environment and capturing their output. Not all invokers support this.

        Args:
            command: List of command arguments to pass to the workflow entrypoint
            stdin: Optional stdin input for the command

        Returns:
            Stripped stdout from the command

        Raises:
            NotImplementedError: If the invoker does not support this operation
            RuntimeError: If the command fails (non-zero exit code)

        Examples:
            Running a command and capturing output:

            >>> import asyncio
            >>> from rattler import MatchSpec
            >>> # invoker = MyInvoker(matchspec=MatchSpec("my-workflow>=1.0.0"))
            >>> # output = asyncio.run(invoker.check_output(["--version"]))
            >>> # output
            >>> # '1.2.3'
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support check_output"
        )
