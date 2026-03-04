# Core Concepts

This page walks through the main ideas behind `wt` — what a workflow is, what
it's made of, and how it goes from a YAML file to running code.

---

## Workflows

A **workflow** is a pipeline of steps that produces a JSON result. Side effects
(writing files, calling APIs, updating databases) can happen along the way, but
the final output is always a JSON object — returned on stdout when running from
the CLI, or in the HTTP response body when triggered through the REST API.

---

## Registered functions

Workflows are composed of **registered functions**: ordinary Python functions
decorated with `@register` from `wt-registry`. Registration serves two
purposes:

1. **Discovery without imports.** The compiler discovers tasks by running
   `wt-registry` as a subprocess inside an ephemeral conda environment. This
   avoids importing task code directly, which would create dependency conflicts
   between the compiler and the task packages.

2. **Schema generation.** Type annotations on registered functions are used to
   generate JSON schemas — these schemas power auto-generated web forms and
   validate parameters at compile time.

```python
from wt_registry import register

@register(description="Generate a list of integers from 0 to count-1.")
def generate_numbers(count: int) -> list[int]:
    return list(range(count))
```

The `@register` decorator accepts optional metadata (`title`, `description`,
`tags`, `deprecated`) but leaves the function itself completely unchanged.

At runtime, the compiler wraps registered functions as **tasks** — instances of
`wt_task.SyncTask` with execution methods like `.call()`, `.map()`, and
`.partial()`. You never need to use `@task` directly; registration is all that
is required from function authors.

---

## The DAG

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

## The spec.yaml

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

For the complete field-by-field reference, see the
[`spec.yaml` reference](reference/spec-yaml.md).

---

## Compilation

`wt-compiler` reads the spec and produces a **standalone Python package**. The
"compile, don't interpret" design means there is no opaque runtime interpreter
— what you see in the generated code is what executes. This makes compiled
workflows easy to read, diff, and version-control.

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

---

## Execution

Once compiled, a workflow can run in several ways:

- **Locally via CLI** — run the generated entry point with `pixi run`.
- **Through the REST API** — `wt-runner` is a FastAPI server that accepts
  workflow parameters as JSON and returns the workflow's JSON output.
- **On Cloud Batch** — for heavy workloads, the runner can dispatch to Google
  Cloud Batch.

All execution paths produce the same JSON output; only the transport differs.

An **invoker** is an execution backend that runs a compiled workflow.
Implementations include `LocalSubprocessInvoker` (runs via `pixi run` locally)
and `CloudBatchInvoker` (dispatches to Google Cloud Batch).

---

## Key terms

| Term | Definition |
|------|------------|
| **Registered function** | A Python function decorated with `@register` from wt-registry. Makes the function discoverable by the compiler and generates a JSON schema from its type annotations. |
| **Task** | A runtime wrapper created by the compiler from a registered function. Provides `.call()`, `.map()`, `.partial()`, `.validate()`, and `.skipif()` methods. Developers register functions; the compiler generates the corresponding `task(...)` calls. |
| **Task instance** | A specific invocation of a task within a workflow, identified by its `id` in the `spec.yaml`. The same registered function can appear as multiple task instances with different parameters. |
| **Registry** | The global, in-process collection of all registered functions. Populated at import time by `@register` decorators. Accessed via `get_registry()` or the `wt-registry` CLI. |
| **Compiled workflow** | The output of compilation: a self-contained directory with generated DAG code, parameter schemas, a `pixi.toml`, Dockerfile, and tests. Executable via `pixi run` or wt-runner. |
| **Invoker** | An execution backend that runs a compiled workflow. See above. |
| **Runner** | The `wt-runner` FastAPI server that accepts workflow parameters over HTTP and dispatches execution to an invoker. |
| **Metapackage** | A dependency-only package (empty `__init__.py`) that bundles a core wt package with GCP-specific dependencies. Exists because conda does not support pip-style extras. |

---

## Tooling

`wt` sits at the intersection of two packaging ecosystems — **PyPI** (pip/uv)
and **conda** (pixi/rattler). Which one you reach for depends on what you are
doing.

### uv — Python package development

[uv](https://docs.astral.sh/uv/) is a fast Python package manager. It is
sufficient for writing task code, running tests, inspecting the registry, and
running the compiler. If your tasks depend on packages that are best installed
via conda (e.g. `geopandas`, `gdal`, `rasterio`), pixi is preferable.

### pixi — workflow execution and the conda ecosystem

[pixi](https://pixi.sh) is a cross-platform package manager built on the conda
ecosystem. Compiled workflows are **pixi projects** — the compiler outputs a
`pixi.toml`, and both execution backends invoke workflows via `pixi run`.

**pixi is required to run any compiled workflow end-to-end.**

If you want a single-tool experience, pixi can handle everything uv does (it
supports
[pypi-dependencies](https://pixi.sh/latest/reference/pixi_manifest/#pypi-dependencies)).

### How `requirements:` resolves

The `requirements:` section in `spec.yaml` resolves packages from **conda
channels only**. The compiler supports a fixed set of channels: `conda-forge`,
`microsoft`, the `ecoscope-workflows` prefix.dev channels, and local file-based
development channels. Specifying a channel outside this set raises a validation
error.

!!! tip "Roadmap — PyPI support in requirements"
    Support for pip-compatible package sources in the `requirements:` section
    is forthcoming. This will enable editable installs during development and
    simpler packaging workflows.

### Which tool when?

| You want to... | Use |
|---|---|
| Develop a task package (PyPI-only deps) | uv or pixi |
| Develop a task package with system deps | pixi |
| Run `wt-compiler compile` | uv or pixi |
| Run a compiled workflow | pixi (required) |
| Use one tool for everything | pixi |
