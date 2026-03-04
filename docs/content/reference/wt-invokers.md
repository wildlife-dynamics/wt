# wt-invokers

`wt-invokers` provides the execution layer for the wt ecosystem. It defines
an abstract `AbstractInvoker` interface with two concrete implementations for
running compiled workflows.

**Modules:** `abstract` · `local` · `cloud_batch`

**Public API:**

```python
from wt_invokers import (
    AbstractInvoker,
    LocalSubprocessInvoker,
    CloudBatchInvoker,
    InvokerError,
    InvocationTimeoutError,
    InstallationError,
)
```

| Invoker | Environment | Waitable |
|---------|-------------|----------|
| `LocalSubprocessInvoker` | Local machine via pixi | Yes |
| `CloudBatchInvoker` | Google Cloud Batch containers | No |

---

## AbstractInvoker

Abstract base class that all workflow invokers must implement.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `matchspec` | `MatchSpec` | Rattler MatchSpec identifying the workflow package |
| `results_env_var` | `str` | Name of the environment variable for results URL |

### Abstract Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `is_installed()` | `-> bool` | Check whether the workflow is installed |
| `install()` | `-> None` | Install the workflow |
| `run()` | `(**kwargs)` | Launch the workflow with configuration |
| `wait()` | `-> int` | Wait for completion and return exit code |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `is_waitable` | `bool` | Whether this invoker supports waiting for completion |

### Concrete Methods

| Method | Description |
|--------|-------------|
| `check_output()` | Run a one-off command in the workflow environment |

---

## LocalSubprocessInvoker

Executes workflows as local subprocesses using pixi environments. Suitable for
development, testing, and small-scale deployments.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `matchspec` | `MatchSpec` | Workflow MatchSpec |
| `results_env_var` | `str` | Environment variable for results URL |
| `cwd` | `Path` | Working directory for subprocess execution |

### Properties

| Property | Value | Description |
|----------|-------|-------------|
| `entrypoint` | `str` | Pixi command (e.g. `pixi run -e default my-workflow`) |
| `is_waitable` | `True` | Always supports waiting |

### Methods

| Method | Description |
|--------|-------------|
| `is_installed()` | Check if workflow is available in the pixi environment |
| `install()` | Raises `NotImplementedError` |
| `run(**kwargs)` | Launch workflow in a subprocess |
| `wait()` | Block until subprocess completes, return exit code |
| `check_output()` | Run a one-off command and capture stdout |

---

## CloudBatchInvoker

Submits workflows to Google Cloud Batch for containerized execution. Jobs are
submitted asynchronously — does not wait for completion.

Requires GCP extras: `pip install wt-invokers[gcp]`

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_CLOUD_PROJECT` | yes | — | GCP project ID |
| `CLOUD_RUN_REGION` | no | `us-central1` | GCP region |
| `BATCH_SERVICE_ACCOUNT` | no | — | Service account email |

### Properties

| Property | Value | Description |
|----------|-------|-------------|
| `entrypoint` | `str` | Pixi command |
| `is_waitable` | `False` | Does not support waiting |

### Methods

| Method | Description |
|--------|-------------|
| `is_installed()` | Always returns `True` |
| `install()` | Raises `NotImplementedError` |
| `run(**kwargs)` | Submit workflow to Cloud Batch |
| `wait()` | No-op, always returns `0` |

The Cloud Batch job is structured as a single TaskGroup with one Task
containing one Runnable (the container).

---

## Exceptions

| Exception | Description |
|-----------|-------------|
| `InvokerError` | Base exception for invoker errors |
| `InvocationTimeoutError` | Workflow execution timed out |
| `InstallationError` | Workflow installation failed |
