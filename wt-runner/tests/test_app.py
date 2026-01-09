"""Tests for FastAPI application endpoints."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from rattler import MatchSpec

from wt_runner.app import (
    app,
    prepare_invoker_parameters,
    resolve_matchspec,
    resolve_results_url,
)


@pytest.fixture
def client() -> TestClient:
    """Create test client for FastAPI app.

    Returns:
        TestClient instance
    """
    return TestClient(app)


def test_health_check(client: TestClient):
    """Test health check endpoint returns ok status."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_resolve_matchspec_with_query_param():
    """Test matchspec resolution with query parameter."""
    matchspec = resolve_matchspec(matchspec="numpy>=1.20")
    assert isinstance(matchspec, MatchSpec)
    assert str(matchspec) == "numpy >=1.20"


def test_resolve_matchspec_without_param_raises():
    """Test matchspec resolution raises without parameter."""
    with pytest.raises(ValueError, match="Query param `matchspec` is required"):
        resolve_matchspec(matchspec=None)


def test_resolve_results_url_with_scheme():
    """Test results URL resolution with scheme."""
    url = "gs://bucket/results"
    result = resolve_results_url(results_url=url)
    assert result == url


def test_resolve_results_url_with_absolute_path(tmp_path):
    """Test results URL resolution with absolute local path."""
    path = tmp_path / "results"
    path.mkdir()
    result = resolve_results_url(results_url=str(path))
    assert result.startswith("file://")


def test_resolve_results_url_with_relative_path_raises():
    """Test results URL resolution raises with relative path."""
    with pytest.raises(
        ValueError, match="Results URL must be an absolute local path or a URL with scheme"
    ):
        resolve_results_url(results_url="relative/path")


def test_prepare_invoker_parameters():
    """Test invoker parameter preparation from command payload."""
    pytest.importorskip("ecoscope_eda_core", reason="ecoscope_eda_core not installed")
    from ecoscope_eda_core.messages.commands import RunWorkflowParams

    payload = RunWorkflowParams(
        match_spec="test-workflow>=1.0",
        invoker_type="BlockingLocalSubprocessInvoker",
        invoker_kwargs={
            "workflow_run_id": "test-123",
            "results_url": "gs://bucket/results",
            "params": {"key": "value"},
            "data_connections_env_vars": {"SECRET": "value"},
            "trace_context": {"traceparent": "00-123-456-01"},
            "execution_mode": "sequential",
            "mock_io": True,
        },
    )

    invoker_params, trace_context = prepare_invoker_parameters(payload)

    assert invoker_params["workflow_run_id"] == "test-123"
    assert invoker_params["results_url"] == "gs://bucket/results"
    assert invoker_params["execution_mode"] == "sequential"
    assert invoker_params["mock_io"] is True
    assert "config_text" in invoker_params
    assert invoker_params["extra_env"] == {"SECRET": "value"}
    assert trace_context == {"traceparent": "00-123-456-01"}


def test_prepare_invoker_parameters_with_async_mode():
    """Test invoker parameter preparation with async execution mode."""
    pytest.importorskip("ecoscope_eda_core", reason="ecoscope_eda_core not installed")
    from ecoscope_eda_core.messages.commands import RunWorkflowParams

    payload = RunWorkflowParams(
        match_spec="test-workflow>=1.0",
        invoker_type="BlockingLocalSubprocessInvoker",
        invoker_kwargs={
            "workflow_run_id": "test-123",
            "results_url": "gs://bucket/results",
            "params": {"key": "value"},
            "execution_mode": "async",
            "mock_io": False,
        },
    )

    invoker_params, _ = prepare_invoker_parameters(payload)

    assert invoker_params["execution_mode"] == "async"
    assert "lithops_config_text" in invoker_params


@pytest.mark.asyncio
async def test_extract_payload_from_pubsub_request():
    """Test payload extraction from Pub/Sub request."""
    pytest.importorskip("ecoscope_eda_core", reason="ecoscope_eda_core not installed")
    import base64

    from fastapi import Request

    from wt_runner.app import extract_payload_from_pubsub_request

    # Create mock request with Pub/Sub message format
    payload_data = {
        "match_spec": "test-workflow>=1.0",
        "invoker_type": "BlockingLocalSubprocessInvoker",
        "invoker_kwargs": {
            "workflow_run_id": "test-123",
            "results_url": "gs://bucket/results",
            "params": {},
        },
    }

    message = {
        "message": {
            "data": base64.b64encode(
                json.dumps({"type": "RunWorkflow", "payload": payload_data}).encode()
            ).decode()
        }
    }

    mock_request = MagicMock(spec=Request)
    mock_request.json = AsyncMock(return_value=message)

    result = await extract_payload_from_pubsub_request(mock_request)

    assert result.match_spec == "test-workflow>=1.0"
    assert result.invoker_type == "BlockingLocalSubprocessInvoker"


