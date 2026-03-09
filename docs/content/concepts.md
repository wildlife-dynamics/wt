# Core Concepts

This page walks through the main ideas behind `wt` — what a workflow is, what
it's made of, and how it goes from a YAML file to running code.

---

## Workflows

### Lifecycle

```
 Register            Specify             Compile              Run
┌────────────┐   ┌───────────────┐   ┌──────────────┐   ┌──────────────┐
│ @register  │   │ spec.yaml     │   │ wt-compiler  │   │ pixi run /   │
│ decorator  │-->│ declares the  │-->│ generates a  │-->│ wt-runner    │
│ marks      │   │ DAG and its   │   │ standalone   │   │ executes the │
│ functions  │   │ data flow     │   │ Python pkg   │   │ compiled DAG │
└────────────┘   └───────────────┘   └──────────────┘   └──────────────┘
```

1. **Register** — Decorate Python functions with `@register` (from the
   `wt-registry` package) to make them discoverable. Type annotations drive
   JSON schema generation for web forms.
2. **Specify** — Write a `spec.yaml` that declares which tasks to run, how data
   flows between them (`partial`, `map`, `mapvalues`), and what to skip.
3. **Compile** — `wt-compiler` resolves dependencies, validates the spec, and
   generates a self-contained pixi workspace with DAG code, parameter schemas,
   a `pixi.toml`, and a Dockerfile.
4. **Run** — Execute locally via the generated CLI (`pixi run`), through the
   `wt-runner` FastAPI server, or on Google Cloud Batch.

### Results

A **workflow** is a DAG of tasks that produces a JSON result. Side effects
(writing files, calling APIs, updating databases) can happen along the way, but
the final output is always a `result.json` file written to the results
directory configured by the `WT_RESULTS` environment variable. The file
contains three fields:

```json
{"result": <return value>, "error": <error string or null>, "trace": <traceback string or null>}
```

- **`result`** — the return value of the terminal task (any JSON-serializable
  type).
- **`error`** — error details if the workflow failed, otherwise `null`.
- **`trace`** — the Python traceback string if the workflow errored, otherwise
  `null`.

The output format is identical regardless of how the workflow is executed —
CLI, REST API, or Cloud Batch.

---

## Registered functions

Workflows are composed of **registered functions**: ordinary Python functions
decorated with `@register` from `wt-registry`. Registration serves two
purposes:

1. **Discovery without imports.** The compiler discovers tasks by running
   `wt-registry` as a subprocess in an ephemeral environment.

    !!! info "Why subprocess discovery?"
        Importing task code directly would force the compiler to install every
        task library's dependencies (GDAL, PyTorch, etc.). The subprocess
        approach keeps the compiler lightweight and avoids dependency conflicts.

2. **Schema generation.** Type annotations on registered functions are used to
   generate JSON schemas — these schemas power auto-generated web forms and
   validate parameters at compile time.

```python
from wt_registry import register

@register(description="Add two integers.")
def add(a: int, b: int) -> int:
    return a + b
```

This is the same `add` function used throughout
[Getting Started](getting-started.md).

The `@register` decorator accepts optional metadata (`title`, `description`,
`tags`, `deprecated`) but leaves the function itself completely unchanged. If
`title` is omitted, it is auto-generated from the function name (e.g. `add`
becomes *Add*).

At runtime, the compiler wraps registered functions as **tasks** — instances of
`wt_task.SyncTask` with execution methods like `.call()`, `.map()`, and
`.partial()`. You never need to use `@task` directly; registration is all that
is required from function authors.

---

## The DAG and spec.yaml

### Data flow

Functions in a workflow form a **directed acyclic graph** (DAG). In practical
terms: tasks are nodes, data flows forward along edges, and circular
dependencies are impossible — the compiler rejects them. If task B uses the
output of task A, then A must run before B.

