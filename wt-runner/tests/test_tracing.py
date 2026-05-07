"""Tests for OpenTelemetry tracing functionality."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wt_runner.tracing import (
    attach_context,
    build_context_headers,
    configure_tracer,
    make_otel_console_exporter_file_dst_kws,
    otel_span_formatter,
)


def test_otel_span_formatter():
    """Test OTEL span formatter produces unindented JSON."""
    mock_span = MagicMock()
    mock_span.to_json.return_value = '{"span": "data"}'

    result = otel_span_formatter(mock_span)

    assert result.startswith('{"span": "data"}')
    assert result.endswith("\n")
    mock_span.to_json.assert_called_once_with(indent=None)


def test_make_otel_console_exporter_file_dst_kws_creates_directory():
    """Test console exporter file kwargs creates target directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        target_dir = Path(tmpdir) / "new_dir"
        assert not target_dir.exists()

        result = make_otel_console_exporter_file_dst_kws(target_dir)

        assert target_dir.exists()
        assert target_dir.is_dir()
        assert "out" in result
        assert "formatter" in result
        assert result["formatter"] == otel_span_formatter

        # Clean up opened file
        result["out"].close()


def test_make_otel_console_exporter_file_dst_kws_existing_directory():
    """Test console exporter file kwargs works with existing directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        target_dir = Path(tmpdir)
        assert target_dir.exists()

        result = make_otel_console_exporter_file_dst_kws(target_dir)

        assert "out" in result
        assert "formatter" in result
        traces_file = target_dir / "otel_traces.jsonl"
        assert traces_file.exists()

        # Clean up opened file
        result["out"].close()


def test_make_otel_console_exporter_file_dst_kws_raises_if_not_directory():
    """Test console exporter file kwargs raises if target exists but is not directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a file at the target path
        target_path = Path(tmpdir) / "not_a_dir"
        target_path.touch()

        with pytest.raises(ValueError, match="exists but is not a directory"):
            make_otel_console_exporter_file_dst_kws(target_path)


def test_configure_tracer_no_exporter():
    """Test tracer configuration without exporter."""
    with patch("wt_runner.tracing.trace.set_tracer_provider") as mock_set_provider:
        configure_tracer(name="test-service", version="1.0.0", exporter=None)

        mock_set_provider.assert_called_once()
        provider = mock_set_provider.call_args[0][0]
        assert provider.resource.attributes["service.name"] == "test-service"
        assert provider.resource.attributes["service.version"] == "1.0.0"


def test_configure_tracer_with_console_exporter():
    """Test tracer configuration with console exporter."""
    with (
        patch("wt_runner.tracing.trace.set_tracer_provider") as mock_set_provider,
        patch("wt_runner.tracing.ConsoleSpanExporter") as mock_exporter,
    ):
        configure_tracer(
            name="test-service", version="1.0.0", exporter="console", exporter_kws={}
        )

        mock_exporter.assert_called_once_with()
        mock_set_provider.assert_called_once()


def test_configure_tracer_with_gcp_exporter():
    """Test tracer configuration with GCP exporter."""
    with (
        patch("wt_runner.tracing.trace.set_tracer_provider") as mock_set_provider,
        patch("wt_runner.tracing.HAS_GCP_EXPORTER", True),
        patch("wt_runner.tracing.CloudTraceSpanExporter") as mock_exporter,
    ):
        configure_tracer(
            name="test-service", version="1.0.0", exporter="gcp", exporter_kws={}
        )

        mock_exporter.assert_called_once_with()
        mock_set_provider.assert_called_once()


def test_configure_tracer_with_unknown_exporter_raises():
    """Test tracer configuration raises with unknown exporter."""
    with pytest.raises(ValueError, match="Unknown exporter: unknown"):
        configure_tracer(name="test-service", exporter="unknown")


def test_build_context_headers():
    """Test building trace context headers from current context."""
    with patch("wt_runner.tracing.propagate.inject") as mock_inject:

        def inject_side_effect(headers):
            headers["traceparent"] = "00-test-trace-id-span-id-01"

        mock_inject.side_effect = inject_side_effect

        result = build_context_headers()

        assert "traceparent" in result
        assert result["traceparent"] == "00-test-trace-id-span-id-01"
        mock_inject.assert_called_once()


def test_attach_context_with_traceparent_only():
    """Test attaching context with only traceparent."""
    with (
        patch("wt_runner.tracing.propagate.extract") as mock_extract,
        patch("wt_runner.tracing.context.attach") as mock_attach,
    ):
        mock_ctx = MagicMock()
        mock_extract.return_value = mock_ctx

        attach_context(traceparent="00-test-trace-id-span-id-01")

        mock_extract.assert_called_once_with(
            carrier={"traceparent": "00-test-trace-id-span-id-01"}
        )
        mock_attach.assert_called_once_with(mock_ctx)


def test_attach_context_with_traceparent_and_tracestate():
    """Test attaching context with both traceparent and tracestate."""
    with (
        patch("wt_runner.tracing.propagate.extract") as mock_extract,
        patch("wt_runner.tracing.context.attach") as mock_attach,
    ):
        mock_ctx = MagicMock()
        mock_extract.return_value = mock_ctx

        attach_context(traceparent="00-test-trace-id-span-id-01", tracestate="vendor=value")

        mock_extract.assert_called_once_with(
            carrier={
                "traceparent": "00-test-trace-id-span-id-01",
                "tracestate": "vendor=value",
            }
        )
        mock_attach.assert_called_once_with(mock_ctx)
