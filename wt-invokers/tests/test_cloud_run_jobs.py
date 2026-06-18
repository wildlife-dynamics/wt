"""Tests for CloudRunJobsSandboxInvoker (proxy).

Follows the ``test_cloud_batch.py`` mock pattern: ``google.cloud.run_v2`` is
replaced in ``sys.modules`` so the invoker can be imported and instantiated
without the real SDK.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rattler import MatchSpec

import wt_invokers.cloud_run_jobs as module
from wt_invokers.cloud_run_jobs import CloudRunJobsSandboxInvoker

# A syntactically valid digest; the proxy validates format and forwards it
# verbatim to the sandbox CLI, so the exact value is never hashed here.
_VALID_DIGEST = "sha256:" + "a" * 64


@pytest.fixture
def mock_run_modules(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch the Cloud Run symbols on wt_invokers.cloud_run_jobs.

    Rather than manipulating sys.modules (which can interact badly with other
    third-party libraries' module caches), we directly patch the symbols that
    the invoker module references. ``CLOUD_RUN_AVAILABLE`` is also set to True
    so instantiation succeeds.
    """
    mock_jobs_client_cls = MagicMock()
    mock_run_job_request = MagicMock()
    mock_env_var = MagicMock()

    monkeypatch.setattr(module, "CLOUD_RUN_AVAILABLE", True)
    monkeypatch.setattr(module, "JobsAsyncClient", mock_jobs_client_cls, raising=False)
    monkeypatch.setattr(module, "RunJobRequest", mock_run_job_request, raising=False)
    monkeypatch.setattr(module, "EnvVar", mock_env_var, raising=False)

    return MagicMock(
        JobsAsyncClient=mock_jobs_client_cls,
        RunJobRequest=mock_run_job_request,
        EnvVar=mock_env_var,
    )


def test_init_succeeds_when_available(mock_run_modules: Any) -> None:
    inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    assert inv.matchspec.name.normalized == "w"


def test_init_fails_without_sdk() -> None:
    original = module.CLOUD_RUN_AVAILABLE
    module.CLOUD_RUN_AVAILABLE = False
    try:
        with pytest.raises(ImportError, match="Google Cloud Run"):
            CloudRunJobsSandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    finally:
        module.CLOUD_RUN_AVAILABLE = original


@pytest.mark.asyncio
async def test_is_installed_returns_true(mock_run_modules: Any) -> None:
    inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    assert await inv.is_installed() is True


@pytest.mark.asyncio
async def test_install_raises(mock_run_modules: Any) -> None:
    inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    with pytest.raises(NotImplementedError):
        await inv.install()


def test_is_waitable_false(mock_run_modules: Any) -> None:
    inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    assert inv.is_waitable is False


@pytest.mark.asyncio
async def test_wait_returns_zero(mock_run_modules: Any) -> None:
    inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    assert await inv.wait() == 0


@pytest.mark.asyncio
async def test_run_triggers_job_with_correct_args(mock_run_modules: Any) -> None:
    # MagicMock(name=...) sets the mock's own ``_mock_name``, NOT its
    # ``.name`` attribute. Assign the attribute explicitly so the invoker's
    # ``operation.metadata.name`` path returns a real resource-name string.
    op = MagicMock()
    op.metadata.name = (
        "projects/my-proj/locations/us-central1/jobs/sandbox-job/executions/exec-1"
    )
    fake_client = MagicMock()
    fake_client.get_job = AsyncMock()
    fake_client.run_job = AsyncMock(return_value=op)

    with patch(
        "wt_invokers.cloud_run_jobs.JobsAsyncClient",
        return_value=fake_client,
    ):
        inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("my-wf>=1.0.0"))
        await inv.run(
            workflow_run_id="run-1",
            config_text="k: v",
            results_url="file:///results",
            execution_mode="sequential",
            mock_io=False,
            environment_tar_url="https://x/env.tar",
            environment_tar_digest=_VALID_DIGEST,
            results_upload_url="https://x/out",
            job_name="sandbox-job",
            project_id="my-proj",
            region="us-central1",
        )
        await inv.wait()

    fake_client.get_job.assert_awaited_once()
    get_call = fake_client.get_job.await_args
    assert (
        get_call.kwargs["name"]
        == "projects/my-proj/locations/us-central1/jobs/sandbox-job"
    )
    fake_client.run_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_defaults_region_to_us_central1(mock_run_modules: Any) -> None:
    op = MagicMock()
    op.metadata.name = "projects/p/locations/us-central1/jobs/j/executions/x"
    fake_client = MagicMock()
    fake_client.get_job = AsyncMock()
    fake_client.run_job = AsyncMock(return_value=op)

    with patch(
        "wt_invokers.cloud_run_jobs.JobsAsyncClient",
        return_value=fake_client,
    ):
        inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
        await inv.run(
            workflow_run_id="r",
            config_text="k: v",
            results_url="file:///r",
            execution_mode="sequential",
            mock_io=False,
            environment_tar_url="https://x/e.tar",
            environment_tar_digest=_VALID_DIGEST,
            results_upload_url="https://x/o",
            job_name="j",
            project_id="p",
        )
        await inv.wait()

    fq = fake_client.get_job.await_args.kwargs["name"]
    assert fq == "projects/p/locations/us-central1/jobs/j"


