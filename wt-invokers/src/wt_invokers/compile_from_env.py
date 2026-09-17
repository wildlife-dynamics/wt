"""On-the-fly compile-and-run invoker for baked-in environments.

This module provides :class:`CompileFromEnvInvoker`, an invoker that compiles
a workflow spec *on the fly* against the current (baked-in) environment and
runs the resulting package as a local subprocess -- with no dependency solve
and no separate workflow-package install.

It is the counterpart to ``wt-compiler``'s ``--from-env`` compile path: an
invoker image that bakes in ``ecoscope.platform`` + the ``wt`` stack + the task
libraries can turn a spec into a running DAG in ~1s, because the tasks are
already importable and the DAG is rendered rather than solved.

It extends :class:`~wt_invokers.compiled_package.CompiledPackageInvoker` with a
compile step: :meth:`_ensure_built` compiles the spec to a package on disk and
sets ``release_dir``/``package_name``; the inherited ``_run`` then executes it.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from .compiled_package import CompiledPackageInvoker


@dataclass
class CompileFromEnvInvoker(CompiledPackageInvoker):
    r"""Compile a spec against the current environment and run it locally.

    The workflow to run is given by :attr:`spec_path` (a ``spec.yaml``). On the
    first run (or via :meth:`install`), the spec is compiled with
    ``wt-compiler``'s ``compile_workflow_from_env`` -- which discovers tasks by
    running the installed ``wt-registry`` in the current environment, with no
    dependency solve -- and the artifacts are written to a build directory. The
    inherited runner then executes ``python -m <package>.cli run`` with the
    build directory on ``PYTHONPATH``.

    This is intended for a "trusted invoker" image that bakes in the ``wt``
    stack and task libraries, so on-the-fly (re)compilation is cheap and no
    per-workflow install or solve is required.

    Attributes:
        spec_path: Path to the ``spec.yaml`` to compile and run. Required.
        discover_packages: Optional dotted module paths forwarded to
            ``wt-registry --package`` during compilation, in addition to
            entry-point auto-discovery.
        build_dir: Optional directory to compile into. Defaults to a fresh
            temporary directory created on first build.

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

    spec_path: str | Path | None = None
    discover_packages: list[str] | None = None
    build_dir: str | Path | None = None

    def _ensure_built(self) -> tuple[Path, str]:
        """Compile the spec (once) and set ``release_dir``/``package_name``.

        The compiled artifacts are cached on the instance so repeated runs of
        the same spec reuse the build. Compilation uses the current-environment
        (solve-free) discovery path.

        Returns:
            A ``(release_dir, package_name)`` tuple.

        Raises:
            ValueError: If :attr:`spec_path` was not set.
            ImportError: If ``wt-compiler`` is not installed in the environment.
        """
        if self.release_dir is not None and self.package_name is not None:
            return Path(self.release_dir), self.package_name

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

        self.release_dir = build_root / artifacts.release_name
        self.package_name = artifacts.package_name
        return self.release_dir, self.package_name

    async def is_installed(self) -> bool:
        """Return whether the spec has already been compiled.

        Returns:
            True if a prior build is cached on this invoker, False otherwise.
        """
        return self.release_dir is not None

    async def install(self) -> None:
        """Compile the spec, making the workflow runnable.

        For this invoker "install" means compile-from-env: there is no package
        download or dependency solve. Idempotent -- a cached build is reused.
        """
        self._ensure_built()

    async def _pre_run(self) -> None:
        """Ensure the spec is compiled before the inherited ``_run`` executes."""
        self.release_dir, self.package_name = self._ensure_built()
