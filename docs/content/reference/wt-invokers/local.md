# LocalSubprocessInvoker

The `LocalSubprocessInvoker` executes workflows as local subprocesses using [pixi](https://pixi.sh/) environments. It is suitable for development, testing, and small-scale deployments.

**Module:** `wt_invokers.local`

## Class Definition

```python
@dataclass
class LocalSubprocessInvoker(AbstractInvoker):
    matchspec: MatchSpec
    results_env_var: str = ...   # inherited from AbstractInvoker
    cwd: str | None = None       # defaults from environment
```

### Attributes

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `matchspec` | `rattler.MatchSpec` | *(required)* | Rattler MatchSpec identifying the workflow package |
| `results_env_var` | `str` | `"WT_RESULTS"` | Environment variable name for the results URL (inherited) |
| `cwd` | `str \| None` | `None` | Working directory for subprocess execution. Falls back to `WT_INVOKERS__LOCAL_SUBPROCESS_INVOKER__CWD` environment variable. |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `WT_INVOKERS__LOCAL_SUBPROCESS_INVOKER__CWD` | Default working directory for subprocess execution |
| `WT_INVOKERS__RESULTS_ENV_VAR` | Override the name of the results environment variable (default: `WT_RESULTS`) |

## Properties

### `entrypoint`

```python
@property
def entrypoint(self) -> str
```

Returns the pixi command used to invoke the workflow. The package name is extracted from the matchspec.

```python
>>> from rattler import MatchSpec
>>> invoker = LocalSubprocessInvoker(matchspec=MatchSpec("my-workflow>=1.0.0"))
>>> invoker.entrypoint
'pixi run -e default my-workflow'
```

**Raises:** `ValueError` if the matchspec does not contain a package name.

### `is_waitable`

```python
@property
def is_waitable(self) -> bool  # always True
```

Local subprocesses are always waitable. Returns `True`.

## Methods

### `is_installed`

```python
async def is_installed(self) -> bool
```

Checks whether the workflow is installed by running `<entrypoint> --help` and checking the return code.

**Returns:** `True` if the command exits with code 0, `False` otherwise.

### `install`

```python
async def install(self) -> None
```

**Raises:** `NotImplementedError`. Dynamic installation is not yet supported for local subprocess invokers.

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

Launches the workflow in a subprocess. This method:

1. Creates the results directory if `results_url` uses a `file://` scheme.
2. Writes `config_text` to a temporary YAML file.
3. Optionally writes `lithops_config_text` to a temporary file and sets `LITHOPS_CONFIG_FILE`.
4. Sets the results URL in the environment via `results_env_var`.
5. Merges `extra_env` into the subprocess environment.
6. Starts the subprocess with `subprocess.Popen`.

The constructed command follows this pattern:

```
pixi run -e default <workflow> run \
    --config-file <tmpfile.yaml> \
    --execution-mode <mode> \
    --mock-io|--no-mock-io \
    [--otel-exporter <exporter>] \
    [--otel-console-exporter-dst <dst>]
```

**Parameters:** See [AbstractInvoker.run](abstract.md#run) for the full parameter reference. The `**kwargs` are ignored by this implementation.

### `wait`

```python
async def wait(
    self,
    timeout: float | None = None,
    error_msg: str | None = None,
) -> int
```

Blocks until the subprocess completes.

**Returns:** The process exit code (`0` for success).

**Raises:**

- `RuntimeError` -- if `run()` has not been called yet.
- `InvocationTimeoutError` -- if the timeout is reached. The process is **not** killed automatically on timeout.

### `check_output`

```python
async def check_output(
    self,
    command: list[str],
    stdin: str | None = None,
) -> str
```

Runs a one-off command via the workflow entrypoint and captures stdout. The command arguments are appended to the entrypoint:

```
pixi run -e default <workflow> <command args...>
```

**Returns:** Stripped stdout from the command.

**Raises:** `RuntimeError` if the command exits with a non-zero code.

## Usage

### Basic Execution

```python
import asyncio
from rattler import MatchSpec
from wt_invokers import LocalSubprocessInvoker

invoker = LocalSubprocessInvoker(
    matchspec=MatchSpec("my-workflow>=1.0.0"),
    cwd="/path/to/project",
)

async def main():
    if not await invoker.is_installed():
        raise RuntimeError("Workflow not installed")

    await invoker.run(
        workflow_run_id="run-001",
        config_text="param1: value1\nparam2: 42",
        results_url="file:///tmp/results/run-001",
        execution_mode="sequential",
        mock_io=False,
    )

    exit_code = await invoker.wait(timeout=300)
    if exit_code != 0:
        raise RuntimeError(f"Workflow failed with exit code {exit_code}")

asyncio.run(main())
```

### With Extra Environment Variables

```python
await invoker.run(
    workflow_run_id="run-002",
    config_text="param: value",
    results_url="file:///tmp/results/run-002",
    execution_mode="sequential",
    mock_io=False,
    extra_env={
        "DATABASE_URL": "postgresql://localhost/mydb",
        "API_KEY": "secret-key",
    },
)
```

### Querying Workflow Metadata

```python
# Get the workflow version
version = await invoker.check_output(["--version"])
print(version)  # "1.2.3"

# Get workflow schema
import json
schema_json = await invoker.check_output(["get", "rjsf"])
schema = json.loads(schema_json)
```
