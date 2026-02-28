# HTTP API Reference

`wt-runner` exposes a FastAPI application with endpoints for workflow execution, metadata retrieval, and parameter conversion.

**Module:** `wt_runner.app`

## Common Query Parameters

Several endpoints share these dependency-injected query parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `matchspec` | `str` | *(required)* | Rattler matchspec for the workflow (e.g., `my-workflow>=1.0.0`). Can be overridden by the `ECOSCOPE_WORKFLOWS_MATCHSPEC_OVERRIDE` environment variable. |
| `invoker_type` | `str` | `"BlockingLocalSubprocessInvoker"` | Invoker backend to use. One of `BlockingLocalSubprocessInvoker`, `AsyncLocalSubprocessInvoker`, or `CloudBatchInvoker`. |

## Endpoints

---

### `GET /` -- Health Check

Returns a simple status check.

**Response:** `200 OK`

```json
{"status": "ok"}
```

---

### `POST /` -- Run Workflow

Execute a workflow with the specified parameters.

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `matchspec` | `str` | Yes | -- | Workflow matchspec |
| `invoker_type` | `str` | No | `"BlockingLocalSubprocessInvoker"` | Invoker backend |
| `results_url` | `str` | Yes | -- | URL or absolute local path for results storage |
| `execution_mode` | `"async" \| "sequential"` | Yes | -- | Execution mode |
| `mock_io` | `bool` | Yes | -- | Whether to mock I/O operations |
| `workflow_run_id` | `str` | No | `""` | Unique identifier for this run |
| `timeout` | `float \| null` | No | `null` | Timeout in seconds (waitable invokers only) |
| `docker_image_uri` | `str \| null` | No | `null` | Docker image URI (required for `CloudBatchInvoker`) |

**Headers:**

| Header | Description |
|--------|-------------|
| `traceparent` | W3C Trace Context traceparent header for distributed tracing |
| `tracestate` | W3C Trace Context tracestate header |

**Request Body:**

