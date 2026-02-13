"""Tests that verify GCP dependencies are available when installed."""

import pytest


def test_gcp_available_with_gcp_extra():
    """GCP_AVAILABLE is True when gcp extra is installed."""
    pytest.importorskip("google.cloud.batch_v1")
    from wt_invokers.cloud_batch import GCP_AVAILABLE

    assert GCP_AVAILABLE is True


def test_cloud_batch_invoker_instantiable():
    """CloudBatchInvoker can be instantiated when gcp extra is installed."""
    pytest.importorskip("google.cloud.batch_v1")
    from rattler import MatchSpec

    from wt_invokers.cloud_batch import CloudBatchInvoker

    invoker = CloudBatchInvoker(matchspec=MatchSpec("test-workflow>=1.0.0"))
    assert str(invoker.matchspec) == str(MatchSpec("test-workflow>=1.0.0"))
