# DagCompiler

The `DagCompiler` class is the core engine that transforms a validated `Spec` into a complete set of workflow artifacts. It also provides lower-level methods for generating individual components (parameter schemas, DAG code, pixi configuration, dependency graphs).

**Module:** `wt_compiler.compiler`

## Class: `DagCompiler`

A Pydantic `BaseModel` that holds the spec and compiler options.

### Constructor Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `spec` | `Spec` | -- (required) | The validated workflow specification |
| `wt_runner_channel` | `str` | -- (required) | Channel URL where the `wt-runner` package is available |
| `variant` | `str \| None` | `None` | Platform variant suffix (e.g., `"gcp"`) for emitting variant package names like `wt-runner-gcp`, `wt-task-gcp` |
| `jinja_templates_dir` | `pathlib.Path` | `<package>/templates` | Directory containing Jinja2 templates |
| `pkg_name_prefix` | `str` | `"wt"` | Prefix for generated package names |
| `results_env_var` | `str` | `"WT_RESULTS"` | Name of the environment variable the generated CLI reads for the results URL |

### Computed Properties

| Property | Type | Description |
|----------|------|-------------|
| `release_name` | `str` | Release directory name, e.g. `wt-my-workflow-workflow` |
| `package_name` | `str` | Python package name (release name with dashes replaced by underscores) |
| `file_header` | `str` | Comment header prepended to all generated files |
| `per_taskinstance_omit_args` | `dict[str, list[str]]` | Mapping of task instance ID to argument names that should be omitted from parameter forms (because they are bound by `partial`, `map`, or `mapvalues`) |

---

### `.compile()`

The main entry point. Generates all workflow artifacts from the spec.

```python
def compile(
    self,
    spec_relpath: str,
    installed_requirements: list[SpecRequirement] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> WorkflowArtifacts
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `spec_relpath` | `str` | Relative path to the spec file (stored in artifacts for reference) |
| `installed_requirements` | `list[SpecRequirement] \| None` | Solved/pinned requirements from the discovery phase |
| `on_progress` | `Callable[[str], None] \| None` | Optional callback invoked at each compilation sub-step with a status message |

**Returns:** `WorkflowArtifacts` containing all generated files.

Compilation proceeds through these sub-steps:

1. **Generate schemas** -- Calls `get_params_jsonschema()` twice (flat and hierarchical), applies RJSF overrides.
2. **Render DAGs** -- Renders sequential DAG code (real and mock-I/O variants) from Jinja2 templates.
3. **Generate package files** -- Produces `params.py`, `formdata.py`, `cli.py`, `dispatch.py`, `metadata.py`, `response.py`, `params.json`, `rjsf.json`.
4. **Generate tests** -- Produces `conftest.py`, `test_metadata.py`, `test_results.py`.
5. **Generate pixi.toml** -- Builds complete pixi configuration with all dependencies.
6. **Generate Dockerfile / .dockerignore** -- Renders Docker configuration.
7. **Build graph** -- Creates a pydot directed graph of task dependencies.
8. **Generate README** -- Renders README with a fingerprint block for change tracking.

---

### `.get_params_jsonschema()`

Generate a JSON Schema configuration for the workflow's user-facing parameters.

```python
def get_params_jsonschema(
    self,
    flat: bool = True,
) -> ReactJSONSchemaFormConfiguration
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `flat` | `bool` | `True` | If `True`, all task parameters are at the top level. If `False`, task groups are preserved as nested objects. |

**Returns:** A `ReactJSONSchemaFormConfiguration` with `properties`, `$defs`, and `uiSchema`.

Arguments that are bound by `partial`, `map`, or `mapvalues` are automatically omitted from the schema, since they are not user-configurable.

---

### `.render_dag()`

Render a DAG Python file from a Jinja2 template.

```python
@ruff_formatted
def render_dag(
    self,
    dag_type: DagTypes,
    mock_io: bool = False,
) -> str
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dag_type` | `DagTypes` | -- | `"async"` or `"sequential"` |
| `mock_io` | `bool` | `False` | If `True`, I/O tasks are replaced with mock imports |

**Returns:** Ruff-formatted Python source code for the DAG.

---

### `.generate_params_model()`

Generate a Pydantic model from a JSON schema using `datamodel-code-generator`.

