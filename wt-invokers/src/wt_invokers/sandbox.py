"""Sandbox invoker: runs workflows from a pixi-pack tarball with results upload.

This invoker composes :class:`~wt_invokers.mixins.PixiUnpackMixin` and
:class:`~wt_invokers.mixins.UploadResultsArchiveMixin` on top of
:class:`~wt_invokers.abstract.AbstractInvoker` so that a single ``run()`` /
``wait()`` cycle downloads and activates a pixi-pack environment, executes
the workflow, and then uploads the results archive — all from Python.

The invoker itself is not sandboxed; its interface is just constrained enough
(two external URLs: environment in, results out) for downstream deployments
to enforce network and filesystem isolation via container sandboxing,
egress proxies, etc.

A ``[project.scripts]`` console entry point ``wt-invokers.sandbox`` calls
:func:`main` in this module, which is the ENTRYPOINT of the sandbox Docker
image.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rattler import MatchSpec

from .abstract import AbstractInvoker
from .exceptions import InvocationTimeoutError
from .mixins import PixiUnpackMixin, UploadResultsArchiveMixin
from .utils import yaml_to_json


@dataclass
class SandboxInvoker(PixiUnpackMixin, UploadResultsArchiveMixin, AbstractInvoker):
    """Invoker with a minimal network/filesystem interface for sandboxed deployments.

    This invoker is not itself sandboxed. Its interface is deliberately
    constrained to just two external URLs (``environment_tar_url`` for input,
    ``results_upload_url`` for output), which facilitates downstream
    deployments that enforce actual network and filesystem isolation (e.g.
    behind an egress proxy with restricted outbound access). Those
    deployments are responsible for enforcing the sandbox; this invoker just
    provides the minimal interface that simplifies sandboxing.

    Attributes:
        matchspec: Rattler MatchSpec specifying the workflow package
        work_dir: Working directory for unpacking the environment and running
            the workflow. Defaults to ``WT_INVOKERS__SANDBOX_INVOKER__WORK_DIR``
            env var or ``/work``.

    Examples:
        Running a workflow locally against a file:// environment tarball:

        >>> from rattler import MatchSpec
        >>> invoker = SandboxInvoker(  # doctest: +SKIP
        ...     matchspec=MatchSpec("my-workflow>=1.0.0"),
        ...     work_dir="/tmp/sandbox",
        ... )
    """

    work_dir: str = field(
        default_factory=lambda: os.environ.get(
            "WT_INVOKERS__SANDBOX_INVOKER__WORK_DIR", "/work"
        )
    )

    async def is_installed(self) -> bool:
        """Workflow is in the pixi-pack tarball, always effectively installed."""
        return True

    async def install(self) -> None:
        """Not supported — the workflow must ship inside the tarball."""
        raise NotImplementedError(
            "SandboxInvoker does not support dynamic install; the workflow "
            "must be bundled in the pixi-pack environment tarball."
        )

    @property
    def is_waitable(self) -> bool:
        return True

    def _workflow_name(self) -> str:
        name = self.matchspec.name
        if name is None:
            raise ValueError("MatchSpec must have a package name")
        return str(name.normalized)

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
        """Start the workflow subprocess after pixi-unpack has activated the env.

        The ``PixiUnpackMixin`` pre-run hook is responsible for populating
        ``self.run_state["activate_path"]``. This method sources that
        activation script then execs the bundled workflow binary.

        ``shell=True`` is used so the command can ``source`` the activation
        script and run the workflow in one process. The workflow binary is
        arbitrary user code that already has full subprocess access, so
        shell-quoting is not a meaningful trust boundary — the container
        sandbox is. No untrusted input is interpolated into the command.
        """
        config_as_json = yaml_to_json(text=config_text)
        workflow_name = self._workflow_name()

        mock_flag = "--mock-io" if mock_io else "--no-mock-io"
        otel_args = ""
        if otel_exporter:
            otel_args += f" --otel-exporter {otel_exporter}"
        if otel_console_exporter_dst:
            otel_args += f" --otel-console-exporter-dst {otel_console_exporter_dst}"

        activate_path = self.run_state.get("activate_path")
        if not activate_path:
            raise RuntimeError(
                "activate_path not set in run_state; PixiUnpackMixin._pre_run "
                "must have run first"
            )

        # Quote the JSON once so single quotes inside the payload don't break
        # the shell string (rare but defensive).
        config_as_json_sq = config_as_json.replace("'", "'\"'\"'")
        cmd = (
            f"source {activate_path}"
            f" && {workflow_name} run"
            f" --config-json '{config_as_json_sq}'"
            f" --execution-mode {execution_mode}"
            f" {mock_flag}{otel_args}"
        )

        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        env[self.results_env_var] = results_url

        self.run_state["process"] = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=self.work_dir,
        )

    async def _wait(
        self,
        timeout: float | None = None,
        error_msg: str | None = None,
    ) -> int:
        process: subprocess.Popen[bytes] | None = self.run_state.get("process")
        if process is None:
            raise RuntimeError("Process not started. Call run() first.")
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise InvocationTimeoutError(error_msg or str(e)) from e

    async def check_output(self, command: list[str], stdin: str | None = None) -> str:
        """Sandbox invocations do not support driver-side introspection."""
        raise NotImplementedError(
            "SandboxInvoker does not support check_output; the workflow "
            "runs inside a sandboxed container and its environment is not "
            "reachable from the driver process."
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wt-invokers.sandbox",
        description=(
            "Run a workflow inside a sandboxed environment: download a pixi-pack "
            "tarball, execute the workflow, upload the results archive."
        ),
    )
    p.add_argument(
        "--matchspec",
        required=True,
        help="Rattler matchspec for the workflow",
    )
    p.add_argument("--workflow-run-id", required=True)
    p.add_argument("--environment-tar-url", required=True)
    p.add_argument("--results-upload-url", required=True)
    p.add_argument(
        "--results-url",
        default="file:///results",
        help="Local directory URL for workflow outputs (file://)",
    )
    p.add_argument("--config-json", required=True)
    p.add_argument(
        "--execution-mode",
        default="sequential",
        choices=["sequential", "parallel", "async"],
    )
    p.add_argument("--mock-io", dest="mock_io", action="store_true")
    p.add_argument("--no-mock-io", dest="mock_io", action="store_false")
    p.set_defaults(mock_io=False)
    p.add_argument("--otel-exporter", default=None)
    p.add_argument("--otel-console-exporter-dst", default=None)
    return p


async def _amain(args: argparse.Namespace) -> int:
    from urllib.parse import urlparse

    # Ensure the local results dir exists so the workflow can write into it.
    results_parsed = urlparse(args.results_url)
    if results_parsed.scheme in ("file", ""):
        Path(results_parsed.path).mkdir(parents=True, exist_ok=True)

    invoker = SandboxInvoker(matchspec=MatchSpec(args.matchspec))
    await invoker.run(
        workflow_run_id=args.workflow_run_id,
        config_text=args.config_json,
        results_url=args.results_url,
        execution_mode=args.execution_mode,
        mock_io=args.mock_io,
        otel_exporter=args.otel_exporter,
        otel_console_exporter_dst=args.otel_console_exporter_dst,
        environment_tar_url=args.environment_tar_url,
        results_upload_url=args.results_upload_url,
    )
    return await invoker.wait()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: parse args, run the sandbox invoker, exit with its code."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_amain(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
