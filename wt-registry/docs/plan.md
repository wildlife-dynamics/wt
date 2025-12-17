# Implementation Plan: wt-registry Package

## Overview
Create a standalone Python package to replace the entry-point-based auto-discovery registry system with an explicit `@register` decorator approach. The registry will store function metadata, import paths, and JSON schemas in a fully serializable format.

## Package Structure

```
wt-registry/
├── pyproject.toml              # Package config, dependencies (pydantic only), CLI entry point
├── README.md                   # Project overview with coverage badge
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml              # CI workflow: tests, doctests, type checks, coverage
└── src/
    └── wt_registry/
        ├── __init__.py         # Public API: register, get_registry
        ├── models.py           # RegistryMetadata & RegistryEntry pydantic models
        ├── registry.py         # Global registry storage & retrieval
        ├── validation.py       # Function signature type validation
        ├── decorator.py        # @register decorator implementation
        ├── exceptions.py       # Custom exceptions
        └── cli.py              # argparse-based CLI for JSON output
```

## Core Components

### 1. Metadata Schema (`models.py`)

**RegistryMetadata** - User-provided metadata:
- `title: str` - Required, human-readable title
- `description: str` - Required, detailed description
- `tags: list[str]` - Optional categorization tags
- `deprecated: bool` - Default False
- `deprecation_message: str | None` - Deprecation details

**RegistryEntry** - Complete registry entry:
- `metadata: RegistryMetadata` - User metadata above
- `module_path: str` - Auto-detected from `func.__module__`
- `function_name: str` - Auto-detected from `func.__qualname__`
- `_func_ref: Callable` - Private reference to function for lazy schema generation
- Property `json_schema: dict` - Lazy-generates schema from `_func_ref` (no caching)
- Computed properties: `import_statement`, `fully_qualified_name`

### 2. Global Registry (`registry.py`)

```python
_GLOBAL_REGISTRY: dict[str, RegistryEntry] = {}  # Keyed by fully qualified name

def register_entry(entry: RegistryEntry) -> None
    # Add to registry, raise DuplicateRegistrationError if exists

def get_registry() -> MappingProxyType[str, RegistryEntry]
    # Return immutable view

def to_json() -> str
    # Serialize entire registry to JSON string

def clear_registry() -> None
    # For testing only
```

### 3. Type Validation (`validation.py`)

```python
def validate_function_signature(func: Callable) -> None
```

Validates that:
- Function is not async (raise ValidationError)
- Function is not a class (raise ValidationError)
- All parameters have type annotations (raise ValidationError listing untyped params)
- Return type is annotated (raise ValidationError)

Uses `inspect.signature()` to check annotations.

### 4. Decorator Implementation (`decorator.py`)

```python
@register(
    *,  # Keyword-only args
    title: str,
    description: str,
    tags: list[str] | None = None,
    deprecated: bool = False,
    deprecation_message: str | None = None,
) -> Callable
```

**Flow:**
1. Extract `module_path` from `func.__module__`
2. Extract `function_name` from `func.__qualname__`
3. Create `RegistryEntry` with metadata, module/function info, and function reference
   - **NO validation at this point** (lazy validation)
   - **NO schema generation at this point** (lazy generation)
   - Store reference to function for later validation and schema generation
4. Call `register_entry()` to store in global registry
5. Return original function unchanged (no wrapping)

**Lazy Validation & Schema Generation:**
- `RegistryEntry.json_schema` property validates and generates schema on every access
- Validation step: calls `validate_function_signature(self._func_ref)` first
- Schema generation: uses `pydantic.TypeAdapter(self._func_ref).json_schema()`
- **No caching** - regenerates on every access (acceptable since only accessed during build-time export)
- Only happens when registry is accessed (e.g., CLI export), not at import time

**Error handling:**
- Duplicate registration → `DuplicateRegistrationError` with FQN (at registration time)
- Untyped function → `ValidationError` with specific parameter names (at schema access time)
- Schema generation failure → `SchemaGenerationError` (at schema access time)

### 5. CLI (`cli.py`)

```bash
wt-registry [--format json|pretty] [--filter-tag TAG]... [--module PATTERN]
```

