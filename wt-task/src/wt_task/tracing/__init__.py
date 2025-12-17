"""OpenTelemetry tracing utilities for wt-task.

This package provides tracing configuration and decorators for instrumenting
task execution with OpenTelemetry. Tracing is optional and requires the
`tracing` extra: `pip install wt-task[tracing]`
"""

from ._config import (
    OTelConsoleExporterDst,
    OtelExporterChoice,
    attach_context,
    configure_tracer,
    make_otel_console_exporter_file_dst_kws,
)
from ._decorator import with_tracing

__all__ = [
    "OtelExporterChoice",
    "OTelConsoleExporterDst",
    "attach_context",
    "configure_tracer",
    "make_otel_console_exporter_file_dst_kws",
    "with_tracing",
]
