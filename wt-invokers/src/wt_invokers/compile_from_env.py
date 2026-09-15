"""On-the-fly compile-and-run invoker for baked-in environments.

This module provides :class:`CompileFromEnvInvoker`, an invoker that compiles
a workflow spec *on the fly* against the current (baked-in) environment and
runs the resulting package as a local subprocess -- with no dependency solve
and no separate workflow-package install.

It is the counterpart to ``wt-compiler``'s ``--from-env`` compile path: an
invoker image that bakes in ``ecoscope.platform`` + the ``wt`` stack + the task
libraries can turn a spec into a running DAG in ~1s, because the tasks are
already importable and the DAG is rendered rather than solved.

Unlike :class:`~wt_invokers.local.LocalSubprocessInvoker`, this invoker is
driven by a *spec* (the workflow definition) rather than a ``matchspec``
naming a pre-built package. The compiled package is executed in the current
interpreter's environment via ``PYTHONPATH`` -- the frozen env already provides
every runtime dependency, so ``pixi`` is never invoked at run time.
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
class CompileFromEnvInvoker(AbstractInvoker):
    r"""Compile a spec against the current environment and run it locally.

    The workflow to run is given by :attr:`spec_path` (a ``spec.yaml``). On the
    first run (or via :meth:`install`), the spec is compiled with
    ``wt-compiler``'s ``compile_workflow_from_env`` -- which discovers tasks by
    running the installed ``wt-registry`` in the current environment, with no
    dependency solve -- and the artifacts are written to a build directory. The
    compiled package is then executed in the current interpreter via
    ``python -m <package>.cli run`` with the build directory on ``PYTHONPATH``.

    This is intended for a "trusted invoker" image that bakes in the ``wt``
    stack and task libraries, so on-the-fly (re)compilation is cheap and no
    per-workflow install or solve is required.

    Attributes:
        spec_path: Path to the ``spec.yaml`` to compile and run. Required.
        matchspec: Unused by this invoker (redeclared with a default so the
            spec-driven model does not require one). Present only for
            interface compatibility with :class:`AbstractInvoker`.
        discover_packages: Optional dotted module paths forwarded to
            ``wt-registry --package`` during compilation, in addition to
            entry-point auto-discovery.
        build_dir: Optional directory to compile into. Defaults to a fresh
            temporary directory created on first build.
        cwd: Optional working directory for the workflow subprocess.

    Examples:
        Compiling and running a spec in a baked-in environment:

        >>> import asyncio
        >>> from wt_invokers.compile_from_env import CompileFromEnvInvoker
        >>> invoker = CompileFromEnvInvoker(spec_path="spec.yaml")
        >>> # asyncio.run(invoker.run(
        >>> #     workflow_run_id="run-123",
        >>> #     config_text='{"total": {"a": 40, "b": 2}}',
        >>> #     results_url="file:///tmp/results",
        >>> #     execution_mode="sequential",
        >>> #     mock_io=False,
        >>> # ))
        >>> # exit_code = asyncio.run(invoker.wait(timeout=300))
    """

    matchspec: MatchSpec | None = None  # type: ignore[assignment]  # spec-driven: base requires MatchSpec, this invoker doesn't
    spec_path: str | Path | None = None
    discover_packages: list[str] | None = None
    build_dir: str | Path | None = None
    cwd: str | None = field(
        default_factory=lambda: os.environ.get(
            "WT_INVOKERS__COMPILE_FROM_ENV_INVOKER__CWD"
        )
    )
    _release_dir: Path | None = field(default=None, init=False, repr=False)
    _package_name: str | None = field(default=None, init=False, repr=False)

    def _ensure_built(self) -> tuple[Path, str]:
        """Compile the spec (once) and return the build dir and package name.

        The compiled artifacts are cached on the instance so repeated runs of
        the same spec reuse the build. Compilation uses the current-environment
        (solve-free) discovery path.

        Returns:
            A ``(release_dir, package_name)`` tuple, where ``release_dir`` is
            the directory to place on ``PYTHONPATH`` and ``package_name`` is
            the importable package.

        Raises:
            ValueError: If :attr:`spec_path` was not set.
            ImportError: If ``wt-compiler`` is not installed in the environment.
        """
        if self._release_dir is not None and self._package_name is not None:
            return self._release_dir, self._package_name

        if self.spec_path is None:
            raise ValueError("spec_path must be set to compile a workflow.")

        # wt-compiler is an optional dependency: only the compile-from-env
        # invoker needs it, and pulling it (and rattler) into every invoker
        # user is undesirable. Import lazily behind this invoker's code path.
        from wt_compiler.compiler import (  # noqa: PLC0415  # optional dependency, scoped to this invoker
            compile_workflow_from_env,
        )

        build_root = (
            Path(self.build_dir)
            if self.build_dir is not None
            else Path(tempfile.mkdtemp(prefix="wt-compile-from-env-"))
        )
        build_root.mkdir(parents=True, exist_ok=True)

        # Compile from a copy of the spec inside build_root so the artifacts
        # land in build_root/<release_name> (release_dir is spec-relative).
        spec_dst = build_root / "spec.yaml"
        spec_dst.write_text(Path(self.spec_path).read_text())

        artifacts = compile_workflow_from_env(
            spec_dst,
            progress=False,
            discover_packages=self.discover_packages,
        )
        artifacts.dump(clobber=True)

        self._release_dir = build_root / artifacts.release_name
        self._package_name = artifacts.package_name
        return self._release_dir, self._package_name

    async def is_installed(self) -> bool:
        """Return whether the spec has already been compiled.

        Returns:
            True if a prior build is cached on this invoker, False otherwise.
        """
        return self._release_dir is not None

    async def install(self) -> None:
        """Compile the spec, making the workflow runnable.

        For this invoker "install" means compile-from-env: there is no package
        download or dependency solve. Idempotent -- a cached build is reused.
        """
        self._ensure_built()

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
        """Compile (if needed) and launch the workflow subprocess.

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
        release_dir, package_name = self._ensure_built()

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
