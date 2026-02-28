# @task Decorator

The `task` function is the primary entry point for creating task wrappers. It works both as a decorator on function definitions and as a wrapper function in generated DAG code.

**Module:** `wt_task.decorator`

## Signature

```python
def task(
    func: Callable[P, R] | None = None,
    *,
    description: str | None = None,
    tags: list[str] | None = None,
) -> SyncTask[P, R, K, V] | Callable[[Callable[P, R]], SyncTask[P, R, K, V]]
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | `Callable[P, R] \| None` | `None` | The function to wrap. `None` when used as `@task(...)` with parentheses. |
| `description` | `str \| None` | `None` | Optional human-readable description of the task. |
| `tags` | `list[str] \| None` | `None` | Optional list of tags for categorization. |

### Returns

- When `func` is provided (bare `@task` or `task(fn)`): returns a `SyncTask` instance.
- When `func` is `None` (`@task(...)` with arguments): returns a decorator function that accepts a callable and returns a `SyncTask`.

## Usage Forms

### Bare decorator (no parentheses)

```python
@task
def add(a: int, b: int) -> int:
    return a + b
```

The function `add` is immediately wrapped into a `SyncTask`. No parentheses are needed when you do not need to pass `description` or `tags`.

### Decorator with arguments

```python
@task(description="Multiply two numbers", tags=["math"])
def multiply(a: int, b: int) -> int:
    return a * b
```

When parentheses are used, `task(...)` returns a decorator function. The inner function is wrapped when Python applies the returned decorator.

### Wrapper function (generated code)

In compiler-generated DAG code, `task` is used as a plain wrapper around already-registered functions:

```python
from wt_task import task
from my_package.tasks import registered_func

result = task(registered_func).partial(x=5).call()
```

This form is equivalent to `@task` but applied after import rather than at definition time.

## What `task()` Creates

Calling `task()` in any of the above forms produces a `SyncTask` instance -- a frozen dataclass with the following fields:

| Field | Type | Value |
|-------|------|-------|
| `func` | `Callable[P, R]` | The original function |
| `tags` | `list[str]` | Tags from decorator args (defaults to `[]`) |
| `description` | `str \| None` | Description from decorator args |
| `task_instance_id` | `str \| None` | Always `None` initially; set later via `.set_task_instance_id()` |
| `executor` | `SyncExecutor[P, R]` | A `PythonExecutor()` instance (default) |

The `task_instance_id` field is deliberately not settable through the decorator. The wt-compiler sets it later via the `.set_task_instance_id()` method during DAG code generation, ensuring each task invocation in a workflow has a unique identifier.

## Type Alias

```python
Task = SyncTask
```

`Task` is a convenience alias for `SyncTask`, exported from `wt_task`.

## Behavior

- The returned `SyncTask` is **callable**: `add(1, 2)` delegates to the executor's `.call()` method.
- The original function is preserved as `task_instance.func`.
- `SyncTask` is a **frozen dataclass** -- all transformation methods (`.partial()`, `.validate()`, etc.) return new instances rather than mutating the original.
- When OpenTelemetry is available, `.call()`, `.map()`, and `.mapvalues()` automatically create tracing spans using the `task_instance_id` as the span name.