**Implementation:**
- Use builtin argparse (no additional dependencies)
- Default format: JSON to stdout
- Filter by tags (multiple allowed, OR logic)
- Filter by module pattern (supports fnmatch wildcards)
- Pretty format option for human inspection

**Output:**
- JSON: `{fqn: entry.model_dump(mode='json'), ...}`
- Pretty: Multi-line formatted text with title, description, tags, import

### 6. Package Configuration (`pyproject.toml`)

```toml
[project]
name = "wt-registry"
dynamic = ["version"]
requires-python = ">=3.10"
dependencies = ["pydantic>=2.0.0,<3.0.0"]

[project.scripts]
wt-registry = "wt_registry.cli:main"

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "mypy>=1.0.0",
    "ruff>=0.1.0",
]

[build-system]
requires = ["hatchling", "hatchling-vcs"]
build-backend = "hatchling.build"

[tool.hatch.version]
source = "vcs"

[tool.hatch.build.hooks.vcs]
version-file = "src/wt_registry/_version.py"

[tool.pytest.ini_options]
testpaths = ["tests", "src/wt_registry"]
python_files = ["test_*.py"]
addopts = "--doctest-modules --doctest-continue-on-failure --cov=wt_registry --cov-report=term-missing --cov-report=xml"

[tool.coverage.run]
source = ["src/wt_registry"]
omit = ["*/tests/*", "*/_version.py"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
]
```

Initialize with `uv` for package management. Version will be inferred from git tags.

### 7. CI/CD Configuration (`.github/workflows/ci.yml`)

**GitHub Actions workflow to run on every push and PR:**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Full history for version inference

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install uv
        run: pip install uv

      - name: Install dependencies
        run: uv pip install --system -e ".[dev]"

      - name: Run tests with coverage
        run: pytest

      - name: Run type checking
        run: mypy src/wt_registry

      - name: Run linting
        run: ruff check src/wt_registry

      - name: Upload coverage to Codecov
        if: matrix.python-version == '3.12'
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml
          fail_ci_if_error: false
