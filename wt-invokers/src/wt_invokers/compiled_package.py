"""Invoker that runs a pre-built compiled workflow package via its CLI.

This is the shared "run a compiled package" mechanic: given a compiled package
directory and its importable package name, it launches
``python -m <package>.cli run`` as a subprocess in the current (shared)
environment, with the package directory on ``PYTHONPATH``. The frozen env is
expected to supply every runtime dependency, so ``pixi`` is never invoked.

It is matchspec-agnostic (the workflow is identified by an on-disk package, not
a match spec). Callers that compile elsewhere (e.g. the wt-compiler-service hot
compile server) construct this directly with a pre-built package.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import TimeoutExpired
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from .abstract import AbstractInvoker
from .exceptions import InvocationTimeoutError

if TYPE_CHECKING:
    from rattler import MatchSpec


@dataclass
class CompiledPackageInvoker(AbstractInvoker):
    r"""Run a pre-built compiled workflow package via its generated CLI.

    The workflow is identified by :attr:`release_dir` (the directory containing
    the compiled package) and :attr:`package_name` (its importable name). The
    invocation is ``python -m <package_name>.cli run`` with ``release_dir`` on
    ``PYTHONPATH``.

    Attributes:
        matchspec: Unused (redeclared with a default so the package-driven
            model does not require one). Present only for interface
            compatibility with :class:`AbstractInvoker`.
        release_dir: Directory containing the compiled package (placed on
            ``PYTHONPATH``).
        package_name: Importable package name (e.g. ``wt_demo_workflow``).
        cwd: Optional working directory for the workflow subprocess.

    Examples:
        Running an already-compiled package:

        >>> import asyncio
        >>> from pathlib import Path
        >>> from wt_invokers.compiled_package import CompiledPackageInvoker
        >>> invoker = CompiledPackageInvoker(
        ...     release_dir=Path("/build/wt-demo-workflow"),
        ...     package_name="wt_demo_workflow",
        ... )
        >>> # asyncio.run(invoker.run(
        >>> #     workflow_run_id="run-123",
        >>> #     config_text='{"total": {"a": 40, "b": 2}}',
        >>> #     results_url="file:///tmp/results",
        >>> #     execution_mode="sequential",
        >>> #     mock_io=False,
        >>> # ))
        >>> # exit_code = asyncio.run(invoker.wait(timeout=300))
    """

    matchspec: MatchSpec | None = None  # type: ignore[assignment]  # package-driven: base requires MatchSpec, this invoker doesn't
    release_dir: Path | None = None
    package_name: str | None = None
    cwd: str | None = field(
        default_factory=lambda: os.environ.get(
            "WT_INVOKERS__COMPILED_PACKAGE_INVOKER__CWD"
        )
    )

    def _resolve_package(self) -> tuple[Path, str]:
        """Return ``(release_dir, package_name)``, raising if either is unset.

        Returns:
            The compiled package's directory and importable name.

        Raises:
            ValueError: If ``release_dir`` or ``package_name`` is not set.
        """
        if self.release_dir is None or self.package_name is None:
            raise ValueError(
                "release_dir and package_name must be set to run a compiled package."
            )
        return Path(self.release_dir), self.package_name

    async def is_installed(self) -> bool:
        """Return whether a compiled package is set on this invoker.

        Returns:
            True if both ``release_dir`` and ``package_name`` are set.
        """
        return self.release_dir is not None and self.package_name is not None

    async def install(self) -> None:
        """No-op: the compiled package is supplied at construction."""

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
        lithops_config_text: str | None = None,  # noqa: ARG002  # not used by this invoker
        **kwargs: Any,  # noqa: ARG002, ANN401  # interface passthrough
    ) -> None:
        """Launch the compiled package's CLI as a subprocess.

        Args:
            workflow_run_id: Unique identifier for this run (unused here).
            config_text: YAML/JSON configuration text for the workflow.
            results_url: URL where workflow results should be stored.
            execution_mode: Execution mode (e.g. ``"sequential"``).
            mock_io: Whether to mock I/O with third-party services.
            otel_exporter: Optional OpenTelemetry exporter backend.
            otel_console_exporter_dst: Optional console exporter destination.
            extra_env: Optional extra environment variables to pass.
            lithops_config_text: Ignored by this invoker.
            **kwargs: Additional arguments (ignored).
        """
        release_dir, package_name = self._resolve_package()

        # Create results directory for file:// URLs.
        parsed = urlparse(results_url)
        if parsed.scheme in ("file", ""):
            Path(url2pathname(parsed.path)).mkdir(  # local mkdir; fast metadata op
                parents=True, exist_ok=True
            )

        run_env = dict(extra_env or {})
        run_env[self.results_env_var] = results_url

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".yaml"
        ) as config_tmpfile:
            config_tmpfile.write(config_text)
            config_tmpfile.flush()

            otel_args: list[str] = []
            if otel_exporter:
                otel_args += ["--otel-exporter", otel_exporter]
            if otel_console_exporter_dst:
                otel_args += ["--otel-console-exporter-dst", otel_console_exporter_dst]

            cmd = [
                sys.executable,
                "-m",
                f"{package_name}.cli",
                "run",
                "--config-file",
                config_tmpfile.name,
                "--execution-mode",
                execution_mode,
                "--mock-io" if mock_io else "--no-mock-io",
                *otel_args,
            ]

            # Put the compiled package on PYTHONPATH; the frozen env supplies
            # every runtime dependency, so no install/solve is needed.
            existing_pythonpath = os.environ.get("PYTHONPATH", "")
            pythonpath = (
                f"{release_dir}{os.pathsep}{existing_pythonpath}"
                if existing_pythonpath
                else str(release_dir)
            )
            env = os.environ.copy() | run_env | {"PYTHONPATH": pythonpath}

            self.run_state["process"] = subprocess.Popen(  # noqa: ASYNC220, S603  # subprocess is intentional; cmd built from configured interpreter + compiled package
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
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
            return process.wait(timeout=timeout)
        except TimeoutExpired as e:
            raise InvocationTimeoutError(error_msg or str(e)) from e
