"""Proxy invoker that dispatches to a pre-deployed Google Cloud Run Job.

This invoker does *not* run the workflow itself. It asks a pre-deployed
Cloud Run Job to start a new execution whose container runs
``wt-invokers.sandbox`` (the :class:`~wt_invokers.sandbox.SandboxInvoker`
CLI). All the actual pixi-unpack, workflow execution, and results-upload
work happens inside that container.

Because the job runs asynchronously, this invoker is not waitable: ``wait()``
is a no-op that returns ``0``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

try:
    from google.cloud.run_v2 import JobsAsyncClient, RunJobRequest
    from google.cloud.run_v2.types import EnvVar

    CLOUD_RUN_AVAILABLE = True
except ImportError:
    CLOUD_RUN_AVAILABLE = False

from .abstract import AbstractInvoker
from .utils import yaml_to_json

logger = logging.getLogger(__name__)


@dataclass
class CloudRunJobsSandboxInvoker(AbstractInvoker):
    """Proxy invoker that triggers a Cloud Run Job to execute the sandbox CLI.

    The per-invocation values — ``environment_tar_url``, ``results_upload_url``,
    ``job_name``, ``project_id``, and optional ``region`` — come in as
    ``**kwargs`` on each :meth:`run` call. Nothing is stored on the instance
    between invocations.

    Attributes:
        matchspec: Rattler MatchSpec specifying the workflow package

    Note:
        Requires the ``gcp`` optional dependency::

            pip install wt-invokers[gcp]

        or the ``wt-invokers-gcp`` metapackage.
    """

    def __post_init__(self) -> None:
        if not CLOUD_RUN_AVAILABLE:
            raise ImportError(
                "Google Cloud Run dependencies not available. "
                "Install with: pip install wt-invokers[gcp]"
            )

    async def is_installed(self) -> bool:
        return True

    async def install(self) -> None:
        raise NotImplementedError(
            "Dynamic installation of workflows is not yet supported."
        )

    @property
    def is_waitable(self) -> bool:
        return False

    async def _wait(
        self,
        timeout: float | None = None,
        error_msg: str | None = None,
    ) -> int:
        return 0

    async def _ensure_job_exists(self, fq_job_name: str) -> None:
        client = JobsAsyncClient()
        try:
            await client.get_job(name=fq_job_name)
        except Exception as e:
            raise RuntimeError(
                f"Pre-deployed Cloud Run Job not found: {fq_job_name}. "
                f"Original error: {e}"
            ) from e

    async def _run(  # type: ignore[override]
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
        *,
        environment_tar_url: str,
        results_upload_url: str,
        job_name: str,
        project_id: str,
        region: str = "us-central1",
    ) -> None:
        """Trigger a new execution of the pre-deployed Cloud Run Job.

        Args:
            environment_tar_url: Signed URL of the pixi-pack environment tarball.
            results_upload_url: Signed URL where the results archive should be
                uploaded after the workflow finishes.
            job_name: Short name of the pre-deployed Cloud Run Job.
            project_id: GCP project ID.
            region: GCP region (default ``us-central1``).
        """
        config_as_json = yaml_to_json(text=config_text)
        fq_job_name = f"projects/{project_id}/locations/{region}/jobs/{job_name}"
        await self._ensure_job_exists(fq_job_name)

        matchspec_str = str(self.matchspec)
        container_args = [
            "--matchspec",
            matchspec_str,
            "--workflow-run-id",
            workflow_run_id,
            "--environment-tar-url",
            environment_tar_url,
            "--results-upload-url",
            results_upload_url,
            "--results-url",
            results_url,
            "--config-json",
            config_as_json,
            "--execution-mode",
            execution_mode,
        ]
        if mock_io:
            container_args.append("--mock-io")
        else:
            container_args.append("--no-mock-io")
        if otel_exporter:
            container_args.extend(["--otel-exporter", otel_exporter])
        if otel_console_exporter_dst:
            container_args.extend(
                ["--otel-console-exporter-dst", otel_console_exporter_dst]
            )

        env_vars = dict(extra_env or {})
        env_vars[self.results_env_var] = results_url

        client = JobsAsyncClient()
        override = RunJobRequest.Overrides()
        container_override = RunJobRequest.Overrides.ContainerOverride()
        container_override.args = container_args
        container_override.env = [EnvVar(name=k, value=v) for k, v in env_vars.items()]
        override.container_overrides = [container_override]

        request = RunJobRequest(
            name=fq_job_name,
            overrides=override,
        )
        operation = await client.run_job(request=request)
        logger.info(
            "Triggered Cloud Run Job execution for %s (metadata=%s)",
            fq_job_name,
            getattr(getattr(operation, "metadata", None), "name", None),
        )
