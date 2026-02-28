# wt-compiler

Workflow compiler that transforms YAML specifications into complete, executable workflow packages.

## Overview

`wt-compiler` is the build tool of the wt ecosystem. Given a `spec.yaml` file that declares task dependencies, parameter bindings, and execution topology, it produces a self-contained workflow package containing:

- Executable Python DAG code (sequential and mock-I/O variants)
- JSON parameter schemas and Pydantic parameter models
- A CLI entry point for running the workflow
- A `pixi.toml` with all resolved conda dependencies
- A `Dockerfile` for containerized deployment
- Generated tests with mock-I/O support
- A dependency graph visualization (PNG)

The compiler operates without importing any task code directly. Instead, it creates an ephemeral conda environment using py-rattler, runs the `wt-registry` CLI inside that environment to discover tasks and their JSON schemas, then generates code that calls those tasks through the `wt-task` API.

| Module | Purpose |
|--------|---------|
| [`compiler`](compiler.md) | `DagCompiler` class and top-level compilation functions |
| [`spec`](spec.md) | `Spec`, `TaskInstance`, `TaskGroup`, and related Pydantic models |
| [`discovery`](discovery.md) | Task discovery via ephemeral rattler environments and `wt-registry` CLI |
| [`artifacts`](artifacts.md) | Output artifact models (`WorkflowArtifacts`, `PackageDirectory`, `PixiToml`, etc.) |
| `cli` | `wt-compiler compile` command-line interface |
| `exceptions` | `DiscoveryError`, `RegistryNotFoundError`, `RegistryExecutionError`, `EnvironmentCreationError` |
| `jsonschema` | React JSON Schema Form configuration and override utilities |
| `requirements` | Channel and platform constants, `NamelessMatchSpec` parsing |
| `formatting` | `@ruff_formatted` decorator for auto-formatting generated code |

## Installation

```bash
pip install wt-compiler
```

Or with uv:

```bash
uv add wt-compiler
```

### Requirements

- Python >= 3.12
- `wt-contracts` >= 0.1.0, < 1.0.0
- `pydantic` >= 2.0.0, < 3.0.0
- `jinja2` >= 3.0.0
- `ruamel.yaml` >= 0.17.0
- `py-rattler` >= 0.22.0, < 0.23.0
- `datamodel-code-generator` >= 0.25.0
- `pydot` >= 1.4.0
- `ruff` >= 0.1.0
- `tomli-w` >= 1.0.0

## Quick Example

### CLI usage

```bash
wt-compiler compile --spec path/to/spec.yaml --clobber
```

### Python API

```python
import asyncio
from wt_compiler import compile_workflow_from_yaml

artifacts = asyncio.run(
    compile_workflow_from_yaml("path/to/spec.yaml")
)
artifacts.dump(clobber=True)
print(f"Output: {artifacts.release_dir}")
```

## Public API

All public symbols are re-exported from the top-level package:

```python
from wt_compiler import (
    # Core compilation
    DagCompiler,
    Fingerprint,
    compile_workflow,
    compile_workflow_from_yaml,
    # Discovery
    discover_tasks_from_requirements,
    discover_tasks_from_spec_requirements,
    populate_known_tasks,
    # Exceptions
    DiscoveryError,
    EnvironmentCreationError,
    RegistryNotFoundError,
    RegistryExecutionError,
    # Spec models
    Spec,
    SpecRequirement,
    TaskInstance,
    TaskGroup,
    KnownTask,
    TaskTag,
)
```

## Compilation Pipeline

The end-to-end pipeline executed by `compile_workflow_from_yaml()`:

1. **Parse requirements** -- Read the `requirements` section from `spec.yaml` without validating the full spec.
2. **Discover tasks** -- Create an ephemeral conda environment with py-rattler, install the declared packages, and run `wt-registry --format json` to obtain task metadata and JSON schemas.
3. **Validate spec** -- With the global `known_tasks` dict now populated, parse and validate the complete `Spec` model (topological ordering, dependency resolution, etc.).
4. **Compile artifacts** -- Instantiate `DagCompiler` and call `.compile()` to generate all output files.
5. **Write to disk** -- Call `artifacts.dump()` to write the package directory.

## Versioning

`wt-compiler` uses `setuptools-scm` for versioning. Versions are derived from git tags matching the pattern `wt-compiler/v<version>`.
