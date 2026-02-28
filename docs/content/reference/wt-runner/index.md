# wt-runner

FastAPI web service for workflow execution using wt-invokers.

## Overview

`wt-runner` provides an HTTP API for executing workflows, retrieving workflow metadata, and converting between parameter formats. It supports multiple invoker backends and integrates with OpenTelemetry for distributed tracing.

The server exposes endpoints for:

- **Running workflows** via HTTP POST or Google Cloud Pub/Sub messages.
- **Retrieving metadata** such as React JSON Schema Form (RJSF) schemas.
- **Converting parameters** between form data and workflow parameter formats.

## Installation

Install the core package:

```bash
pip install wt-runner
```

For GCP integration (Cloud Trace, Pub/Sub, ecoscope-eda-core):

```bash
pip install wt-runner[gcp]
```

Or install the GCP metapackage:

```bash
pip install wt-runner-gcp
```

### Requirements

- Python >= 3.13
- `wt-contracts` >= 0.1.0, < 1.0.0
- `wt-invokers` >= 0.1.0, < 1.0.0
- `fastapi` >= 0.100.0
- `uvicorn` >= 0.20.0
- `pydantic` >= 2.0.0, < 3.0.0
- `py-rattler` >= 0.8.0
- `ruamel.yaml` >= 0.18.0
- `opentelemetry-api` >= 1.0.0
- `opentelemetry-sdk` >= 1.0.0
- `obstore` >= 0.6.0

GCP extras add:

- `opentelemetry-sdk` >= 1.37.0
- `opentelemetry-exporter-gcp-trace` >= 1.9.0
- `gcloud-aio-pubsub` >= 6.1.0
- `ecoscope-eda-core`

## Running the Server

Start the server with uvicorn:

```bash
uvicorn wt_runner:app --host 0.0.0.0 --port 8000
```

For development with auto-reload:

```bash
uvicorn wt_runner:app --host 0.0.0.0 --port 8000 --reload
```

## Public API

The top-level package exports:

```python
from wt_runner import (
    # FastAPI application
    app,
    # Testing utilities
    Case,
    CaseRunner,
    # Tracing
    configure_tracer,
    attach_context,
    build_context_headers,
    TraceContextHeaders,
)
```

## Invoker Registry

The server maps invoker type names to invoker classes:

| Invoker Type String | Class | Behavior |
|---------------------|-------|----------|
| `"BlockingLocalSubprocessInvoker"` | `LocalSubprocessInvoker` | Runs locally, waits for result |
| `"AsyncLocalSubprocessInvoker"` | `LocalSubprocessInvoker` | Runs locally, waits for result |
| `"CloudBatchInvoker"` | `CloudBatchInvoker` | Submits to GCP, returns 202 Accepted |

The invoker type is selected via the `invoker_type` query parameter (default: `"BlockingLocalSubprocessInvoker"`).

## Middleware

The application includes two middleware layers:

| Middleware | Configuration |
|------------|---------------|
| CORS | Allows all origins, credentials, and headers. Methods restricted to `POST`. |
| GZip | Compresses responses larger than 1000 bytes. |

## Testing Utilities

`wt-runner` ships two testing utilities for running workflow test cases:

### `Case`

A Pydantic model describing a test case:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | *(required)* | Human-readable name |
| `description` | `str` | *(required)* | What the test case covers |
| `params` | `dict[str, Any]` | *(required)* | Workflow parameters |
| `raises` | `bool` | `False` | Whether an error is expected |
| `expected_status_code` | `int` | `200` | Expected HTTP status code |

### `CaseRunner`

A dataclass that can execute a `Case` via the FastAPI app or CLI:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `execution_mode` | `"async" \| "sequential"` | *(required)* | Execution mode |
| `mock_io` | `bool` | *(required)* | Whether to mock I/O |
| `case` | `Case` | *(required)* | Test case to run |
| `results_subdir` | `Path` | *(required)* | Directory for results |
| `traceparent` | `str \| None` | `None` | W3C traceparent header |
| `otel_exporter` | `"console" \| "gcp" \| None` | `"console"` | OpenTelemetry exporter |
| `otel_console_exporter_dst` | `"stdout" \| "file"` | `"file"` | Console exporter destination |

**Methods:**

- `run_app(app, data_connections_env_vars=None)` -- Executes the test case via the FastAPI test client.
- `run_cli(matchspec)` -- Executes the test case via the CLI using `LocalSubprocessInvoker`.

## Versioning

`wt-runner` uses `setuptools-scm` for versioning. Versions are derived from git tags matching the pattern `wt-runner/v<version>`.
