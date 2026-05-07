"""Tests that verify wt-runner-gcp dependencies are importable."""


def test_has_gcp_exporter():
    """HAS_GCP_EXPORTER is True when wt-runner-gcp is installed."""
    import opentelemetry.exporter.cloud_trace  # noqa: F401, PLC0415  # optional-dep presence test
    from wt_runner.tracing import HAS_GCP_EXPORTER  # noqa: PLC0415  # optional-dep presence test

    assert HAS_GCP_EXPORTER is True


def test_has_ecoscope():
    """HAS_ECOSCOPE is True when wt-runner-gcp is installed."""
    import ecoscope_eda_core  # noqa: F401, PLC0415  # optional-dep presence test
    from wt_runner.app import HAS_ECOSCOPE  # noqa: PLC0415  # optional-dep presence test

    assert HAS_ECOSCOPE is True
