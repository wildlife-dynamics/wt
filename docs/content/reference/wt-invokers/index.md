# wt-invokers

Abstract invoker interface and implementations for executing workflows in different environments.

## Overview

`wt-invokers` provides the execution layer for the wt ecosystem. It defines an abstract invoker interface (`AbstractInvoker`) and ships two concrete implementations:

| Invoker | Environment | Waitable |
|---------|-------------|----------|
| [`LocalSubprocessInvoker`](local.md) | Local machine via pixi | Yes |
| [`CloudBatchInvoker`](cloud-batch.md) | Google Cloud Batch containers | No |

Invokers handle the full lifecycle of workflow execution: checking whether a workflow is installed, installing it (if supported), launching it with configuration, and optionally waiting for completion.

## Installation

Install the core package:

```bash
pip install wt-invokers
```

To use the `CloudBatchInvoker`, install with GCP extras:

```bash
pip install wt-invokers[gcp]
```

Or install the GCP metapackage (equivalent, useful for conda):

```bash
pip install wt-invokers-gcp
```

### Requirements

- Python >= 3.10
- `wt-contracts` >= 0.1.0, < 1.0.0
- `py-rattler` >= 0.8.0
- `ruamel.yaml` >= 0.17.0

GCP extras add:

- `google-cloud-batch` >= 0.19.0
- `google-auth` >= 2.0.0

## Quick Example

```python
import asyncio
from rattler import MatchSpec
from wt_invokers import LocalSubprocessInvoker

invoker = LocalSubprocessInvoker(
    matchspec=MatchSpec("my-workflow>=1.0.0")
)

async def run_workflow():
    await invoker.run(
        workflow_run_id="run-123",
        config_text="param: value",
        results_url="file:///tmp/results",
        execution_mode="sequential",
        mock_io=False,
    )
    exit_code = await invoker.wait(timeout=300)
    print(f"Workflow finished with exit code {exit_code}")

asyncio.run(run_workflow())
```

## Public API

All public symbols are re-exported from the top-level package:

```python
from wt_invokers import (
    # Base class
    AbstractInvoker,
    # Implementations
    LocalSubprocessInvoker,
    CloudBatchInvoker,
    # Exceptions
    InvokerError,
    InvocationTimeoutError,
    InstallationError,
)
```

## Exceptions

All exceptions inherit from `InvokerError`.

| Exception | Raised When |
|-----------|-------------|
| `InvokerError` | Base exception for all invoker-related errors |
| `InvocationTimeoutError` | A workflow execution exceeds the specified timeout |
| `InstallationError` | A workflow cannot be installed in the target environment |

## Architecture

Invokers are dataclasses that hold a `rattler.MatchSpec` identifying the workflow package to execute. The `MatchSpec` determines the entrypoint command (via `pixi run -e default <package-name>`).

The execution flow is:

1. **Check installation** -- `is_installed()` verifies the workflow is available.
2. **Install if needed** -- `install()` sets up the workflow (not yet supported for dynamic installation).
3. **Run** -- `run()` launches the workflow with configuration, environment variables, and execution options.
4. **Wait** (if supported) -- `wait()` blocks until the workflow completes and returns an exit code.

## Versioning

`wt-invokers` uses `setuptools-scm` for versioning. Versions are derived from git tags matching the pattern `wt-invokers/v<version>`.
