# wt-runner

FastAPI application for executing workflows using wt-invokers.

## Overview

`wt-runner` is a production-ready web service that provides HTTP endpoints for executing workflows. It integrates with `wt-invokers` to support multiple execution backends (local subprocess, cloud batch, etc.) and provides comprehensive workflow management capabilities.

## Features

- **Workflow Execution**: Run workflows with various configurations via HTTP API
- **Pub/Sub Integration**: Process workflow requests from Google Cloud Pub/Sub
- **Metadata Endpoints**: Retrieve workflow schemas and metadata
- **Format Conversion**: Convert between parameter formats (params ↔ formdata)
- **OpenTelemetry Tracing**: Built-in distributed tracing support
- **Multiple Invokers**: Support for different execution backends via wt-invokers

## Installation

### Basic Installation

```bash
pip install wt-runner
```

### With Optional Dependencies

```bash
# For Google Cloud Platform support
pip install wt-runner[gcp]

# For storage support (obstore)
pip install wt-runner[storage]

# For OpenTelemetry tracing
pip install wt-runner[tracing]

# For workflow integration
pip install wt-runner[workflows]

# All optional dependencies
pip install wt-runner[gcp,storage,tracing,workflows]
```

### Development Installation

```bash
cd wt-runner
uv sync
uv run pytest
```

## Usage

### Starting the Server

```bash
# Basic usage
uvicorn wt_runner.app:app

# With custom host and port
uvicorn wt_runner.app:app --host 0.0.0.0 --port 8000

# With auto-reload for development
uvicorn wt_runner.app:app --reload
```

### Using the FastAPI App in Code

```python
from wt_runner import app

# The app can be imported and used with any ASGI server
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8000)
```

## API Endpoints

### Health Check

```bash
GET /
```

Returns server health status.

**Response:**
```json
{
  "status": "ok"
}
```

### Run Workflow

```bash
POST /
```

Execute a workflow with specified parameters.

**Query Parameters:**
- `matchspec` (required): Rattler matchspec for the workflow package
- `invoker_type` (optional): Type of invoker to use (default: `BlockingLocalSubprocessInvoker`)
- `results_url` (required): URL or path for storing results
- `workflow_run_id` (optional): Unique identifier for the workflow run
- `timeout` (optional): Timeout in seconds
- `docker_image_uri` (optional): Docker image URI for the workflow

**Request Body:**
```json
{
  "params": {
    "key": "value"
  },
  "execution_mode": "sequential",
  "mock_io": false,
  "data_connections_env_vars": {
    "SECRET_KEY": "secret_value"
  },
  "lithops_config": {
    "lithops": {
      "backend": "localhost",
      "storage": "localhost"
    }
  }
}
```

**Response:**
```json
{
  "result": {...},
  "error": null,
  "trace": null
}
```

### Run from Pub/Sub

```bash
POST /run-from-pubsub
```

Process workflow execution requests from Google Cloud Pub/Sub messages.

**Request Body:** (Pub/Sub message format)
```json
{
  "message": {
    "data": "base64-encoded-workflow-params"
  }
}
```

**Response:**
```json
{
  "status": "processed"
}
```

### Get RJSF Schema

```bash
GET /rjsf?matchspec=<workflow-matchspec>
```

Retrieve the React JSON Schema Form schema for a workflow.

**Response:**
```json
{
  "schema": {...},
  "uiSchema": {...}
}
```

### Get Data Connection Property Names

```bash
GET /data-connection-property-names?matchspec=<workflow-matchspec>
```

Retrieve data connection property names for a workflow.

### Convert Form Data to Params

```bash
POST /formdata-to-params?matchspec=<workflow-matchspec>
```

Convert form data format to workflow parameters.

**Request Body:**
```json
{
  "field1": "value1",
  "field2": "value2"
}
```

### Convert Params to Form Data

```bash
POST /params-to-formdata?matchspec=<workflow-matchspec>
```

Convert workflow parameters to form data format.

**Request Body:**
```json
{
  "param1": "value1",
  "param2": "value2"
}
```

## Configuration

### Environment Variables

- `ECOSCOPE_WORKFLOWS_MATCHSPEC_OVERRIDE`: Override matchspec for all requests
- `ECOSCOPE_WORKFLOWS_OTEL_EXPORTER`: OpenTelemetry exporter type (`console` or `gcp`)
- `ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_DST`: Console exporter destination (`stdout` or `file`)
- `ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_FILE_DST_TARGET_DIR`: Directory for trace files

### OpenTelemetry Tracing

