"""Tests for wt_runner.testing module."""
# ruff: noqa: S108  # /tmp paths are test data, not real filesystem operations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from wt_runner.testing import Case, CaseRunner


class TestCase:
    """Tests for Case Pydantic model."""

    def test_basic_case_creation(self):
        """Test creating a Case with required fields."""
        case = Case(
            name="test case",
            description="A test case",
            params={"key": "value"},
        )
        assert case.name == "test case"
        assert case.description == "A test case"
        assert case.params == {"key": "value"}
        assert case.raises is False
        assert case.expected_status_code == 200

    def test_case_with_raises(self):
        """Test creating a Case that expects an error."""
        case = Case(
            name="error case",
            description="Should raise",
            params={},
            raises=True,
            expected_status_code=500,
        )
        assert case.raises is True
        assert case.expected_status_code == 500

    def test_case_missing_required_fields(self):
        """Test that missing required fields raises ValidationError."""
        with pytest.raises(ValidationError):
            Case(name="incomplete")  # type: ignore[call-arg]

    def test_case_serialization(self):
        """Test Case model serialization round-trip."""
        case = Case(
            name="round trip",
            description="Test serialization",
            params={"a": 1, "b": [2, 3]},
        )
        dumped = case.model_dump()
        restored = Case.model_validate(dumped)
        assert restored == case

    def test_case_default_values(self):
        """Test that defaults are correctly applied."""
        case = Case(name="defaults", description="check defaults", params={})
        assert case.raises is False
        assert case.expected_status_code == 200


class TestCaseRunner:
    """Tests for CaseRunner dataclass."""

    def test_instantiation_with_defaults(self):
        """Test CaseRunner can be instantiated with minimal args."""
        case = Case(name="test", description="desc", params={})
        runner = CaseRunner(
            execution_mode="sequential",
            mock_io=True,
            case=case,
            results_subdir=Path("/tmp/test-results"),
        )
        assert runner.execution_mode == "sequential"
        assert runner.mock_io is True
        assert runner.case is case
        assert runner.results_subdir == Path("/tmp/test-results")
        assert runner.traceparent is None
        assert runner.otel_exporter == "console"
        assert runner.otel_console_exporter_dst == "file"

    def test_instantiation_with_all_args(self):
        """Test CaseRunner with all arguments specified."""
        case = Case(name="test", description="desc", params={"x": 1})
        runner = CaseRunner(
            execution_mode="async",
            mock_io=False,
            case=case,
            results_subdir=Path("/tmp/results"),
            traceparent="00-abc-def-01",
            otel_exporter="gcp",
            otel_console_exporter_dst="stdout",
        )
        assert runner.execution_mode == "async"
        assert runner.mock_io is False
        assert runner.traceparent == "00-abc-def-01"
        assert runner.otel_exporter == "gcp"
        assert runner.otel_console_exporter_dst == "stdout"

    def test_run_app_success(self):
        """Test run_app with a mocked FastAPI TestClient."""
        case = Case(
            name="success",
            description="should succeed",
            params={"key": "value"},
            expected_status_code=200,
        )
        runner = CaseRunner(
            execution_mode="sequential",
            mock_io=True,
            case=case,
            results_subdir=Path("/tmp/results"),
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "ok"}
        mock_response.text = '{"result": "ok"}'

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        mock_app = MagicMock()

        with patch("wt_runner.testing.TestClient", return_value=mock_client):
            result = runner.run_app(mock_app)

        assert result == {"result": "ok"}

    def test_run_app_with_traceparent(self):
        """Test run_app includes traceparent header when set."""
        case = Case(name="trace", description="tracing", params={})
        runner = CaseRunner(
            execution_mode="sequential",
            mock_io=True,
            case=case,
            results_subdir=Path("/tmp/results"),
            traceparent="00-abc-def-01",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("wt_runner.testing.TestClient", return_value=mock_client):
            runner.run_app(MagicMock())

        # Verify traceparent was included in headers
        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["traceparent"] == "00-abc-def-01"
