# wt-registry Examples

This directory contains standalone examples demonstrating wt-registry features.

## Running Examples

All examples are standalone uv scripts. From the repository root:

### One-time Setup

```bash
uv sync
```

This installs the local wt-registry package and all dependencies.

### Running Examples

```bash
uv run python examples/basic_registration.py
uv run python examples/cli_json_output.py
# ... etc
```

Each script is self-contained and demonstrates a specific feature.

## Available Examples

### Getting Started

- **basic_registration.py** - Start here! Basic function registration and CLI usage
- **cli_json_output.py** - JSON output format for programmatic use
- **cli_pretty_output.py** - Human-readable output format

### Advanced Features

- **filtering_functions.py** - Filter registry by function names
- **deprecated_functions.py** - Mark functions as deprecated
- **multiple_modules.py** - Work with functions from multiple modules

## Example Structure

Each example follows this pattern:
1. Function definitions with @register decorator
2. Metadata (title, description, tags, etc.)
3. CLI invocation to display registered functions

## Contributing Examples

When adding significant features to wt-registry, please add corresponding examples here!
