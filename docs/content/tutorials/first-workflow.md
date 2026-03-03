# Building Your First Workflow

In this tutorial you will build a small data-processing workflow end-to-end:
define task functions, wire them together in a `spec.yaml`, and compile the
workflow into executable artifacts with `wt-compiler`.

!!! note "Prerequisites"
    This tutorial assumes you have already completed the
    [Registering Tasks](registering-tasks.md) tutorial and are comfortable with
    the `@register` decorator and how the registry works.

---

## What you will build

A three-step workflow that:

1. Generates a list of numbers.
2. Doubles each number (mapped over the list).
3. Sums the results into a single total.

By the end you will have a compiled workflow package containing Python DAG code,
JSON parameter schemas, and a `pixi.toml` for reproducible environments.

---

## Step 1 -- Install the packages

You need three packages: **wt-registry** (function registration), **wt-task**
(the `@task` runtime decorator), and **wt-compiler** (the compiler CLI).

```bash
pip install wt-registry wt-task wt-compiler
```

!!! tip
    If you use [uv](https://docs.astral.sh/uv/) you can install them in one
    shot with `uv pip install wt-registry wt-task wt-compiler`.

---

## Step 2 -- Create a task package

Create a small Python package that contains your task functions. The directory
layout looks like this:

```
my_tasks/
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

Every function has full type annotations and is decorated with `@register`.
The registry will auto-generate a title from the function name (for example,
`generate_numbers` becomes *Generate Numbers*).

Install your package in editable mode so the tasks are importable:

```bash
pip install -e ./my_tasks
```

### Verify registration

Run the `wt-registry` CLI to confirm the tasks are discoverable:

```bash
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

---

## Step 3 -- Write the spec.yaml

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

Let's break down what each section does:

**`id`** -- A unique identifier for the workflow. It must be a valid Python
identifier.

**`requirements`** -- The conda/pip packages the workflow depends on at runtime.
The compiler uses these to discover which tasks are available.

**`workflow`** -- An ordered list of task instances. Each entry specifies:

- **`id`** -- A unique name for this step, used to reference its return value
  elsewhere.
- **`task`** -- The registered function name (or a fully-qualified dotted path
  if names collide).
- **`partial`** -- Static keyword arguments bound to the task.
- **`map`** -- Applies the task to each element of an iterable, producing a list
  of results. `argnames` names the parameter to bind and `argvalues` is a
  reference to the iterable.

The `${{ workflow.<id>.return }}` syntax creates a dependency: `doubled` depends
on the return value of `numbers`, and `total` depends on the return value of
`doubled`. Tasks must appear in topological order -- every dependency is listed
before the task that uses it.

!!! tip
    For the full reference on every field in the spec format, see the
    [`spec.yaml` reference](../reference/spec-yaml.md) page.

---

## Step 4 -- Compile the workflow

Run the compiler, pointing it at your spec:

```bash
wt-compiler compile --spec spec.yaml
```

The compiler performs these steps automatically:

1. **Parses** the `requirements` from your spec.
2. **Creates an ephemeral conda environment** (via
   [py-rattler](https://github.com/conda/rattler)) containing those packages.
3. **Discovers tasks** by running the `wt-registry` CLI inside that environment
   and collecting the JSON schema for every registered function.
4. **Validates** the full spec against the discovered tasks (checking that
   referenced task names exist, argument names match function signatures, and
   dependencies are in topological order).
5. **Generates** the compiled artifacts.

You will see a progress spinner while this runs. When it finishes, you will see:

```
Compiled workflow to: /path/to/wt-double-and-sum
```

!!! warning
    The compiler needs network access to solve conda packages. If the output
    directory already exists, add `--clobber` to overwrite it.

---

## Step 5 -- Explore the compiled artifacts

The compiler produces a self-contained package directory. Here is what it looks
like:

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

The key files to look at:

- **`dags/run_sequential.py`** -- The compiled DAG. This is auto-generated
  Python code that imports your tasks via `wt-task`, wires up `.partial()`,
  `.map()`, and `.call()` invocations, and executes them in the correct order.

- **`params.json`** -- A JSON Schema describing every user-facing parameter of
  the workflow (in this case, the `count` argument of `generate_numbers`).
  Arguments that are wired to other task outputs are excluded since they are
  resolved automatically at runtime.

- **`pixi.toml`** -- A [pixi](https://pixi.sh) environment definition that pins
  every dependency to the exact versions the compiler solved. This ensures
  reproducible execution on any machine.

---

## What the compiled DAG looks like

The generated `run_sequential.py` will contain code similar to this (simplified
for clarity):

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

Notice the method chaining: each task is wrapped with `wt-task`, given a unique
instance ID, and then executed via `.call()` or `.map()`. The `.validate()`
method adds Pydantic parsing so string inputs from a web form or CLI are
coerced to the correct Python types. The `.handle_errors()` method ensures any
exception surfaces the task instance ID for easier debugging.

---

## Next steps

!!! note "Running compiled workflows requires pixi"
    The compiled output is a [pixi](https://pixi.sh) project. Both the local
    subprocess invoker and Cloud Batch invoker execute workflows via
    `pixi run`. See [Tooling & Prerequisites](../concepts/tooling.md) for
    install instructions and when to use pixi vs uv.

You have built, compiled, and inspected your first workflow. From here you can:

- **Run it locally** using the generated CLI or by invoking the DAG directly
  with `pixi run` inside the compiled directory.
- **Add more tasks** -- try grouping related steps with
  [task groups](../reference/spec-yaml.md#task-groups) for better organization.
- **Use `mapvalues`** to transform key-value pairs while preserving the keys
  (see the [spec reference](../reference/spec-yaml.md#mapvalues)).
- **Add `skipif` conditions** to conditionally skip expensive steps during dry
  runs.
- **Deploy** the workflow using the generated `Dockerfile` for containerized
  execution.
