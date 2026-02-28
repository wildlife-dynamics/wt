# wt-task

Task decorator and execution framework for the wt workflow ecosystem.

## Overview

`wt-task` provides the `@task` decorator that wraps plain Python functions with a chainable, composable execution API. Decorated functions gain `.call()`, `.map()`, `.mapvalues()`, `.partial()`, `.validate()`, and other methods that the wt-compiler uses when generating executable DAG code.

The package supports both synchronous execution (via `SyncTask` with a `PythonExecutor`) and asynchronous execution (via `AsyncTask` with custom `AsyncExecutor` implementations). It also includes optional OpenTelemetry tracing, error handling with task-instance context, and conditional skip logic.

| Module | Purpose |
|--------|---------|
| [`decorator`](decorator.md) | `@task` decorator and `Task` type alias |
| [`base`](methods.md) | `_Task` base class with shared transformation methods |
| [`sync_task`](methods.md) | `SyncTask` -- synchronous execution with `.call()`, `.map()`, `.mapvalues()` |
| [`async_task`](methods.md) | `AsyncTask` -- asynchronous execution returning `Future` / `FutureSequence` |
| `exceptions` | `TaskInstanceError` and `handle_errors` wrapper |
| `skip` | `SkipSentinel`, `skipif`, and `unpack_listlike` utilities |
| `executors` | `SyncExecutor`, `AsyncExecutor`, `PythonExecutor`, `Future`, `FutureSequence` |
| `testing` | `create_func_magicmock` for mocking task I/O in tests |
| `tracing` | Optional OpenTelemetry instrumentation (requires `gcp` extra) |

## Installation

```bash
pip install wt-task
```

Or with uv:

```bash
uv add wt-task
```

For GCP tracing support:

```bash
pip install wt-task[gcp]
# or install the metapackage
pip install wt-task-gcp
```

### Requirements

- Python >= 3.10
- `wt-contracts` >= 0.1.0, < 1.0.0
- `pydantic` >= 2.0.0, < 3.0.0

## Quick Example

```python
from wt_task import task

@task
def add(a: int, b: int) -> int:
    return a + b

# Direct call (task is callable)
add(1, 2)          # 3

# Explicit .call()
add.call(1, 2)     # 3

# Partial application + map
add.partial(a=1).map("b", [2, 3, 4])      # [3, 4, 5]

# Map over key-value pairs, preserving keys
add.partial(a=1).mapvalues("b", [("x", 2), ("y", 3)])  # [("x", 3), ("y", 4)]

# Validation (coerces string inputs to declared types)
add.validate().call("1", "2")  # 3

# Method chaining (typical pattern in compiled DAGs)
result = (
    add
    .partial(b=2)
    .validate()
    .set_task_instance_id("add_step")
    .handle_errors()
    .call(a=10)
)
# result == 12
```

## Public API

All public symbols are re-exported from the top-level package:

```python
from wt_task import (
    # Decorator and task types
    task,
    Task,          # alias for SyncTask
    SyncTask,
    AsyncTask,
    # Exceptions
    TaskInstanceError,
    handle_errors,
    # Executors
    SyncExecutor,
    AsyncExecutor,
    PythonExecutor,
    Future,
    FutureSequence,
    # Skip utilities
    SkipSentinel,
    SKIP_SENTINEL,
    SkippedDependencyFallback,
    skipif,
    unpack_listlike,
)
```

## Versioning

`wt-task` uses `setuptools-scm` for versioning. Versions are derived from git tags matching the pattern `wt-task/v<version>`.
