"""Google Cloud Batch invoker implementation.

This module provides a CloudBatchInvoker that runs workflows on Google Cloud
Batch. This requires optional GCP dependencies.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from typing import Any

try:
    from google.cloud.batch_v1 import (
        AllocationPolicy,
        BatchServiceClient,
        ComputeResource,
        CreateJobRequest,
        Environment,
        Job,
        LogsPolicy,
        Runnable,
        ServiceAccount,
        TaskGroup,
        TaskSpec,
    )

    GCP_AVAILABLE = True
except ImportError:
    GCP_AVAILABLE = False

from .abstract import AbstractInvoker
from .utils import yaml_to_json


@dataclass
class CloudBatchInvoker(AbstractInvoker):
    """Invoker that runs workflows on Google Cloud Batch.

    This invoker submits workflows to Google Cloud Batch for execution in
    containerized environments. It requires the google-cloud-batch package
    to be installed.

    Attributes:
        matchspec: Rattler MatchSpec specifying the workflow package

    Environment Variables:
        GOOGLE_CLOUD_PROJECT: GCP project ID
        CLOUD_RUN_REGION: GCP region (default: us-central1)
        BATCH_SERVICE_ACCOUNT: Optional service account email for batch jobs

    Examples:
        Creating and using a cloud batch invoker:

        >>> from rattler import MatchSpec
        >>> invoker = CloudBatchInvoker(
        ...     matchspec=MatchSpec("my-workflow>=1.0.0")
        ... )

        Running a workflow on Cloud Batch:

        >>> import asyncio
        >>> invoker = CloudBatchInvoker(
        ...     matchspec=MatchSpec("my-workflow>=1.0.0")
        ... )
        >>> config = "param1: value1\\nparam2: value2"
        >>> # asyncio.run(invoker.run(
        >>> #     workflow_run_id="run-123",
        >>> #     config_text=config,
        >>> #     results_url="gs://bucket/results",
        >>> #     execution_mode="sequential",
        >>> #     mock_io=False,
        >>> #     docker_image_uri="gcr.io/project/workflow:latest",
        >>> #     cpu_milli=8000,
        >>> #     memory_mib=32768
        >>> # ))

    Note:
        This invoker requires the 'gcp' optional dependencies:
        pip install wt-invokers[gcp]
    """

    def __post_init__(self) -> None:
        """Initialize the invoker and check GCP availability."""
        if not GCP_AVAILABLE:
            raise ImportError(
                "Google Cloud Batch dependencies not available. "
                "Install with: pip install wt-invokers[gcp]"
            )

    @property
    def entrypoint(self) -> str:
        """Get the entrypoint command for the workflow.

        Returns:
            Command string to invoke the workflow via pixi

        Examples:
            Getting the entrypoint:

            >>> from rattler import MatchSpec
            >>> invoker = CloudBatchInvoker(
            ...     matchspec=MatchSpec("my-workflow>=1.0.0")
            ... )
            >>> invoker.entrypoint
            'pixi run -e default my-workflow'
        """
        name = self.matchspec.name
        if name is None:
            raise ValueError("MatchSpec must have a package name")
        return f"pixi run -e default {name.normalized}"

    async def is_installed(self) -> bool:
        """Check if the workflow is installed.

        For Cloud Batch, we assume the workflow is installed in the Docker
        image. This may be revisited for custom workflows.

        Returns:
            True (assumes workflow is in the container image)

        Examples:
            Checking installation:

            >>> import asyncio
            >>> from rattler import MatchSpec
            >>> invoker = CloudBatchInvoker(
            ...     matchspec=MatchSpec("my-workflow>=1.0.0")
            ... )
            >>> asyncio.run(invoker.is_installed())
            True
        """
        # Assuming the workflow is installed in the docker image
        # TODO: revisit this once supporting custom workflows with custom matchspecs
        return True

    async def install(self) -> None:
        """Install the workflow.

        Raises:
            NotImplementedError: Dynamic installation is not yet supported

        Examples:
            Attempting to install:

            >>> import asyncio
            >>> from rattler import MatchSpec
            >>> invoker = CloudBatchInvoker(
            ...     matchspec=MatchSpec("my-workflow>=1.0.0")
            ... )
            >>> # asyncio.run(invoker.install())
            >>> # NotImplementedError: Dynamic installation not yet supported.
        """
        raise NotImplementedError(
            "Dynamic installation of workflows is not yet supported."
        )

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
        """Invoke the workflow with GCP Cloud Batch API.

        Args:
            workflow_run_id: Unique identifier for this workflow run
            config_text: YAML configuration text for the workflow
            results_url: URL where workflow results should be stored (e.g., gs://...)
            execution_mode: Execution mode (e.g., "sequential", "parallel")
            mock_io: Whether to mock I/O operations
            otel_exporter: Optional OpenTelemetry exporter endpoint
            otel_console_exporter_dst: Optional console exporter destination
            extra_env: Optional extra environment variables to pass
            lithops_config_text: Optional Lithops configuration text (not used)
            **kwargs: Additional Cloud Batch-specific arguments:
                - docker_image_uri (required): Docker image URI
                - project_id: GCP project ID (default: from GOOGLE_CLOUD_PROJECT)
                - region: GCP region (default: from CLOUD_RUN_REGION or us-central1)
                - cpu_milli: CPU allocation in millicores (default: 8000)
                - memory_mib: Memory allocation in MiB (default: 32768)
                - machine_type: Optional specific machine type
                - timeout: Optional timeout in seconds
                - gpu_type: Optional GPU type
                - gpu_count: Optional GPU count (default: 1)

        Raises:
            ValueError: If docker_image_uri or workflow_run_id is missing

        Examples:
            Running a workflow:

            >>> import asyncio
            >>> from rattler import MatchSpec
            >>> invoker = CloudBatchInvoker(
            ...     matchspec=MatchSpec("my-workflow>=1.0.0")
            ... )
            >>> config = '''
            ... param1: value1
            ... param2: 42
            ... '''
            >>> # asyncio.run(invoker.run(
            >>> #     workflow_run_id="run-123",
            >>> #     config_text=config,
            >>> #     results_url="gs://my-bucket/results",
            >>> #     execution_mode="sequential",
            >>> #     mock_io=False,
            >>> #     docker_image_uri="gcr.io/project/workflow:latest"
            >>> # ))
        """
        # Validate required parameters
        docker_image_uri = kwargs.pop("docker_image_uri", None)
        if not docker_image_uri:
            raise ValueError("docker_image_uri is required for Cloud Batch invoker")
        if not workflow_run_id:
            raise ValueError("workflow_run_id cannot be blank for Cloud Batch invoker")

        # Generate unique job name
        clean_workflow_run_id = (
            workflow_run_id.lower().strip().replace("_", "-").rstrip("-")
        )
        unique_prefix = f"job-{uuid.uuid4().hex[:6].lower()}"  # Generate unique prefix
        job_name_unique = f"{unique_prefix}-{clean_workflow_run_id}"[
            :61
        ]  # Max length for GCP job names

        # Convert config to JSON
        config_as_json = yaml_to_json(text=config_text)

        # Build command
        cmd = self.entrypoint.split() + [
            "run",
            "--config-json",
            config_as_json,
            "--execution-mode",
            execution_mode,
            "--mock-io" if mock_io else "--no-mock-io",
            *(["--otel-exporter", otel_exporter] if otel_exporter else []),
            *(
                ["--otel-console-exporter-dst", otel_console_exporter_dst]
                if otel_console_exporter_dst
                else []
            ),
        ]

        # Setup environment variables
        extra_env = (
            {k: v for k, v in os.environ.items() if k.startswith("WT_")}
            | (extra_env or {})
            | {self.results_env_var: results_url}
        )

        # Prepare parameters for Cloud Batch job
        params = {
            "job_name": job_name_unique,
            "docker_image_uri": docker_image_uri,
            "cmd": cmd,
            "extra_env": extra_env,
        } | kwargs

        # Create and submit the job
        await self._create_container_job(**params)

    @property
    def is_waitable(self) -> bool:
        """Check if the invoker supports waiting for completion.

        Returns:
            False (Cloud Batch jobs run asynchronously)

        Examples:
            Checking if waitable:

            >>> from rattler import MatchSpec
            >>> invoker = CloudBatchInvoker(
            ...     matchspec=MatchSpec("my-workflow>=1.0.0")
            ... )
            >>> invoker.is_waitable
            False
        """
        # Cloud Batch jobs are not waitable
        return False

    async def wait(
        self,
        timeout: float | None = None,
        error_msg: str | None = None,
    ) -> int:
        """Wait for the workflow to finish.

        This is a no-op for Cloud Batch as jobs run asynchronously.

        Args:
            timeout: Ignored
            error_msg: Ignored

        Returns:
            0 (always successful)

        Examples:
            Calling wait (no-op):

            >>> import asyncio
            >>> from rattler import MatchSpec
            >>> invoker = CloudBatchInvoker(
            ...     matchspec=MatchSpec("my-workflow>=1.0.0")
            ... )
            >>> asyncio.run(invoker.wait())
            0
        """
        # Cannot wait for the job to finish in this invoker
        return 0

    async def _create_container_job(
        self, job_name: str, docker_image_uri: str, cmd: list[str], **kwargs: Any
    ) -> Job:
        """Run a containerized job on Cloud Batch.

        Args:
            job_name: Unique job name for GCP
            docker_image_uri: Docker image URI to use
            cmd: Command to run in the container
            **kwargs: Additional parameters:
                - extra_env: Environment variables dict
                - project_id: GCP project ID
                - region: GCP region
                - cpu_milli: CPU allocation
                - memory_mib: Memory allocation
                - machine_type: Optional machine type
                - timeout: Optional timeout in seconds
                - gpu_type: Optional GPU type
                - gpu_count: Optional GPU count

        Returns:
            Created Cloud Batch Job object

        Raises:
            google.api_core.exceptions.GoogleAPIError: If job creation fails
        """
        # Extract parameters with defaults
        extra_env = kwargs.get("extra_env")
        project_id = kwargs.get("project_id", os.getenv("GOOGLE_CLOUD_PROJECT"))
        region = kwargs.get("region", os.getenv("CLOUD_RUN_REGION", "us-central1"))
        cpu_milli = kwargs.get("cpu_milli", 8000)  # Default to 8 vCPUs
        memory_mib = kwargs.get("memory_mib", 32768)  # Default to 32 GiB

        client = BatchServiceClient()

        # Define what will be done as part of the job
        runnable = Runnable()
        runnable.container = Runnable.Container()
        runnable.container.image_uri = docker_image_uri
        runnable.container.commands = cmd

        # Set environment variables if provided
        if extra_env:
            env = Environment()
            env.variables = extra_env
            runnable.environment = env

        # Jobs can be divided into tasks. In this case, we have only one task
        task = TaskSpec()
        task.runnables = [runnable]

        # Set resources for the task
        resources = ComputeResource()
        resources.cpu_milli = cpu_milli
        resources.memory_mib = memory_mib
        task.compute_resource = resources

        if timeout := kwargs.get("timeout"):
            task.max_run_duration = f"{int(timeout)}s"  # e.g. "600s" for 10 minutes

        # Tasks are grouped inside a job using TaskGroups
        group = TaskGroup()
        group.task_count = 1
        group.task_spec = task

        # Policies define what kind of VMs the tasks will run on
        policy = AllocationPolicy.InstancePolicy()

        # Optional: Specify machine type
        if machine_type := kwargs.get("machine_type"):
            policy.machine_type = machine_type

        instances = AllocationPolicy.InstancePolicyOrTemplate()
        instances.policy = policy
        allocation_policy = AllocationPolicy()
        allocation_policy.instances = [instances]

        # Use a different service account if specified
        if batch_service_account_email := os.getenv("BATCH_SERVICE_ACCOUNT"):
            job_service_account = ServiceAccount()
            job_service_account.email = batch_service_account_email
            allocation_policy.service_account = job_service_account

        # Add GPU accelerators if needed
        if (gpu_type := kwargs.get("gpu_type")) and (
            gpu_count := kwargs.get("gpu_count", 1) > 0
        ):
            accelerator = AllocationPolicy.Accelerator()
            accelerator.type_ = gpu_type
            accelerator.count = gpu_count
            policy.accelerators = [accelerator]
            instances.install_gpu_drivers = True

        # Create the job
        job = Job()
        job.task_groups = [group]
        job.allocation_policy = allocation_policy
        job.logs_policy = LogsPolicy()
        job.logs_policy.destination = LogsPolicy.Destination.CLOUD_LOGGING  # type: ignore[assignment]

        create_request = CreateJobRequest()
        create_request.job = job
        create_request.job_id = job_name
        create_request.parent = f"projects/{project_id}/locations/{region}"

        # There's no async(io) compatible client for the Cloud Batch API
        return await asyncio.to_thread(client.create_job, create_request)
