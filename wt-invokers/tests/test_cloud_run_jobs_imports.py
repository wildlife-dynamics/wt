"""Tests that verify Cloud Run dependencies are available when installed."""

from __future__ import annotations

import pytest


def test_cloud_run_available_with_extra() -> None:
    pytest.importorskip("google.cloud.run_v2")
    from wt_invokers.cloud_run_jobs import CLOUD_RUN_AVAILABLE

    assert CLOUD_RUN_AVAILABLE is True


def test_cloud_run_jobs_invoker_instantiable() -> None:
    pytest.importorskip("google.cloud.run_v2")
    from rattler import MatchSpec

    from wt_invokers.cloud_run_jobs import CloudRunJobsSandboxInvoker

    invoker = CloudRunJobsSandboxInvoker(matchspec=MatchSpec("test>=1.0.0"))
    assert str(invoker.matchspec) == str(MatchSpec("test>=1.0.0"))