Here is the add→double chain from
[How-To Guides — Chaining task outputs](tutorials.md#chaining-task-outputs),
expressed as a spec:

```yaml
workflow:
  - id: total
    name: "Add Two Numbers"
    task: custom_tasks.tasks.add

  - id: doubled
    name: "Double the Sum"
    task: custom_tasks.tasks.double
    partial:
      n: ${{ workflow.total.return }}
```

That spec produces the following DAG:

```
  user input
    a: int, b: int
         │
         ▼
  ┌─────────────┐
  │    total    │  add(a: int, b: int) -> int
  └──────┬──────┘
         │
         │  int  ─── ${{ workflow.total.return }}
         │
         ▼
  ┌─────────────┐
  │   doubled   │  double(n: int) -> int
  └──────┬──────┘
         │
         │  int
         ▼
    result.json
    {"result": 12, ...}
```

Key rules:

- Tasks are listed in **topological order** — every dependency before its
  dependent.
- `${{ workflow.<id>.return }}` references one task's output as another's input.
- The terminal (last) task's return value becomes the `result` field in
  `result.json`.

### spec.yaml

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

`wt-compiler` reads the spec and produces a **standalone pixi workspace**. The
"compile, don't interpret" design means there is no opaque runtime interpreter
— what you see in the generated code is what executes. This makes compiled
workflows easy to read, diff, and version-control.

During compilation, the compiler:

1. Resolves `requirements` into a temporary environment (conda packages and/or
   PyPI packages).
2. Discovers registered functions by running `wt-registry` as a **subprocess**
   inside that environment — no direct imports, no dependency conflicts.
3. Validates the spec against the discovered function schemas.
4. Generates plain Python code that wires functions together using `wt-task`
   method chains (`.partial()`, `.map()`, `.call()`).
5. Pins every dependency version so the workflow is fully reproducible.

The compiled output includes DAG code, parameter schemas (JSON Schema for web
forms), a `pixi.toml` for environment management, a Dockerfile, and tests. The
output directory is named `<prefix>-<id-with-hyphens>-workflow` — for example,
a spec with `id: add_then_double` and the default `wt` prefix produces
`wt-add-then-double-workflow`.

---

## Configuration and execution

Once compiled, a workflow needs **configuration** (parameter values) and an
**execution backend**. The compiler generates schemas that ensure configuration
is consistent across all interfaces.

### Auto-generated web forms

The compiler generates [RJSF](https://rjsf-team.github.io/react-jsonschema-form/)-compatible
JSON schemas from your type annotations. These schemas power auto-generated web
forms that let non-developers configure workflows without writing code or JSON.

Here is a live form generated from the add-then-double workflow:

<div class="rjsf-form" data-schema-url="../examples/getting-started/chaining-tasks/rjsf.json"></div>

**The pipeline:** Type annotations → JSON Schema → RJSF web form.

The compiler produces two schema files:

- **`rjsf.json`** — hierarchical schema with `uiSchema` for form layout. RJSF-compatible.
- **`params.json`** — flat schema for CLI usage (`--config-json` / `--config-file`).

Both describe the same parameters; the compiler guarantees that form submissions
from a rendered `rjsf.json` are compatible with the CLI's `--config-json` and
`--config-file` parameter schemas.

!!! note "Forms and execution"
    `wt-compiler` generates the form schemas but does **not** provide a built-in
    web UI or wire forms into workflow execution. Connecting rendered forms to an
    execution backend is the responsibility of the platform integrator — for
    example, [Ecoscope Platform](https://github.com/wildlife-dynamics/ecoscope-platform)
    (link TBD). The compiler's guarantee is schema compatibility: what the form
    produces is what the CLI accepts.

### CLI

Run the generated entry point with `pixi run`:

```bash
pixi run wt-add-then-double-workflow run --config-json '{"total": {"a": 3, "b": 3}}'
```

Parameters can also be loaded from a file:

```bash
pixi run wt-add-then-double-workflow run --config-file params.json
```

The `--config-json` keys correspond to task instance `id` values in the spec.
Only unbound parameters (those not fixed via `partial` or `${{ }}` references)
appear in the configuration.

### REST API and Cloud Batch

For production deployments, `wt-runner` is a FastAPI server that accepts
workflow parameters as JSON and dispatches execution to an **invoker**:

- **`LocalSubprocessInvoker`** — runs via `pixi run` locally.
- **`CloudBatchInvoker`** — dispatches to Google Cloud Batch for heavy
  workloads.

All execution paths produce the same `result.json` output; only the transport
differs.

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
and **conda** (pixi/rattler).

### uv — Python package development

[uv](https://docs.astral.sh/uv/) is a fast Python package manager. It is
sufficient for writing task code, running tests, inspecting the registry, and
running the compiler. If your tasks depend on packages that are best installed
via conda (e.g. `geopandas`, `gdal`, `rasterio`), pixi is preferable.

### pixi — workflow execution and the conda ecosystem

[pixi](https://pixi.sh) is a cross-platform package manager built on the conda
ecosystem. Compiled workflows are **pixi workspaces** — the compiler outputs a
`pixi.toml`, and both execution backends invoke workflows via `pixi run`.

**pixi is required to run any compiled workflow end-to-end.**

If you want a single-tool experience, pixi can handle everything uv does,
including [PyPI packages](https://pixi.sh/latest/reference/pixi_manifest/#pypi-dependencies).

### How `requirements:` resolves

The `requirements:` section in `spec.yaml` supports two kinds of package
sources:

- **Conda packages** — resolved from conda channels (`conda-forge`,
  `microsoft`, the `ecoscope-workflows` prefix.dev channels, and local
  file-based development channels). Specifying a channel outside this set
  raises a validation error.

- **PyPI packages** — referenced via `path:` (local filesystem), `git:`
  (Git repo URL), or `url:` (direct URL to a wheel or sdist). These are
  installed via `uv pip install` into the conda environment during task
  discovery, and appear in the compiled workflow's `pixi.toml` under
  `[pypi-dependencies]`.

For local development, `path:` is the simplest option — point directly at
your task package directory without needing to publish to any channel:

```yaml
requirements:
  - name: my-tasks
    path: /home/user/my-tasks
```

For the complete requirements reference, see
[spec.yaml — requirements](reference/spec-yaml.md#requirements).

### Which tool when?

| You want to... | Use |
|---|---|
| Develop a task package | uv or pixi |
| Run `wt-compiler compile` | uv or pixi |
| Run a compiled workflow | pixi (required) |
| Use one tool for everything | pixi |
