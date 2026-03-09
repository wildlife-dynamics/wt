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

The `[project.entry-points."wt_registry"]` section tells `wt-registry` which
module to import when discovering tasks. Without this entrypoint, the compiler
will not find your functions.

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
uv venv
uv pip install -e ./custom-tasks
uv run wt-registry --package custom_tasks --format pretty
```

You should see each function listed with its title, description, and import
path.

??? example "Expected `--format pretty` output"

    ```
    === custom_tasks.tasks.add ===
    Title: Add
    Description: Add two integers.
    Deprecated: No
    Import: from custom_tasks.tasks import add

    === custom_tasks.tasks.double ===
    Title: Double
    Description: Double a number.
    Deprecated: No
    Import: from custom_tasks.tasks import double

    === custom_tasks.tasks.split_digits ===
    Title: Split Digits
    Description: Split an integer into its individual digits as strings.
    Deprecated: No
    Import: from custom_tasks.tasks import split_digits

    === custom_tasks.tasks.parse_int ===
    Title: Parse Int
    Description: Parse a string as an integer.
    Deprecated: No
    Import: from custom_tasks.tasks import parse_int
    ```

??? example "Expected `--format json` output (what the compiler consumes)"

    Use `--format json` (the default) to see the machine-readable output.
    The compiler consumes this JSON to generate web forms and perform
    input validation — each entry's `json_schema` defines the parameter
    types and constraints that drive the auto-generated UI.

    ```bash
    uv run wt-registry --package custom_tasks --format json
    ```

    ```json
    {"entries":{"custom_tasks.tasks.add":{"metadata":{"title":"Add","description":"Add two integers.","tags":[],"deprecated":false,"deprecation_message":null},"module_path":"custom_tasks.tasks","public_module_path":"custom_tasks.tasks","function_name":"add","import_statement":"from custom_tasks.tasks import add as add","json_schema":{"additionalProperties":false,"properties":{"a":{"title":"A","type":"integer"},"b":{"title":"B","type":"integer"}},"required":["a","b"],"type":"object"}},"custom_tasks.tasks.double":{"metadata":{"title":"Double","description":"Double a number.","tags":[],"deprecated":false,"deprecation_message":null},"module_path":"custom_tasks.tasks","public_module_path":"custom_tasks.tasks","function_name":"double","import_statement":"from custom_tasks.tasks import double as double","json_schema":{"additionalProperties":false,"properties":{"n":{"anyOf":[{"type":"integer"},{"type":"number"}],"title":"N"}},"required":["n"],"type":"object"}},"custom_tasks.tasks.split_digits":{"metadata":{"title":"Split Digits","description":"Split an integer into its individual digits as strings.","tags":[],"deprecated":false,"deprecation_message":null},"module_path":"custom_tasks.tasks","public_module_path":"custom_tasks.tasks","function_name":"split_digits","import_statement":"from custom_tasks.tasks import split_digits as split_digits","json_schema":{"additionalProperties":false,"properties":{"n":{"title":"N","type":"integer"}},"required":["n"],"type":"object"}},"custom_tasks.tasks.parse_int":{"metadata":{"title":"Parse Int","description":"Parse a string as an integer.","tags":[],"deprecated":false,"deprecation_message":null},"module_path":"custom_tasks.tasks","public_module_path":"custom_tasks.tasks","function_name":"parse_int","import_statement":"from custom_tasks.tasks import parse_int as parse_int","json_schema":{"additionalProperties":false,"properties":{"s":{"title":"S","type":"string"}},"required":["s"],"type":"object"}}},"version":"1.0.0"}
    ```

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
- **`trace`** — the Python traceback string if the workflow errored, otherwise `null`

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

!!! warning "Local paths are for development only"
    The `path:` requirement installs a package from your local filesystem.
    Compiled workflows that use `path:` will not work on other machines.
    For distributable workflows, use `git:` or conda channel requirements
    instead — see [Distributing workflows](tutorials.md#coming-soon).

**Compile and run:**

```bash
wt-compiler compile --spec spec.yaml
cd wt-add-two-numbers-workflow
pixi run wt-add-two-numbers-workflow run --config-json '{"sum": {"a": 1, "b": 2}}'
```

The compiler generates a directory named `wt-add-two-numbers-workflow`
containing a **pixi project** with a pixi task (entrypoint) of the same name.
The `--config-json` keys correspond to the **task instance IDs** from the spec.
For full detail on compiled artifacts, see the
[wt-compiler reference](reference/wt-compiler.md).

**Expected result** (contents of `result.json` in your results directory):

```json
{"result": 3, "error": null, "trace": null}
```

**Key points:**

- The `requirements` section uses a `path:` source to reference your local task
  package — no conda channel needed.
- Both parameters (`a` and `b`) are unbound, so they become user-facing
  configuration.
- The `--config-json` key `"sum"` matches the task instance `id` in the spec.

---

## Step 4 — Partial arguments

Bind one parameter at compile time so only the other is user-configurable.

```yaml
--8<-- "examples/getting-started/example-2/spec.yaml"
```

```bash
wt-compiler compile --spec spec.yaml --clobber
cd wt-add-with-partial-workflow
pixi run wt-add-with-partial-workflow run --config-json '{"sum": {"a": 1}}'
```

**Expected result** (contents of `result.json` in your results directory):

```json
{"result": 6, "error": null, "trace": null}
```

**Key points:**

- `partial` fixes `b` to `5`. Only `a` remains as a user parameter.
- The result is `1 + 5 = 6`.

---

## Step 5 — Piping task outputs

Chain two tasks together so the output of one feeds into the next.

```yaml
--8<-- "examples/getting-started/example-3/spec.yaml"
```

```bash
wt-compiler compile --spec spec.yaml --clobber
cd wt-add-then-double-workflow
pixi run wt-add-then-double-workflow run --config-json '{"sum": {"a": 3, "b": 3}}'
```

**Expected result** (contents of `result.json` in your results directory):

```json
{"result": 12, "error": null, "trace": null}
```

**Key points:**

- `${{ workflow.sum.return }}` references the return value of the `sum` task.
- Tasks must appear in **topological order** — every dependency before its
  dependent.
- The terminal task's return value becomes `result.json`'s `result` field.

---

## Step 6 — List return types

A task can return any JSON-serializable type, including lists.

```yaml
--8<-- "examples/getting-started/example-4/spec.yaml"
```

```bash
wt-compiler compile --spec spec.yaml --clobber
cd wt-add-then-split-workflow
pixi run wt-add-then-split-workflow run
```

**Expected result** (contents of `result.json` in your results directory):

```json
{"result": ["1", "2"], "error": null, "trace": null}
```

**Key points:**

- Both parameters of `add` are bound via `partial` (`4 + 8 = 12`), so there are
  no user-facing parameters.
- `split_digits(12)` returns `["1", "2"]` — a list of strings.
- This output is a natural input for `map`, which we cover in
  [How-To Guides](tutorials.md#map-fan-out).

---

## Step 7 — What's next

You now know how to register tasks, write specs with `partial` and `${{ }}`
references, compile workflows, and run them.

**Continue learning:**

- [**How-To Guides**](tutorials.md) — `map` fan-out picks up right where
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
| `--pkg-name-prefix PREFIX` | `wt` | Prefix for generated package/directory names |
| `--variant VARIANT` | *none* | Platform variant suffix (e.g. `gcp`) |
| `--no-progress` | off | Disable progress spinner (useful in CI) |
