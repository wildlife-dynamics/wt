# Task Methods

This page documents all methods available on `SyncTask` and `AsyncTask` instances. Transformation methods (`.partial()`, `.validate()`, etc.) are defined on the shared `_Task` base class and available on both task types. Execution methods (`.call()`, `.map()`, `.mapvalues()`) have synchronous and asynchronous variants.

All transformation methods return a **new task instance** (frozen dataclass semantics), enabling method chaining:

```python
result = (
    my_task
    .partial(x=10)
    .validate()
    .set_task_instance_id("step_1")
    .handle_errors()
    .call(y=20)
)
```

---

## Execution Methods

### `.call()`

Execute the task with the given arguments.

**SyncTask signature:**

```python
def call(self, *args: P.args, **kwargs: P.kwargs) -> R
```

**AsyncTask signature:**

```python
def call(self, *args: P.args, **kwargs: P.kwargs) -> Future[R]
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `*args` | `P.args` | Positional arguments passed to the wrapped function |
| `**kwargs` | `P.kwargs` | Keyword arguments passed to the wrapped function |

**Returns:** The function's return value (`R`) for `SyncTask`, or a `Future[R]` for `AsyncTask`.

`.call()` is an alias for `__call__` that provides more readable method-chaining syntax. When OpenTelemetry is available, `.call()` creates a tracing span named after the `task_instance_id`.

```python
@task
def add(a: int, b: int) -> int:
    return a + b

# These are equivalent:
add(1, 2)
add.call(1, 2)

# .call() is preferred after chaining:
add.partial(a=1).call(b=2)  # more readable than add.partial(a=1)(b=2)
```

---

### `.map()`

Execute the task once for each element in a sequence of argument values.

**SyncTask signature:**

```python
def map(
    self,
    argnames: str | Sequence[str],
    argvalues: Sequence[Any] | Sequence[tuple[Any, ...]] | SkipSentinel,
) -> Sequence[R | SkipSentinel]
```

**AsyncTask signature:**

```python
def map(
    self,
    argnames: str | Sequence[str],
    argvalues: Sequence[V] | Sequence[tuple[V, ...]],
) -> FutureSequence[R]
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `argnames` | `str \| Sequence[str]` | Name(s) of the argument(s) to vary across calls |
| `argvalues` | `Sequence[Any] \| SkipSentinel` | Values to iterate over. Single values when `argnames` is a string; tuples when `argnames` is a sequence. |

**Returns:** A sequence of results (one per input value). `SyncTask` returns `Sequence[R]`; `AsyncTask` returns `FutureSequence[R]`.

Constant arguments should be bound first with `.partial()`.

```python
@task
def square(x: int) -> int:
    return x * x

# Single argument
square.map("x", [1, 2, 3])  # [1, 4, 9]

# Multiple arguments
@task
def add(a: int, b: int) -> int:
    return a + b

add.map(["a", "b"], [(1, 2), (3, 4)])  # [3, 7]

# With partial for constant args
add.partial(a=10).map("b", [1, 2, 3])  # [11, 12, 13]
```

When `argvalues` is a `SkipSentinel`, the function is not executed and `[SkipSentinel]` is returned.

---

### `.mapvalues()`

Execute the task over key-value pairs, preserving keys in the output. Similar to PySpark's `RDD.mapValues`.

**SyncTask signature:**

```python
def mapvalues(
    self,
    argnames: str | Sequence[str],
    argvalues: Sequence[tuple[K, V]] | SkipSentinel,
) -> Sequence[tuple[K, R]] | Sequence[tuple[None, SkipSentinel]]
```

**AsyncTask signature:**

```python
def mapvalues(
    self,
    argnames: str | Sequence[str],
    argvalues: Sequence[tuple[K, V]],
) -> FutureSequence[tuple[K, R]]
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `argnames` | `str \| Sequence[str]` | Name(s) of the argument(s) to vary |
| `argvalues` | `Sequence[tuple[K, V]] \| SkipSentinel` | Sequence of `(key, value)` tuples. Keys are passed through; values are transformed. |

**Returns:** Sequence of `(key, result)` tuples with original keys preserved.

```python
@task
def length(s: str) -> int:
    return len(s)

length.mapvalues("s", [("a", "hello"), ("b", "world")])
# [("a", 5), ("b", 5)]

@task
def multiply(x: int, factor: int) -> int:
    return x * factor

