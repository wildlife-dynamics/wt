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

!!! info "Learn more"
    **Tutorial:** [Registering Tasks](../tutorials/registering-tasks.md) —
    hands-on walkthrough of the `@register` decorator.
    **Reference:** [wt-registry API](../reference/wt-registry/index.md) —
    full decorator options, registry API, and CLI.

Workflows are composed of **registered functions**: ordinary Python functions
decorated with `@register`. Registration serves two purposes:

1. **Discovery without imports.** The compiler discovers tasks by running
   `wt-registry` as a subprocess inside an ephemeral conda environment. This
   avoids importing task code directly, which would create dependency conflicts
   between the compiler and the task packages.

2. **Schema generation.** Type annotations on registered functions are used to
   generate JSON schemas — these schemas power the auto-generated web forms
   that end users fill out to configure a workflow, and they validate parameters
   at compile time.

```python
from wt_registry import register

@register(description="Generate a list of integers from 0 to count-1.")
def generate_numbers(count: int) -> list[int]:
    return list(range(count))
```

The `@register` decorator accepts optional metadata (`title`, `description`,
`tags`, `deprecated`) but leaves the function itself completely unchanged — you
can still call it like any normal Python function.

---

## The DAG — how functions connect

!!! info "Learn more"
    **Reference:** [wt-task API](../reference/wt-task/index.md) —
    the `@task` decorator and method chains (`.call()`, `.map()`, `.partial()`)
    that wire the DAG together at runtime.

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

!!! info "Learn more"
    **Tutorial:** [Building Your First Workflow](../tutorials/first-workflow.md) —
    write a complete `spec.yaml` step by step.
    **Reference:** [`spec.yaml` reference](../reference/spec-yaml.md) —
    full syntax for `partial`, `map`, `mapvalues`, `skipif`, and task groups.

The DAG is expressed in a file called **`spec.yaml`**. Its syntax borrows from
GitHub Actions (`${{ }}` expressions) and Astronomer's DAG Factory (declarative
DAG definition), with additions for fan-out, argument binding, conditional
execution, and task grouping.

Key constructs:

- **`partial`** binds arguments to literal values or `${{ }}` references.
- **`map`** fans a task out over an iterable — one invocation per item.
- **`mapvalues`** fans out while preserving `(key, value)` pairs.
- **`skipif`** conditionally skips a task based on boolean condition functions.
- **Task groups** (`type: task-group`) organize related tasks under a heading.

For a complete spec example, see the
[first-workflow tutorial](../tutorials/first-workflow.md#step-3-write-the-specyaml)
or the [spec.yaml reference](../reference/spec-yaml.md).

---

## Compilation — from spec to executable

!!! info "Learn more"
    **How-to:** [Compile a Workflow](../how-to/compile-workflow.md) —
    compile your first workflow end to end.
    **Reference:** [wt-compiler API](../reference/wt-compiler/index.md) —
    compiler internals, spec models, and task discovery.

`wt-compiler` reads the spec and produces a **standalone Python package**.
The "compile, don't interpret" design means there is no opaque runtime
interpreter — what you see in the generated code is what executes. This makes
compiled workflows easy to read, diff, and version-control.

During compilation, the compiler:

1. Resolves `requirements` into a temporary conda environment.
2. Discovers registered functions by running `wt-registry` as a **subprocess**
   inside that environment — no direct imports, no dependency conflicts.
3. Validates the spec against the discovered function schemas.
4. Generates plain Python code that wires functions together using `wt-task`
   method chains (`.partial()`, `.map()`, `.call()`).
5. Pins every dependency version so the workflow is fully reproducible.

The compiled output includes DAG code, parameter schemas (JSON Schema for web
forms), a `pixi.toml` for environment management, a Dockerfile, and tests.
See the [first-workflow tutorial](../tutorials/first-workflow.md#step-5-explore-the-compiled-artifacts)
for a detailed walkthrough of the output structure.

```bash
wt-compiler compile --spec spec.yaml
```

---

## Execution — running the compiled workflow

!!! info "Learn more"
    **Tutorial:** [Running a Workflow](../tutorials/running-a-workflow.md) —
    run a compiled workflow step by step.
    **Reference:** [wt-runner API](../reference/wt-runner/index.md) —
    FastAPI server, HTTP endpoints, and tracing.
    **Reference:** [wt-invokers API](../reference/wt-invokers/index.md) —
    execution backends (local subprocess, Cloud Batch).

Once compiled, a workflow can run in several ways:

- **Locally via CLI** — run the generated entry point with `pixi run`.
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
