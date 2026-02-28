# Tracing

OpenTelemetry tracing configuration for `wt-runner`, with support for console output and Google Cloud Trace export.

**Module:** `wt_runner.tracing`

## Overview

`wt-runner` uses [OpenTelemetry](https://opentelemetry.io/) for distributed tracing. The tracing module configures a `TracerProvider` with a `BatchSpanProcessor` and supports two exporter backends:

| Exporter | Description | Dependency |
|----------|-------------|------------|
| `"console"` | Writes spans to stdout or a JSONL file | Included with `opentelemetry-sdk` |
| `"gcp"` | Exports spans to Google Cloud Trace | Requires `opentelemetry-exporter-gcp-trace` (GCP extras) |

Trace context propagation follows the [W3C Trace Context](https://www.w3.org/TR/trace-context/) standard via the `traceparent` and `tracestate` headers.

## Configuration

### Environment Variables

Tracing is configured through environment variables read by the application at startup:

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `ECOSCOPE_WORKFLOWS_OTEL_EXPORTER` | `"console"`, `"gcp"`, or unset | unset (no exporter) | Exporter backend to use |
| `ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_DST` | `"stdout"`, `"file"` | `"file"` | Where the console exporter writes spans |
| `ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_FILE_DST_TARGET_DIR` | directory path | -- | Directory for the `otel_traces.jsonl` file (required when exporter is `"console"` and destination is `"file"`) |

### Startup Behavior

The tracer is configured during the FastAPI [lifespan](https://fastapi.tiangolo.com/advanced/events/) startup event. The configuration flow:

1. Read `ECOSCOPE_WORKFLOWS_OTEL_EXPORTER` to determine the exporter type.
2. If console exporter with file destination, read and validate the target directory.
3. Call `configure_tracer()` with the application name and version.

If no exporter is configured, a `TracerProvider` is still created (spans are generated but not exported).

## Functions

### `configure_tracer`

```python
def configure_tracer(
    name: str,
    version: str = "",
    exporter: Literal["console", "gcp"] | None = None,
    exporter_kws: dict[str, Any] | None = None,
) -> None
```

Configure the global OpenTelemetry tracer provider.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | *(required)* | Service name (set to the app title, `"wt-runner"`) |
| `version` | `str` | `""` | Service version |
| `exporter` | `"console" \| "gcp" \| None` | `None` | Exporter backend. `None` means no spans are exported. |
| `exporter_kws` | `dict[str, Any] \| None` | `None` | Additional kwargs passed to the exporter constructor |

**Raises:**

- `ValueError` -- if an unknown exporter type is specified.
- `RuntimeError` -- if `"gcp"` is requested but `opentelemetry-exporter-gcp-trace` is not installed.

The tracer provider is configured with a `Resource` containing `service.name` and `service.version` attributes. When an exporter is specified, spans are batched and exported via `BatchSpanProcessor`.

### `attach_context`

```python
def attach_context(
    traceparent: str,
    tracestate: str | None = None,
) -> None
```

Attach trace context from incoming W3C headers to the current OpenTelemetry context. This enables distributed tracing across service boundaries.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `traceparent` | `str` | W3C traceparent header value (e.g., `00-<trace-id>-<span-id>-01`) |
| `tracestate` | `str \| None` | W3C tracestate header value (optional, vendor-specific key-value pairs) |

### `build_context_headers`

```python
def build_context_headers() -> TraceContextHeaders
```

Extract the current trace context as W3C headers. Used to propagate context to subprocess invocations via environment variables.

**Returns:** A `TraceContextHeaders` dictionary containing `traceparent` and optionally `tracestate`.

### `make_otel_console_exporter_file_dst_kws`

```python
def make_otel_console_exporter_file_dst_kws(
    target_dir: Path,
) -> dict[str, Any]
```

Create kwargs for a `ConsoleSpanExporter` that writes to a file.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `target_dir` | `Path` | Directory to write traces to. Created if it does not exist. |

**Returns:** Dictionary with `out` (file handle) and `formatter` (JSON line formatter) keys, suitable for passing to `ConsoleSpanExporter`.

The output file is `otel_traces.jsonl` in the target directory, opened in append mode with line buffering. Each span is written as a single unindented JSON line.

**Raises:** `ValueError` if `target_dir` exists but is not a directory.

### `otel_span_formatter`

```python
def otel_span_formatter(span: ReadableSpan) -> str
```

Format a span as a single-line JSON string followed by a newline. Used as the formatter for the file-based console exporter.

## Types

### `TraceContextHeaders`

```python
class TraceContextHeaders(TypedDict, total=False):
    traceparent: str
    tracestate: str
```

A `TypedDict` representing W3C Trace Context headers. Both fields are optional (the `total=False` makes all keys non-required).

### `OtelExporterChoice`

```python
OtelExporterChoice = Literal["console", "gcp"]
```

### `OTelConsoleExporterDst`

```python
OTelConsoleExporterDst = Literal["stdout", "file"]
```

## Trace Propagation Flow

The tracing system propagates context across the following boundaries:

1. **HTTP request to wt-runner** -- The `traceparent` header on incoming requests is extracted via `attach_context()`.
2. **wt-runner to workflow subprocess** -- Trace context is injected as environment variables (`TRACEPARENT`, `TRACESTATE`) via `build_context_headers()`.
3. **Workflow subprocess to wt-task** -- The workflow reads the environment variables and attaches context for its own spans.

This enables end-to-end tracing from the initial API call through to individual task executions.

## Example Configuration

### Console Exporter to File

```bash
export ECOSCOPE_WORKFLOWS_OTEL_EXPORTER=console
export ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_DST=file
export ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_FILE_DST_TARGET_DIR=/var/log/traces

uvicorn wt_runner:app --host 0.0.0.0 --port 8000
```

Spans are written to `/var/log/traces/otel_traces.jsonl`.

### Google Cloud Trace Exporter

```bash
export ECOSCOPE_WORKFLOWS_OTEL_EXPORTER=gcp

uvicorn wt_runner:app --host 0.0.0.0 --port 8000
```

Requires `opentelemetry-exporter-gcp-trace` to be installed and GCP Application Default Credentials to be configured.

### No Tracing

```bash
# Simply do not set ECOSCOPE_WORKFLOWS_OTEL_EXPORTER
uvicorn wt_runner:app --host 0.0.0.0 --port 8000
```

A `TracerProvider` is still created, but spans are discarded.