multiply.partial(factor=2).mapvalues("x", [("a", 5), ("b", 10)])
# [("a", 10), ("b", 20)]
```

---

## Transformation Methods

All transformation methods are defined on `_Task` and available on both `SyncTask` and `AsyncTask`. Each returns a new task instance (immutable chaining).

### `.partial()`

Bind keyword arguments to fixed values, returning a new task. Analogous to `functools.partial`, but keyword-only.

```python
def partial(self, *args: P.args, **kwargs: P.kwargs) -> Self
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `**kwargs` | `P.kwargs` | Keyword arguments to bind |

**Returns:** A new task with a `functools.partial`-wrapped function.

**Raises:** `ValueError` if positional arguments are provided (only keyword arguments are supported).

```python
@task
def add(a: int, b: int) -> int:
    return a + b

add_one = add.partial(a=1)
add_one.call(b=2)  # 3
add_one.map("b", [2, 3, 4])  # [3, 4, 5]
```

---

### `.validate()`

Enable Pydantic input/output validation, returning a new task. The wrapped function is passed through `pydantic.validate_call` with `validate_return=True` and `arbitrary_types_allowed=True`.

This is essential in compiled DAGs where parameters may arrive as strings from JSON/YAML and need coercion to the declared Python types.

```python
def validate(self) -> Self
```

**Returns:** A new task whose function is wrapped with `pydantic.validate_call`.

```python
@task
def add(a: int, b: int) -> int:
    return a + b

add("1", "2")                    # returns "1" (no coercion)
add.validate().call("1", "2")    # returns 3 (strings coerced to int)
```

---

### `.set_task_instance_id()`

Assign a unique identifier to the task instance, returning a new task. The ID is used for tracing spans and error-handling context.

```python
def set_task_instance_id(self, task_instance_id: str, /) -> Self
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `task_instance_id` | `str` | Unique identifier for this task instance (positional-only) |

**Returns:** A new task with `task_instance_id` set.

```python
t = add.set_task_instance_id("add_step_1")
t.task_instance_id  # "add_step_1"
```

---

### `.handle_errors()`

Wrap the function so that any exception is caught and re-raised as a `TaskInstanceError` with the `task_instance_id` attached. This ensures that exceptions in workflow DAGs are surfaced with the correct context for debugging.

```python
def handle_errors(self) -> Self
```

**Returns:** A new task whose function is wrapped with `handle_errors`.

**Warnings:** Emits a warning if `task_instance_id` is not set (error messages will lack context).

```python
from wt_task.exceptions import TaskInstanceError

@task
def divide(a: int, b: int) -> float:
    return a / b

try:
    divide.set_task_instance_id("div_1").handle_errors().call(10, 0)
except TaskInstanceError as e:
    print(e)
    # Task instance 'div_1' raised ZeroDivisionError('division by zero')
```

---

### `.skipif()`

Add conditional skip logic, returning a new task. If any condition function returns `True` when evaluated against the task's arguments, the function is not executed and `SKIP_SENTINEL` is returned instead.

```python
def skipif(
    self,
    conditions: list[Callable[..., bool]],
    unpack_depth: int = 1,
) -> Self
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `conditions` | `list[Callable[..., bool]]` | -- | Condition functions. Each receives the unpacked argument values and returns `True` to skip. |
| `unpack_depth` | `int` | `1` | How many levels of nested lists/tuples to unpack before evaluating conditions. |

**Returns:** A new task whose function is wrapped with `skipif`.

```python
from wt_task.skip import SkipSentinel

@task
def process(x: int) -> int:
    return x * 2

def is_negative(x: int) -> bool:
    return x < 0

conditional = process.skipif([is_negative])
conditional.call(5)    # 10
conditional.call(-5)   # SkipSentinel instance
```

---

### `.with_tracing()`

Enable OpenTelemetry tracing for the function invocation. Wraps the function with the `with_tracing` decorator from `wt_task.tracing`.

```python
def with_tracing(self) -> Self
```

**Returns:** A new task whose function creates a tracing span on each call.

Requires the `gcp` extra: `pip install wt-task[gcp]`.

---

### `.set_executor()`

Switch the executor backend, returning either a `SyncTask` or `AsyncTask` depending on the executor type.

