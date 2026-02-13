"""Pytest configuration and fixtures for wt-runner tests."""

import pytest


@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    """Reset environment variables for each test.

    This prevents tests from interfering with each other through
    environment variable modifications.
    """
    # Clear any OTEL-related environment variables
    monkeypatch.delenv("ECOSCOPE_WORKFLOWS_OTEL_EXPORTER", raising=False)
    monkeypatch.delenv("ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_DST", raising=False)
    monkeypatch.delenv(
        "ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_FILE_DST_TARGET_DIR", raising=False
    )
    monkeypatch.delenv("ECOSCOPE_WORKFLOWS_MATCHSPEC_OVERRIDE", raising=False)
