# wt-compiler

Workflow compiler for generating DAG artifacts from workflow specifications.

## Overview

`wt-compiler` is a key component of the wt (workflow toolkit) ecosystem. It compiles workflow specifications (YAML files) into complete, executable workflow packages including:

- DAG Python code (async, sequential, and Jupytext variants)
- Pydantic parameter models with JSON schemas
- CLI interfaces for workflow execution
- Pixi configuration for dependency management
- Dockerfiles for containerized deployment
- Test suites

## Key Innovation: Environment-Isolated Task Discovery

Unlike legacy systems that require importing task libraries directly, `wt-compiler` uses **subprocess-based task discovery**:

1. Creates ephemeral rattler/pixi environments with specified requirements
2. Calls `wt-registry` CLI in that environment
3. Parses JSON output (validated against `wt-contracts` schemas)
4. Compiles workflows without Python import dependencies on task libraries

This enables:
- ✅ Cross-environment compilation (Python 3.10 compiler can target Python 3.12 tasks)
- ✅ Isolation from task library dependency conflicts
- ✅ Type-safe contracts via `wt-contracts` package
- ✅ No circular dependencies between packages

## Installation

```bash
# From source (development)
cd wt/wt-compiler
uv sync

# Once published to PyPI
uv add wt-compiler
```

## Usage

### Scaffold a new workflow project

```bash
# Interactive mode (default) — arrow-key prompts for all fields
wt-compiler init

# Write into a specific parent directory
wt-compiler init --output-dir /path/to/projects

# Overwrite an existing directory
wt-compiler init --clobber

# Batch mode — supply all required fields as flags (CI / scripting)
wt-compiler init --no-interactive \
    --workflow-id my_workflow \
    --workflow-name "My Workflow" \
    --author-name "Jane Smith"

# Batch mode with a conda requirement
wt-compiler init --no-interactive \
    --workflow-id my_workflow \
    --workflow-name "My Workflow" \
    --author-name "Jane Smith" \
    --requirements '{"name":"numpy","version":">=1.0","channel":"conda-forge"}'

# --requirements is repeatable for multiple packages
wt-compiler init --no-interactive ... \
    --requirements '{"name":"numpy","version":">=1.0"}' \
    --requirements '{"name":"mypkg","path":"/abs/path/to/mypkg"}'
```

`init` scaffolds a new project directory at `<output-dir>/<workflow-id>/` containing a
`spec.yaml`, CI configuration, and packaging boilerplate. See
[`src/wt_compiler/wizard/README.md`](src/wt_compiler/wizard/README.md) for details on
customising the wizard or adding custom templates.

### Use a custom wizard provider

Third-party packages can ship their own wizard providers by exposing a
`wt_compiler.wizard_providers` entry point (see
[wizard README](src/wt_compiler/wizard/README.md) for packaging details).
Once the package is installed in the current environment, it is discovered
automatically — no registration step required.

`wt-compiler init` will prompt you to choose a provider at startup, or you
can select one directly with `--provider`:

```bash
wt-compiler init --provider my-provider-name
```

### Basic Compilation

```python
from wt_compiler import compile_workflow, Spec
from rattler import MatchSpec

# Load a workflow specification
spec = Spec.parse_file("workflow/spec.yaml")

# Compile to artifacts
artifacts = compile_workflow(
    spec=spec,
    spec_relpath="workflow/spec.yaml"
)

# Write artifacts to disk
artifacts.dump(clobber=True)
```

### Task Discovery

```python
from wt_compiler.discovery import discover_tasks_from_requirements
from rattler import MatchSpec

# Discover tasks from requirements
requirements = [
    MatchSpec("my-task-library>=1.0.0"),
    MatchSpec("another-library>=2.0.0"),
]

tasks = discover_tasks_from_requirements(requirements)
# Returns: dict[task_name, dict[module_path, KnownTask]]
```

### Workflow Specification Format

```yaml
id: my-workflow
requirements:
  - name: my-task-library
    version: ">=1.0.0"
    channel: conda-forge

workflow:
  - id: task1
    task: extract_data
    partial:
      source: "s3://my-bucket/data.csv"

  - id: task2
    task: transform_data
    partial:
      input_data: "${{ workflow.task1.return }}"
    map:
      argnames: param
      argvalues: "${{ workflow.task1.return }}"
```

## Architecture

### Package Structure

