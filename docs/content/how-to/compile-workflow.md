# Compile a Workflow

This guide walks you through compiling a workflow specification into
executable artifacts using the `wt-compiler compile` command.

---

## Prerequisites

Before compiling, ensure:

1. **wt-compiler is installed** in your environment:

    ```bash
    pip install wt-compiler
    ```

    or via conda/pixi:

    ```bash
    pixi add wt-compiler
    ```

2. **You have a valid `spec.yaml`** that declares the workflow tasks,
   dependencies, and requirements. See the
   [`spec.yaml` reference](../reference/spec-yaml.md) for the
   complete format.

3. **The packages listed in your spec's `requirements` section are available**
   on the configured conda channels. The compiler creates an ephemeral
   environment from those requirements to discover registered tasks.

---

## Basic compilation

Pass the path to your spec file with the `--spec` flag:

```bash
wt-compiler compile --spec spec.yaml
```

The compiler runs through four phases:

1. **Parse requirements** from the YAML file.
2. **Discover tasks** by solving and installing the requirements into a
   temporary conda environment, then calling the `wt-registry` CLI.
3. **Validate the full spec** (now possible because the task registry is
   populated).
4. **Generate artifacts** -- DAG code, parameter schemas, Dockerfile,
   `pixi.toml`, tests, and a dependency graph image.

On success you will see:

```
Compiled workflow to: /path/to/wt-my-workflow-workflow
```

---

## CLI options

The full set of flags for `wt-compiler compile`:

| Flag | Default | Description |
|------|---------|-------------|
| `--spec FILE` | *(required)* | Path to the workflow `spec.yaml`. |
| `--clobber` | off | Overwrite the output directory if it already exists. |
| `--update` | off | Carry over the lockfile from the previous build and bump the version. Requires `--clobber` and must not be combined with `--install`. |
| `--install` | off | Run `pixi install -a` after compilation to generate a lockfile and install all dependencies. |
| `--pkg-name-prefix PREFIX` | `wt` | Prefix for the generated package and directory names. |
| `--variant VARIANT` | *none* | Platform variant suffix. For example, `--variant gcp` emits `wt-runner-gcp` and `wt-task-gcp` dependencies instead of the base packages. |
| `--results-env-var ENV_VAR` | `WT_RESULTS` | Name of the environment variable the generated CLI reads for the results URL. |
| `--no-progress` | off | Disable the progress spinner (useful in CI). |

---

## Compilation output

Given a spec with `id: patrol_events`, the compiler produces a directory
named `wt-patrol-events-workflow/` (derived from the prefix, the spec ID
with underscores replaced by hyphens, and the `-workflow` suffix).

The directory structure looks like this:

```
wt-patrol-events-workflow/
├── pixi.toml                # Pixi workspace with dependencies, features, and tasks
├── pixi.lock                # (only if --install was passed)
├── Dockerfile               # Container build for the workflow
├── .dockerignore
├── graph.png                # Dependency graph of the DAG
├── README.md                # Includes a fingerprint for change detection
├── VERSION.yaml             # Semantic version (MAJ.MIN.PATCH)
├── tests/
│   ├── conftest.py
│   ├── test_metadata.py
│   └── test_results.py
└── wt_patrol_events_workflow/   # Python package
    ├── __init__.py
    ├── cli.py               # Click CLI entry point
    ├── dispatch.py           # DAG dispatch logic
    ├── metadata.py           # Workflow metadata
    ├── response.py           # Response model
    ├── params.py             # Pydantic model (flat parameters)
    ├── formdata.py           # Pydantic model (hierarchical / RJSF)
    ├── params.json           # Flat JSON Schema
    ├── rjsf.json             # Hierarchical JSON Schema with UI overrides
    └── dags/
        ├── __init__.py
        ├── run_sequential.py          # Sequential DAG
        └── run_sequential_mock_io.py  # Sequential DAG with mocked I/O tasks
```

### Key artifacts

- **`pixi.toml`** -- Contains a `[workspace]`, `[dependencies]`, and
  three environments: `default` (workflow code), `runner`
  (`wt-runner` for the FastAPI server), and `test` (pytest and browser
  testing with Playwright).
- **`dags/run_sequential.py`** -- The real DAG that imports and calls
  every task in topological order.
- **`dags/run_sequential_mock_io.py`** -- A testing variant where tasks
  tagged `io` are replaced with mock functions.