```python
@ruff_formatted
def generate_params_model(
    self,
    params_jsonschema: dict[str, Any],
    file_header: str,
) -> str
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `params_jsonschema` | `dict[str, Any]` | JSON schema for the parameters |
| `file_header` | `str` | Comment to prepend to the generated file |

**Returns:** Ruff-formatted Python source code defining a Pydantic `BaseModel`.

---

### `.get_pixi_toml()`

Generate a `PixiToml` configuration for the workflow package.

```python
def get_pixi_toml(self) -> PixiToml
```

**Returns:** A `PixiToml` model containing:

- **Workspace** with dynamically selected channels based on requirements
- **Dependencies** with per-dependency channel pinning, plus CLI runtime dependencies (`click`, `obstore`, `pydantic`, `ruamel.yaml`, `opentelemetry-api`, `wt-task`)
- **feature.runner** with `wt-runner` (or variant) dependency
- **feature.test** with test dependencies and pixi tasks
- **Environments**: `default`, `runner`, `test`
- **Tasks**: `docker-build` and the workflow CLI command
- **System requirements**: `linux = "4.4.0"` for Docker compatibility

---

### `.build_pydot_graph()`

Build a directed graph visualization of task dependencies.

```python
def build_pydot_graph(self) -> pydot.Dot
```

**Returns:** A `pydot.Dot` graph with HTML-table-styled nodes showing task IDs, input arguments, and return ports, connected by edges representing data flow.

---

### `.ruffrender()` / `.plainrender()`

Render Jinja2 templates with or without `ruff` auto-formatting.

```python
@ruff_formatted
def ruffrender(self, template: str, **kws: Any) -> str

def plainrender(self, template: str, **kws: Any) -> str
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `template` | `str` | Template file name relative to `jinja_templates_dir` |
| `**kws` | `Any` | Template variables |

---

## Top-Level Functions

### `compile_workflow()`

Compile a workflow from a pre-validated `Spec`. Requires the global `known_tasks` dict to be already populated via discovery.

```python
def compile_workflow(
    spec: Spec,
    spec_relpath: str,
    wt_runner_channel: str,
    installed_requirements: list[SpecRequirement] | None = None,
    on_progress: Callable[[str], None] | None = None,
    **compiler_kwargs: Any,
) -> WorkflowArtifacts
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `spec` | `Spec` | Validated workflow specification |
| `spec_relpath` | `str` | Relative path to the spec file |
| `wt_runner_channel` | `str` | Channel URL for `wt-runner` |
| `installed_requirements` | `list[SpecRequirement] \| None` | Pinned requirements from discovery |
| `on_progress` | `Callable[[str], None] \| None` | Progress callback |
| `**compiler_kwargs` | `Any` | Forwarded to `DagCompiler` constructor |

**Returns:** `WorkflowArtifacts`.

---

### `compile_workflow_from_yaml()`

The **recommended entry point** for compilation. This async function handles the complete pipeline: requirement parsing, task discovery, spec validation, and compilation.

```python
async def compile_workflow_from_yaml(
    yaml_path: str | Path,
    progress: bool = True,
    **compiler_kwargs: Any,
) -> WorkflowArtifacts
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `yaml_path` | `str \| Path` | -- | Path to the `spec.yaml` file |
| `progress` | `bool` | `True` | Show a progress spinner on stderr (auto-disabled when stderr is not a TTY) |
| `**compiler_kwargs` | `Any` | -- | Forwarded to `DagCompiler` (e.g., `pkg_name_prefix`, `variant`, `results_env_var`) |

**Returns:** `WorkflowArtifacts`.

**Raises:**

- `FileNotFoundError` if the YAML file does not exist
- `ValueError` if the spec is invalid
- `DiscoveryError` (or subclass) if task discovery fails

```python
import asyncio
from wt_compiler import compile_workflow_from_yaml

artifacts = asyncio.run(
    compile_workflow_from_yaml(
        "spec.yaml",
        pkg_name_prefix="wt",
        variant="gcp",
    )
)
artifacts.dump(clobber=True)
```

---

## `Fingerprint`

A Pydantic model that captures content hashes for change detection and version management.

```python
class Fingerprint(BaseModel):
    spec: Spec
    wa: WorkflowArtifacts
    installed_requirements: list[SpecRequirement] = []
```

### Computed Fields

| Field | Type | Description |
|-------|------|-------------|
| `spec_sha256` | `str` | SHA256 hash of the spec (excluding requirements) |
| `params_sha256` | `str` | SHA256 hash of the parameters schema with documentation keys removed. Used to detect parameter-breaking changes for version bumps. |
| `artifacts_sha256_basic` | `str` | Hash of artifacts excluding Dockerfile and pixi.toml |
| `artifacts_sha256_strict` | `str` | Hash of all artifacts |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `.to_yaml()` | `str` | Serialize the fingerprint (excluding `spec` and `wa`) to a YAML string |

---

## CLI

The `wt-compiler` command-line interface is installed as a console script.

```
wt-compiler compile [OPTIONS]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--spec FILE` | `Path` | -- (required) | Path to the workflow `spec.yaml` file |
| `--clobber` | flag | `False` | Overwrite existing output directory |
| `--update` | flag | `False` | Carry over lockfile and bump version (requires `--clobber`, incompatible with `--install`) |
| `--pkg-name-prefix PREFIX` | `str` | `"wt"` | Package name prefix for generated artifacts |
| `--install` | flag | `False` | Generate a new pixi lockfile and install dependencies after compilation |
| `--no-progress` | flag | `False` | Disable the progress spinner |
| `--variant VARIANT` | `str` | `None` | Platform variant suffix (e.g., `"gcp"`) |
| `--results-env-var ENV_VAR` | `str` | `"WT_RESULTS"` | Environment variable name for the results URL |