def test_is_422_with_valid_error():
    """Test _is_422 identifies validation errors correctly."""
    from wt_runner.app import _is_422

    error_data = [
        {
            "type": "missing",
            "loc": ["body", "params"],
            "msg": "Field required",
            "input": {},
            "url": "https://errors.pydantic.dev/...",
        }
    ]

    assert _is_422(error_data) is True


def test_is_422_with_invalid_data():
    """Test _is_422 returns False for non-error data."""
    from wt_runner.app import _is_422

    assert _is_422([{"result": "success"}]) == False
    assert _is_422({"error": "message"}) == False
    assert _is_422([]) == False


@pytest.mark.asyncio
async def test_upload_error_to_gcs():
    """Test error upload to GCS."""
    pytest.importorskip("obstore", reason="obstore not installed")
    from wt_runner.app import upload_error_to_gcs

    error_details = {"error": "Test error", "trace": "Stack trace"}
    results_url = "gs://test-bucket/results"

    with patch("wt_runner.app.obstore") as mock_obstore_module:
        with patch("wt_runner.app.HAS_OBSTORE", True):
            mock_store = AsyncMock()
            mock_obstore_module.store.from_url.return_value = mock_store

            await upload_error_to_gcs(error_details, results_url)

            mock_obstore_module.store.from_url.assert_called_once_with(results_url)
            mock_store.put_async.assert_called_once()
            call_args = mock_store.put_async.call_args
            assert call_args[0][0] == "result.json"
            assert json.loads(call_args[0][1].decode()) == error_details


@pytest.mark.asyncio
async def test_get_metadata_attribute_success():
    """Test successful metadata attribute retrieval."""
    from wt_runner.app import _get_metadata_attribute

    mock_invoker = AsyncMock()
    mock_invoker.check_output = AsyncMock(return_value='{"schema": "data"}')

    result = await _get_metadata_attribute("rjsf", mock_invoker)

    assert result == {"schema": "data"}
    mock_invoker.check_output.assert_called_once_with(["get", "rjsf"])


@pytest.mark.asyncio
async def test_get_metadata_attribute_no_output():
    """Test metadata attribute retrieval with no output raises."""
    from wt_runner.app import _get_metadata_attribute

    mock_invoker = AsyncMock()
    mock_invoker.check_output = AsyncMock(return_value=None)

    with pytest.raises(RuntimeError, match="Failed to get rjsf"):
        await _get_metadata_attribute("rjsf", mock_invoker)


@pytest.mark.asyncio
async def test_get_metadata_attribute_invalid_json():
    """Test metadata attribute retrieval with invalid JSON raises."""
    from wt_runner.app import _get_metadata_attribute

    mock_invoker = AsyncMock()
    mock_invoker.check_output = AsyncMock(return_value="not json")

    with pytest.raises(RuntimeError, match="Failed to parse rjsf"):
        await _get_metadata_attribute("rjsf", mock_invoker)


@pytest.mark.asyncio
async def test_convert_success():
    """Test successful conversion between formats."""
    from wt_runner.app import _convert

    mock_invoker = AsyncMock()
    mock_invoker.check_output = AsyncMock(return_value='{"converted": "data"}')

    result = await _convert("formdata", "params", '{"input": "data"}', mock_invoker)

    assert result == {"converted": "data"}
    mock_invoker.check_output.assert_called_once_with(
        ["convert", "--from", "formdata", "--to", "params"], stdin='{"input": "data"}'
    )


@pytest.mark.asyncio
async def test_convert_no_output():
    """Test conversion with no output raises."""
    from wt_runner.app import _convert

    mock_invoker = AsyncMock()
    mock_invoker.check_output = AsyncMock(return_value=None)

    with pytest.raises(RuntimeError, match="Failed to convert"):
        await _convert("formdata", "params", '{"input": "data"}', mock_invoker)


@pytest.mark.asyncio
async def test_convert_invalid_json():
    """Test conversion with invalid JSON output raises."""
    from wt_runner.app import _convert

    mock_invoker = AsyncMock()
    mock_invoker.check_output = AsyncMock(return_value="not json")

    with pytest.raises(RuntimeError, match="Failed to parse"):
        await _convert("formdata", "params", '{"input": "data"}', mock_invoker)