Enable tracing by setting environment variables:

```bash
# Console exporter (stdout)
export ECOSCOPE_WORKFLOWS_OTEL_EXPORTER=console
export ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_DST=stdout

# Console exporter (file)
export ECOSCOPE_WORKFLOWS_OTEL_EXPORTER=console
export ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_DST=file
export ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_FILE_DST_TARGET_DIR=/path/to/traces

# GCP Cloud Trace
export ECOSCOPE_WORKFLOWS_OTEL_EXPORTER=gcp
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
```

### Programmatic Tracing Configuration

```python
from wt_runner import configure_tracer

configure_tracer(
    name="my-service",
    version="1.0.0",
    exporter="console",
    exporter_kws={}
)
```

## Development

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=wt_runner --cov-report=term-missing

# Run specific test file
uv run pytest tests/test_app.py

# Run with verbose output
uv run pytest -v
```

### Type Checking

```bash
uv run mypy src/wt_runner
```

### Linting and Formatting

```bash
# Check code
uv run ruff check src/wt_runner

# Format code
uv run ruff format src/wt_runner
```

## Architecture

### Dependencies

- **wt-invokers**: Provides workflow execution backends (required)
- **wt-contracts**: Shared interface contracts (required)
- **FastAPI**: Web framework for API endpoints
- **Uvicorn**: ASGI server for running the application
- **Rattler**: Conda package management
- **OpenTelemetry**: Distributed tracing (optional)
- **obstore**: Object storage abstraction (optional)

### Package Structure

```
wt-runner/
├── src/wt_runner/
│   ├── __init__.py       # Package exports
│   ├── app.py            # FastAPI application
│   ├── tracing.py        # OpenTelemetry tracing
│   └── _version.py       # Version info (auto-generated)
├── tests/
│   ├── test_app.py       # Endpoint tests
│   ├── test_tracing.py   # Tracing tests
│   └── conftest.py       # Pytest configuration
├── pyproject.toml        # Package metadata
└── README.md
```

## Invoker Support

The runner supports all invokers provided by `wt-invokers`:

- `BlockingLocalSubprocessInvoker`: Synchronous local subprocess execution
- `AsyncLocalSubprocessInvoker`: Asynchronous local subprocess execution
- `CloudBatchInvoker`: Google Cloud Batch execution (requires GCP dependencies)

See [wt-invokers documentation](../wt-invokers/README.md) for more details.

## Error Handling

The runner provides comprehensive error handling:

- **400 Bad Request**: Invalid request parameters
- **422 Unprocessable Entity**: Validation errors
- **500 Internal Server Error**: Workflow execution failures
- **503 Service Unavailable**: Timeout errors

All errors include detailed trace information in the response.

## Examples

### Basic Workflow Execution

```python
import httpx

response = httpx.post(
    "http://localhost:8000/",
    params={
        "matchspec": "my-workflow>=1.0",
        "results_url": "gs://bucket/results",
    },
    json={
        "params": {"input": "data"},
        "execution_mode": "sequential",
        "mock_io": False,
    },
)

result = response.json()
print(result["result"])
```

### With Custom Invoker

```python
response = httpx.post(
    "http://localhost:8000/",
    params={
        "matchspec": "my-workflow>=1.0",
        "invoker_type": "AsyncLocalSubprocessInvoker",
        "results_url": "gs://bucket/results",
    },
    json={
        "params": {"input": "data"},
        "execution_mode": "async",
        "mock_io": False,
    },
)
```

### With Tracing

```python
response = httpx.post(
    "http://localhost:8000/",
    params={
        "matchspec": "my-workflow>=1.0",
        "results_url": "gs://bucket/results",
    },
    headers={
        "traceparent": "00-trace-id-span-id-01",
    },
    json={
        "params": {"input": "data"},
        "execution_mode": "sequential",
        "mock_io": False,
    },
)
```

## Contributing

Contributions are welcome! Please ensure:

1. All tests pass: `uv run pytest`
2. Type checking passes: `uv run mypy src/wt_runner`
3. Code is formatted: `uv run ruff format src/wt_runner`
4. Test coverage remains >90%
5. All public functions have docstrings

## License

BSD-3-Clause

## Related Packages

- [wt-contracts](../wt-contracts/README.md): Shared interface contracts
- [wt-invokers](../wt-invokers/README.md): Workflow execution backends
- [wt-task](../wt-task/README.md): Task decorator and execution
- [wt-compiler](../wt-compiler/README.md): Workflow compilation
- [wt-registry](../wt-registry/README.md): Function registration
