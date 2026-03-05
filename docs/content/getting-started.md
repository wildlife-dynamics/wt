# Getting Started

This guide walks you through building a workflow end-to-end: register task
functions, wire them together in a `spec.yaml`, compile the workflow, and run
it. By the end you will have a working workflow that generates numbers, doubles
them, and sums the results.

---

## Prerequisites

- Python 3.10 or later
- [uv](https://docs.astral.sh/uv/) or [pixi](https://pixi.sh) — see
  [Concepts — Tooling](concepts.md#tooling) for when to use which
- [pixi](https://pixi.sh) is **required** to run compiled workflows

---

## 1. Create a task package

!!! tip "Already have tasks?"
    If you're composing a workflow entirely from tasks in an existing registry,
    skip to [Step 2. Write the spec](#2-write-the-spec).

The compiler discovers tasks by installing packages into an ephemeral
environment and running `wt-registry` as a subprocess. This means your tasks
must live in an **installable Python package** — a standalone `.py` file is not
enough.

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
    "wt-task",
]

[tool.setuptools.packages.find]
where = ["src"]
```

### `src/my_tasks/__init__.py`

Re-export the task functions so the compiler can import them with a clean path:

```python
from my_tasks.tasks import double_number, generate_numbers, sum_numbers
```

### `src/my_tasks/tasks.py`

Every registered function **must** have complete type annotations on all
parameters and on the return type. These annotations drive JSON schema
generation for web forms and compile-time validation.

```python
"""Simple numeric tasks for our first workflow."""

from wt_registry import register


@register(description="Generate a list of integers from 0 to count-1.")
def generate_numbers(count: int) -> list[int]:
    return list(range(count))


@register(description="Double a single integer.")
def double_number(value: int) -> int:
    return value * 2


@register(description="Sum a list of integers.")
def sum_numbers(values: list[int]) -> int:
    return sum(values)
```

The `@register` decorator auto-generates a title from the function name
(`generate_numbers` becomes *Generate Numbers*), stores the entry in a global
registry, and returns the original function unchanged.

### Decorator parameters

All parameters are keyword-only and optional:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `title` | `str \| None` | Auto-generated from function name | Human-readable title |
| `description` | `str \| None` | `None` | Detailed description |
| `tags` | `list[str] \| None` | `[]` | Categorization tags (e.g. `["statistics", "math"]`) |
| `deprecated` | `bool` | `False` | Mark the function as deprecated |
| `deprecation_message` | `str \| None` | `None` | Explain what to use instead |

### Install and verify

Install your package in editable mode, then verify the tasks are discoverable:

```bash
pip install -e ./my-tasks
wt-registry --package my_tasks --format pretty
```

You should see output like:

```
=== my_tasks.tasks.generate_numbers ===
Title: Generate Numbers
Description: Generate a list of integers from 0 to count-1.
Deprecated: No
Import: from my_tasks.tasks import generate_numbers as generate_numbers

=== my_tasks.tasks.double_number ===
Title: Double Number
Description: Double a single integer.
Deprecated: No
Import: from my_tasks.tasks import double_number as double_number

=== my_tasks.tasks.sum_numbers ===
Title: Sum Numbers
Description: Sum a list of integers.
Deprecated: No
Import: from my_tasks.tasks import sum_numbers as sum_numbers
```

Use `--format json` (the default) to see the machine-readable output that
the compiler consumes, or add `--function calculate_mean` to filter by name.

### Validation rules

wt-registry uses **lazy validation**: the `@register` decorator itself does
not validate your function's signature. Validation happens when the JSON schema
is first accessed (typically during CLI export or compilation).

| Rule | Error |
|------|-------|
| All parameters must have type annotations | `ValidationError: ... has untyped parameters: x` |
| Return type must be annotated | `ValidationError: ... has no return type annotation` |
| Async functions are not supported | `ValidationError: Async functions are not supported` |
| Classes cannot be registered | `ValidationError: Classes are not supported` |
| Duplicate fully-qualified names | `DuplicateRegistrationError` (raised at import time) |

### Packaging for distribution

For the compiler to resolve your task package from `requirements:`, it must be
available on a conda channel. The simplest approach for local development is a
**local file-based conda channel** built with `pixi build`.

#### Using pixi build

```bash
# Build a conda package from your pixi project
pixi build
```

This produces a local conda package. Point the compiler to the output directory
as a local channel.

#### Standard pip packaging

Task packages use standard `pyproject.toml` and can be published to PyPI or
installed locally. This works for local development and registries whose
dependencies are all on PyPI. However, the compiler's `requirements:` section
currently resolves from **conda channels only** — see
[Concepts — Tooling](concepts.md#tooling) for details and the PyPI roadmap.

#### Key requirements for discoverability

- Your package must declare `wt-registry` as a dependency (so the CLI is
  available in the ephemeral environment).
- Your tasks must be importable via the package name (i.e. `import my_tasks`
  must trigger registration).
- Every task function must have complete type annotations.

### JSON schema generation

Behind the scenes, wt-registry generates a JSON schema from each function's
type annotations using Pydantic's `TypeAdapter`. You can inspect a function's
schema directly:

```python
import json
from wt_registry import get_registry
import my_tasks  # noqa: F401

registry = get_registry()
entry = registry["my_tasks.tasks.generate_numbers"]
print(json.dumps(entry.json_schema, indent=2))
```

You can use `pydantic.Field` inside `typing.Annotated` to add descriptions,
defaults, and other metadata to individual parameters:

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

---

## 2. Write the spec

Create a file called `spec.yaml` next to your task package:

```yaml
id: double_and_sum

requirements:
  - name: my-tasks
    version: ">=0.1.0"

workflow:
  # Step 1: generate a list of numbers
  - id: numbers
    name: "Generate Numbers"
    task: generate_numbers

  # Step 2: double each number (map over the list)
  - id: doubled
    name: "Double Each Number"
    task: double_number
    map:
      argnames: value
      argvalues: ${{ workflow.numbers.return }}

  # Step 3: sum the doubled values
  - id: total
    name: "Sum Results"
    task: sum_numbers
    partial:
      values: ${{ workflow.doubled.return }}
```

**`id`** — A unique identifier for the workflow (valid Python identifier).

**`requirements`** — Conda packages the workflow depends on at runtime. The
compiler uses these to discover which tasks are available.

**`workflow`** — An ordered list of task instances. Each entry specifies:

- **`id`** — A unique name for this step, used to reference its return value
  elsewhere via `${{ workflow.<id>.return }}`.
- **`task`** — The registered function name (or a fully-qualified dotted path
  if names collide).
- **`partial`** — Static keyword arguments bound to the task.
- **`map`** — Applies the task to each element of an iterable, producing a list
  of results. `argnames` names the parameter to bind and `argvalues` is a
  reference to the iterable.

Tasks must appear in **topological order** — every dependency is listed before
the task that uses it.

### Additional patterns

**Fan-out with `mapvalues`** — like `map`, but operates on key-value pairs and
preserves the keys. The upstream task must return a `Sequence[tuple[K, V]]`:

```yaml
  - id: results
    task: process_group
    mapvalues:
      argnames: group_data
      argvalues: ${{ workflow.grouped.return }}
```

**Conditional execution with `skipif`** — skip a task based on boolean
condition functions:

```yaml
  - id: expensive_step
    task: run_model
    partial:
      data: ${{ workflow.fetch.return }}
    skipif:
      conditions:
        - is_dry_run
      unpack_depth: 1
```

**Task groups** — group related tasks under a heading for organization (no
effect on execution):

```yaml
  - type: task-group
    title: "Data Ingestion"
    description: "Fetch data from all sources"
    tasks:
      - id: fetch_a
        task: fetch_source_a
      - id: fetch_b
        task: fetch_source_b
```

For the complete field-by-field reference, see [`spec.yaml`](reference/spec-yaml.md).

---

## 3. Compile the workflow

!!! warning "Requirements resolve from conda channels"
    The `requirements:` section resolves packages from **conda channels only**.
    `my-tasks` must be available as a conda package for the compiler to discover
    it. See [Packaging for distribution](#packaging-for-distribution) above
    for instructions on building conda packages from your task code. PyPI
    support in `requirements:` is on the roadmap.

Run the compiler:

```bash
wt-compiler compile --spec spec.yaml
```

The compiler:

1. **Parses** the `requirements` from your spec.
2. **Creates an ephemeral conda environment** (via
   [py-rattler](https://github.com/conda/rattler)) containing those packages.
3. **Discovers tasks** by running the `wt-registry` CLI inside that environment.
4. **Validates** the spec against the discovered tasks.
5. **Generates** the compiled artifacts.

On success:

```
Compiled workflow to: /path/to/wt-double-and-sum
```

### CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `--spec FILE` | *(required)* | Path to the workflow `spec.yaml`. |
| `--clobber` | off | Overwrite the output directory if it already exists. |
| `--update` | off | Carry over the lockfile from the previous build and bump the version. Requires `--clobber` and must not be combined with `--install`. |
| `--install` | off | Run `pixi install -a` after compilation to generate a lockfile. |
| `--pkg-name-prefix PREFIX` | `wt` | Prefix for the generated package and directory names. |
| `--variant VARIANT` | *none* | Platform variant suffix (e.g. `--variant gcp` emits GCP dependencies). |
| `--results-env-var ENV_VAR` | `WT_RESULTS` | Environment variable the generated CLI reads for the results URL. |
| `--no-progress` | off | Disable the progress spinner (useful in CI). |

### Common recipes

```bash
# Overwrite an existing build
wt-compiler compile --spec spec.yaml --clobber

# Re-compile and preserve the lockfile (bumps version)
wt-compiler compile --spec spec.yaml --clobber --update

# Compile and install dependencies
wt-compiler compile --spec spec.yaml --install

# Compile with GCP variant
wt-compiler compile --spec spec.yaml --variant gcp

# Change the package name prefix
wt-compiler compile --spec spec.yaml --pkg-name-prefix myorg
```

### Troubleshooting

| Error | Fix |
|-------|-----|
| `FileExistsError: Path '...' already exists` | Add `--clobber` to overwrite. |
| `wt-registry executable not found` | Ensure at least one package in `requirements` depends on `wt-registry`, or add it explicitly. |
| `wt-registry CLI failed with exit code ...` | Check for incompatible versions, missing dependencies, or import errors in task modules. |
| `Environment creation failed during solve phase` | Check package names, version constraints, and channel reachability. |
| `Task '<name>' not found in known tasks` | Verify the task is decorated with `@register`, the package is in `requirements`, and the name is spelled correctly. Use the fully qualified path if two packages export the same function name. |

### Compiled artifacts

The compiler produces a self-contained package directory:

```
wt-double-and-sum/
├── pixi.toml                 # Reproducible environment definition
├── Dockerfile                # Container image for deployment
├── .dockerignore
├── README.md                 # Auto-generated documentation with DAG graph
├── VERSION.yaml              # Semantic version tracking
├── graph.png                 # Visual DAG of the workflow
├── tests/
│   ├── conftest.py
│   ├── test_metadata.py
│   └── test_results.py
└── wt_double_and_sum/        # Python package
    ├── __init__.py
    ├── params.json            # JSON Schema for workflow parameters
    ├── params.py              # Pydantic parameter models
    ├── formdata.py            # Form-data models for web UIs
    ├── rjsf.json              # React JSON Schema Form configuration
    ├── cli.py                 # CLI entry point for running the workflow
    ├── dispatch.py            # Dispatch logic for execution backends
    ├── metadata.py            # Workflow metadata
    ├── response.py            # Response models
    └── dags/
        ├── __init__.py
        ├── run_sequential.py       # Sequential DAG execution code
        └── run_sequential_mock_io.py  # DAG with mocked I/O for testing
```

### What the compiled DAG looks like

The generated `run_sequential.py` contains code similar to this (simplified):

```python
from my_tasks import generate_numbers, double_number, sum_numbers
from wt_task import task

# Wrap each imported function as a Task
generate_numbers = task(generate_numbers)
double_number = task(double_number)
sum_numbers = task(sum_numbers)

def run(params: dict):
    # Step 1: generate numbers
    numbers = (
        generate_numbers
        .set_task_instance_id("numbers")
        .validate()
        .handle_errors()
        .call(count=params["numbers"]["count"])
    )

    # Step 2: double each number (map)
    doubled = (
        double_number
        .set_task_instance_id("doubled")
        .validate()
        .handle_errors()
        .map("value", numbers)
    )

    # Step 3: sum results
    total = (
        sum_numbers
        .set_task_instance_id("total")
        .partial(values=doubled)
        .validate()
        .handle_errors()
        .call()
    )

    return total
```

Each task is wrapped with `wt-task`, given a unique instance ID, then executed
via `.call()` or `.map()`. The `.validate()` method adds Pydantic parsing so
string inputs from a web form or CLI are coerced to the correct Python types.

---

## 4. Run the workflow

### Install dependencies

```bash
cd wt-double-and-sum
pixi install
```

### Run via the generated CLI

Pass parameters as a JSON string:

```bash
pixi run workflow run --config-json '{"numbers": {"count": 5}}'
```

Or create a YAML config file:

```yaml title="config.yaml"
numbers:
  count: 5
```

```bash
pixi run workflow run --config-file config.yaml
```

Parameter keys correspond to **task instance IDs** from the spec. Only
parameters that are *not* wired to other task outputs appear here — `numbers.count`
is the only user-facing parameter because `doubled` and `total` get their
inputs from other task outputs.

### Inspect the output

The workflow prints a JSON result to stdout:

```json
{
  "result": 20
}
```

The result is `20` because: `generate_numbers(5)` produces `[0, 1, 2, 3, 4]`,
`double_number` maps over each to produce `[0, 2, 4, 6, 8]`, and
`sum_numbers` returns `0 + 2 + 4 + 6 + 8 = 20`.

### Run with mock I/O

If your workflow includes tasks tagged with `io`, the compiler generates a mock
variant. Activate it with `--mock-io`:

```bash
pixi run workflow run --config-file config.yaml --mock-io
```

### OpenTelemetry tracing

```bash
pixi run workflow run --config-file config.yaml --otel-exporter console
```

Use `--otel-exporter gcp` for Google Cloud Trace export. Tracing is off by
default.

### Run via wt-runner (HTTP)

For production use, workflows are typically executed through `wt-runner`, a
FastAPI server. The compiled workflow includes a `runner` pixi environment:

```bash
pixi run -e runner start
```

Then trigger the workflow via HTTP:

```bash
curl -X POST http://localhost:8080/workflow \
  -H "Content-Type: application/json" \
  -d '{"params": {"numbers": {"count": 5}}}'
```

The server can dispatch to different backends (local subprocess, Cloud Batch)
depending on configuration. See the [wt-runner](reference/wt-runner.md) and
[wt-invokers](reference/wt-invokers.md) reference pages for details.
