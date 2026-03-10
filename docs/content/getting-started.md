# Getting Started

Build a workflow from scratch in five steps. By the end you will have
registered a task, written a spec, compiled a workflow, and run it — both from
the CLI and via an auto-generated web form.

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
module to import when discovering tasks. By convention, use your package name as
the entry-point key (`custom-tasks`). The value (`custom_tasks.tasks`) is the
Python module containing your `@register`-decorated functions. Without this
entry point, the compiler will not find your functions.

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

## Step 2 — Your first spec.yaml

A **spec** declares which tasks to run and how data flows between them. Here is
the simplest possible workflow: one task, all parameters provided by the user at
runtime.

```yaml
--8<-- "examples/getting-started/single-task/spec.yaml"
```

!!! note "Replace the path"
    Change `/absolute/path/to/custom-tasks` to the actual absolute path to
    your `custom-tasks/` directory.

!!! warning "Local paths are for development only"
    The `path:` requirement installs a package from your local filesystem.
    Compiled workflows that use `path:` will not work on other machines.
    For distributable workflows, use `git:` or conda channel requirements
    instead — see [Distributing workflows](tutorials.md#coming-soon).

Let's walk through the spec field by field:

- **`id`** — a unique identifier for the workflow. The compiler uses this to
  name the output directory (`wt-<id>-workflow`).
- **`requirements`** — the packages the compiler must install to discover tasks.
  Each entry has a `name` and a source (`path:`, `git:`, or a conda channel).
- **`workflow`** — an ordered list of task instances. Each entry has:
    - **`id`** — identifies this task instance within the workflow. Used in
      `${{ }}` references and as the key in `--config-json`.
    - **`name`** — a human-readable label (used in web forms and logs).
    - **`task`** — the fully-qualified import path of the registered function.

For the full spec syntax, see the [`spec.yaml` reference](reference/spec-yaml.md).

---

## Step 3 — Compiling

Run the compiler to turn your spec into an executable workflow:

```bash
wt-compiler compile --spec spec.yaml
```

The compiler:

1. Resolves `requirements` into a temporary environment.
2. Discovers registered functions by running `wt-registry` as a subprocess.
3. Validates the spec against the discovered function schemas.
4. Generates a self-contained **pixi workspace** with DAG code, parameter
   schemas, a `pixi.toml`, and a Dockerfile.

The output directory is named `wt-add-two-numbers-workflow`. Take a look inside:

```
wt-add-two-numbers-workflow/
├── pixi.toml
├── Dockerfile
├── ...
├── wt_add_two_numbers_workflow/
│   ├── dags/             # Generated DAG code
│   ├── params.json       # Flat parameter schema (CLI)
│   ├── rjsf.json         # Hierarchical schema (web forms)
│   └── ...
└── tests/
    └── ...
```

Two schema files are generated from your type annotations:

- **`rjsf.json`** — hierarchical schema with `uiSchema` for form layout.
  [RJSF](https://rjsf-team.github.io/react-jsonschema-form/)-compatible.
- **`params.json`** — flat schema for CLI usage (`--config-json` / `--config-file`).

Both describe the same parameters; only the structure differs. For full detail
on compiled artifacts, see the
[wt-compiler reference](reference/wt-compiler.md).

---

## Step 4 — Configuration and running

Compiled workflows write their output to a **results directory** controlled by
an environment variable:

```bash
mkdir results
export WT_RESULTS=file://$(pwd)/results
```

### CLI

```bash
cd wt-add-two-numbers-workflow
pixi run wt-add-two-numbers-workflow run --config-json '{"total": {"a": 1, "b": 2}}'
```

!!! info "Two `run` commands?"
    `pixi run` launches a command inside the pixi environment. The second `run`
    is the workflow CLI's own `run` subcommand. Together:
    `pixi run <entrypoint> run --config-json ...`.

**Expected result** (contents of `result.json` in your results directory):

```json
{"result": 3, "error": null, "trace": null}
```

- Both parameters (`a` and `b`) are unbound, so they become user-facing
  configuration.
- The `--config-json` key `"total"` matches the task instance `id` in the spec.

### Web form

The compiler also generated an `rjsf.json` schema from your type annotations.
Here is what the auto-generated form looks like — try entering values for `a`
and `b` and watch the `formData` update live:

<div class="rjsf-form" data-schema-url="../examples/getting-started/single-task/rjsf.json"></div>

??? example "rjsf.json"

    ```json
    --8<-- "examples/getting-started/single-task/rjsf.json"
    ```

**The pipeline:** Type annotations → JSON Schema → RJSF web form.

The form is generated entirely from the type annotations on your `add`
function. For the full story on how the compiler produces form schemas and how
they relate to the CLI, see
[Concepts — Configuration and execution](concepts.md#configuration-and-execution).

---

## Step 5 — What's next

You now know how to register tasks, write a spec, compile a workflow, run it
from the CLI, and preview auto-generated web forms.

**Continue learning:**

- [**How-To Guides**](tutorials.md) — partial arguments, chaining task outputs,
  `map` fan-out, and more
- [**spec.yaml reference**](reference/spec-yaml.md) — complete field-by-field
  documentation including `map`, `mapvalues`, `skipif`, and task groups
- [**Concepts**](concepts.md) — the full mental model behind the framework
- [**wt-compiler reference**](reference/wt-compiler.md) — CLI options,
  compiled artifacts, and troubleshooting
