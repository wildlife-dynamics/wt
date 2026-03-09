# Getting Started

Build a workflow from scratch in seven steps. Each step adds one concept and
produces a runnable workflow you can compile and test.

---

## Prerequisites

- Python 3.10 or later
- [uv](https://docs.astral.sh/uv/) — for package development and running the compiler
- [pixi](https://pixi.sh) — **required** to run compiled workflows
- `wt-compiler` — install with `uv pip install wt-compiler` or `pixi global install wt-compiler`

---

## Step 1 — Create a task package

The compiler discovers tasks by installing packages into an ephemeral
environment and running `wt-registry` as a subprocess. Your tasks must live in
an **installable Python package**.

### Directory structure

```
custom-tasks/
├── pyproject.toml
└── src/
    └── custom_tasks/
        ├── __init__.py
        └── tasks.py
```

### `pyproject.toml`

```toml
--8<-- "examples/custom-tasks/pyproject.toml"
```

### `src/custom_tasks/__init__.py`

Re-export the task functions so the compiler can import them:

```python
--8<-- "examples/custom-tasks/src/custom_tasks/__init__.py"
```

### `src/custom_tasks/tasks.py`

Every registered function **must** have complete type annotations on all
parameters and on the return type. These annotations drive JSON schema
generation for web forms and compile-time validation.

```python
--8<-- "examples/custom-tasks/src/custom_tasks/tasks.py"
```

The `@register` decorator auto-generates a title from the function name
(`add` becomes *Add*), stores the entry in a global registry, and returns the
original function unchanged.

### Install and verify

```bash
uv pip install -e ./custom-tasks
wt-registry --package custom_tasks --format pretty
```

You should see each function listed with its title, description, and import
path. Use `--format json` (the default) to see the machine-readable output
the compiler consumes.

For more on the decorator, validation rules, and JSON schema generation, see
the [wt-registry reference](reference/wt-registry.md).

---

## Step 2 — Set up results

Compiled workflows write their output to a **results directory**. The location
is controlled by an environment variable (default: `WT_RESULTS`).

```bash
mkdir results
export WT_RESULTS=file://$(pwd)/results
```

Each workflow run writes a `result.json` file with three fields:

- **`result`** — the return value of the terminal task (any JSON-serializable type)
- **`error`** — error details if the workflow failed, otherwise `null`
- **`trace`** — OpenTelemetry trace ID if tracing is enabled, otherwise `null`

Cloud storage (`gs://`, `s3://`) is also supported via
[obstore](https://developmentseed.org/obstore/).

---

## Step 3 — Single task

The simplest workflow: one task, all parameters provided by the user at
runtime.

```yaml
--8<-- "examples/getting-started/example-1/spec.yaml"
```

!!! note "Replace the path"
    Change `/absolute/path/to/custom-tasks` to the actual absolute path to
    your `custom-tasks/` directory.

**Compile and run:**

```bash
wt-compiler compile --spec spec.yaml --install
cd wt-add-two-numbers
pixi run workflow run --config-json '{"result": {"a": 1, "b": 2}}'
```

**Expected result:**

```json
{"result": 3, "error": null, "trace": null}
```

**Key point:** The `requirements` section uses a `path:` source to reference
your local task package — no conda channel needed. Both parameters (`a` and
`b`) are unbound, so they become user-facing configuration.

---

## Step 4 — Partial arguments

Bind one parameter at compile time so only the other is user-configurable.

```yaml
--8<-- "examples/getting-started/example-2/spec.yaml"
```

```bash
wt-compiler compile --spec spec.yaml --clobber --install
cd wt-add-with-partial
pixi run workflow run --config-json '{"result": {"a": 1}}'
```

**Expected result:**

```json
{"result": 6, "error": null, "trace": null}
```

**Key point:** `partial` fixes `b` to `5`. Only `a` remains as a user
parameter. The result is `1 + 5 = 6`.

---

## Step 5 — Piping task outputs

Chain two tasks together so the output of one feeds into the next.

```yaml
--8<-- "examples/getting-started/example-3/spec.yaml"
```

```bash
wt-compiler compile --spec spec.yaml --clobber --install
cd wt-add-then-double
pixi run workflow run --config-json '{"sum": {"a": 3, "b": 3}}'
```

**Expected result:**

```json
{"result": 12, "error": null, "trace": null}
```

**Key point:** `${{ workflow.sum.return }}` references the return value of the
`sum` task. Tasks must appear in **topological order** — every dependency
before its dependent. The terminal task's return value becomes `result.json`'s
`result` field.

---

## Step 6 — List return types

A task can return any JSON-serializable type, including lists.

```yaml
--8<-- "examples/getting-started/example-4/spec.yaml"
```

```bash
wt-compiler compile --spec spec.yaml --clobber --install
cd wt-add-then-split
pixi run workflow run
```

**Expected result:**

```json
{"result": ["1", "2"], "error": null, "trace": null}
```

**Key point:** Both parameters of `add` are bound via `partial`, so there are
no user-facing parameters. `split_digits` returns `["1", "2"]` — a list of
strings. This output is a natural input for `map`, which we cover in
[Tutorials](tutorials.md#map-fan-out).

---

## Step 7 — What's next

You now know how to register tasks, write specs with `partial` and `${{ }}`
references, compile workflows, and run them.

**Continue learning:**

- [**Tutorials**](tutorials.md) — `map` fan-out picks up right where
  Example 4 left off
- [**spec.yaml reference**](reference/spec-yaml.md) — complete field-by-field
  documentation including `map`, `mapvalues`, `skipif`, and task groups
- [**Concepts**](concepts.md) — the full mental model behind the framework
- [**wt-compiler reference**](reference/wt-compiler.md) — CLI options,
  compiled artifacts, and troubleshooting

### Quick reference: compiler CLI

| Flag | Default | Description |
|------|---------|-------------|
| `--spec FILE` | *(required)* | Path to the workflow `spec.yaml` |
| `--clobber` | off | Overwrite the output directory if it exists |
| `--update` | off | Carry over the lockfile and bump version (requires `--clobber`) |
| `--install` | off | Run `pixi install -a` after compilation |
| `--pkg-name-prefix PREFIX` | `wt` | Prefix for generated package/directory names |
| `--variant VARIANT` | *none* | Platform variant suffix (e.g. `gcp`) |
| `--no-progress` | off | Disable progress spinner (useful in CI) |