```python
def set_executor(
    self,
    name_or_executor: Literal["python"] | AsyncExecutor | SyncExecutor,
) -> SyncTask[P, R, K, V] | AsyncTask[P, R, K, V]
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `name_or_executor` | `"python" \| AsyncExecutor \| SyncExecutor` | `"python"` for the default `PythonExecutor`, or a custom executor instance. |

**Returns:**

- `SyncTask` when `name_or_executor` is `"python"` or a `SyncExecutor` instance.
- `AsyncTask` when `name_or_executor` is an `AsyncExecutor` instance.

**Raises:** `ValueError` if the argument is not a recognized executor name or instance.

```python
from wt_task.executors import PythonExecutor

custom = add.set_executor(PythonExecutor())
type(custom)  # SyncTask
```

---

## Executor Interfaces

### `SyncExecutor` (abstract)

Base class for synchronous executors. Subclasses must implement:

| Method | Signature | Description |
|--------|-----------|-------------|
| `call` | `(func, *args, **kwargs) -> R` | Execute a function synchronously |
| `map` | `(func, iterable) -> Sequence[R]` | Map a function over an iterable |

### `AsyncExecutor` (abstract)

Base class for asynchronous executors. Subclasses must implement:

| Method | Signature | Description |
|--------|-----------|-------------|
| `call` | `(func, *args, **kwargs) -> Future[R]` | Execute a function asynchronously |
| `map` | `(func, iterable) -> FutureSequence[R]` | Map a function over an iterable asynchronously |

### `PythonExecutor`

The default `SyncExecutor`. Executes functions directly in the current thread using standard Python calls. `call()` delegates to `func(*args, **kwargs)` and `map()` uses the built-in `map()`.

### `Future` (abstract)

Represents a pending asynchronous result. Subclasses must implement `.gather() -> R`.

### `FutureSequence` (abstract)

Represents a sequence of pending asynchronous results. Subclasses must implement `.gather() -> Sequence[R]`.

---

## Exception Classes

### `TaskInstanceError`

Raised by `.handle_errors()` when the wrapped function raises an exception. Wraps the original exception with the `task_instance_id` for debugging context.

| Attribute | Type | Description |
|-----------|------|-------------|
| `task_instance_id` | `str` | The task instance identifier |
| `exc` | `Exception` | The original exception |

String representation: `Task instance '<id>' raised <ExceptionType>('<message>')`.

### `handle_errors()` (function)

Standalone function that wraps any callable with `TaskInstanceError` handling:

```python
from wt_task.exceptions import handle_errors

wrapped = handle_errors(my_func, task_instance_id="step_1")
```

---

## Skip Utilities

### `SkipSentinel`

Sentinel class returned when a task execution is skipped. A global singleton `SKIP_SENTINEL` is provided. `SkipSentinel` implements Pydantic core/JSON schema hooks so it can participate in validated models.

### `skipif()` (function)

Standalone function that wraps a callable with conditional skip logic:

```python
from wt_task.skip import skipif, SkipSentinel

def any_is_skip(*args):
    return any(isinstance(a, SkipSentinel) for a in args)

wrapped = skipif(my_func, conditions=[any_is_skip], unpack_depth=1)
```

### `unpack_listlike()`

Recursively unpack nested lists and tuples to a specified depth before evaluating skip conditions:

```python
from wt_task.skip import unpack_listlike

unpack_listlike([1, [2, 3], (4, 5)], unpack_depth=1)
# [1, 2, 3, 4, 5]
```

### `SkippedDependencyFallback`

Type alias for `pydantic.functional_validators.BeforeValidator`. Used in Pydantic models to provide fallback values when a dependency was skipped.

---

## Testing Utilities

### `create_func_magicmock()`

**Module:** `wt_task.testing`

Create a `unittest.mock.MagicMock` that returns pre-loaded example data for a registered task. Used in compiled DAG test code to mock I/O tasks without hitting real external services.

```python
from wt_task.testing import create_func_magicmock

mock = create_func_magicmock(
    anchor="my_package.tasks.io",
    func_name="fetch_data",
)
# mock() returns the example data loaded from the package's example-return file
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `anchor` | `str` | Dotted module path containing the real task |
| `func_name` | `str` | Name of the task function to mock |

**Returns:** A `MagicMock` with the real function's signature and `functools.WRAPPER_ASSIGNMENTS` attributes copied, plus `__signature__` explicitly set.

Example-return files are discovered by convention: `{func_name_dashed}.example-return.{ext}` in the anchor module's package resources. The file extension determines the loader (`.json` built-in; additional formats via `wt_task.mock_loaders` entry points). An environment variable `WT_TASK_MOCK_IO__{ANCHOR}_{FUNC_NAME}` (uppercased, dots replaced with underscores) can override the file path.
