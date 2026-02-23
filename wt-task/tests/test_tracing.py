"""Tests that verify GCP tracing dependencies are available when installed."""

import pytest


def test_tracing_available_with_gcp_extra():
    """TRACING_AVAILABLE is True when gcp extra is installed."""
    pytest.importorskip("opentelemetry")
    from wt_task.tracing._config import TRACING_AVAILABLE

    assert TRACING_AVAILABLE is True


def test_cloud_trace_exporter_importable():
    """CloudTraceSpanExporter can be imported when gcp extra is installed."""
    pytest.importorskip("opentelemetry.exporter.cloud_trace")
    from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

    assert CloudTraceSpanExporter is not None