```json
{
    "params": {
        "param1": "value1",
        "param2": 42
    },
    "execution_mode": "sequential",
    "mock_io": false,
    "data_connections_env_vars": {
        "DATABASE_URL": "postgresql://..."
    },
    "lithops_config": null
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `params` | `dict[str, Any]` | Yes | Workflow parameters |
| `execution_mode` | `"async" \| "sequential"` | Yes | Execution mode |
| `mock_io` | `bool` | Yes | Whether to mock I/O |
| `data_connections_env_vars` | `dict[str, SecretStr] \| null` | No | Secret environment variables for data connections |
| `lithops_config` | `LithopsConfig \| null` | No | Lithops configuration for async execution |

**Response (waitable invoker):** `200 OK`

```json
{
    "result": { "...": "workflow output" },
    "error": null,
    "trace": null
}
```

**Response (non-waitable invoker, e.g., CloudBatch):** `202 Accepted`

```json
{
    "result": {},
    "error": null,
    "trace": null
}
```

**Response (error):** `500 Internal Server Error`

```json
{
    "result": null,
    "error": "Error message",
    "trace": "Full traceback..."
}
```

---

### `POST /run-from-pubsub` -- Run from Pub/Sub

Process `RunWorkflow` messages from Google Cloud Pub/Sub. This endpoint is designed to be called by a Pub/Sub push subscription.

!!! note "Requires ecoscope-eda-core"
    This endpoint requires the `ecoscope-eda-core` package. Returns `501 Not Implemented` if it is not installed.

**Request Body:** Standard [Pub/Sub push message format](https://cloud.google.com/pubsub/docs/push):

```json
{
    "message": {
        "data": "<base64-encoded RunWorkflow JSON>"
    }
}
```

The base64-decoded payload must be a `RunWorkflow` message (from `ecoscope_eda_core.messages.commands`) containing:

| Field | Type | Description |
|-------|------|-------------|
| `match_spec` | `str` | Workflow matchspec |
| `command` | `str` | Command name |
| `invoker_type` | `str` | Invoker backend |
| `invoker_kwargs` | `dict` | Parameters including `workflow_run_id`, `results_url`, `params`, `execution_mode`, `mock_io`, `data_connections_env_vars`, `trace_context` |

**Response:** `200 OK`

```json
{"status": "processed"}
```

**Response (error):**

```json
{
    "status": "error",
    "error": "Error description",
    "trace": "Full traceback..."
}
```

Errors from this endpoint are returned with `200` status to prevent Pub/Sub retries for unrecoverable failures. Error details are also uploaded to the results URL as `result.json`.

The maximum timeout for Pub/Sub-triggered runs is 570 seconds (just under the Pub/Sub acknowledgement deadline of 600 seconds).

---

### `GET /rjsf` -- React JSON Schema Form

Retrieve the RJSF schema for a workflow. This schema can be used to render a dynamic form in a web UI.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `matchspec` | `str` | Yes | Workflow matchspec |
| `invoker_type` | `str` | No | Invoker backend (must support `check_output`) |

**Response:** `200 OK`

```json
{
    "schema": { "...": "JSON Schema" },
    "uiSchema": { "...": "UI Schema" }
}
```

Internally calls the workflow CLI: `<workflow> get rjsf`.

---

### `GET /data-connection-property-names` -- Data Connection Properties

Retrieve the data connection property names for a workflow.

**Query Parameters:** Same as `/rjsf`.

**Response:** `200 OK`

```json
{
    "property_names": ["connection_1", "connection_2"]
}
```

Internally calls the workflow CLI: `<workflow> get data-connection-property-names`.

---

### `POST /formdata-to-params` -- Form Data to Parameters

Convert and validate form data (from an RJSF form submission) into workflow parameters.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `matchspec` | `str` | Yes | Workflow matchspec |
| `invoker_type` | `str` | No | Invoker backend |

**Request Body:**

```json
{
    "field1": "value1",
    "field2": 42
}
```

**Response:** `200 OK` -- Validated parameters dictionary.

**Response:** `422 Unprocessable Entity` -- Validation errors in Pydantic format.

---

### `POST /params-to-formdata` -- Parameters to Form Data

Convert workflow parameters back to form data format.

**Query Parameters:** Same as `/formdata-to-params`.

**Request Body:**

```json
{
    "param1": "value1",
    "param2": 42
}
```

**Response:** `200 OK` -- Form data dictionary.

**Response:** `422 Unprocessable Entity` -- Validation errors.

---

## Response Model

The standard response model for workflow execution endpoints:

```python
class ResponseModel(BaseModel):
    result: dict[str, Any] | None = None
    error: str | None = None
    trace: str | None = None
```

| Field | Type | Description |
|-------|------|-------------|
| `result` | `dict \| null` | Workflow output data. `null` if an error occurred. |
| `error` | `str \| null` | Error message. `null` on success. |
| `trace` | `str \| null` | Full Python traceback. `null` on success. |

## Pydantic Models

### `LithopsConfig`

Configuration for [Lithops](https://lithops-cloud.github.io/) async execution:

```python
class LithopsConfig(BaseModel):
    lithops: Lithops = Lithops()
    gcp: GCP | None = None
    gcp_cloudrun: GCPCloudRun | None = None
```

**`Lithops` fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `backend` | `"localhost" \| "gcp_cloudrun"` | `"localhost"` | Compute backend |
| `storage` | `"localhost" \| "gcp_storage"` | `"localhost"` | Storage backend |
| `log_level` | `str` | `"DEBUG"` | Logging level |
| `data_limit` | `int` | `256` | Data limit in MB |

## Internal Functions

### `resolve_matchspec`

Resolves the workflow matchspec from the query parameter or the `ECOSCOPE_WORKFLOWS_MATCHSPEC_OVERRIDE` environment variable (which takes precedence).

### `resolve_invoker`

Resolves the invoker type string to an invoker instance, checks installation, and installs if needed.

### `resolve_results_url`

Normalizes the results URL. Relative paths are rejected. Absolute local paths are converted to `file://` URIs.

### `upload_error_to_gcs`

Uploads error details as `result.json` to the results URL using `obstore`. Used by the Pub/Sub endpoint to persist errors.
