"""wt-invokers: Abstract invoker interface and implementations.

This package provides invokers for executing workflows in different
environments (local subprocess, Google Cloud Batch, etc.).

The main abstractions are:
- AbstractInvoker: Base class for all invokers
- LocalSubprocessInvoker: Run workflows in local subprocesses
- CloudBatchInvoker: Run workflows on Google Cloud Batch (requires gcp extras)

Examples:
    Using the local subprocess invoker:

    >>> import asyncio
    >>> from rattler import MatchSpec
    >>> from wt_invokers import LocalSubprocessInvoker
    >>>
    >>> invoker = LocalSubprocessInvoker(
    ...     matchspec=MatchSpec("my-workflow>=1.0.0")
    ... )
    >>> # asyncio.run(invoker.run(
    >>> #     workflow_run_id="run-123",
    >>> #     config_text="param: value",
    >>> #     results_url="file:///tmp/results",
    >>> #     execution_mode="sequential",
    >>> #     mock_io=False
    >>> # ))
    >>> # exit_code = asyncio.run(invoker.wait())

    Using the cloud batch invoker:

    >>> from wt_invokers import CloudBatchInvoker
    >>> invoker = CloudBatchInvoker(
    ...     matchspec=MatchSpec("my-workflow>=1.0.0")
    ... )
    >>> # asyncio.run(invoker.run(
    >>> #     workflow_run_id="run-456",
    >>> #     config_text="param: value",
    >>> #     results_url="gs://bucket/results",
    >>> #     execution_mode="sequential",
    >>> #     mock_io=False,
    >>> #     docker_image_uri="gcr.io/project/image:latest"
    >>> # ))
"""

from __future__ import annotations

from wt_invokers.abstract import AbstractInvoker
from wt_invokers.cloud_batch import CloudBatchInvoker
from wt_invokers.cloud_run_jobs import CloudRunJobsSandboxInvoker
from wt_invokers.exceptions import (
    InstallationError,
    InvocationTimeoutError,
    InvokerError,
)
from wt_invokers.local import LocalSubprocessInvoker
from wt_invokers.mixins import (
    PixiUnpackMixin,
    RetryableHTTPError,
    UploadResultsArchiveMixin,
)
from wt_invokers.sandbox import SandboxInvoker

try:
    from wt_invokers._version import __version__
except ImportError:
    __version__ = "0.0.0+unknown"

__all__ = [
    "AbstractInvoker",
    "LocalSubprocessInvoker",
    "CloudBatchInvoker",
    "CloudRunJobsSandboxInvoker",
    "SandboxInvoker",
    "PixiUnpackMixin",
    "UploadResultsArchiveMixin",
    "RetryableHTTPError",
    "InvokerError",
    "InvocationTimeoutError",
    "InstallationError",
    "__version__",
]
