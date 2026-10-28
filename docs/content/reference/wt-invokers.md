# wt-invokers

`wt-invokers` provides the execution layer for the wt ecosystem. It defines
an abstract `AbstractInvoker` interface with concrete implementations for
running compiled workflows.

**Modules:** `abstract` · `local` · `compiled_package` · `cloud_batch`

**Public API:**

```python
from wt_invokers import (
    AbstractInvoker,
    LocalSubprocessInvoker,
    CompiledPackageInvoker,
    CloudBatchInvoker,
    InvokerError,
    InvocationTimeoutError,
    InstallationError,
)
```

| Invoker | Execution Target | Supports Waiting |
|---------|-----------------|-----------------|
| `LocalSubprocessInvoker` | Local machine via pixi | Yes |
| `CompiledPackageInvoker` | Local machine, a compiled package on `PYTHONPATH` | Yes |
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

!!! note "Async API"
    All abstract methods are `async`. Callers must `await` them.

| Method | Signature | Description |
|--------|-----------|-------------|
| `is_installed()` | `async -> bool` | Check whether the workflow is installed |
| `install()` | `async -> None` | Install the workflow |
| `run()` | see below | Launch the workflow with configuration |
| `wait()` | `async -> int` | Wait for completion and return exit code |

**`run()` signature:**

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
| `terminate_grace_seconds` | `float` | Time between SIGTERM and SIGKILL for a stopped run (default 10) |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `WT_INVOKERS__LOCAL_SUBPROCESS_INVOKER__CWD` | Default working directory |
| `WT_INVOKERS__SUBPROCESS__TERMINATE_GRACE_SECONDS` | Default `terminate_grace_seconds` (shared with `CompiledPackageInvoker`) |

### Properties

| Property | Value | Description |
|----------|-------|-------------|
| `entrypoint` | `str` | Pixi command (e.g. `pixi run -e default my-workflow`) |
| `is_waitable` | `True` | Always supports waiting |
| `last_log_tail` | `str` | Last 8KB of the most recent finished run's output; survives `wait()` |

### Methods

| Method | Description |
|--------|-------------|
| `is_installed()` | Check if workflow is available in the pixi environment |
| `install()` | Raises `NotImplementedError` |
| `run(**kwargs)` | Launch workflow in a subprocess |
| `wait()` | Wait for the subprocess and return its exit code (see [Subprocess runs](#subprocess-runs)) |
| `check_output()` | Run a one-off command and capture stdout |

---

## CompiledPackageInvoker

Runs a compiled workflow package that is already on disk, by putting
`release_dir` on `PYTHONPATH` and invoking its generated CLI. Used for
packages compiled on the fly, without publishing them first.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `matchspec` | `MatchSpec` | Identifies the build; its package name gives the importable package |
| `release_dir` | `Path` | Directory containing the compiled package |
| `pixi_env` | `str \| None` | Pixi environment to run in. When unset, the running interpreter is used, so the ambient environment must carry the workflow's runtime dependencies |
| `manifest_path` | `Path \| None` | Explicit path to the workspace's pixi manifest |
| `cwd` | `str \| None` | Working directory for subprocess execution |
| `terminate_grace_seconds` | `float` | Time between SIGTERM and SIGKILL for a stopped run (default 10) |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `WT_INVOKERS__COMPILED_PACKAGE_INVOKER__CWD` | Default working directory |
| `WT_INVOKERS__SUBPROCESS__TERMINATE_GRACE_SECONDS` | Default `terminate_grace_seconds` |

---

## Subprocess runs

`LocalSubprocessInvoker` and `CompiledPackageInvoker` share how they run and
wait for the workflow process.

- **Output.** The child's stdout and stderr are drained continuously and
  forwarded to this process's stderr, so they reach the host's log collector
  (Cloud Logging on Cloud Run). The last 8KB is kept as `last_log_tail` for
  error reporting. Draining also stops a chatty workflow from filling the pipe
  and blocking.
- **Waiting.** `wait()` waits on a worker thread, so concurrent runs sharing
  one event loop don't block each other.
- **Timeouts and cancellation.** If `wait(timeout=...)` expires, or the task
  awaiting it is cancelled, the child is sent SIGTERM, given
  `terminate_grace_seconds` to exit, then sent SIGKILL. A timeout still raises
  `InvocationTimeoutError` once the child is gone. The generated workflow CLI
  flushes its spans on SIGTERM within 5 seconds, so keep the grace window
  above that if you change it.

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