@pytest.mark.asyncio
async def test_run_missing_required_kwarg_raises(mock_run_modules: Any) -> None:
    inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    with pytest.raises(TypeError):
        # missing required kwargs
        await inv.run(
            workflow_run_id="r",
            config_text="k: v",
            results_url="file:///r",
            execution_mode="sequential",
            mock_io=False,
        )


@pytest.mark.asyncio
async def test_ensure_job_exists_raises_clear_error_on_missing(
    mock_run_modules: Any,
) -> None:
    fake_client = MagicMock()
    fake_client.get_job = AsyncMock(side_effect=Exception("NOT FOUND"))

    with patch(
        "wt_invokers.cloud_run_jobs.JobsAsyncClient",
        return_value=fake_client,
    ):
        inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
        with pytest.raises(
            RuntimeError,
            match=r"Pre-deployed Cloud Run Job .* is not available \(Exception\)",
        ):
            await inv.run(
                workflow_run_id="r",
                config_text="k: v",
                results_url="file:///r",
                execution_mode="sequential",
                mock_io=False,
                environment_tar_url="https://x/e.tar",
                environment_tar_digest=_VALID_DIGEST,
                results_upload_url="https://x/o",
                job_name="j",
                project_id="p",
            )


class FakeContainerOverride:
    def __init__(self) -> None:
        self.args: list[str] = []
        self.env: list[Any] = []


class FakeOverrides:
    def __init__(self) -> None:
        self.container_overrides: list[Any] = []


def _make_fakes(captured: dict[str, Any]) -> tuple[Any, type]:
    """Build a fake JobsAsyncClient and RunJobRequest that record into ``captured``."""
    fake_client = MagicMock()
    fake_client.get_job = AsyncMock()

    class FakeRunJobRequest:
        class Overrides:
            def __new__(cls) -> Any:
                return FakeOverrides()

            class ContainerOverride:
                def __new__(cls) -> Any:
                    return FakeContainerOverride()

        def __init__(self, name: str, overrides: Any) -> None:
            captured["name"] = name
            captured["overrides"] = overrides

    async def fake_run_job(request: Any) -> Any:
        captured["request"] = request
        op = MagicMock()
        op.metadata = MagicMock()
        op.metadata.name = "x"
        return op

    fake_client.run_job = fake_run_job
    return fake_client, FakeRunJobRequest


@pytest.mark.asyncio
async def test_run_builds_container_args(mock_run_modules: Any) -> None:
    """Container args forwarded to the sandbox CLI include all workflow inputs."""
    captured: dict[str, Any] = {}
    fake_client, fake_request_cls = _make_fakes(captured)

    with (
        patch("wt_invokers.cloud_run_jobs.JobsAsyncClient", return_value=fake_client),
        patch("wt_invokers.cloud_run_jobs.RunJobRequest", fake_request_cls),
        patch("wt_invokers.cloud_run_jobs.EnvVar", MagicMock),
    ):
        inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("my-wf>=1.0.0"))
        await inv.run(
            workflow_run_id="run-42",
            config_text="k: v",
            results_url="file:///results",
            execution_mode="sequential",
            mock_io=True,
            otel_exporter="http://otel",
            otel_console_exporter_dst="stdout",
            extra_env={"X": "1"},
            environment_tar_url="https://e/env.tar",
            environment_tar_digest=_VALID_DIGEST,
            results_upload_url="https://e/out",
            job_name="j",
            project_id="p",
        )
        await inv.wait()

    assert captured["name"] == "projects/p/locations/us-central1/jobs/j"
    override = captured["overrides"]
    assert len(override.container_overrides) == 1
    args = override.container_overrides[0].args
    assert "--matchspec" in args
    assert "--workflow-run-id" in args
    assert "run-42" in args
    assert "--environment-tar-url" in args
    assert "https://e/env.tar" in args
    assert "--environment-tar-digest" in args
    assert _VALID_DIGEST in args
    # The digest immediately follows its flag in the argv.
    assert args[args.index("--environment-tar-digest") + 1] == _VALID_DIGEST
    assert "--results-upload-url" in args
    assert "https://e/out" in args
    assert "--results-url" in args
    assert "file:///results" in args
    assert "--mock-io" in args
    assert "--otel-exporter" in args
    assert "http://otel" in args
    assert "--otel-console-exporter-dst" in args
    assert "stdout" in args
    assert "--dangerously-skip-results-archive-upload" not in args


