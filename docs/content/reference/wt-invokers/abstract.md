# AbstractInvoker

::: wt_invokers.abstract

The `AbstractInvoker` is the base class that all workflow invokers must implement. It defines the interface for installing and executing workflows in different environments.

**Module:** `wt_invokers.abstract`

## Class Definition

```python
@dataclass
class AbstractInvoker(ABC):
    matchspec: MatchSpec
    results_env_var: str = ...  # defaults from WT_INVOKERS__RESULTS_ENV_VAR or "WT_RESULTS"
```

`AbstractInvoker` is an abstract [dataclass](https://docs.python.org/3/library/dataclasses.html) that uses Python's ABC mechanism. Subclasses must implement all abstract methods and the `is_waitable` property.

### Attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `matchspec` | `rattler.MatchSpec` | *(required)* | Rattler MatchSpec identifying the workflow package to invoke |
| `results_env_var` | `str` | `"WT_RESULTS"` | Name of the environment variable used to pass the results URL to the workflow process. Reads from `WT_INVOKERS__RESULTS_ENV_VAR` at init time. |

## Abstract Methods

### `is_installed`

```python
async def is_installed(self) -> bool
```

Check whether the workflow is installed and available for execution.

**Returns:** `True` if the workflow is available, `False` otherwise.

### `install`

```python
async def install(self) -> None
```

Install the workflow using the configured matchspec.

**Raises:**

- `NotImplementedError` -- if dynamic installation is not supported by this invoker.
- `InstallationError` -- if installation fails.

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

Launch the workflow with the given configuration.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `workflow_run_id` | `str` | Unique identifier for this workflow run |
| `config_text` | `str` | YAML or JSON configuration text for the workflow |
| `results_url` | `str` | URL where workflow results should be stored (e.g., `file:///tmp/results` or `gs://bucket/path`) |
| `execution_mode` | `str` | Execution mode, typically `"sequential"` or `"async"` |
| `mock_io` | `bool` | Whether to mock I/O operations |
| `otel_exporter` | `str \| None` | OpenTelemetry exporter endpoint (optional) |
| `otel_console_exporter_dst` | `str \| None` | Console exporter destination (optional) |
| `extra_env` | `dict[str, str] \| None` | Additional environment variables to pass to the workflow process |
| `lithops_config_text` | `str \| None` | Lithops configuration text for async execution (optional) |
| `**kwargs` | `Any` | Additional invoker-specific arguments (e.g., `docker_image_uri` for Cloud Batch) |

**Raises:** `RuntimeError` if workflow invocation fails.

### `wait`

```python
async def wait(
    self,
    timeout: float | None = None,
    error_msg: str | None = None,
) -> int
```

Wait for the workflow to finish and return its exit code.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `timeout` | `float \| None` | Timeout in seconds. `None` means wait indefinitely. |
| `error_msg` | `str \| None` | Custom error message to use if timeout occurs |

**Returns:** Exit code of the workflow (`0` for success, non-zero for failure).

**Raises:**

- `RuntimeError` -- if the process was not started or has already finished.
- `InvocationTimeoutError` -- if the timeout is reached.

### `is_waitable` (property)

```python
@property
def is_waitable(self) -> bool
```

Whether this invoker supports waiting for completion. Some invokers (e.g., Cloud Batch) submit work asynchronously and do not support blocking until completion.

**Returns:** `True` if `wait()` can be called meaningfully, `False` otherwise.

## Concrete Methods

### `check_output`

```python
async def check_output(
    self,
    command: list[str],
    stdin: str | None = None,
) -> str
```

Run a one-off command in the workflow environment and capture its stdout. The base class raises `NotImplementedError`; subclasses that support this (e.g., `LocalSubprocessInvoker`) override it.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `command` | `list[str]` | Arguments to append to the workflow entrypoint |
| `stdin` | `str \| None` | Optional stdin input for the command |

**Returns:** Stripped stdout from the command.

**Raises:**

- `NotImplementedError` -- if the invoker does not support this operation.
- `RuntimeError` -- if the command fails (non-zero exit code).

## Implementing a Custom Invoker

To create a custom invoker, subclass `AbstractInvoker` and implement all abstract methods:

```python
from dataclasses import dataclass
from typing import Any
from rattler import MatchSpec
from wt_invokers import AbstractInvoker


@dataclass
class MyCustomInvoker(AbstractInvoker):
    """Invoker that runs workflows on a custom platform."""

    api_url: str = "https://my-platform.example.com"

    async def is_installed(self) -> bool:
        # Check if the workflow is available on the platform
        return True

    async def install(self) -> None:
        # Deploy the workflow to the platform
        raise NotImplementedError("Dynamic installation not supported")

    async def run(
        self,
        workflow_run_id: str,
        config_text: str,
        results_url: str,
        execution_mode: str,
        mock_io: bool,
        **kwargs: Any,
    ) -> None:
        # Submit the workflow to the platform
        ...

    async def wait(
        self,
        timeout: float | None = None,
        error_msg: str | None = None,
    ) -> int:
        # Poll the platform for completion
        return 0

    @property
    def is_waitable(self) -> bool:
        return True
```

The custom invoker can then be used identically to the built-in invokers:

```python
invoker = MyCustomInvoker(matchspec=MatchSpec("my-workflow>=1.0.0"))
await invoker.run(
    workflow_run_id="run-001",
    config_text="key: value",
    results_url="https://storage.example.com/results",
    execution_mode="sequential",
    mock_io=False,
)
exit_code = await invoker.wait(timeout=600)
```
