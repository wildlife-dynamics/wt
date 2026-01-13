"""Basic OpenTelemetry tracing setup for Google Cloud Trace.

Note this is adapted from https://github.com/PADAS/cdip-routing.
"""

import os
from pathlib import Path
from typing import Literal, TypedDict

from opentelemetry import context, propagate, trace
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
)
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

# Optional GCP exporter
try:
    from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

    HAS_GCP_EXPORTER = True
except ImportError:
    CloudTraceSpanExporter = None  # type: ignore
    HAS_GCP_EXPORTER = False

OtelExporterChoice = Literal["console", "gcp"]
OTelConsoleExporterDst = Literal["stdout", "file"]


def otel_span_formatter(span: ReadableSpan) -> str:
    """Format an OTEL span as an unindented JSON line.

    Args:
        span: The span to format

    Returns:
        Formatted span as JSON line with newline
    """
    return span.to_json(indent=None) + os.linesep


def make_otel_console_exporter_file_dst_kws(target_dir: Path) -> dict:
    """Create kwargs for console exporter writing to a file.

    This opinionated configuration:
      1. Ensures the target directory exists (creating if necessary)
      2. Opens a file `otel_traces.jsonl` in the target directory for appending
      3. Uses line buffering for immediate writes
      4. Uses unindented JSON formatter for easier parsing

    Args:
        target_dir: Directory to write traces to

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
    exporter_kws: dict | None = None,
) -> None:
    """Configure OpenTelemetry tracer with specified exporter.

    Args:
        name: Service name for the tracer
        version: Service version (optional)
        exporter: Type of exporter to use (console or gcp), None for no exporter
        exporter_kws: Additional kwargs for the exporter

    Raises:
        ValueError: If unknown exporter type specified
        RuntimeError: If GCP exporter is requested but not available
    """
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
                _exporter = ConsoleSpanExporter(**_exporter_kws)
            case "gcp":
                if not HAS_GCP_EXPORTER:
                    raise RuntimeError(
                        "GCP exporter requested but opentelemetry-exporter-gcp-trace "
                        "is not installed. Install with: pip install wt-runner[tracing]"
                    )
                _exporter = CloudTraceSpanExporter(**_exporter_kws)
            case _:
                raise ValueError(f"Unknown exporter: {exporter}")

        tracer_provider.add_span_processor(
            # BatchSpanProcessor buffers spans and sends them in batches in a
            # background thread. The default parameters are sensible, but can be
            # tweaked to optimize your performance
            BatchSpanProcessor(_exporter)
        )
    trace.set_tracer_provider(tracer_provider)


class TraceContextHeaders(TypedDict, total=False):
    """W3C Trace Context headers.

    See: https://www.w3.org/TR/trace-context/
    """

    traceparent: str
    tracestate: str


def build_context_headers() -> TraceContextHeaders:
    """Build trace context headers from current OpenTelemetry context.

    Returns:
        Dictionary containing traceparent and optionally tracestate headers
    """
    headers: TraceContextHeaders = {}
    propagate.inject(headers)
    return headers


def attach_context(traceparent: str, tracestate: str | None = None) -> None:
    """Attach tracing context from given traceparent and tracestate headers.

    Args:
        traceparent: W3C traceparent header value
        tracestate: W3C tracestate header value (optional)
    """
    carrier = {"traceparent": traceparent}
    if tracestate:
        carrier["tracestate"] = tracestate
    ctx = propagate.extract(carrier=carrier)
    context.attach(ctx)


# uses the default W3C Trace Context propagator, i.e. `traceparent` header
set_global_textmap(TraceContextTextMapPropagator())
