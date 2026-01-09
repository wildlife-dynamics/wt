"""Tests for CloudBatchInvoker.

This module tests the CloudBatchInvoker implementation using mocks to avoid
requiring actual GCP credentials or making real API calls.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rattler import MatchSpec


@pytest.fixture
def mock_gcp_modules():
    """Mock GCP modules to allow testing without GCP dependencies."""
    with patch.dict("sys.modules"):
        # Create mock modules and classes
        mock_batch = MagicMock()
        mock_batch.AllocationPolicy = MagicMock()
        mock_batch.BatchServiceClient = MagicMock()
        mock_batch.ComputeResource = MagicMock()
        mock_batch.CreateJobRequest = MagicMock()
        mock_batch.Environment = MagicMock()
        mock_batch.Job = MagicMock()
        mock_batch.LogsPolicy = MagicMock()
        mock_batch.Runnable = MagicMock()
        mock_batch.ServiceAccount = MagicMock()
        mock_batch.TaskGroup = MagicMock()
        mock_batch.TaskSpec = MagicMock()

        # Set GCP_AVAILABLE to True in the module
        import sys

        sys.modules["google"] = MagicMock()
        sys.modules["google.cloud"] = MagicMock()
        sys.modules["google.cloud.batch_v1"] = mock_batch

        # Force reimport with mocked modules and inject the mocked classes
        import wt_invokers.cloud_batch

        # Inject all the mocked classes into the module namespace
        wt_invokers.cloud_batch.GCP_AVAILABLE = True
        wt_invokers.cloud_batch.BatchServiceClient = mock_batch.BatchServiceClient
        wt_invokers.cloud_batch.AllocationPolicy = mock_batch.AllocationPolicy
        wt_invokers.cloud_batch.ComputeResource = mock_batch.ComputeResource
        wt_invokers.cloud_batch.CreateJobRequest = mock_batch.CreateJobRequest
        wt_invokers.cloud_batch.Environment = mock_batch.Environment
        wt_invokers.cloud_batch.Job = mock_batch.Job
        wt_invokers.cloud_batch.LogsPolicy = mock_batch.LogsPolicy
        wt_invokers.cloud_batch.Runnable = mock_batch.Runnable
        wt_invokers.cloud_batch.ServiceAccount = mock_batch.ServiceAccount
        wt_invokers.cloud_batch.TaskGroup = mock_batch.TaskGroup
        wt_invokers.cloud_batch.TaskSpec = mock_batch.TaskSpec

        yield mock_batch


def test_cloud_batch_invoker_initialization_without_gcp(mock_gcp_modules) -> None:
    """Test CloudBatchInvoker initialization succeeds when GCP is available."""
    from wt_invokers.cloud_batch import CloudBatchInvoker

    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = CloudBatchInvoker(matchspec=matchspec)

    assert invoker.matchspec == matchspec


def test_cloud_batch_invoker_initialization_fails_without_gcp_libs() -> None:
    """Test CloudBatchInvoker initialization fails without GCP libraries."""
    # Temporarily set GCP_AVAILABLE to False
    import wt_invokers.cloud_batch

    original_value = wt_invokers.cloud_batch.GCP_AVAILABLE
    wt_invokers.cloud_batch.GCP_AVAILABLE = False

    try:
        from wt_invokers.cloud_batch import CloudBatchInvoker

        matchspec = MatchSpec("test-workflow>=1.0.0")

        with pytest.raises(
            ImportError,
            match="Google Cloud Batch dependencies not available",
        ):
            CloudBatchInvoker(matchspec=matchspec)
    finally:
        wt_invokers.cloud_batch.GCP_AVAILABLE = original_value


def test_entrypoint_property(mock_gcp_modules) -> None:
    """Test entrypoint property returns correct command."""
    from wt_invokers.cloud_batch import CloudBatchInvoker

    matchspec = MatchSpec("my-workflow>=1.0.0")
    invoker = CloudBatchInvoker(matchspec=matchspec)

    assert invoker.entrypoint == "pixi run -e default my-workflow"


@pytest.mark.asyncio
async def test_is_installed_returns_true(mock_gcp_modules) -> None:
    """Test is_installed returns True (assumes workflow is in container)."""
    from wt_invokers.cloud_batch import CloudBatchInvoker

    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = CloudBatchInvoker(matchspec=matchspec)

    result = await invoker.is_installed()
    assert result is True


@pytest.mark.asyncio
async def test_install_raises_not_implemented(mock_gcp_modules) -> None:
    """Test install raises NotImplementedError."""
    from wt_invokers.cloud_batch import CloudBatchInvoker

    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = CloudBatchInvoker(matchspec=matchspec)

    with pytest.raises(
        NotImplementedError,
        match="Dynamic installation of workflows is not yet supported",
    ):
        await invoker.install()


def test_is_waitable_property(mock_gcp_modules) -> None:
    """Test is_waitable property returns False."""
    from wt_invokers.cloud_batch import CloudBatchInvoker

    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = CloudBatchInvoker(matchspec=matchspec)

    assert invoker.is_waitable is False


@pytest.mark.asyncio
async def test_wait_returns_zero(mock_gcp_modules) -> None:
    """Test wait returns 0 (no-op for cloud batch)."""
    from wt_invokers.cloud_batch import CloudBatchInvoker

    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = CloudBatchInvoker(matchspec=matchspec)

    exit_code = await invoker.wait()
    assert exit_code == 0


@pytest.mark.asyncio
async def test_run_requires_docker_image_uri(mock_gcp_modules) -> None:
    """Test run raises ValueError if docker_image_uri is missing."""
    from wt_invokers.cloud_batch import CloudBatchInvoker

    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = CloudBatchInvoker(matchspec=matchspec)

    with pytest.raises(ValueError, match="docker_image_uri is required"):
        await invoker.run(
            workflow_run_id="test-run",
            config_text="param: value",
            results_url="gs://bucket/results",
            execution_mode="sequential",
            mock_io=False,
        )


@pytest.mark.asyncio
async def test_run_requires_workflow_run_id(mock_gcp_modules) -> None:
    """Test run raises ValueError if workflow_run_id is blank."""
    from wt_invokers.cloud_batch import CloudBatchInvoker

    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = CloudBatchInvoker(matchspec=matchspec)

    with pytest.raises(ValueError, match="workflow_run_id cannot be blank"):
        await invoker.run(
            workflow_run_id="",
            config_text="param: value",
            results_url="gs://bucket/results",
            execution_mode="sequential",
            mock_io=False,
            docker_image_uri="gcr.io/project/image:latest",
        )


@pytest.mark.asyncio
async def test_run_creates_cloud_batch_job(mock_gcp_modules) -> None:
    """Test run creates a Cloud Batch job with correct parameters."""
    from wt_invokers.cloud_batch import CloudBatchInvoker

    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = CloudBatchInvoker(matchspec=matchspec)

    # Mock the _create_container_job method
    mock_job = MagicMock()
    with patch.object(
        invoker, "_create_container_job", new=AsyncMock(return_value=mock_job)
    ) as mock_create:
        await invoker.run(
            workflow_run_id="test-run-123",
            config_text="param: value",
            results_url="gs://bucket/results",
            execution_mode="sequential",
            mock_io=False,
            docker_image_uri="gcr.io/project/image:latest",
        )

        # Verify _create_container_job was called
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]

        # Check job parameters
        assert "job_name" in call_kwargs
        assert "docker_image_uri" in call_kwargs
        assert call_kwargs["docker_image_uri"] == "gcr.io/project/image:latest"
        assert "cmd" in call_kwargs
        assert "extra_env" in call_kwargs


@pytest.mark.asyncio
async def test_run_sets_environment_variables(mock_gcp_modules) -> None:
    """Test run sets correct environment variables."""
    from wt_invokers.cloud_batch import CloudBatchInvoker

    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = CloudBatchInvoker(matchspec=matchspec)

    extra_env = {"CUSTOM_VAR": "custom_value"}

    with patch.object(invoker, "_create_container_job", new=AsyncMock()) as mock_create:
        await invoker.run(
            workflow_run_id="test-run",
            config_text="param: value",
            results_url="gs://bucket/results",
            execution_mode="sequential",
            mock_io=False,
            docker_image_uri="gcr.io/project/image:latest",
            extra_env=extra_env,
        )

        call_kwargs = mock_create.call_args[1]
        env = call_kwargs["extra_env"]

        assert "WT_RESULTS" in env
        assert env["WT_RESULTS"] == "gs://bucket/results"
        assert env["CUSTOM_VAR"] == "custom_value"


@pytest.mark.asyncio
async def test_run_builds_correct_command(mock_gcp_modules) -> None:
    """Test run builds correct command line."""
    from wt_invokers.cloud_batch import CloudBatchInvoker

    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = CloudBatchInvoker(matchspec=matchspec)

    with patch.object(invoker, "_create_container_job", new=AsyncMock()) as mock_create:
        await invoker.run(
            workflow_run_id="test-run",
            config_text="param: value",
            results_url="gs://bucket/results",
            execution_mode="parallel",
            mock_io=True,
            docker_image_uri="gcr.io/project/image:latest",
            otel_exporter="http://localhost:4318",
        )

        call_kwargs = mock_create.call_args[1]
        cmd = call_kwargs["cmd"]

        assert "pixi" in cmd
        assert "test-workflow" in cmd
        assert "run" in cmd
        assert "--config-json" in cmd
        assert "--execution-mode" in cmd
        assert "parallel" in cmd
        assert "--mock-io" in cmd
        assert "--otel-exporter" in cmd
        assert "http://localhost:4318" in cmd


@pytest.mark.asyncio
async def test_run_generates_unique_job_name(mock_gcp_modules) -> None:
    """Test run generates unique job names for each invocation."""
    from wt_invokers.cloud_batch import CloudBatchInvoker

    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = CloudBatchInvoker(matchspec=matchspec)

    job_names = []

    with patch.object(invoker, "_create_container_job", new=AsyncMock()) as mock_create:
        # Run multiple times
        for i in range(3):
            await invoker.run(
                workflow_run_id="test-run",
                config_text="param: value",
                results_url="gs://bucket/results",
                execution_mode="sequential",
                mock_io=False,
                docker_image_uri="gcr.io/project/image:latest",
            )

            call_kwargs = mock_create.call_args[1]
            job_names.append(call_kwargs["job_name"])

    # All job names should be unique
    assert len(job_names) == len(set(job_names))


@pytest.mark.asyncio
async def test_create_container_job_with_default_resources(mock_gcp_modules) -> None:
    """Test _create_container_job uses default resource values."""
    from wt_invokers.cloud_batch import CloudBatchInvoker

    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = CloudBatchInvoker(matchspec=matchspec)

    mock_client = MagicMock()
    mock_job = MagicMock()
    mock_client.create_job.return_value = mock_job
    mock_gcp_modules.BatchServiceClient.return_value = mock_client

    with patch("asyncio.to_thread", new=AsyncMock(return_value=mock_job)):
        result = await invoker._create_container_job(
            job_name="test-job",
            docker_image_uri="gcr.io/project/image:latest",
            cmd=["pixi", "run", "workflow"],
        )

        assert result == mock_job


@pytest.mark.asyncio
async def test_create_container_job_with_custom_resources(mock_gcp_modules) -> None:
    """Test _create_container_job with custom resource configuration."""
    from wt_invokers.cloud_batch import CloudBatchInvoker

    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = CloudBatchInvoker(matchspec=matchspec)

    mock_client = MagicMock()
    mock_job = MagicMock()
    mock_client.create_job.return_value = mock_job
    mock_gcp_modules.BatchServiceClient.return_value = mock_client

    with (
        patch("asyncio.to_thread", new=AsyncMock(return_value=mock_job)),
        patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "test-project"}),
    ):
        result = await invoker._create_container_job(
            job_name="test-job",
            docker_image_uri="gcr.io/project/image:latest",
            cmd=["pixi", "run", "workflow"],
            cpu_milli=16000,
            memory_mib=65536,
            timeout=600,
            machine_type="n1-standard-8",
        )

        assert result == mock_job


@pytest.mark.asyncio
async def test_create_container_job_with_gpu(mock_gcp_modules) -> None:
    """Test _create_container_job with GPU configuration."""
    from wt_invokers.cloud_batch import CloudBatchInvoker

    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = CloudBatchInvoker(matchspec=matchspec)

    mock_client = MagicMock()
    mock_job = MagicMock()
    mock_client.create_job.return_value = mock_job
    mock_gcp_modules.BatchServiceClient.return_value = mock_client

    with patch("asyncio.to_thread", new=AsyncMock(return_value=mock_job)):
        result = await invoker._create_container_job(
            job_name="test-job",
            docker_image_uri="gcr.io/project/image:latest",
            cmd=["pixi", "run", "workflow"],
            gpu_type="nvidia-tesla-v100",
            gpu_count=2,
        )

        assert result == mock_job
