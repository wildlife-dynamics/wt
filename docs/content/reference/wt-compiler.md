# wt-compiler

`wt-compiler` is the build tool of the wt ecosystem. Given a `spec.yaml`, it
produces a self-contained workflow package containing executable Python DAG
code, JSON parameter schemas, CLI entry point, pixi configuration, Dockerfile,
tests, and a dependency graph visualization.

The compiler operates without importing any task code directly — it creates an
ephemeral conda environment using py-rattler, then runs `wt-registry` as a
subprocess to discover tasks and their JSON schemas.

**Modules:** `compiler` · `spec` · `discovery` · `artifacts` · `cli` ·
`exceptions` · `jsonschema` · `requirements` · `formatting`

---

## DagCompiler

The core engine that transforms a validated `Spec` into workflow artifacts.

### Constructor

```python
DagCompiler(
    spec: Spec,
    wt_runner_channel: str = ...,
    variant: str | None = None,
    jinja_templates_dir: Path = ...,
    pkg_name_prefix: str = "wt",
    results_env_var: str = "WT_RESULTS",
)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `spec` | `Spec` | *(required)* | Validated workflow specification |
| `wt_runner_channel` | `str` | built-in | Channel URL for `wt-runner` package |
| `variant` | `str \| None` | `None` | Platform variant suffix (e.g. `"gcp"`) |
| `jinja_templates_dir` | `Path` | built-in | Path to Jinja2 templates |
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
3. If PyPI requirements are present, install them via `uv pip install` into
   the conda environment.
4. Execute `wt-registry --format json` in the ephemeral environment.
5. Parse output against `RegistryOutput` from wt-contracts.
6. Convert entries to `KnownTask` models.
7. Update the global `known_tasks` dict.

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
| `PyPIInstallError` | `uv pip install` failed for a PyPI requirement |

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
