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
from .utils import validate_environment_tar_digest, yaml_to_json

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
        """Fail fast if the gcp extra is not installed."""
        if not CLOUD_RUN_AVAILABLE:
            raise ImportError(
                "Google Cloud Run dependencies not available. "
                "Install with: pip install wt-invokers[gcp]"
            )

    async def is_installed(self) -> bool:
        """Return ``True``: this proxy invoker has nothing to install."""
        return True

    async def install(self) -> None:
        """Raise — dynamic installation of workflows is not yet supported."""
        raise NotImplementedError(
            "Dynamic installation of workflows is not yet supported."
        )

    @property
    def is_waitable(self) -> bool:
        """Return ``False``: Cloud Run Job executions run asynchronously."""
        return False

    async def _wait(
        self,
        timeout: float | None = None,  # noqa: ASYNC109, ARG002  # interface compatibility — Cloud Run Job is non-waitable
        error_msg: str | None = None,  # noqa: ARG002  # interface compatibility
    ) -> int:
        return 0

    async def _ensure_job_exists(self, fq_job_name: str) -> None:
        # Broad catch is intentional: the check answers "is this job usable?"
        # Any reason it isn't (missing, auth, quota, service unavailable) is
        # equally worth surfacing. The exception type is included so callers
        # can distinguish reasons at a glance; ``from e`` preserves the full
        # traceback for deeper inspection.
        client = JobsAsyncClient()
        try:
            await client.get_job(name=fq_job_name)
        except Exception as e:
            raise RuntimeError(
                f"Pre-deployed Cloud Run Job {fq_job_name} is not available "
                f"({type(e).__name__}): {e}"
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
        lithops_config_text: str | None = None,  # noqa: ARG002  # interface compatibility — proxy invoker doesn't run lithops
        *,
        environment_tar_url: str,
        environment_tar_digest: str,
        results_upload_url: str | None = None,
        skip_results_archive_upload: bool = False,
        job_name: str,
        project_id: str,
        region: str = "us-central1",
    ) -> None:
        """Trigger a new execution of the pre-deployed Cloud Run Job.

        Args:
            workflow_run_id: Unique identifier for this workflow run.
            config_text: YAML workflow configuration; converted to JSON before
                being passed to the sandbox CLI inside the container.
            results_url: Destination URL the workflow writes results to.
            execution_mode: Execution mode forwarded to the sandbox CLI.
            mock_io: Whether to enable mocked I/O for the workflow.
            otel_exporter: Optional OpenTelemetry exporter target.
            otel_console_exporter_dst: Optional console-exporter destination.
            extra_env: Extra environment variables to set in the container.
            lithops_config_text: Unused; accepted for interface compatibility
                with the abstract :meth:`_run` signature.
            environment_tar_url: Signed URL of the pixi-pack environment tarball.
            environment_tar_digest: Expected sha256 digest of the environment
                tarball, formatted as ``"sha256:<64 hex chars>"``. Forwarded to
                the sandbox CLI, which verifies the downloaded tarball against
                it before unpacking.
            results_upload_url: Signed URL where the results archive should be
                uploaded after the workflow finishes. Required unless
                ``skip_results_archive_upload`` is ``True``, in which case it
                must be omitted.
            skip_results_archive_upload: Skip the post-run results archive
                upload inside the sandbox container. Requires ``results_url``
                to be a real destination (not the sandbox staging default
                ``file:///results``) and is mutually exclusive with
                ``results_upload_url``.
            job_name: Short name of the pre-deployed Cloud Run Job.
            project_id: GCP project ID.
            region: GCP region (default ``us-central1``).

        Raises:
            ValueError: If ``environment_tar_digest`` is malformed, or if
                ``results_upload_url`` and ``skip_results_archive_upload`` are
                combined inconsistently. Validation happens eagerly here —
                mirroring the sandbox CLI's rules — because the job runs
                asynchronously, so a CLI-level error would otherwise only
                surface inside the container.
        """
        validate_environment_tar_digest(environment_tar_digest)
        if not skip_results_archive_upload and results_upload_url is None:
            raise ValueError(
                "results_upload_url is required unless skip_results_archive_upload=True"
            )
        if skip_results_archive_upload:
            if results_upload_url is not None:
                raise ValueError(
                    "results_upload_url is mutually exclusive with "
                    "skip_results_archive_upload=True"
                )
            if results_url == "file:///results":
                raise ValueError(
                    "skip_results_archive_upload=True requires results_url "
                    "to point at a real destination, not the sandbox staging "
                    "default file:///results"
                )

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
            "--environment-tar-digest",
            environment_tar_digest,
            "--results-url",
            results_url,
            "--config-json",
            config_as_json,
            "--execution-mode",
            execution_mode,
        ]
        if skip_results_archive_upload:
            container_args.append("--dangerously-skip-results-archive-upload")
        elif results_upload_url is not None:
            container_args.extend(["--results-upload-url", results_upload_url])
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
        # operation.metadata is a google.cloud.run_v2.types.Execution on a
        # well-formed LRO response; an AttributeError here would be a real bug
        # and should surface rather than be silently swallowed.
        execution_resource = operation.metadata.name
        execution_id = execution_resource.rsplit("/", 1)[-1]
        logger.info(
            "Triggered Cloud Run Job execution: id=%s resource=%s",
            execution_id,
            execution_resource,
        )
