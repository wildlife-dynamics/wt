"""Tests that verify GCP dependencies are available when installed."""

import pytest


def test_has_gcp_exporter_with_gcp_extra():
    """HAS_GCP_EXPORTER is True when gcp extra is installed."""
    pytest.importorskip("opentelemetry.exporter.cloud_trace")
    from wt_runner.tracing import HAS_GCP_EXPORTER  # noqa: PLC0415  # optional-dep presence test

    assert HAS_GCP_EXPORTER is True