```

**Coverage badge in README.md:**
```markdown
[![codecov](https://codecov.io/gh/USERNAME/wt-registry/branch/main/graph/badge.svg)](https://codecov.io/gh/USERNAME/wt-registry)
```

## Implementation Sequence

### Phase 1: Project Setup
1. Initialize package structure with `uv init`
2. Create `pyproject.toml` with dependencies
3. Set up `src/wt_registry/` directory structure
4. Create `.gitignore` (include `src/wt_registry/_version.py`, `.coverage`, `coverage.xml`, `htmlcov/` since they're auto-generated), `README.md`

### Phase 2: Core Models & Storage
1. Implement `exceptions.py` - Custom exception classes
2. Implement `models.py` - Pydantic models for `RegistryMetadata` and `RegistryEntry`
3. Implement `registry.py` - Global registry with storage/retrieval functions

### Phase 3: Validation & Decorator
1. Implement `validation.py` - Type signature validation using `inspect` (called lazily from models.py)
2. Implement `decorator.py` - Lightweight `@register` decorator (no validation or schema generation)
3. Create `__init__.py` - Export public API: `register`, `get_registry`
4. Update `models.py` - Add lazy `json_schema` property with validation and generation (no caching)

### Phase 4: CLI
1. Implement `cli.py` - argparse-based command with filtering
2. Configure entry point in `pyproject.toml`

### Phase 5: Testing & Documentation
1. Write unit tests for each module
2. Test decorator with various function signatures
3. Test CLI output and filtering
4. Write comprehensive README with usage examples and coverage badge
5. Set up `.github/workflows/ci.yml` for automated testing, type checking, and coverage reporting

## Critical Files

- `src/wt_registry/models.py` - Data structures defining the registry schema
- `src/wt_registry/decorator.py` - Main user-facing `@register` decorator
- `src/wt_registry/registry.py` - Global registry storage mechanism
- `src/wt_registry/validation.py` - Type safety enforcement
- `pyproject.toml` - Package configuration, dependencies, pytest/coverage config
- `.github/workflows/ci.yml` - CI pipeline for tests, type checking, and coverage
- `README.md` - Documentation with coverage badge

## Usage Example

```python
from wt_registry import register

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
```

```bash
# Export registry to JSON
wt-registry > registry.json

# Filter by tag
wt-registry --filter-tag statistics --format pretty
```

## Key Design Decisions

1. **Explicit over implicit**: `@register` decorator vs entry point auto-discovery
2. **Lazy validation and schema generation**: Don't validate or generate JSON schemas at import time - only when registry is accessed
   - Lightweight imports: App startup is fast even with many registered functions
   - Build-time export: CLI triggers validation and schema generation only during export
   - No caching: Simple, pure property that regenerates on every access (acceptable for build-time use)
3. **Defer validation**: Validation errors appear during build/export, not at import time
4. **JSON-serializable**: Store metadata, not function objects (function refs excluded from serialization)
5. **Simple CLI**: Output to stdout for easy piping and integration
6. **Minimal dependencies**: Only pydantic required (argparse for CLI is builtin)
7. **Type safety**: Require complete type annotations for schema generation
8. **Flat registry**: Single dict keyed by fully qualified name (module.function)

## Performance Characteristics

**Import time (when modules are loaded):**
- Extremely lightweight: Only stores metadata and function reference
- No signature validation
- No Pydantic TypeAdapter calls
- No JSON schema generation
- Fast application startup even with hundreds of registered functions

**Registry access time (when `get_registry()` or `to_json()` is called):**
- Validation and schemas generated on every access to `entry.json_schema`
- No caching - regenerates fresh each time (simple, predictable behavior)
- Only occurs during build/export steps, not normal app runtime
- Validation errors surface at this point (e.g., during CLI export)

## Implementation Changes Required

### Files to Modify

1. **`src/wt_registry/models.py`**:
   - Add imports: `ConfigDict`, `TypeAdapter`, `SchemaGenerationError`, `validate_function_signature`
   - Add private `_func_ref: Any` field (excluded from serialization)
   - Change `json_schema` from field to `@property` with lazy validation + generation (no caching)
   - Property should: (1) validate signature, (2) generate schema, (3) return directly
   - Use `model_config = ConfigDict(arbitrary_types_allowed=True)` to allow Callable storage

2. **`src/wt_registry/decorator.py`**:
   - Remove `validate_function_signature(func)` call from decorator
   - Remove `TypeAdapter(func).json_schema()` call from decorator
   - Pass `func` as `_func_ref` when creating RegistryEntry (not `json_schema`)
   - Remove all try/except blocks (error handling moves to property access)

3. **Tests**:
   - Update tests that expect validation errors at registration time - errors now occur at schema access
   - Tests that access `json_schema` will trigger validation and generation
   - Add specific tests for lazy validation and generation behavior
   - Test that validation errors appear when accessing schema, not during registration
   - Remove tests for caching behavior (no longer relevant)

## Examples

### Adding New Examples

When implementing significant new features, add corresponding examples to demonstrate them:

1. Create a standalone Python script in `examples/`
2. Include a clear docstring explaining the feature
3. Register functions demonstrating the feature
4. Invoke CLI at the end to show output
5. Update `examples/README.md` with description

### Example Structure

Each example should follow this pattern:

```python
#!/usr/bin/env python3
"""
Example: Feature Name

Brief description of what this example demonstrates.

Setup (one-time):
    uv sync

Run with:
    uv run python examples/example_name.py
"""

from wt_registry import register

# Register functions demonstrating the feature
@register(...)
def example_function(...):
    ...

if __name__ == "__main__":
    from wt_registry.cli import main
    import sys

    sys.argv = ["example", "--format", "pretty"]
    main()
```

### Running Examples

Examples serve as both documentation and hands-on demonstrations:

```bash
# One-time setup
uv sync

# Run any example
uv run python examples/basic_registration.py
```

### Current Examples

- `basic_registration.py` - Getting started with function registration
- `cli_json_output.py` - JSON format output
- `cli_pretty_output.py` - Human-readable format
- `filtering_functions.py` - Filtering by function names
- `deprecated_functions.py` - Marking functions as deprecated
- `multiple_modules.py` - Working with multiple modules

Examples are the quickest way for new users to understand and explore wt-registry features.
