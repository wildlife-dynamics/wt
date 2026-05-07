"""Tests that verify GCP dependencies are available when installed."""

import pytest


def test_gcp_available_with_gcp_extra():
    """GCP_AVAILABLE is True when gcp extra is installed."""
    pytest.importorskip("google.cloud.batch_v1")
    # optional-dep presence test
    from wt_invokers.cloud_batch import GCP_AVAILABLE  # noqa: PLC0415

    assert GCP_AVAILABLE is True


def test_cloud_batch_invoker_instantiable():
    """CloudBatchInvoker can be instantiated when gcp extra is installed."""
    pytest.importorskip("google.cloud.batch_v1")
    # optional-dep presence test
    from rattler import MatchSpec  # noqa: PLC0415

    from wt_invokers.cloud_batch import CloudBatchInvoker  # noqa: PLC0415

    invoker = CloudBatchInvoker(matchspec=MatchSpec("test-workflow>=1.0.0"))
    assert str(invoker.matchspec) == str(MatchSpec("test-workflow>=1.0.0"))