- **`VERSION.yaml`** -- Starts at `0.0`. When you re-compile with
  `--clobber --update`, the compiler bumps the version: a minor bump if
  only code changed, a major bump if the parameter schema changed.

---

## Common recipes

### Overwrite an existing build

```bash
wt-compiler compile --spec spec.yaml --clobber
```

Without `--clobber`, the compiler raises a `FileExistsError` if the
output directory already exists.

### Re-compile and preserve the lockfile

```bash
wt-compiler compile --spec spec.yaml --clobber --update
```

This carries the `pixi.lock` from the previous build into the new output
and bumps the version in `VERSION.yaml`. It requires that the previous
build directory contains `pixi.lock`, `VERSION.yaml`, and `README.md`.

!!! warning
    `--update` is only valid together with `--clobber` and without
    `--install`. The compiler exits with an error if this constraint is
    violated.

### Compile and install dependencies

```bash
wt-compiler compile --spec spec.yaml --install
```

After writing artifacts, the compiler runs `pixi install -a` to solve
and lock all dependencies. This is convenient for local development but
not typically used in CI where lockfiles are committed.

### Compile with a GCP variant

```bash
wt-compiler compile --spec spec.yaml --variant gcp
```

This changes the generated `pixi.toml` to depend on `wt-runner-gcp` and
`wt-task-gcp` instead of the base packages, pulling in GCP-specific
dependencies (Cloud Batch, Pub/Sub, OpenTelemetry tracing).

### Change the package name prefix

```bash
wt-compiler compile --spec spec.yaml --pkg-name-prefix myorg
```

The output directory becomes `myorg-<id>-workflow/` and the Python
package becomes `myorg_<id>_workflow/`.

### Use in CI (no spinner)

```bash
wt-compiler compile --spec spec.yaml --no-progress
```

The progress spinner is also automatically disabled when stderr is not a
TTY.

---

## Troubleshooting

### `FileExistsError: Path '...' already exists`

The output directory already exists. Add `--clobber` to overwrite it:

```bash
wt-compiler compile --spec spec.yaml --clobber
```

### `wt-registry executable not found`

The compiler creates a temporary conda environment from your spec's
`requirements` and looks for the `wt-registry` CLI inside it. This
error means none of your listed packages depend on `wt-registry`.

Fix: ensure at least one package in your `requirements` has
`wt-registry` as a conda dependency, or add `wt-registry` explicitly:

```yaml
requirements:
  - name: wt-registry
    version: ">=0.1.0"
  - name: my-tasks-package
    version: ">=1.0"
```

### `wt-registry CLI failed with exit code ...`

The `wt-registry` executable was found but returned an error. The
compiler prints `stdout` and `stderr` from the failed command. Common
causes:

- An incompatible version of `wt-registry`.
- A missing or broken dependency in the environment.
- An import error in one of the registered task modules.

### `Environment creation failed during solve phase`

Dependency resolution could not find a compatible set of packages. Check
that:

- Package names and version constraints in `requirements` are correct.
- The specified channels are reachable.
- There are no conflicting version constraints between packages.

### `Environment creation failed during install phase`

Package installation into the temporary environment failed. If the
error mentions "Directory not empty" (ENOTEMPTY), it is a transient
filesystem race condition -- the compiler retries automatically up to
three times. If it persists:

- Try running the command again.
- Clear the rattler package cache.
- Increase the file descriptor limit: `ulimit -n 4096`.

!!! tip
    The compiler automatically tries to raise the file descriptor limit
    to 4096 at startup. If your system hard limit is lower, you may see
    a warning -- this is usually harmless.

### `--update` rejected

The `--update` flag requires:

- `--clobber` to be set (you are replacing the old build).
- `--install` to **not** be set (lockfile comes from the prior build).
- The previous build directory to contain `pixi.lock`, `VERSION.yaml`,
  and `README.md`.

If any of these conditions is not met, the compiler exits with an error
message explaining the constraint.

### `Task '<name>' not found in known tasks`

A task referenced in the `workflow` section of your spec was not
discovered during the registry scan. Verify that:

- The task is decorated with `@register` in its source package.
- The package is listed in `requirements`.
- The task name or fully qualified reference is spelled correctly.

!!! tip
    If two packages export a task with the same function name, you must
    use the fully qualified dotted path in your spec (for example,
    `mypackage.tasks.extract` instead of just `extract`).
