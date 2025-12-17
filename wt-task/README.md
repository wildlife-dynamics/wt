# wt-task

Task decorator and execution features for the wt ecosystem.

## Overview

`wt-task` provides the `@task` decorator and task execution capabilities for workflow systems. It implements the `TaskProtocol` from `wt-contracts`, enabling type-safe task execution across the wt ecosystem.

## Features

- **Dual-purpose `task` decorator**: Works as both a decorator (`@task`) and wrapper function (`task(func)`)
- **Execution methods**: `call`, `map`, `mapvalues` for different execution patterns
- **Partial application**: Bind arguments with `.partial()` before execution
- **Validation**: Pydantic-based validation with `.validate()`
- **Error handling**: Wrap errors with task instance context
- **Conditional skipping**: Skip execution based on conditions with `.skipif()`
- **Custom executors**: Switch execution backends with `.set_executor()`
- **OpenTelemetry tracing**: Optional tracing support (requires `wt-task[tracing]`)

## Installation

```bash
# Basic installation
pip install wt-task

# With tracing support
pip install wt-task[tracing]

# Development installation
cd wt/wt-task
uv sync
```

## Usage

### Basic Task Definition

```python
from wt_task import task

@task
def add(a: int, b: int) -> int:
    return a + b

# Direct call
result = add(1, 2)  # 3

# Explicit call
result = add.call(1, 2)  # 3
```

### Partial Application

```python
@task
def multiply(a: int, b: int) -> int:
    return a * b

# Bind one argument
multiply_by_2 = multiply.partial(b=2)
result = multiply_by_2.call(a=5)  # 10
```

### Mapping Over Values

```python
@task
def square(x: int) -> int:
    return x * x

# Map over a sequence
results = square.map("x", [1, 2, 3, 4])  # [1, 4, 9, 16]
```

### Mapping Over Key-Value Pairs

```python
@task
def process(data: str) -> int:
    return len(data)

# Map over key-value pairs, preserving keys
results = process.mapvalues("data", [
    ("a", "hello"),
    ("b", "world"),
])
# [("a", 5), ("b", 5)]
```

### Validation

```python
@task
def add_numbers(a: int, b: int) -> int:
    return a + b

# Parse string inputs to ints
result = add_numbers.validate().call("10", "20")  # 30
```

### Error Handling

```python
@task
def divide(a: int, b: int) -> float:
    return a / b

# Add task instance context to errors
task_with_id = divide.set_task_instance_id("task-1")
try:
    task_with_id.handle_errors().call(10, 0)
except TaskInstanceError as e:
    print(e)  # Task instance 'task-1' raised ZeroDivisionError(...)
```

### Method Chaining

All methods return a new task instance, enabling clean method chaining:

```python
result = (
    add
    .partial(a=10)
    .validate()
    .set_task_instance_id("add-task")
    .handle_errors()
    .call(b="20")
)  # 30
```

## Architecture

`wt-task` is designed to work seamlessly with other wt packages:

- **wt-contracts**: Implements the `TaskProtocol` interface
- **wt-compiler**: Generated DAG code uses `task()` wrapper function
- **wt-registry**: Task functions are registered separately with `@register`

## Development

```bash
# Create environment and install dependencies
cd wt/wt-task
uv sync

# Run tests
uv run pytest

# Type checking
uv run mypy src/

# Linting
uv run ruff check .

# Formatting
uv run ruff format .
```

## Testing

The package includes comprehensive tests for all features:

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=wt_task --cov-report=html

# Run specific test file
uv run pytest tests/test_decorator.py
```

## License

Apache-2.0
