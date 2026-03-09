# wt-contracts

Shared interface contracts for wt workflow packages.

## Overview

`wt-contracts` provides type-safe interface definitions (Pydantic models + Protocols) that enable inter-package compatibility across the wt ecosystem. This package contains **no implementation logic** - only contracts that other packages depend on.

## Purpose

The wt architecture separates serializable metadata (`@register`) from execution features (`@task`). To enable cross-environment discovery via CLI serialization boundary, we need shared contracts that all packages agree on:

1. **Registry Contract**: JSON schema for wt-registry CLI output
2. **Task Execution Contract**: Protocol defining task execution interface
3. **Generated CLI Contract**: Standard CLI arguments for generated workflows

## Package Contents

### `wt_contracts.registry`

Pydantic models for wt-registry CLI output:
- `RegistryMetadata`: Function metadata (title, description, tags, deprecation)
- `RegistryEntry`: Complete registry entry (metadata + schemas + import info)
- `RegistryOutput`: Top-level CLI output format

### `wt_contracts.task`

Protocol for task execution interface:
- `TaskProtocol[P, R]`: Generic protocol with methods like `.partial()`, `.call()`, `.map()`

### `wt_contracts.cli`

Standard CLI contracts for generated workflows:
- `WorkflowCLIArgs`: Standard CLI arguments
- `WorkflowCLIEnv`: Standard environment variables

## Installation

```bash
pip install wt-contracts
# or
uv add wt-contracts
```

## Usage

```python
from wt_contracts.registry import RegistryOutput, RegistryEntry
from wt_contracts.task import TaskProtocol
from wt_contracts.cli import WorkflowCLIArgs

# Deserialize registry CLI output
registry_data = RegistryOutput.model_validate_json(cli_output)

# Type-check task implementations
def my_task_wrapper(func: Callable[P, R]) -> TaskProtocol[P, R]:
    ...
```

## Development

```bash
# Install dependencies (including dev dependencies)
cd wt/wt-contracts

# IMPORTANT: Use --group dev to install pytest, mypy, ruff, etc.
uv sync --group dev

# Run tests
uv run pytest

# Type check
uv run mypy src/

# Lint
uv run ruff check .
```

**Note**: This project uses `[dependency-groups]` instead of `[project.optional-dependencies]`. You **must** use `--group dev` to install dev dependencies. Running `uv sync` alone will only install production dependencies (pydantic).

## Design Philosophy

- **Minimal dependencies**: Only pydantic (for validation)
- **No implementation**: Pure interface definitions
- **Type-safe**: Full mypy strict mode compliance
- **Version stability**: Breaking changes require major version bump
- **Lightweight**: Fast to install, minimal impact on dependency trees

## Related Packages

- `wt-registry`: Function registration with JSON schema generation (uses registry contracts)
- `wt-task`: Task decorator with execution features (implements task protocol)
- `wt-compiler`: Workflow compilation (uses all contracts for discovery + generation)
- `wt-invokers`: Workflow invocation (uses CLI contract)
- `wt-runner`: FastAPI workflow execution server (uses CLI contract)

## License

BSD-3-Clause
