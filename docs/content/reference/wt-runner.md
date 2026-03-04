# wt-runner

`wt-runner` provides an HTTP API for executing compiled workflows using
wt-invokers. It supports multiple invoker backends and integrates with
OpenTelemetry for distributed tracing.

**Modules:** `app` · `tracing`

---

## HTTP API

### Common Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `matchspec` | `str` | *(required)* | Rattler matchspec identifying the workflow package |
| `invoker_type` | `str` | `"BlockingLocalSubprocessInvoker"` | Invoker backend to use |

### Invoker Registry

| `invoker_type` string | Invoker class |
|----------------------|---------------|
| `"BlockingLocalSubprocessInvoker"` | `LocalSubprocessInvoker` |
| `"AsyncLocalSubprocessInvoker"` | `LocalSubprocessInvoker` |
| `"CloudBatchInvoker"` | `CloudBatchInvoker` |

### Endpoints

#### `GET /`

Health check. Returns `200 OK`.

#### `POST /`

Run a workflow with configuration and parameters.

**Request body:**

```json
{
  "params": {"step_id": {"param": "value"}},
  "config": {}
}
```

**Response:**

```json
{
  "result": { ... },
  "error": null,
  "trace": null
}
```

On failure, `error` contains the exception message and `trace` contains the
full traceback.

#### `POST /run-from-pubsub`

Process `RunWorkflow` messages from Google Cloud Pub/Sub. Used for
event-driven workflow execution in GCP deployments.

#### `GET /rjsf`

Retrieve the React JSON Schema Form configuration for a workflow. Used by
web UIs to render parameter forms.

#### `GET /data-connection-property-names`

Get data connection property names from workflow metadata.

#### `POST /formdata-to-params`

Convert hierarchical form data to flat workflow parameters.

#### `POST /params-to-formdata`

Convert flat workflow parameters to hierarchical form data.

### Response Model

```python
class ResponseModel(BaseModel):
    result: dict[str, Any] | None = None
    error: str | None = None
    trace: str | None = None
```

### Middleware

- **CORS:** Allows all origins and credentials; methods restricted to POST.
- **GZip:** Compresses responses larger than 1000 bytes.

---

## Tracing

OpenTelemetry tracing for distributed observability across the workflow
execution chain.

### Environment Variables

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `ECOSCOPE_WORKFLOWS_OTEL_EXPORTER` | `"console"`, `"gcp"`, or unset | unset (disabled) | Exporter type |
| `ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_DST` | `"stdout"`, `"file"` | `"file"` | Console exporter destination |
| `ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_FILE_DST_TARGET_DIR` | directory path | — | Directory for trace files (required when using file destination) |

### Functions

| Function | Description |
|----------|-------------|
| `configure_tracer()` | Configure the global OpenTelemetry tracer provider |
| `attach_context()` | Attach trace context from W3C headers |
| `build_context_headers()` | Extract current trace context as W3C headers |
| `otel_span_formatter()` | Format a span as single-line JSON |

### Trace Propagation

Traces propagate through the execution chain using W3C trace context headers:

```
HTTP request → wt-runner → workflow subprocess → wt-task
```

---

## Testing Utilities

| Name | Description |
|------|-------------|
| `Case` | Pydantic model describing a test case (parameters + expected output) |
| `CaseRunner` | Dataclass that executes a `Case` via FastAPI test client or CLI |
