# Registering Tasks with wt-registry

In this tutorial you will register your first task function with `wt-registry`,
inspect the registry at runtime, and export it from the command line. By the end
you will understand how the `@register` decorator works, what validation it
performs, and how registered functions flow into the rest of the wt workflow
framework.

## Prerequisites

- Python 3.10 or later
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## 1. Install wt-registry

`wt-registry` depends on `wt-contracts` (shared Pydantic models used across all
wt packages). Installing `wt-registry` pulls it in automatically.

```bash
uv pip install wt-registry
```

Or with plain pip:

```bash
pip install wt-registry
```

!!! tip
    If you are developing inside the wt monorepo, install in editable mode
    from the repository root instead:

    ```bash
    uv pip install -e wt-contracts -e wt-registry
    ```

Verify the install by checking for the CLI entry point:

```bash
wt-registry --help
```

You should see output describing the available flags (`--format`, `--pretty`,
`--function`, `--package`).

## 2. Create a task package

The compiler discovers tasks by installing packages into an ephemeral
environment and running `wt-registry` as a subprocess. This means your tasks
must live in an **installable Python package** — a standalone `.py` file is not
enough. Let's create one now.

Set up the following directory structure:

```
my-tasks/
├── pyproject.toml
└── src/
    └── my_tasks/
        ├── __init__.py
        └── tasks.py
```

### `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"

[project]
name = "my-tasks"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "wt-registry",
]

[tool.setuptools.packages.find]
where = ["src"]
```

### `src/my_tasks/__init__.py`

Re-export the task functions so the compiler can import them with a clean path:

```python
from my_tasks.tasks import calculate_mean
```

### `src/my_tasks/tasks.py`

Every function you register **must** have complete type annotations on all
parameters and on the return type. wt-registry uses these annotations to
generate a JSON schema that downstream tools (wt-compiler, wt-runner) rely on.

```python
def calculate_mean(values: list[float]) -> float:
    """Return the arithmetic mean of a list of numbers."""
    return sum(values) / len(values)
```

### Install the package

Install your package in editable mode so the tasks are importable:

```bash
pip install -e ./my-tasks
```

This is the same workflow you will use in the
[next tutorial](first-workflow.md) and when developing real task packages. For
more on uv vs pixi and packaging choices, see
[Tooling & Prerequisites](../concepts/tooling.md).

## 3. Register the function with `@register`

Import the decorator and apply it to your function:

```python title="src/my_tasks/tasks.py" hl_lines="1 4"
from wt_registry import register


@register()
def calculate_mean(values: list[float]) -> float:
    """Return the arithmetic mean of a list of numbers."""
    return sum(values) / len(values)
```

That is the minimal form -- `@register()` with no arguments. The decorator:

1. **Auto-generates a title** from the function name by converting `snake_case`
   to Title Case. `calculate_mean` becomes *Calculate Mean*.
2. **Stores the entry** in a global, in-process registry keyed by the fully
   qualified name (`my_tasks.tasks.calculate_mean`).
3. **Returns the original function unchanged** -- you can still call
   `calculate_mean([1.0, 2.0, 3.0])` exactly as before.

### Decorator parameters

All parameters are keyword-only and optional:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `title` | `str \| None` | Auto-generated from function name | Human-readable title |
| `description` | `str \| None` | `None` | Detailed description of what the function does |
| `tags` | `list[str] \| None` | `[]` | Categorization tags (e.g. `["statistics", "math"]`) |
| `deprecated` | `bool` | `False` | Mark the function as deprecated |
| `deprecation_message` | `str \| None` | `None` | Explain what to use instead |

Here is a more complete example with multiple functions:

```python title="src/my_tasks/tasks.py"
from wt_registry import register


@register(
    title="Calculate Mean",
    description="Compute the arithmetic mean of a list of floats",
    tags=["statistics", "math"],
)
def calculate_mean(values: list[float]) -> float:
    """Return the arithmetic mean of a list of numbers."""
    return sum(values) / len(values)


@register(
    title="Fetch Events",
    tags=["io", "earthranger"],
)
def fetch_events(url: str, limit: int = 100) -> dict:
    """Fetch event data from a remote API."""
    return {}


@register(
    title="Old Processor",
    deprecated=True,
    deprecation_message="Use new_processor instead",
)
def old_processor(data: list[int]) -> list[int]:
    """Legacy data processor."""
    return data
```

Don't forget to update `src/my_tasks/__init__.py` to re-export the new
functions if you add them.

!!! note
    Registration happens at **import time** -- as soon as Python executes the
    decorated function definition, the entry is added to the global registry.
    There is no separate "init" step.

## 4. Inspect the registry in Python

Use `get_registry()` to retrieve an immutable view of all registered functions:

```python title="inspect_registry.py"
from wt_registry import get_registry

# Import tasks module to trigger registration
import my_tasks  # noqa: F401

registry = get_registry()

for fqn, entry in registry.items():
    print(f"{fqn}")
    print(f"  Title:       {entry.metadata.title}")
    print(f"  Description: {entry.metadata.description}")
    print(f"  Tags:        {entry.metadata.tags}")
    print(f"  Deprecated:  {entry.metadata.deprecated}")
    print(f"  Import:      {entry.import_statement}")
    print()
```

Running this produces:

```
my_tasks.tasks.calculate_mean
  Title:       Calculate Mean
  Description: Compute the arithmetic mean of a list of floats
  Tags:        ['statistics', 'math']
  Deprecated:  False
  Import:      from my_tasks.tasks import calculate_mean

