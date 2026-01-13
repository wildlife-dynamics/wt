"""OpenTelemetry tracing configuration for Google Cloud Trace.

This module provides utilities for configuring OpenTelemetry tracing with
various exporters including console and Google Cloud Trace.

Note: This is adapted from https://github.com/PADAS/cdip-routing.
"""

import os
from pathlib import Path
from typing import Literal

try:
    from opentelemetry import context, propagate, trace
    from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
    from opentelemetry.propagate import set_global_textmap
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SpanExporter,
    )
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    TRACING_AVAILABLE = True
except ImportError:
    TRACING_AVAILABLE = False

OtelExporterChoice = Literal["console", "gcp"]
"""Type for OpenTelemetry exporter choices."""

OTelConsoleExporterDst = Literal["stdout", "file"]
"""Type for console exporter destination choices."""


def otel_span_formatter(span: "ReadableSpan") -> str:
    """Format an OTEL span as an unindented JSON line.

    Args:
        span: OpenTelemetry span to format

    Returns:
        JSON line string with span data
    """
    if not TRACING_AVAILABLE:
        return ""
    result: str = span.to_json(indent=None) + os.linesep
    return result


def make_otel_console_exporter_file_dst_kws(target_dir: Path) -> dict[str, object]:
    """Create kwargs for a console exporter writing to a file.

    This function:
    1. Ensures the target directory exists (creating if necessary)
    2. Opens a file `otel_traces.jsonl` in the target directory for appending
    3. Uses a JSON line formatter for spans (unindented for easier parsing)

    Args:
        target_dir: Directory where trace file will be created

    Returns:
        Dictionary of kwargs for ConsoleSpanExporter

    Raises:
        ValueError: If target_dir exists but is not a directory
    """
    if target_dir.exists() and not target_dir.is_dir():
        raise ValueError(f"Target dir {target_dir} exists but is not a directory")
    elif not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
    traces_outpath = target_dir / "otel_traces.jsonl"
    return {
        "out": traces_outpath.open("a", buffering=1),
        "formatter": otel_span_formatter,
    }


def configure_tracer(
    name: str,
    version: str = "",
    exporter: OtelExporterChoice | None = None,
    exporter_kws: dict[str, object] | None = None,
) -> None:
    """Configure OpenTelemetry tracer with specified exporter.

    Sets up the global tracer provider with the specified service name, version,
    and exporter. If no exporter is specified, tracing is configured but no spans
    are exported.

    Args:
        name: Service name for traces
        version: Service version
        exporter: Type of exporter to use ("console" or "gcp")
        exporter_kws: Additional kwargs for the exporter

    Raises:
        ValueError: If an unknown exporter type is specified
        ImportError: If tracing dependencies are not installed

    Examples:
        >>> # Configure with console exporter to stdout
        >>> configure_tracer("my-service", "1.0.0", "console")
        >>> # Configure with file output
        >>> from pathlib import Path
        >>> kws = make_otel_console_exporter_file_dst_kws(Path("./traces"))
        >>> configure_tracer("my-service", "1.0.0", "console", kws)
    """
    if not TRACING_AVAILABLE:
        raise ImportError(
            "OpenTelemetry dependencies not installed. Install with: pip install wt-task[tracing]"
        )

    resource = Resource.create(
        {
            "service.name": name,
            "service.version": version,
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    if exporter:
        _exporter: SpanExporter
        _exporter_kws = exporter_kws or {}
        match exporter:
            case "console":
                _exporter = ConsoleSpanExporter(**_exporter_kws)  # type: ignore[arg-type]
            case "gcp":
                _exporter = CloudTraceSpanExporter(**_exporter_kws)  # type: ignore[no-untyped-call]
            case _:
                raise ValueError(f"Unknown exporter: {exporter}")

        tracer_provider.add_span_processor(
            # BatchSpanProcessor buffers spans and sends them in batches in a
            # background thread. The default parameters are sensible, but can be
            # tweaked to optimize your performance
            BatchSpanProcessor(_exporter)
        )
    trace.set_tracer_provider(tracer_provider)


class TraceContextHeaders(dict[str, str]):
    """Type for trace context headers.

    Contains traceparent and optionally tracestate headers for distributed tracing.
    """

    traceparent: str
    tracestate: str | None


def build_context_headers() -> TraceContextHeaders:
    """Build trace context headers from current context.

    Returns:
        Dictionary with traceparent and tracestate headers

    Raises:
        ImportError: If tracing dependencies are not installed
    """
    if not TRACING_AVAILABLE:
        raise ImportError(
            "OpenTelemetry dependencies not installed. Install with: pip install wt-task[tracing]"
        )

    headers: TraceContextHeaders = TraceContextHeaders()
    propagate.inject(headers)
    return headers


def attach_context(traceparent: str, tracestate: str | None = None) -> None:
    """Attach tracing context from given traceparent and tracestate headers.

    This allows continuing a trace started in another process or service.

    Args:
        traceparent: W3C traceparent header value
        tracestate: Optional W3C tracestate header value

    Raises:
        ImportError: If tracing dependencies are not installed

    Examples:
        >>> # In a distributed system, receive headers and attach context
        >>> attach_context(
        ...     "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        ... )
    """
    if not TRACING_AVAILABLE:
        raise ImportError(
            "OpenTelemetry dependencies not installed. Install with: pip install wt-task[tracing]"
        )

    carrier: dict[str, str] = {"traceparent": traceparent}
    if tracestate:
        carrier["tracestate"] = tracestate
    ctx = propagate.extract(carrier=carrier)
    context.attach(ctx)


# uses the default W3C Trace Context propagator, i.e. `traceparent` header
if TRACING_AVAILABLE:
    set_global_textmap(TraceContextTextMapPropagator())
