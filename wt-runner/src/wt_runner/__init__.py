"""wt-runner: FastAPI application for workflow execution.

This package provides a FastAPI web service for executing workflows using
wt-invokers. It includes endpoints for:
- Running workflows with various configurations
- Processing Pub/Sub messages
- Retrieving workflow metadata and schemas
- Converting between parameter formats
"""

from wt_runner.app import app
from wt_runner.testing import Case, CaseRunner
from wt_runner.tracing import (
    TraceContextHeaders,
    attach_context,
    build_context_headers,
    configure_tracer,
)

try:
    from wt_runner._version import __version__, __version_tuple__
except ImportError:
    __version__ = "unknown"
    __version_tuple__ = (0, 0, 0)

__all__ = [
    "app",
    "Case",
    "CaseRunner",
    "configure_tracer",
    "attach_context",
    "build_context_headers",
    "TraceContextHeaders",
    "__version__",
    "__version_tuple__",
]