my_tasks.tasks.fetch_events
  Title:       Fetch Events
  Description: None
  Tags:        ['io', 'earthranger']
  Deprecated:  False
  Import:      from my_tasks.tasks import fetch_events

my_tasks.tasks.old_processor
  Title:       Old Processor
  Description: None
  Tags:        []
  Deprecated:  True
  Import:      from my_tasks.tasks import old_processor
```

`get_registry()` returns a `MappingProxyType` -- a read-only dict. You cannot
add or remove entries through it; that can only happen via the `@register`
decorator.

## 5. Use the CLI to export the registry

The `wt-registry` CLI is how wt-compiler discovers tasks in a real workflow
build. It imports the modules you specify with `--package`, which triggers
`@register`, then serializes the registry to stdout.

### Pretty (human-readable) output

```bash
wt-registry --package my_tasks --format pretty
```

```
=== my_tasks.tasks.calculate_mean ===
Title: Calculate Mean
Description: Compute the arithmetic mean of a list of floats
Tags: statistics, math
Deprecated: No
Import: from my_tasks.tasks import calculate_mean

=== my_tasks.tasks.fetch_events ===
Title: Fetch Events
Tags: io, earthranger
Deprecated: No
Import: from my_tasks.tasks import fetch_events

=== my_tasks.tasks.old_processor ===
Title: Old Processor
Deprecated: Yes (Use new_processor instead)
Import: from my_tasks.tasks import old_processor
```

### JSON output (default)

```bash
wt-registry --package my_tasks
```

This produces compact JSON conforming to the `RegistryOutput` schema from
wt-contracts. Add `--pretty` for indented output:

```bash
wt-registry --package my_tasks --pretty
```

### Filtering by function name

If you only need specific functions, use `--function`:

```bash
wt-registry --package my_tasks --function calculate_mean --format pretty
```

You can repeat `--function` to select multiple functions.

## 6. Understanding validation

wt-registry uses **lazy validation**: the `@register` decorator itself does
*not* validate your function's signature. Validation happens later, when the
JSON schema is first accessed (typically during CLI export or when you read
`entry.json_schema` in code).

This means a function with missing annotations will register successfully but
fail when you try to export it.

### All parameters must be typed

```python
@register()
def bad_function(x, y: int) -> str:  # 'x' has no type annotation
    return str(x + y)
```

Accessing the schema raises `ValidationError`:

```
wt_registry.exceptions.ValidationError:
  Function my_tasks.tasks.bad_function has untyped parameters: x.
  All parameters must have type annotations.
```

### Return type must be annotated

```python
@register()
def also_bad(x: int):  # no return type
    return x * 2
```

```
wt_registry.exceptions.ValidationError:
  Function my_tasks.tasks.also_bad has no return type annotation.
  Return type must be annotated.
```

### Async functions are not supported

```python
@register()
async def not_allowed(x: int) -> str:
    return str(x)
```

```
wt_registry.exceptions.ValidationError:
  Async functions are not supported: my_tasks.tasks.not_allowed.
  Only synchronous functions can be registered.
```

### Classes cannot be registered

```python
@register()
class NotAFunction:
    pass
```

```
wt_registry.exceptions.ValidationError:
  Classes are not supported: my_tasks.tasks.NotAFunction.
  Only functions can be registered.
```

### Duplicate registration

Registering two functions with the same fully qualified name (same module, same
name) raises `DuplicateRegistrationError` immediately at import time:

```
wt_registry.exceptions.DuplicateRegistrationError:
  Function my_tasks.tasks.calculate_mean is already registered
```

!!! tip
    If you see this error in tests, make sure you are calling
    `clear_registry()` between test cases to reset state. The registry is
    global and persists for the lifetime of the process.

## 7. JSON schema generation

Behind the scenes, wt-registry generates a JSON schema from each function's
type annotations using Pydantic's `TypeAdapter`. This schema describes the
function's parameters and their types, and is consumed by wt-compiler to
validate workflow YAML specifications.

You can inspect a function's schema directly:

```python
import json
from wt_registry import get_registry
import my_tasks  # noqa: F401

registry = get_registry()
entry = registry["my_tasks.tasks.calculate_mean"]
print(json.dumps(entry.json_schema, indent=2))
```

The output will look something like:

```json
{
  "properties": {
    "values": {
      "items": {
        "type": "number"
      },
      "title": "Values",
      "type": "array"
    }
  },
  "required": [
    "values"
  ],
  "type": "object"
}
```

!!! tip
    You can use `pydantic.Field` inside `typing.Annotated` to add descriptions,
    defaults, and other metadata to individual parameters. wt-registry includes
    a custom schema generator that surfaces these annotations in the JSON
    schema:

    ```python
    from typing import Annotated
    from pydantic import Field

    @register()
    def calculate_mean(
        values: Annotated[
            list[float],
            Field(description="List of numeric values to average"),
        ],
    ) -> float:
        return sum(values) / len(values)
    ```

## Summary

In this tutorial you learned how to:

- Install `wt-registry` (which brings in `wt-contracts` automatically)
- Create an installable task package with `pyproject.toml`
- Write a fully typed function and register it with `@register()`
- Provide optional metadata: title, description, tags, and deprecation info
- Inspect the registry programmatically with `get_registry()`
- Export the registry with the `wt-registry` CLI in JSON or human-readable format
- Understand the validation rules and how to fix common errors
- Access the generated JSON schema for a registered function

Next: [Building Your First Workflow](first-workflow.md) — wire your registered
tasks together in a `spec.yaml` and compile them into executable artifacts.
