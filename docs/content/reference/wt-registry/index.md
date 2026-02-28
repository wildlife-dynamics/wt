# wt-registry

Explicit function registry with JSON schema generation.

## Overview

`wt-registry` provides the `@register` decorator that marks Python functions as workflow tasks. When applied, the decorator:

1. Records function metadata (title, description, tags) in a global in-process registry.
2. Validates that the function has complete type annotations (deferred to export time).
3. Generates a JSON Schema from the function's type hints (deferred to export time).

The package also provides a CLI (`wt-registry`) that serializes the registry to JSON in the `wt-contracts` `RegistryOutput` format, which `wt-compiler` consumes for task discovery.

## Installation

```bash
pip install wt-registry
```

Or with uv:

```bash
uv add wt-registry
```

### Requirements

- Python >= 3.10
- wt-contracts >= 0.1.0, < 1.0.0
- Pydantic >= 2.0.0, < 3.0.0

## Quick Example

```python
from wt_registry import register, get_registry

@register(
    title="Calculate Mean",
    description="Calculate the arithmetic mean of a list of numbers",
    tags=["statistics", "math"],
)
def calculate_mean(values: list[float]) -> float:
    return sum(values) / len(values)

# The function is registered at import time
registry = get_registry()
assert "mymodule.calculate_mean" in registry
```

Then export the registry via CLI:

```bash
wt-registry --package mypackage.tasks --format json --pretty
```

## Modules

| Module | Purpose |
|--------|---------|
| [`decorator`](decorator.md) | The `@register` decorator |
| [`registry`](registry.md) | Global registry storage (`get_registry`, `clear_registry`, `register_entry`, `to_json`) |
| [`cli`](cli.md) | CLI entry point and serialization helpers |

### Internal Modules

These modules support the public API but are not intended for direct use:

| Module | Purpose |
|--------|---------|
| `validation` | `validate_function_signature()` -- ensures functions have complete type annotations |
| `jsonschema` | `jsonschema_from_task_func()` -- generates JSON Schema with proper `Field()` metadata surfacing |
| `models` | `RegistryEntry` model (wt-registry's internal variant with lazy schema generation) |
| `exceptions` | `RegistryError`, `ValidationError`, `DuplicateRegistrationError`, `SchemaGenerationError` |

## Public API

The top-level package re-exports the two most commonly used symbols:

```python
from wt_registry import register, get_registry
```

## Design: Lazy Validation and Schema Generation

Registration via `@register` is intentionally lightweight -- it stores metadata and a reference to the function but does **not** validate the signature or generate the JSON schema at decoration time. This keeps import-time side effects minimal.

Validation and schema generation happen lazily when `RegistryEntry.json_schema` is accessed, which occurs during CLI export (`wt-registry --format json`). If a function has missing type annotations or an unsupported type, the error surfaces at export time rather than at import time.
