# Compiler Artifacts

When `DagCompiler.compile()` runs, it produces a `WorkflowArtifacts` object that contains every file needed to run, test, and deploy the compiled workflow. This page documents the artifact models and the on-disk directory structure.

**Module:** `wt_compiler.artifacts`

---

## Output Directory Structure

After calling `artifacts.dump()`, the release directory has this layout:

```
wt-<spec_id>-workflow/
├── pixi.toml               # Conda environment + task definitions
├── pixi.lock                # Locked dependency versions (after install/update)
├── VERSION.yaml             # Semantic version (MAJ.MIN.PATCH)
├── Dockerfile               # Container build configuration
├── .dockerignore
├── README.md                # With fingerprint block for change tracking
├── graph.png                # DAG dependency visualization
├── tests/
│   ├── conftest.py          # Pytest fixtures and mock-I/O configuration
│   ├── test_metadata.py     # Tests for workflow metadata
│   └── test_results.py      # Tests for workflow execution results
└── <package_name>/          # Python package (underscored name)
    ├── __init__.py
    ├── cli.py               # Click-based CLI entry point
    ├── dispatch.py           # DAG dispatch logic
    ├── metadata.py           # Workflow metadata module
    ├── response.py           # Response model
    ├── params.py             # Pydantic model (flat parameter schema)
    ├── formdata.py           # Pydantic model (hierarchical parameter schema)
    ├── params.json           # Flat JSON Schema for parameters
    ├── rjsf.json             # Hierarchical JSON Schema for React JSON Schema Form
    └── dags/
        ├── __init__.py
        ├── run_sequential.py          # Sequential DAG (production)
        └── run_sequential_mock_io.py  # Sequential DAG (mock I/O for testing)
```

---

## `WorkflowArtifacts`

The top-level container for all generated files. This is what `DagCompiler.compile()` returns.

```python
class WorkflowArtifacts(_AllowArbitraryTypes):
    spec_relpath: str
    release_name: str
    package_name: str
    package: PackageDirectory
    tests: Tests
    pixi_toml: PixiToml         # alias: "pixi.toml"
    dockerfile: str              # alias: "Dockerfile"
    dockerignore: str            # alias: ".dockerignore"
    pydot_graph: pydot.Dot | None  # alias: "graph.png"
    readme_md: str | None        # alias: "README.md"
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `spec_relpath` | `str` | Relative path to the source spec file |
| `release_name` | `str` | Release directory name (e.g., `wt-my-workflow-workflow`) |
| `package_name` | `str` | Python package name (e.g., `wt_my_workflow_workflow`) |
| `package` | `PackageDirectory` | All files in the Python package directory |
| `tests` | `Tests` | Generated test files |
| `pixi_toml` | `PixiToml` | Pixi configuration model |
| `dockerfile` | `str` | Dockerfile content |
| `dockerignore` | `str` | .dockerignore content |
| `pydot_graph` | `pydot.Dot \| None` | Dependency graph object (written as PNG) |
| `readme_md` | `str \| None` | README with fingerprint block |

### Methods

| Method | Description |
|--------|-------------|
| `dump(clobber=False, update=False)` | Write all artifacts to disk at `release_dir` |
| `install()` | Run `pixi install -a` in the release directory |
| `update()` | Run `pixi update --no-install` in the release directory |
| `from_disk(spec_relpath, artifacts_dir)` | Class method: load artifacts from an existing directory |

### `dump()` Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `clobber` | `bool` | `False` | Overwrite existing output directory |
| `update` | `bool` | `False` | Carry over the lockfile from the previous build and auto-bump the version |

When `update=True`:

- The prior `pixi.lock`, `VERSION.yaml`, and `README.md` must exist.
- If the `params_sha256` changed, the major version is bumped (breaking parameter change).
- If the `params_sha256` is unchanged, the minor version is bumped.

---

## `PackageDirectory`

All files within the generated Python package.

```python
class PackageDirectory(BaseModel):
    dags: Dags
    rjsf: dict[str, Any]        # alias: "rjsf.json"
    params_json: dict[str, Any]  # alias: "params.json"
    params_model: str            # alias: "params.py"
    formdata_model: str          # alias: "formdata.py"
    cli: str                     # alias: "cli.py"
    dispatch: str                # alias: "dispatch.py"
    metadata: str                # alias: "metadata.py"
    response: str                # alias: "response.py"
    init_dot_py: str             # alias: "__init__.py"