```
wt-compiler/
├── src/wt_compiler/
│   ├── __init__.py          # Public exports
│   ├── spec.py              # Spec and TaskInstance models
│   ├── compiler.py          # DagCompiler class
│   ├── discovery.py         # Task discovery via rattler + CLI
│   ├── artifacts.py         # Artifact generation models
│   ├── jsonschema.py        # JSON schema utilities
│   ├── requirements.py      # Rattler channel/matchspec handling
│   ├── util.py              # Import validation utilities
│   ├── formatting.py        # Ruff formatting decorator
│   ├── _models.py           # Pydantic base classes
│   └── templates/           # Jinja2 templates
│       ├── pkg/
│       │   ├── dags/
│       │   │   ├── run_async.jinja2
│       │   │   ├── run_sequential.jinja2
│       │   │   └── jupytext.jinja2
│       │   ├── cli.jinja2
│       │   ├── dispatch.jinja2
│       │   └── ...
│       ├── tests/
│       ├── Dockerfile.jinja2
│       └── pixi.jinja2
└── tests/
    ├── test_spec.py
    ├── test_compiler.py
    ├── test_discovery.py
    └── ...
```

### Dependencies

- **wt-contracts** (>=0.1.0): Shared type contracts (RegistryOutput, TaskProtocol, etc.)
- **pydantic** (>=2.0.0): Data validation and modeling
- **jinja2**: Template rendering
- **ruamel.yaml**: YAML parsing
- **rattler** (>=0.8.0): Conda environment management
- **datamodel-code-generator**: Generate Pydantic models from JSON schemas
- **pydot**: DAG visualization

## Implementation Status

### ✅ Completed Components

1. **Package Structure** - Full directory layout with src/ structure
2. **pyproject.toml** - setuptools-scm configuration, dependencies, tool configs
3. **spec.py** - Complete Spec, TaskInstance, and related models (~700 lines)
4. **discovery.py** - Task discovery via rattler + wt-registry CLI
5. **artifacts.py** - All artifact models (Dags, PixiToml, WorkflowArtifacts, etc.)
6. **requirements.py** - Channel and MatchSpec handling
7. **jsonschema.py** - JSON schema utilities with RJSF support
8. **util.py** - Import reference validation
9. **formatting.py** - Ruff formatting decorator
10. **_models.py** - Pydantic base model classes
11. **templates/** - All Jinja2 templates copied from legacy codebase
12. **compiler.py** - Core DagCompiler class structure

### ⚠️ Needs Expansion

The following areas are implemented as simplified stubs and need full implementation:

#### compiler.py TODOs

1. **get_params_jsonschema()** - Currently returns empty schema
   - Needs: Extract schemas from discovered task metadata
   - Needs: Merge schemas for task groups
   - Needs: Apply omit_args logic
   - Needs: Generate proper UI schema
   - Needs: Apply RJSF overrides

2. **generate_params_model()** - Stub implementation
   - Needs: Use datamodel-code-generator to create Pydantic model from JSON schema
   - Needs: Proper imports and type hints

3. **Graph visualization** - Not implemented
   - Needs: Generate pydot graphs showing task dependencies
   - Needs: Export to PNG

4. **README generation** - Not implemented
   - Needs: Generate README.md with fingerprint information
   - Needs: Include workflow diagram, parameter documentation

5. **Version management** - Basic implementation only
   - Needs: Full VERSION.yaml bump logic
   - Needs: Lockfile carryover for updates

6. **get_per_taskinstance_params_notebook()** - Empty stub
   - Needs: Generate parameter notebooks for Jupytext DAG

#### discovery.py TODOs

1. **rattler-py native API** - Currently uses subprocess fallback
   - Needs: Update when rattler-py solve/install API is stable
   - Needs: Better error handling

2. **Schema validation** - Basic validation only
   - Needs: Full wt-contracts schema validation
   - Needs: Better error messages for malformed CLI output

#### Testing

- **Unit tests** - Not yet written
  - Need tests for: spec parsing, validation, compilation
  - Need tests for: task discovery with mock environments
  - Need tests for: artifact generation
  - Need tests for: template rendering

## Development

### Setup

```bash
cd wt/wt-compiler
uv sync
```

### Run Tests

```bash
uv run pytest
```

### Type Checking

```bash
uv run mypy src/wt_compiler
```

### Linting

```bash
uv run ruff check src/wt_compiler
uv run ruff format src/wt_compiler
```

## Relationship to Other Packages

- **wt-contracts**: Depends on (provides type contracts)
- **wt-registry**: Called via subprocess (no Python dependency)
- **wt-task**: No dependency (generates code that uses it)
- **wt-runner**: No dependency (runner may depend on compiler in future)
- **wt-invokers**: No dependency

## Migration from Legacy

This package replaces `ecoscope_workflows_core.compiler`. Key differences:

1. **No direct task imports** - Uses CLI-based discovery instead
2. **wt-contracts integration** - Type-safe schemas for all interfaces
3. **Modular dependencies** - Only depends on wt-contracts
4. **Simplified models** - Spec models are now in spec.py instead of compiler.py

## Future Work

1. Complete all TODO areas in compiler.py
2. Write comprehensive test suite
3. Add CLI tool for standalone compilation
4. Add workflow visualization tools
5. Add workflow validation tools
6. Performance optimization for large workflows
7. Better error messages and debugging tools

## Contributing

See main wt repository CONTRIBUTING.md for guidelines.

## License

BSD-3-Clause
