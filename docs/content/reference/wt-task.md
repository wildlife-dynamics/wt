# wt-task

`wt-task` provides the `@task` decorator that wraps plain Python functions with
a chainable, composable execution API. Used in generated DAG code to execute
registered functions with validation, error handling, and tracing.

**Modules:** `decorator` · `base` · `sync_task` · `async_task` · `exceptions` ·
`skip` · `executors` · `testing` · `tracing`

**Public API:**

```python
from wt_task import task, SyncTask, AsyncTask
```

---

## `@task` Decorator

```python
def task(
    func: Callable[P, R] | None = None,
    *,
    description: str | None = None,
    tags: list[str] | None = None,
) -> SyncTask[P, R, K, V] | Callable[[Callable[P, R]], SyncTask[P, R, K, V]]
```

Works as both a decorator and a wrapper function. Creates a `SyncTask` instance.

### Usage forms

```python
# Bare decorator
@task
def my_func(x: int) -> int:
    return x * 2

# With arguments
@task(description="...", tags=["io"])
def my_func(x: int) -> int:
    return x * 2

# Wrapper function (used in generated DAG code)
result = task(registered_func).partial(x=5).call()
```

### `SyncTask` fields

| Field | Type | Description |
|-------|------|-------------|
| `func` | `Callable` | The wrapped function |
| `tags` | `list[str]` | Categorization tags |
| `description` | `str \| None` | Task description |
| `task_instance_id` | `str \| None` | Unique identifier for this instance |
| `executor` | `Executor \| None` | Custom executor backend |

---

## Execution Methods

### `.call(*args, **kwargs) -> R`

Execute the task directly with the given arguments.

### `.map(argnames, argvalues) -> Sequence[R]`

Map the task over a sequence. `argnames` is the parameter name (or list of
names) to bind each element to; `argvalues` is the iterable.

```python
results = task(process_item).map("item", items)
# Equivalent to: [process_item(item=x) for x in items]
```

### `.mapvalues(argnames, argvalues) -> Sequence[tuple[K, R]]`

Map over key-value pairs, preserving the keys. Input must be a sequence of
`(key, value)` tuples.

```python
results = task(transform).mapvalues("data", grouped_data)
# Input:  [("group_a", data_a), ("group_b", data_b)]
# Output: [("group_a", result_a), ("group_b", result_b)]
```

---

## Transformation Methods

All transformation methods return a **new task instance** (immutable — the
original is unchanged), enabling method chaining:

```python
result = (
    task(my_func)
    .set_task_instance_id("step_one")
    .partial(x=5)
    .validate()
    .handle_errors()
    .call()
)
```

| Method | Signature | Description |
|--------|-----------|-------------|
| `.partial(**kwargs)` | `-> Self` | Bind keyword arguments |
| `.validate()` | `-> Self` | Enable Pydantic validation (coerces string inputs to correct types) |
| `.set_task_instance_id(id)` | `-> Self` | Assign a unique identifier for error reporting |
| `.handle_errors()` | `-> Self` | Wrap exceptions as `TaskInstanceError` with instance ID |
| `.skipif(conditions, unpack_depth=1)` | `-> Self` | Conditionally skip based on boolean condition functions |
| `.with_tracing()` | `-> Self` | Enable OpenTelemetry tracing |
| `.set_executor(name_or_executor)` | `-> SyncTask \| AsyncTask` | Switch executor backend |

---

## Exceptions and Skip

| Name | Description |
|------|-------------|
| `TaskInstanceError` | Wraps an exception with the task instance ID for debugging |
| `SkipSentinel` | Returned when a task is skipped via `.skipif()` |
| `SKIP_SENTINEL` | Singleton instance of `SkipSentinel` |

---

## Testing

```python
from wt_task.testing import create_func_magicmock
```

`create_func_magicmock` creates a `MagicMock` with the same signature as the
original function, useful for testing DAG code without executing real tasks.
