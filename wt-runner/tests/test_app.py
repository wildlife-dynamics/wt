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
        command="run",
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
        command="run",
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
        "command": "run",
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


def test_to_fastapi_422_translates_jsonschema_errors():
    """Test _to_fastapi_422 maps jsonschema-native errors to FastAPI shape."""
    from wt_runner.app import _to_fastapi_422

    errors = [
        {
            "message": "42 is not of type 'string'",
            "path": ["fetch_data", "since"],
            "schema_path": ["properties", "fetch_data", "properties", "since", "type"],
            "validator": "type",
        }
    ]
    out = _to_fastapi_422(errors)
    assert out == [
        {
            "loc": ["fetch_data", "since"],
            "msg": "42 is not of type 'string'",
            "type": "type",
        }
    ]


def test_to_fastapi_422_handles_empty_path():
    """Test _to_fastapi_422 with no path."""
    from wt_runner.app import _to_fastapi_422

    out = _to_fastapi_422([{"message": "boom", "path": [], "validator": "required"}])
    assert out == [{"loc": [], "msg": "boom", "type": "required"}]


@pytest.mark.asyncio
async def test_upload_error_to_gcs():
    """Test error upload to GCS."""
    import sys

    from wt_runner.app import upload_error_to_gcs

    # Get the actual module from sys.modules to avoid namespace collision
    # between wt_runner.app (module) and wt_runner.app (FastAPI instance
    # imported in __init__.py)
    app_module = sys.modules["wt_runner.app"]

    error_details = {"error": "Test error", "trace": "Stack trace"}
    results_url = "gs://test-bucket/results"

    with patch.object(app_module, "obstore") as mock_obstore_module:
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
    """Test successful conversion: envelope ``{"result": ...}`` is unwrapped."""
    from wt_runner.app import _convert

    mock_invoker = AsyncMock()
    mock_invoker.check_output = AsyncMock(return_value='{"result": {"converted": "data"}}')

    result = await _convert("formdata", "params", '{"input": "data"}', mock_invoker)

    assert result == {"converted": "data"}
    mock_invoker.check_output.assert_called_once_with(
        ["convert", "--from", "formdata", "--to", "params"], stdin='{"input": "data"}'
    )


@pytest.mark.asyncio
async def test_convert_validation_error_envelope():
    """Test ``{"validation_errors": [...]}`` envelope raises _ConvertValidationError."""
    from wt_runner.app import _convert, _ConvertValidationError

    payload = {
        "validation_errors": [
            {"message": "boom", "path": ["x"], "schema_path": [], "validator": "type"}
        ]
    }
    mock_invoker = AsyncMock()
    mock_invoker.check_output = AsyncMock(return_value=json.dumps(payload))

    with pytest.raises(_ConvertValidationError) as exc_info:
        await _convert("formdata", "params", '{"input": "data"}', mock_invoker)
    assert exc_info.value.errors == payload["validation_errors"]


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


@pytest.mark.asyncio
async def test_convert_unexpected_envelope():
    """Test envelope missing both keys raises."""
    from wt_runner.app import _convert

    mock_invoker = AsyncMock()
    mock_invoker.check_output = AsyncMock(return_value='{"unknown": "key"}')

    with pytest.raises(RuntimeError, match="Unexpected convert envelope"):
        await _convert("formdata", "params", '{"input": "data"}', mock_invoker)
