"""Invoker that runs a pre-built compiled workflow package via its CLI.

Given a compiled package directory, this launches ``python -m <package>.cli
run`` with that directory on ``PYTHONPATH``. The environment -- either the
ambient one or a named pre-solved pixi environment -- is expected to supply
every runtime dependency, so nothing is ever installed or solved.

The workflow is identified by its matchspec, exactly as for a published
package. A compiled-but-unpublished build fills all three matchspec fields:

    <release-name>==<version>=<content-hash>

so a build that came out of a warm compile server and one pulled from a conda
channel are named the same way, and a build's identity survives being passed
across a process boundary as a string.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ._subprocess import SubprocessInvokerBase


@dataclass
class CompiledPackageInvoker(SubprocessInvokerBase):
    r"""Run a pre-built compiled workflow package via its generated CLI.

    Attributes:
        matchspec: Identifies the build. Its package name yields the importable
            package name; its version and build string identify which build.
        release_dir: Directory containing the compiled package (placed on
            ``PYTHONPATH``).
        pixi_env: Optional named pixi environment to run in. When set, the
            command is prefixed with ``pixi run -e <env>``; when unset the
            running interpreter is used, which assumes the ambient environment
            already carries the workflow's runtime dependencies.
        manifest_path: Optional explicit path to the workspace's pixi manifest.
        cwd: Optional working directory for the workflow subprocess.

    Environment Variables:
        WT_INVOKERS__COMPILED_PACKAGE_INVOKER__CWD: Default working directory

    Examples:
        Running an already-compiled package:

        >>> from pathlib import Path
        >>> from rattler import MatchSpec
        >>> invoker = CompiledPackageInvoker(
        ...     matchspec=MatchSpec("wt-demo-workflow==0.2.0=a1b2c3d4e5f60718"),
        ...     release_dir=Path("/build/wt-demo-workflow"),
        ... )
        >>> invoker.package_name
        'wt_demo_workflow'
        >>> # asyncio.run(invoker.run(
        >>> #     workflow_run_id="run-123",
        >>> #     config_text='{"total": {"a": 40, "b": 2}}',
        >>> #     results_url="file:///tmp/results",
        >>> #     execution_mode="sequential",
        >>> #     mock_io=False,
        >>> # ))
        >>> # exit_code = asyncio.run(invoker.wait(timeout=300))
    """

    release_dir: Path | None = None
    pixi_env: str | None = None
    manifest_path: Path | None = None
    cwd: str | None = field(
        default_factory=lambda: os.environ.get(
            "WT_INVOKERS__COMPILED_PACKAGE_INVOKER__CWD"
        )
    )

    @property
    def package_name(self) -> str:
        """Importable package name, derived from the matchspec's package name.

        Mirrors the compiler's own ``release_name`` -> ``package_name``
        derivation, so a build never has to carry both.

        Returns:
            The importable package name (e.g. ``wt_demo_workflow``).

        Raises:
            ValueError: If the matchspec has no package name.

        Examples:
            >>> from rattler import MatchSpec
            >>> invoker = CompiledPackageInvoker(
            ...     matchspec=MatchSpec("ecoscope-workflows-events-workflow==1.2.0")
            ... )
            >>> invoker.package_name
            'ecoscope_workflows_events_workflow'
        """
        name = self.matchspec.name
        if name is None:
            raise ValueError("MatchSpec must have a package name")
        return name.normalized.replace("-", "_")

    def _resolve_release_dir(self) -> Path:
        """Return the compiled package's directory.

        Returns:
            The directory placed on ``PYTHONPATH``.

        Raises:
            ValueError: If ``release_dir`` is not set.
        """
        if self.release_dir is None:
            raise ValueError("release_dir must be set to run a compiled package.")
        return Path(self.release_dir)

    def _entrypoint_argv(self) -> list[str]:
        """Return the argv that invokes the compiled package's CLI module."""
        module_args = ["-m", f"{self.package_name}.cli"]
        if self.pixi_env is None:
            return [sys.executable, *module_args]
        argv = ["pixi", "run"]
        if self.manifest_path is not None:
            argv += ["--manifest-path", str(self.manifest_path)]
        return [*argv, "-e", self.pixi_env, "python", *module_args]

    def _run_env_overrides(self) -> dict[str, str]:
        """Put the compiled package on ``PYTHONPATH``, ahead of any existing entries."""
        release_dir = self._resolve_release_dir()
        existing = os.environ.get("PYTHONPATH", "")
        pythonpath = (
            f"{release_dir}{os.pathsep}{existing}" if existing else str(release_dir)
        )
        return {"PYTHONPATH": pythonpath}

    async def is_installed(self) -> bool:
        """Return whether a compiled package directory is set on this invoker.

        Returns:
            True if ``release_dir`` is set.
        """
        return self.release_dir is not None

    async def install(self) -> None:
        """No-op: the compiled package is supplied at construction."""
