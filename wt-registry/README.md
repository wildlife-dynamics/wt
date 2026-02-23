# wt-registry

[![codecov](https://codecov.io/gh/USERNAME/wt-registry/branch/main/graph/badge.svg)](https://codecov.io/gh/USERNAME/wt-registry)

Explicit function registry with JSON schema generation for Python.

## Overview

`wt-registry` provides a simple, explicit decorator-based approach to registering functions with rich metadata and automatic JSON schema generation using Pydantic.

## Features

- **Explicit Registration**: Use `@register` decorator with metadata (title, description, tags)
- **Type Safety**: Requires complete type annotations for all registered functions
- **JSON Schema Generation**: Automatically generates JSON schemas using Pydantic TypeAdapter
- **Minimal Dependencies**: Only requires Python 3.10+ and Pydantic
- **CLI Tool**: Export registry contents as JSON via command-line interface
- **Fully Serializable**: Registry stores metadata and schemas, not function objects

## Quick Start with Examples

The fastest way to see wt-registry in action:

```bash
# Clone the repository
git clone https://github.com/USERNAME/wt-registry.git
cd wt-registry

# One-time setup
uv sync

# Run an example
uv run python examples/basic_registration.py
```

See [examples/README.md](examples/README.md) for more examples demonstrating:
- Basic function registration
- JSON and pretty output formats
- Function filtering
- Deprecated function handling
- Multi-module scenarios

## Installation

```bash
uv pip install wt-registry
```

## Quick Start

```python
from wt_registry import register, get_registry

@register(
    title="Calculate Statistics",
    description="Calculate mean, median, and stdev of numeric values",
    tags=["statistics", "analysis"]
)
def calculate_statistics(
    values: list[float],
    precision: int = 2
) -> dict[str, float]:
    import statistics
    return {
        "mean": round(statistics.mean(values), precision),
        "median": round(statistics.median(values), precision),
        "stdev": round(statistics.stdev(values), precision) if len(values) > 1 else 0.0,
    }

# Access the registry
registry = get_registry()
for fqn, entry in registry.items():
    print(f"{entry.metadata.title}: {fqn}")
    print(f"  Schema: {entry.json_schema}")
```

## CLI Usage

Export the entire registry as JSON:

```bash
wt-registry > registry.json
```

Filter by tags:

```bash
wt-registry --filter-tag statistics --format pretty
```

Filter by module:

```bash
wt-registry --module "myapp.tasks.*"
```

## Requirements

- Python 3.10+
- Pydantic 2.0+

## Development

Install development dependencies:

```bash
# IMPORTANT: Use --group dev (not --extra dev) with dependency-groups
uv sync --group dev
```

**Note**: This project uses `[dependency-groups]` instead of `[project.optional-dependencies]`. You **must** use `--group dev` to install dev dependencies (pytest, mypy, ruff, etc.). Running `uv sync` alone will not install dev dependencies.

Set up pre-commit hooks (automatically runs ruff linting and formatting on every commit):

```bash
uv run pre-commit install
```

Run tests:

```bash
uv run pytest
```

Run type checking:

```bash
uv run mypy src/wt_registry
```

## License

BSD-3-Clause
