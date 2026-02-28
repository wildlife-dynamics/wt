# Task Models

Module: `wt_contracts.task`

This module defines `TaskProtocol`, the interface contract that `wt-task` implements and `wt-compiler` generates code against. Using a `Protocol` (structural subtyping) allows type-safe task execution without creating a direct dependency between the compiler and the task runtime.

---

## TaskProtocol

```python
from wt_contracts import TaskProtocol
```

```python
class TaskProtocol(Protocol[P, R]):
    ...
```

A generic Protocol parameterized by:

- **`P`** (`ParamSpec`) -- the parameter specification of the wrapped function.
- **`R`** (`TypeVar`, covariant) -- the return type of the wrapped function.

Any class that implements all the methods below satisfies this protocol. In practice, `wt-task`'s `SyncTask` and `AsyncTask` are the primary implementations.

### Methods

#### `partial(**kwargs) -> Self`

Apply partial function application. Binds keyword arguments to the task, returning a new task instance with those parameters fixed.

Used in generated DAG code to set parameters from `spec.yaml`.

```python
# In wt-compiler generated code:
result = task(func).partial(x=1, y=2).call()
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `**kwargs` | `Any` | Keyword arguments to bind |

**Returns:** A new task with the given arguments partially applied.

---

#### `call(*args, **kwargs) -> R`

Execute the task directly with the given arguments.

```python
result = task(func).call(x=1, y=2)
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `*args` | `P.args` | Positional arguments |
| `**kwargs` | `P.kwargs` | Keyword arguments |

**Returns:** The result of executing the wrapped function (`R`).

---

#### `map(argname, argvalues, **kwargs) -> Sequence[R]`

Map over a sequence of values for a single parameter. Executes the task once for each value in `argvalues`, binding each value to the parameter named `argname`.

```python
# Equivalent to [func(x=1, y=10), func(x=2, y=10), func(x=3, y=10)]
results = task(func).map("x", [1, 2, 3], y=10)
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `argname` | `str` | Parameter name to map over |
| `argvalues` | `Sequence[Any]` | Sequence of values for that parameter |
| `**kwargs` | `Any` | Fixed keyword arguments applied to every execution |

**Returns:** A `Sequence[R]` with one result per input value.

---

#### `mapvalues(argname, argvalues, **kwargs) -> Sequence[tuple[Any, R]]`

Map over key-value pairs, preserving keys. Similar to `map`, but the input is a sequence of `(key, value)` tuples and the output preserves the keys as `(key, result)` tuples.

```python
results = task(func).mapvalues("x", [("a", 1), ("b", 2)], y=10)
# Returns: [("a", result_a), ("b", result_b)]
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `argname` | `str` | Parameter name to map over |
| `argvalues` | `Sequence[tuple[Any, Any]]` | Sequence of `(key, value)` tuples |
| `**kwargs` | `Any` | Fixed keyword arguments applied to every execution |

**Returns:** A `Sequence[tuple[Any, R]]` of `(key, result)` tuples.

---

#### `validate() -> Self`

Validate the task configuration (e.g., run Pydantic validation on bound parameters). Returns `self` for method chaining.

```python
task(func).partial(x=1).validate().call()
```

**Returns:** `Self`, enabling method chaining.

---

#### `skipif(condition) -> Self`

Conditionally skip task execution. If the `condition` callable returns `True`, the task is skipped and a sentinel value is returned instead of executing.

```python
task(func).skipif(lambda: os.path.exists("skip.txt")).call()
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `condition` | `Callable[..., bool]` | Callable that returns `True` to skip, `False` to execute |

**Returns:** `Self`, enabling method chaining.

---

#### `set_executor(executor) -> Self`

Set a custom executor for task execution (e.g., `ThreadPoolExecutor`, `ProcessPoolExecutor`).

```python
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=4)
task(func).set_executor(executor).map("x", [1, 2, 3])
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `executor` | `Any` | Executor instance |

**Returns:** `Self`, enabling method chaining.

---

### Method Chaining

`TaskProtocol` methods are designed for fluent chaining. A typical generated DAG step looks like:

```python
result = (
    task(process_data)
    .partial(config=config, threshold=0.5)
    .skipif(lambda: cached_result_exists())
    .validate()
    .map("input_file", input_files)
)
```