@pytest.mark.asyncio
async def test_run_skip_upload_builds_container_args(mock_run_modules: Any) -> None:
    """Skipping the upload forwards the skip flag and omits --results-upload-url."""
    captured: dict[str, Any] = {}
    fake_client, fake_request_cls = _make_fakes(captured)

    with (
        patch("wt_invokers.cloud_run_jobs.JobsAsyncClient", return_value=fake_client),
        patch("wt_invokers.cloud_run_jobs.RunJobRequest", fake_request_cls),
        patch("wt_invokers.cloud_run_jobs.EnvVar", MagicMock),
    ):
        inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("my-wf>=1.0.0"))
        await inv.run(
            workflow_run_id="run-42",
            config_text="k: v",
            results_url="gs://bucket/results",
            execution_mode="sequential",
            mock_io=False,
            environment_tar_url="https://e/env.tar",
            environment_tar_digest=_VALID_DIGEST,
            skip_results_archive_upload=True,
            job_name="j",
            project_id="p",
        )
        await inv.wait()

    args = captured["overrides"].container_overrides[0].args
    assert "--dangerously-skip-results-archive-upload" in args
    assert "--results-upload-url" not in args
    assert "--results-url" in args
    assert "gs://bucket/results" in args


@pytest.mark.asyncio
async def test_run_skip_upload_with_upload_url_raises(mock_run_modules: Any) -> None:
    inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    with pytest.raises(ValueError, match="mutually exclusive"):
        await inv.run(
            workflow_run_id="r",
            config_text="k: v",
            results_url="gs://bucket/results",
            execution_mode="sequential",
            mock_io=False,
            environment_tar_url="https://x/e.tar",
            environment_tar_digest=_VALID_DIGEST,
            results_upload_url="https://x/o",
            skip_results_archive_upload=True,
            job_name="j",
            project_id="p",
        )


@pytest.mark.asyncio
async def test_run_missing_upload_url_without_skip_raises(
    mock_run_modules: Any,
) -> None:
    """results_upload_url stays effectively required when not skipping."""
    inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    with pytest.raises(ValueError, match="results_upload_url is required"):
        await inv.run(
            workflow_run_id="r",
            config_text="k: v",
            results_url="file:///r",
            execution_mode="sequential",
            mock_io=False,
            environment_tar_url="https://x/e.tar",
            environment_tar_digest=_VALID_DIGEST,
            job_name="j",
            project_id="p",
        )


@pytest.mark.asyncio
async def test_run_skip_upload_with_default_results_url_raises(
    mock_run_modules: Any,
) -> None:
    """The sandbox staging default results_url is meaningless when not uploading."""
    inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    with pytest.raises(ValueError, match="real destination"):
        await inv.run(
            workflow_run_id="r",
            config_text="k: v",
            results_url="file:///results",
            execution_mode="sequential",
            mock_io=False,
            environment_tar_url="https://x/e.tar",
            environment_tar_digest=_VALID_DIGEST,
            skip_results_archive_upload=True,
            job_name="j",
            project_id="p",
        )


@pytest.mark.asyncio
async def test_run_bad_digest_format_raises_eagerly(mock_run_modules: Any) -> None:
    """A malformed environment_tar_digest is rejected before the job is submitted."""
    inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    with pytest.raises(ValueError, match="environment_tar_digest must be"):
        await inv.run(
            workflow_run_id="r",
            config_text="k: v",
            results_url="file:///r",
            execution_mode="sequential",
            mock_io=False,
            environment_tar_url="https://x/e.tar",
            environment_tar_digest="not-a-valid-digest",
            results_upload_url="https://x/o",
            job_name="j",
            project_id="p",
        )


@pytest.mark.asyncio
async def test_run_missing_digest_kwarg_raises(mock_run_modules: Any) -> None:
    """environment_tar_digest is a required keyword-only argument."""
    inv = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    with pytest.raises(TypeError):
        await inv.run(
            workflow_run_id="r",
            config_text="k: v",
            results_url="file:///r",
            execution_mode="sequential",
            mock_io=False,
            environment_tar_url="https://x/e.tar",
            results_upload_url="https://x/o",
            job_name="j",
            project_id="p",
        )
