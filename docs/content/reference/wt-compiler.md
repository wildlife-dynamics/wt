# wt-compiler

`wt-compiler` is the build tool of the wt ecosystem. Given a `spec.yaml`, it
produces a self-contained workflow package containing executable Python DAG
code, JSON parameter schemas, CLI entry point, pixi configuration, Dockerfile,
tests, and a dependency graph visualization.

The compiler operates without importing task code — see
[Task Discovery](#task-discovery) below.

**Modules:** `compiler` · `spec` · `discovery` · `artifacts` · `cli` ·
`exceptions` · `jsonschema` · `requirements` · `formatting`

---

## DagCompiler

The core engine that transforms a validated `Spec` into workflow artifacts.

### Constructor

```python
DagCompiler(
    spec: Spec,
    env_overrides: EnvOverrides | None = None,
    installed_requirement_names: set[str] = set(),
    variant: str | None = None,
    jinja_templates_dir: Path = TEMPLATES,
    pkg_name_prefix: str = "wt",
    results_env_var: str = "WT_RESULTS",
)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `spec` | `Spec` | *(required)* | Validated workflow specification |
| `env_overrides` | `EnvOverrides \| None` | `None` | Parsed user-supplied override file. See [Injected Dependencies](#injected-dependencies). |
| `installed_requirement_names` | `set[str]` | `set()` | Names supplied by the spec's transitive solve, used to suppress same-name baseline entries. |
| `variant` | `str \| None` | `None` | Platform variant suffix (e.g. `"gcp"`) — appended to `wt-task` / `wt-runner` package names |
| `jinja_templates_dir` | `Path` | `TEMPLATES` | Path to Jinja2 templates (built-in default) |
| `pkg_name_prefix` | `str` | `"wt"` | Prefix for generated package names |
| `results_env_var` | `str` | `"WT_RESULTS"` | Environment variable name |

### Key Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `.compile()` | `WorkflowArtifacts` | Generate all workflow artifacts |
| `.get_params_jsonschema(flat=True)` | `dict` | Generate JSON Schema for parameters |
| `.render_dag()` | `str` | Render DAG Python file from Jinja2 template |
| `.generate_params_model()` | `str` | Generate Pydantic model from JSON schema |
| `.get_pixi_toml()` | `PixiToml` | Generate pixi configuration |
| `.build_pydot_graph()` | `pydot.Dot` | Build dependency graph visualization |

### Top-level Functions

```python
# Compile from pre-validated Spec
compile_workflow(spec, **kwargs) -> WorkflowArtifacts

# Recommended entry point — handles the complete pipeline
compile_workflow_from_yaml(spec_path, **kwargs) -> WorkflowArtifacts
```

---

## Spec Models

Pydantic models representing the parsed workflow specification.

### `Spec`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique workflow identifier |
| `requirements` | `list[SpecRequirement \| PyPIRequirement]` | Package requirements (conda and/or PyPI) |
| `rjsf_overrides` | `dict` | React JSON Schema Form overrides |
| `task_instance_defaults` | `dict` | Default options applied to every task instance |
| `workflow` | `list[TaskInstance \| TaskGroup]` | Ordered list of task instances and groups |

### `TaskInstance`

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Display name |
| `id` | `str` | Unique identifier |
| `known_task_name` | `str` | Registered task name or fully qualified path |
| `skipif` | `SkipIf \| None` | Skip conditions |
| `partial` | `dict` | Static keyword arguments |
| `map` | `MapSpec \| None` | Map configuration |
| `mapvalues` | `MapSpec \| None` | Mapvalues configuration |

### `TaskGroup`

Named group of related task instances for organizational purposes.

### `SpecRequirement`

Conda package requirement with `name`, `version`, and optional `channel`.

### `PyPIRequirement`

PyPI package requirement with `name` and exactly one source (`git`, `path`,
or `url`). Optional fields include `rev`/`branch`/`tag` (git only),
`editable` (path only), `subdirectory`, and `extras`.

Key methods:

| Method | Returns | Description |
|--------|---------|-------------|
| `.to_pixi_dict()` | `dict` | Convert to pixi.toml `[pypi-dependencies]` format |
| `.to_pip_install_arg()` | `str` | Convert to a `pip install` argument string |

### `KnownTask`

Metadata for a discovered/registered task. The global `known_tasks` dict is
populated during discovery before `Spec` validation.

---

## Task Discovery

Task discovery creates ephemeral environments to discover registered functions
without importing task code into the compiler process.

### How it works

1. Solve conda dependencies using py-rattler's async `solve()`.
2. Install conda packages with py-rattler's async `install()`.
3. If PyPI requirements are present, install them via a single bulk
   `uv pip install --reinstall-package <name> ...` into the conda
   environment. The bulk call ensures all path/git/url sources resolve
   together; `--reinstall-package` forces uv to replace any conda-installed
   `.dist-info` with the explicit source.
4. If a `--env-overrides` file declares a `feature.discovery` section, its
   conda deps are added to the rattler match-specs and its pypi deps are
   merged into the bulk install. On a per-package collision with
   `spec.yaml`'s `requirements:`, the override wins and a one-line warning
   is logged.
5. Execute `wt-registry --format json` in the ephemeral environment.
6. Parse output against `RegistryOutput` from wt-contracts.
7. Convert entries to `KnownTask` models.
8. Update the global `known_tasks` dict.

### Functions

| Function | Description |
|----------|-------------|
| `discover_tasks_from_requirements()` | Primary async function for task discovery |
| `populate_known_tasks()` | Discover tasks and update global state |
| `discover_tasks_from_spec_requirements()` | Discover from `SpecRequirement` objects |

### Exceptions

| Exception | Description |
|-----------|-------------|
| `RegistryNotFoundError` | `wt-registry` executable not found in environment |
| `RegistryExecutionError` | `wt-registry` returned non-zero exit code |
| `EnvironmentCreationError` | py-rattler failed to solve or install |
| `PyPIInstallError` | The bulk `uv pip install` failed; the failure is shared across every requirement in the batch |

---

## Compiled Artifacts

### `WorkflowArtifacts`

Top-level container for all generated files.

| Field | Type | Description |
|-------|------|-------------|
| `spec_relpath` | `str` | Relative path to source spec file |
| `release_name` | `str` | Release directory name |
| `package_name` | `str` | Python package name |
| `package` | `PackageDirectory` | All files in the Python package directory |
| `tests` | `Tests` | Generated test files |
| `pixi_toml` | `PixiToml` | Pixi configuration |
| `dockerfile` | `str` | Dockerfile content |
| `dockerignore` | `str` | .dockerignore content |
| `pydot_graph` | `pydot.Dot` | Dependency graph object |
| `readme_md` | `str` | README with fingerprint block |

| Method | Description |
|--------|-------------|
| `.dump(clobber=False, update=False)` | Write all artifacts to disk |
| `.install()` | Run `pixi install -a` |
| `.update()` | Run `pixi update --no-install` |
| `.from_disk()` | Class method to load from existing directory |

### Output directory structure

```
wt-<id>-workflow/
├── pixi.toml
├── VERSION.yaml
├── Dockerfile
├── .dockerignore
├── README.md
├── graph.png
├── tests/
│   ├── conftest.py
│   ├── test_metadata.py
│   └── test_results.py
└── wt_<id>_workflow/
    ├── __init__.py
    ├── cli.py
    ├── dispatch.py
    ├── metadata.py
    ├── response.py
    ├── params.py
    ├── formdata.py
    ├── params.json
    ├── rjsf.json
    └── dags/
        ├── __init__.py
        ├── run_sequential.py
        └── run_sequential_mock_io.py
```

---

## Injected Dependencies

`wt-compiler` emits a self-contained `pixi.toml`. On top of whatever the
workflow author declares in `spec.yaml requirements:`, the compiler also
injects a fixed set of dependencies needed by the compiled package and
its tests — `click`, `obstore`, `pydantic`, `ruamel.yaml`,
`opentelemetry-api`, `wt-task`, `wt-runner`, plus `pandas`, `pyarrow`,
`pytest`, `playwright`, etc. for the `test` env. These three layers
combine, in this order:

### Layer A — defaults

Shipped with `wt-compiler` as the package resource
`default-env-injections.toml`. Same shape as the env-overrides file
described in Layer C: `[feature.<name>.dependencies]` for conda specs,
`[feature.<name>.pypi-dependencies]` for pypi entries, organized into
the `default`, `runner`, and `test` features. The bundled file is the
source of truth for baseline versions and channels and is inspectable
in the wt-compiler source tree.

### Layer B — `spec.yaml requirements:`

If a workflow's `requirements:` already declares one of Layer A's names
(or pulls it in transitively, as seen by the discovery solve), Layer
A's entry for that name is suppressed. The workflow's pin wins.

### Layer C — `--env-overrides`

A user-supplied TOML fragment with the same shape as Layer A. Intended
for development and testing of `wt` feature branches — patching or
debugging workflow issues — not for production. The conventional file
name is `wt-compiler-env-overrides.toml`, but the file name is a
convention only; the compiler reads whatever path is passed via
`--env-overrides=PATH` (no auto-detection).

A name declared in either `[feature.<f>.dependencies]` or
`[feature.<f>.pypi-dependencies]` of Layer C displaces same-name
entries on either side of the lower layers. Per-feature, per-name —
declaring `wt-task` in `feature.runner.pypi-dependencies` displaces any
`wt-task` entry in the runner feature's conda or pypi sub-section, but
does not affect `wt-task` in *other* features.

### Discovery overlay (Layer C only)

Layer C may additionally declare a `[feature.discovery.*]` block that
the compiler overlays onto its own discovery env via
`uv pip install --reinstall-package`. Discovery is a wt-compiler-only
pseudo-feature and is **never emitted into the compiled pixi.toml** —
note this asymmetry explicitly. The `discovery` feature is rejected
in any other context (e.g. it's invalid in `default-env-injections.toml`).

### Where each feature lands

The `default`, `runner`, and `test` features map onto pixi.toml as you
would expect:

| Feature | Where it lands in the compiled `pixi.toml` |
|---------|--------------------------------------------|
| `default` | top-level `[dependencies]` and `[pypi-dependencies]` |
| `runner` | `[feature.runner.dependencies]` and `[feature.runner.pypi-dependencies]` |
| `test` | `[feature.test.dependencies]` and `[feature.test.pypi-dependencies]` |
| `discovery` | wt-compiler discovery env only (never emitted into pixi.toml) |

### Section types and supported syntax

For every recognized feature, both of the following sections are
supported:

- `[feature.<f>.dependencies]` — conda deps. Either:
    - shorthand string: `pkg = ">=1.0,<2.0"` (channel defaults to
      `conda-forge`), or
    - longform table: `pkg = { version = "...", channel = "..." }`
      where channel may be a known name (`conda-forge`,
      `ecoscope-workflows`, `microsoft`) or a full base URL.
- `[feature.<f>.pypi-dependencies]` — pypi deps. Either:
    - longform table with one of `path` / `git` / `url` plus optional
      `editable`, `extras`, `subdirectory`, `rev` / `branch` / `tag`,
      or
    - bare-version shorthand: `pkg = "*"` or `pkg = ">=1.0"`. The
      shorthand is allowed in env-overrides files; the spec.yaml side
      does **not** yet accept bare-string pypi entries (see
      [`spec.yaml` reference](spec-yaml.md)).

### Path resolution

Two distinct anchors, two distinct phases:

- **The `--env-overrides=PATH` flag itself** — relative to the current
  working directory; resolved to absolute by the CLI before parsing.
- **`path = "..."` entries inside an override file** — relative to the
  override file's own directory (matching pixi.toml semantics).

### Conflict warnings

When an override entry collides by name with a `spec.yaml requirements:`
entry on either side (conda or pypi), the override wins and a one-line
warning is logged so the supersession is visible in CI logs.

### Worked example

The reverse-integration harness ships its own override file at
`tests/reverse_integration/wt-compiler-env-overrides.toml`:

```toml
# Discovery env overlay (never emitted into the compiled pixi.toml).
# Forces the discovery env's wt-* sources to local.
[feature.discovery.pypi-dependencies]
wt-registry  = { path = "../../wt-registry",  editable = true }
wt-task      = { path = "../../wt-task",      editable = true }
wt-contracts = { path = "../../wt-contracts", editable = true }

# Default feature — emitted as top-level [pypi-dependencies] in pixi.toml.
[feature.default.pypi-dependencies]
wt-task      = { path = "../../wt-task",      editable = true, extras = ["gcp"] }
wt-contracts = { path = "../../wt-contracts", editable = true }
wt-registry  = { path = "../../wt-registry",  editable = true }

# Runner feature — emitted as [feature.runner.pypi-dependencies].
[feature.runner.pypi-dependencies]
wt-runner    = { path = "../../wt-runner",    editable = true, extras = ["gcp"] }
wt-task      = { path = "../../wt-task",      editable = true, extras = ["gcp"] }
wt-invokers  = { path = "../../wt-invokers",  editable = true, extras = ["gcp"] }
wt-contracts = { path = "../../wt-contracts", editable = true }
```

Because the file lives in `tests/reverse_integration/`, the
`../..`-relative paths resolve to the monorepo root.

---

## CLI Reference

`wt-compiler` exposes two subcommands: `compile` and `scaffold`.

### `scaffold init`

Scaffold a new workflow project directory.

```bash
# Interactive (default) — arrow-key prompts for all fields
wt-compiler scaffold init

# Use a custom provider (installed in the current environment)
wt-compiler scaffold init --provider my-provider-name

# Write into a specific parent directory
wt-compiler scaffold init --output-dir /path/to/projects

# Overwrite an existing directory
wt-compiler scaffold init --clobber

# Batch / CI mode — supply all required fields as flags
wt-compiler scaffold init --no-interactive \
    --workflow-id my_workflow \
    --workflow-name "My Workflow" \
    --author-name "Jane Smith"
```

### `compile`

Compile a `spec.yaml` into a complete workflow package.

```bash
wt-compiler compile --spec path/to/spec.yaml

# Overwrite an existing output directory
wt-compiler compile --spec spec.yaml --clobber

# Compile and immediately install dependencies
wt-compiler compile --spec spec.yaml --clobber --install

# Re-use the existing lockfile and bump the version
wt-compiler compile --spec spec.yaml --clobber --update

# GCP variant
wt-compiler compile --spec spec.yaml --variant gcp

# Override wt-* sources for development/testing of feature branches.
# See "Injected Dependencies" above for the full layering and override file format.
wt-compiler compile --spec spec.yaml \
    --env-overrides=wt-compiler-env-overrides.toml
```

---

## Wizard Provider System

Custom providers let teams ship organisation-specific workflow scaffolding 
as ordinary Python packages.

### Creating a provider

Subclass `DefaultWizardProvider`, override `get_questions()`, and optionally
add Jinja2 templates colocated with the module:

```python
from wt_compiler.wizard import DefaultWizardProvider

class MyProvider(DefaultWizardProvider):
    def get_questions(self):
        questions = super().get_questions()
        questions.append({
            "dest": "gcp_project",
            "argparse": {"help": "GCP project ID", "type": str},
            "wizard": {},
        })
        return questions
```

### Declaring the entry point

```toml
# pyproject.toml
[project.entry-points."wt_compiler.wizard_providers"]
my-provider = "my_package.provider:MyProvider"
```

Any keys used in this entry-point table may be used as a value passed to `--provider` (e.g. `my-provider` in the example above). Note that a single provider extension package can expose one or multiple custom provider keys in this table.
package exposing this entry point is discovered automatically — no
registration step required. Every provider must produce a `workflow_id`
answer (inherited automatically from `DefaultWizardProvider`) —
`wt-compiler scaffold init` uses it to name the output directory.

### Installing a provider

The provider must be installed into the same environment as `wt-compiler`.

**General use** — `wt-compiler` installed via `pixi global`:

```bash
# Install wt-compiler itself
pixi global install wt-compiler \
    --channel https://repo.prefix.dev/ecoscope-workflows \
    --channel conda-forge

# Add a provider to the same environment
pixi global add --environment wt-compiler my-wt-provider
```

**Local development** — `wt-compiler` invoked via `uv run`:

```bash
uv pip install my-wt-provider
uv run wt-compiler scaffold init
```

See the [wizard implementor guide](https://github.com/wildfire-analytics/wt/blob/main/wt-compiler/src/wt_compiler/wizard/README.md)
for full details on question types, conditional logic, and custom templates.
