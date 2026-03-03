# Core Concepts

This page walks through the main ideas behind `wt` — what a workflow is, what
it's made of, and how it goes from a YAML file to running code. Read this
before diving into the tutorials.

---

## Workflows and their output

A **workflow** is a pipeline of steps that produces a JSON result. Side effects
(writing files, calling APIs, updating databases) can happen along the way, but
the final output is always a JSON object — returned on stdout when running from
the CLI, or in the HTTP response body when triggered through the REST API.

---

## Registered functions — the building blocks

Workflows are composed of **registered functions**: ordinary Python functions
decorated with `@register`. Registration makes a function discoverable by the
compiler without importing its code directly.

```python
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

Every parameter and return type **must** have a type annotation. `wt` uses
those annotations to generate a JSON Schema for each function — and that schema
is what powers the auto-generated web forms that end users fill out to
configure a workflow.

The `@register` decorator accepts optional metadata (`title`, `description`,
`tags`, `deprecated`) but leaves the function itself completely unchanged — you
can still call it like any normal Python function.

---

## The DAG — how functions connect

Functions in a workflow form a **directed acyclic graph** (DAG). Each step can
reference the return value of an earlier step using `${{ workflow.<id>.return }}`
expressions. Data flows forward through the graph; cycles are not allowed.

```
┌──────────────────┐
│ generate_numbers  │
└────────┬─────────┘
         │  list[int]
         ▼
┌──────────────────┐
│  double_number    │  (mapped over each item)
└────────┬─────────┘
         │  list[int]
         ▼
┌──────────────────┐
│   sum_numbers     │
└──────────────────┘
         │  int
         ▼
      result
```

---

## The spec.yaml — expressing the DAG declaratively

The DAG is expressed in a file called **`spec.yaml`**. Its syntax borrows from
GitHub Actions (`${{ }}` expressions) and Astronomer's DAG Factory (declarative
DAG definition), with additions for fan-out, argument binding, conditional
execution, and task grouping.

Here is the spec for the three-step workflow above:

```yaml
id: double_and_sum

requirements:
  - name: my-tasks
    version: ">=0.1.0"

workflow:
  - id: numbers
    name: "Generate Numbers"
    task: generate_numbers
    partial:
      count: 5

  - id: doubled
    name: "Double Each Number"
    task: double_number
    map:
      argnames: value
      argvalues: ${{ workflow.numbers.return }}

  - id: total
    name: "Sum Results"
    task: sum_numbers
    partial:
      values: ${{ workflow.doubled.return }}
```

Key constructs:

- **`partial`** binds arguments to literal values or `${{ }}` references.
- **`map`** fans a task out over an iterable — one invocation per item.
- **`mapvalues`** fans out while preserving `(key, value)` pairs.
- **`skipif`** conditionally skips a task based on boolean condition functions.
- **Task groups** (`type: task-group`) organize related tasks under a heading.

---

## Compilation — from spec to executable

`wt-compiler` reads the spec and produces a **standalone Python package**:

```
wt-double-and-sum/
├── pixi.toml                       # Pinned conda environment
├── Dockerfile
├── graph.png                        # Visual DAG diagram
├── wt_double_and_sum/
│   ├── params.json                  # JSON Schema for web forms
│   ├── rjsf.json                    # React JSON Schema Form config
│   ├── cli.py                       # CLI entry point
│   └── dags/
│       └── run_sequential.py        # Generated DAG code
└── tests/
    └── ...
```

During compilation, the compiler:

1. Resolves `requirements` into a temporary conda environment.
2. Discovers registered functions by running `wt-registry` as a **subprocess**
   inside that environment — no direct imports, no dependency conflicts.
3. Validates the spec against the discovered function schemas.
4. Generates plain Python code that wires functions together using `wt-task`
   method chains (`.partial()`, `.map()`, `.call()`).
5. Pins every dependency version so the workflow is fully reproducible.

The compiled output is what actually runs. There is no interpreter at runtime —
what you see in the generated code is what executes.

```bash
wt-compiler compile --spec spec.yaml
```

---

## Execution — running the compiled workflow

Once compiled, a workflow can run in several ways:

- **Locally via CLI** — run the generated `cli.py` entry point directly.
- **Through the REST API** — `wt-runner` is a FastAPI server that accepts
  workflow parameters as JSON and returns the workflow's JSON output in the
  response body.
- **On Cloud Batch** — for heavy workloads requiring custom hardware, the
  runner can dispatch to Google Cloud Batch.

All execution paths produce the same JSON output; only the transport differs.

---

## Next steps

Now that you have the big picture, head to the
[tutorials](../tutorials/registering-tasks.md) to build a workflow from
scratch — starting with registering your first tasks.
