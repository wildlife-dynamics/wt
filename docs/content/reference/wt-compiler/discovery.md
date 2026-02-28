# Task Discovery

The discovery module implements the core innovation of wt-compiler: discovering tasks without importing any task code into the compiler process. Instead, it creates an ephemeral conda environment, installs the workflow's declared packages, and calls the `wt-registry` CLI to obtain task metadata and JSON schemas.

**Module:** `wt_compiler.discovery`

## How Discovery Works

1. **Solve dependencies** -- Uses py-rattler's async `solve()` to resolve the conda dependency graph for the declared requirements.
2. **Install packages** -- Uses py-rattler's async `install()` to create an ephemeral environment in a temporary directory. Includes retry logic for transient ENOTEMPTY errors during parallel extraction.
3. **Run wt-registry CLI** -- Executes `wt-registry --format json --package <module>...` in the ephemeral environment. Module paths are derived from package names by convention (`foo-bar` -> `foo_bar.tasks`).
4. **Parse output** -- Validates the JSON output against `wt_contracts.registry.RegistryOutput`, then converts each entry into a `KnownTask` model.
5. **Populate global state** -- Updates the `known_tasks` dict in `wt_compiler.spec`, enabling subsequent `Spec` validation.

---

## `discover_tasks_from_requirements()`

The primary async function for task discovery.

```python
async def discover_tasks_from_requirements(
    requirements: list[MatchSpec],
    channels: list[Channel] | None = None,
    platform: Platform | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> DiscoveryResult
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `requirements` | `list[MatchSpec]` | -- (required) | Conda package requirements to install (rattler `MatchSpec` objects) |
| `channels` | `list[Channel] \| None` | `None` | Channels to search. Defaults to `[Channel("conda-forge")]`. |
| `platform` | `Platform \| None` | `None` | Target platform. Auto-detected from `sys.platform` if not provided. |
| `on_progress` | `Callable[[str], None] \| None` | `None` | Callback invoked with status messages (`"Solving dependencies..."`, `"Installing packages..."`, `"Discovering tasks..."`) |

### Returns

`DiscoveryResult` -- a `NamedTuple` with two fields:

| Field | Type | Description |
|-------|------|-------------|
| `tasks` | `dict[str, dict[str, KnownTask]]` | Discovered tasks: `{function_name: {module_path: KnownTask}}` |
| `records` | `list[RepoDataRecord]` | Solved package records from rattler (used later for version pinning) |

### Raises

| Exception | Condition |
|-----------|-----------|
| `RegistryNotFoundError` | `wt-registry` executable not found in the ephemeral environment |
| `RegistryExecutionError` | `wt-registry` CLI returned a non-zero exit code |
| `EnvironmentCreationError` | py-rattler failed to solve or install packages |
| `json.JSONDecodeError` | CLI output is not valid JSON |
| `ValueError` | CLI output does not match the expected `RegistryOutput` schema |

### Example

```python
import asyncio
from rattler import MatchSpec, Channel
from wt_compiler.discovery import discover_tasks_from_requirements

result = asyncio.run(
    discover_tasks_from_requirements(
        requirements=[
            MatchSpec("my-task-library>=1.0.0"),
            MatchSpec("wt-registry>=0.1.0"),
        ],
        channels=[Channel("conda-forge")],
    )
)

for func_name, modules in result.tasks.items():
    for module_path, known_task in modules.items():
        print(f"{known_task.importable_reference}: {list(known_task.json_schema.get('properties', {}).keys())}")
```

---

## `populate_known_tasks()`

Convenience function that discovers tasks and updates the global `known_tasks` dict.

```python
async def populate_known_tasks(
    requirements: list[MatchSpec],
    channels: list[Channel] | None = None,
    on_progress: Callable[[str], None] | None = None,
    **kwargs: Any,
) -> list[RepoDataRecord]
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `requirements` | `list[MatchSpec]` | -- (required) | Conda package requirements |
| `channels` | `list[Channel] \| None` | `None` | Channels to search |
| `on_progress` | `Callable[[str], None] \| None` | `None` | Progress callback |
| `**kwargs` | `Any` | -- | Forwarded to `discover_tasks_from_requirements()` |

**Returns:** `list[RepoDataRecord]` -- the solved package records.

**Side effect:** Clears and repopulates `wt_compiler.spec.known_tasks`.

---

## `discover_tasks_from_spec_requirements()`

Discover tasks from `SpecRequirement` objects (as found in a parsed `Spec`).

```python
async def discover_tasks_from_spec_requirements(
    spec_requirements: list[SpecRequirement],
    **kwargs: Any,
) -> DiscoveryResult
```

Converts `SpecRequirement` objects to `MatchSpec` and `Channel` objects, deduplicates channels, adds all known channels from `requirements.CHANNELS` for transitive dependency resolution, and delegates to `discover_tasks_from_requirements()`.

---

## Environment Creation

### `_create_environment()` (internal)

Creates a conda environment using py-rattler's native async API. Handles transient ENOTEMPTY errors with retry logic.

| Constant | Value | Description |
|----------|-------|-------------|
| `MAX_INSTALL_RETRIES` | `3` | Maximum number of install attempts |
| `INITIAL_BACKOFF_SECONDS` | `0.5` | Initial backoff delay (doubles on each retry) |

The function:

1. Detects virtual packages for the current system (e.g., `__osx`, `__glibc`).
2. Solves dependencies with `rattler.solve()`.
3. Installs packages with `rattler.install()`, retrying on ENOTEMPTY errors with exponential backoff.

---

## Exceptions

### `DiscoveryError`

Base exception for all discovery-related errors.

### `RegistryNotFoundError`

Raised when the `wt-registry` executable is not found in the ephemeral environment. This typically means none of the declared packages depend on `wt-registry`.

| Attribute | Type | Description |
|-----------|------|-------------|
| `executable_path` | `Path` | Expected path to the executable |
| `requirements` | `list[MatchSpec]` | The requirements that were installed |

### `RegistryExecutionError`

Raised when `wt-registry` is found but returns a non-zero exit code.

| Attribute | Type | Description |
|-----------|------|-------------|
| `executable_path` | `Path` | Path to the executable |
| `returncode` | `int` | Exit code |
| `stdout` | `str` | Standard output |
| `stderr` | `str` | Standard error |
| `requirements` | `list[MatchSpec]` | The requirements that were installed |

### `EnvironmentCreationError`

Raised when the ephemeral environment fails to be created (either during solve or install).

| Attribute | Type | Description |
|-----------|------|-------------|
| `env_path` | `Path` | Target environment path |
| `requirements` | `list[MatchSpec]` | The requirements being installed |
| `original_error` | `Exception` | The underlying exception |
| `phase` | `str` | `"solve"` or `"install"` |

The error message includes phase-specific guidance (e.g., dependency resolution hints for solve failures, ENOTEMPTY advice for install failures).

---

## Package-to-Module Convention

The discovery module derives task module paths from package names:

```
Package name:  my-task-library
Module path:   my_task_library.tasks
```

Packages whose names start with `wt-` (e.g., `wt-registry`, `wt-task`) are skipped during module derivation since they are framework packages, not task libraries.