```

### File Descriptions

| File | Format | Description |
|------|--------|-------------|
| `params.json` | JSON | Flat JSON Schema for all user-configurable parameters. Arguments bound by `partial`/`map`/`mapvalues` are excluded. |
| `rjsf.json` | JSON | Hierarchical JSON Schema for React JSON Schema Form, preserving task group structure. Includes `uiSchema` and RJSF overrides. |
| `params.py` | Python | Pydantic `BaseModel` generated from the flat schema via `datamodel-code-generator` |
| `formdata.py` | Python | Pydantic `BaseModel` generated from the hierarchical schema |
| `cli.py` | Python | Click-based CLI that reads parameters from YAML/JSON, runs a DAG, and writes results |
| `dispatch.py` | Python | Logic for selecting which DAG module to execute based on runtime options |
| `metadata.py` | Python | Workflow metadata (spec ID, task list, dependency graph) |
| `response.py` | Python | Response model for structured workflow output |
| `__init__.py` | Python | Empty init file |

---

## `Dags`

The generated DAG code files.

```python
class Dags(BaseModel):
    init_dot_py: str                    # alias: "__init__.py"
    run_sequential_mock_io: str         # alias: "run_sequential_mock_io.py"
    run_sequential: str                 # alias: "run_sequential.py"
```

| File | Description |
|------|-------------|
| `run_sequential.py` | Production DAG that imports real task functions and executes them in topological order |
| `run_sequential_mock_io.py` | Test DAG where I/O-tagged tasks are replaced with `create_func_magicmock()` mocks |
| `__init__.py` | Exposes the DAG functions |

Each DAG file follows the same pattern:

1. Import task functions (real or mock)
2. Wrap each with `task()`
3. Apply `.partial()`, `.validate()`, `.set_task_instance_id()`, `.handle_errors()`, `.skipif()` as configured
4. Execute via `.call()`, `.map()`, or `.mapvalues()` in topological order

---

## `PixiToml`

Model for the `pixi.toml` configuration file.

```python
class PixiToml(_AllowArbitraryAndValidateAssignment):
    workspace: PixiWorkspace
    system_requirements: dict[str, str]   # alias: "system-requirements"
    dependencies: dict[str, NamelessMatchSpecType]
    feature: dict[FeatureName, Feature]
    environments: dict[str, Environment]
    tasks: dict[PixiTaskName, PixiTaskCommand]
    file_header: str                      # excluded from serialization
```

### Methods

| Method | Description |
|--------|-------------|
| `from_file(src)` | Load from a TOML file |
| `from_text(text)` | Load from a TOML string |
| `add_dependency(name, version, channel=None)` | Add a dependency |
| `dump(dst)` | Write to a TOML file |
| `to_toml()` | Serialize to a TOML string |

### Structure Generated by the Compiler

The compiler generates a `pixi.toml` with:

- **`[workspace]`** -- Dynamic channels based on which channels are referenced in requirements
- **`[system-requirements]`** -- `linux = "4.4.0"` for Docker compatibility
- **`[dependencies]`** -- All spec requirements plus CLI runtime deps (`click`, `obstore`, `pydantic`, `ruamel.yaml`, `opentelemetry-api`, `wt-task`)
- **`[feature.runner]`** -- `wt-runner` (or variant) dependency
- **`[feature.test]`** -- Test dependencies (`pytest`, `pandas`, `playwright`, etc.) and pixi tasks
- **`[environments]`** -- `default`, `runner` (no default feature), `test` (runner + test features)
- **`[tasks]`** -- `docker-build` and the workflow CLI command

---

## `Tests`

Generated test files.

```python
class Tests(BaseModel):
    conftest: str         # alias: "conftest.py"
    test_metadata: str    # alias: "test_metadata.py"
    test_results: str     # alias: "test_results.py"
```

| File | Description |
|------|-------------|
| `conftest.py` | Pytest fixtures including mock-I/O setup for I/O-tagged tasks |
| `test_metadata.py` | Tests that the workflow metadata module loads correctly |
| `test_results.py` | Parameterized tests that run the workflow (via CLI and app) with mock I/O and snapshot expected results |

---

## `VersionYaml`

Version tracking for compiled workflows.

```python
class VersionYaml(BaseModel):
    MAJ: int
    MIN: int
    PATCH: int = 0
```

### `bump_from()` (class method)

```python
@classmethod
def bump_from(
    cls,
    prior_version: VersionYaml,
    prior_params_sha256: str,
    new_params_sha256: str,
) -> VersionYaml
```

| Condition | Version Change |
|-----------|---------------|
| `params_sha256` unchanged | Minor bump (`1.2.0` -> `1.3.0`) |
| `params_sha256` changed | Major bump (`1.2.0` -> `2.0.0`) |

Major bumps indicate a breaking change to the parameter schema that would require users to reconfigure existing workflow instances.

---

## Supporting Models

### `PixiWorkspace`

```python
class PixiWorkspace(_AllowArbitraryTypes):
    name: str
    channels: list[ChannelType]
    platforms: list[PlatformType]
```

### `Feature`

A pixi feature definition with dependencies and optional tasks.

```python
class Feature(_AllowArbitraryTypes):
    dependencies: dict[str, NamelessMatchSpecType]
    tasks: dict[PixiTaskName, PixiTaskCommand]
```

### `Environment`

A pixi environment definition.

```python
class Environment(BaseModel):
    features: list[FeatureName]
    solve_group: str                # alias: "solve-group"
    no_default_feature: bool        # alias: "no-default-feature"
```
