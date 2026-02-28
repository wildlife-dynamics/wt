# CloudBatchInvoker

The `CloudBatchInvoker` submits workflows to [Google Cloud Batch](https://cloud.google.com/batch) for execution in containerized environments. Jobs are submitted asynchronously -- the invoker does not wait for completion.

**Module:** `wt_invokers.cloud_batch`

!!! note "Requires GCP extras"
    This invoker requires the `gcp` optional dependencies:

    ```bash
    pip install wt-invokers[gcp]
    ```

    Attempting to instantiate `CloudBatchInvoker` without the GCP dependencies raises `ImportError`.

## Class Definition

```python
@dataclass
class CloudBatchInvoker(AbstractInvoker):
    matchspec: MatchSpec
    results_env_var: str = ...  # inherited from AbstractInvoker
```

### Attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `matchspec` | `rattler.MatchSpec` | *(required)* | Rattler MatchSpec identifying the workflow package |
| `results_env_var` | `str` | `"WT_RESULTS"` | Environment variable name for the results URL (inherited) |

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_CLOUD_PROJECT` | Yes | -- | GCP project ID for job submission |
| `CLOUD_RUN_REGION` | No | `us-central1` | GCP region where the batch job runs |
| `BATCH_SERVICE_ACCOUNT` | No | -- | Service account email for the batch job. If unset, the default compute service account is used. |

## Properties

### `entrypoint`

```python
@property
def entrypoint(self) -> str
```

Returns the pixi command for the workflow, identical to `LocalSubprocessInvoker`:

```
pixi run -e default <package-name>
```

### `is_waitable`

```python
@property
def is_waitable(self) -> bool  # always False
```

Cloud Batch jobs run asynchronously. Returns `False`. The `wait()` method is a no-op that immediately returns `0`.

## Methods

### `is_installed`

```python
async def is_installed(self) -> bool  # always True
```

Always returns `True`. Cloud Batch assumes the workflow is pre-installed in the Docker image.

### `install`

```python
async def install(self) -> None
```

**Raises:** `NotImplementedError`. Dynamic installation is not supported for Cloud Batch.

### `run`

```python
async def run(
    self,
    workflow_run_id: str,
    config_text: str,
    results_url: str,
    execution_mode: str,
    mock_io: bool,
    otel_exporter: str | None = None,
    otel_console_exporter_dst: str | None = None,
    extra_env: dict[str, str] | None = None,
    lithops_config_text: str | None = None,
    **kwargs: Any,
) -> None
```

Submits a workflow as a Cloud Batch container job. This method:

1. Validates that `docker_image_uri` and `workflow_run_id` are provided.
2. Generates a unique job name from the `workflow_run_id` (max 61 characters for GCP).
3. Converts `config_text` from YAML to JSON (Cloud Batch uses `--config-json` instead of `--config-file`).
4. Collects all `WT_*` environment variables from the current process and merges them with `extra_env`.
5. Submits the job via the Cloud Batch API.

**Required kwargs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `docker_image_uri` | `str` | Docker image URI containing the workflow (e.g., `gcr.io/project/image:latest`) |

**Optional kwargs:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_id` | `str` | `GOOGLE_CLOUD_PROJECT` env var | GCP project ID |
| `region` | `str` | `CLOUD_RUN_REGION` env var or `us-central1` | GCP region |
| `cpu_milli` | `int` | `8000` | CPU allocation in millicores (8000 = 8 vCPUs) |
| `memory_mib` | `int` | `32768` | Memory allocation in MiB (32768 = 32 GiB) |
| `machine_type` | `str` | -- | Specific GCE machine type (e.g., `n1-standard-8`) |
| `timeout` | `int` | -- | Job timeout in seconds |
| `gpu_type` | `str` | -- | GPU accelerator type (e.g., `nvidia-tesla-v100`) |
| `gpu_count` | `int` | `1` | Number of GPUs (only used when `gpu_type` is set) |

**Raises:** `ValueError` if `docker_image_uri` is missing or `workflow_run_id` is blank.

The container command follows this pattern:

```
pixi run -e default <workflow> run \
    --config-json '<json>' \
    --execution-mode <mode> \
    --mock-io|--no-mock-io \
    [--otel-exporter <exporter>] \
    [--otel-console-exporter-dst <dst>]
```

### `wait`

```python
async def wait(
    self,
    timeout: float | None = None,
    error_msg: str | None = None,
) -> int
```

No-op for Cloud Batch. Always returns `0` immediately. Cloud Batch jobs are monitored through GCP's own infrastructure (Cloud Logging, Pub/Sub notifications, etc.).

## Cloud Batch Job Structure

Each invocation creates a single Cloud Batch job with the following structure:

- **1 TaskGroup** with **1 Task** containing **1 Runnable** (the container).
- **Compute resources** configured via `cpu_milli` and `memory_mib`.
- **Logging** directed to Cloud Logging (`LogsPolicy.Destination.CLOUD_LOGGING`).
- Optional **GPU accelerators** with automatic driver installation.
- Optional **service account** override via the `BATCH_SERVICE_ACCOUNT` environment variable.

## Usage

### Basic Cloud Batch Submission

```python
import asyncio
from rattler import MatchSpec
from wt_invokers import CloudBatchInvoker

# Ensure GOOGLE_CLOUD_PROJECT is set in the environment
invoker = CloudBatchInvoker(
    matchspec=MatchSpec("my-workflow>=1.0.0")
)

async def submit():
    await invoker.run(
        workflow_run_id="production-run-001",
        config_text="param1: value1\nparam2: 42",
        results_url="gs://my-bucket/results/run-001",
        execution_mode="sequential",
        mock_io=False,
        docker_image_uri="gcr.io/my-project/my-workflow:latest",
    )
    print("Job submitted to Cloud Batch")

asyncio.run(submit())
```

### With Custom Resources and GPU

```python
await invoker.run(
    workflow_run_id="gpu-training-run",
    config_text="model: resnet50\nepochs: 100",
    results_url="gs://my-bucket/results/gpu-run",
    execution_mode="sequential",
    mock_io=False,
    docker_image_uri="gcr.io/my-project/training:latest",
    cpu_milli=16000,        # 16 vCPUs
    memory_mib=65536,       # 64 GiB RAM
    machine_type="n1-standard-16",
    gpu_type="nvidia-tesla-v100",
    gpu_count=2,
    timeout=3600,           # 1 hour timeout
)
```

### Authentication

Cloud Batch authentication follows standard Google Cloud conventions:

1. **Application Default Credentials (ADC)** are used automatically. Set up via:

    ```bash
    gcloud auth application-default login
    ```

2. **Service account** for the batch job (not the API client) can be overridden:

    ```bash
    export BATCH_SERVICE_ACCOUNT="my-sa@my-project.iam.gserviceaccount.com"
    ```

3. **Project and region** are read from environment variables:

    ```bash
    export GOOGLE_CLOUD_PROJECT="my-project"
    export CLOUD_RUN_REGION="us-central1"
    ```

    These can also be passed directly as kwargs to `run()`.
