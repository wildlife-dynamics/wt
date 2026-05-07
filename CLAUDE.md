# Development Guidelines for Claude Code

This document provides best practices and guidelines for developing the wt (Workflow Template) monorepo with Claude Code assistance.

## Repository Structure

This is a **monorepo with 9 packages** (6 core + 3 GCP metapackages) that together provide a workflow compilation and execution framework.

### Package Architecture

```
wt-contracts (foundation - shared type contracts)
    ↓
    ├→ wt-registry (function registration & discovery)
    ├→ wt-task (task execution framework)
    │       └→ wt-task-gcp (metapackage: + GCP tracing)
    ├→ wt-compiler (workflow YAML → executable DAG)
    ├→ wt-invokers (execution backends)
    │       └→ wt-invokers-gcp (metapackage: + Cloud Batch deps)
    └→ wt-runner → wt-invokers (FastAPI web server)
            └→ wt-runner-gcp (metapackage: + Pub/Sub, tracing, Cloud Batch)
                    └→ wt-invokers-gcp
```

### Packages

| Package | Purpose | Key Modules | CLI |
|---------|---------|-------------|-----|
| **wt-contracts** | Shared Pydantic models for inter-package compatibility | `registry.py`, `task.py`, `cli.py` | — |
| **wt-registry** | `@register` decorator for function discovery with JSON schema generation | `decorator.py`, `registry.py`, `validation.py` | `wt-registry` |
| **wt-task** | `@task` decorator with `.call()`, `.map()`, `.partial()`, `.validate()` methods | `decorator.py`, `base.py`, `sync_task.py`, `async_task.py` | — |
| **wt-compiler** | Compiles workflow YAML specs into executable DAG artifacts | `compiler.py`, `spec.py`, `discovery.py`, `templates/` | `wt-compiler` |
| **wt-invokers** | Abstract invoker interface + implementations (local subprocess, Cloud Batch) | `abstract.py`, `local.py`, `cloud_batch.py` | — |
| **wt-runner** | FastAPI server for workflow execution with multi-backend support | `app.py`, `tracing.py` | uvicorn |

#### GCP Metapackages

These are dependency-only metapackages (empty `__init__.py`) that bundle a core package with its GCP-specific dependencies for convenient installation.

| Metapackage | Bundles | GCP Dependencies |
|-------------|---------|------------------|
| **wt-task-gcp** | wt-task | `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-gcp-trace` |
| **wt-invokers-gcp** | wt-invokers | `google-cloud-batch`, `google-auth` |
| **wt-runner-gcp** | wt-runner + wt-invokers-gcp | `opentelemetry-sdk`, `opentelemetry-exporter-gcp-trace`, `gcloud-aio-pubsub`, `ecoscope-eda-core` |

The core packages also expose the same GCP dependencies as optional extras (e.g., `pip install wt-invokers[gcp]`). The primary purpose of the metapackages is to provide a distinct `pyproject.toml` for building separate conda package variants via pixi — conda does not support extras/optional-dependencies, so each variant needs its own package. In the pip/uv context, the metapackages also serve as a convenience alternative to extras syntax.

### Directory Layout

Each package is at the repository root. Core packages follow this structure:
```
<package-name>/            # e.g., wt-registry/, wt-compiler/
├── src/<package_name>/    # Source code (underscores, e.g., wt_registry/)
│   ├── __init__.py
│   └── *.py
├── tests/                 # Unit tests (test_*.py)
├── pyproject.toml         # Package config (setuptools-scm versioning)
└── README.md
```

GCP metapackages are minimal — they contain only a `pyproject.toml` declaring dependencies:
```
<package-name>-gcp/        # e.g., wt-invokers-gcp/
├── src/<package_name>_gcp/
│   └── __init__.py        # Empty (dependency-only metapackage)
├── pyproject.toml         # Declares core package + GCP deps
└── README.md
```

### Key Design Decisions

- **Subprocess-based discovery**: wt-compiler discovers tasks via `wt-registry` CLI (no direct imports), avoiding dependency conflicts
- **No circular dependencies**: wt-contracts is the foundation; all other packages depend on it
- **Pydantic v2**: All packages use Pydantic for data validation and JSON schema generation

## Core Principles

### 1. Always Write and Run Unit Tests

**Every function and feature must have corresponding unit tests.**

- Write tests alongside implementation (TDD encouraged)
- Aim for high code coverage (>90%)
- Run tests frequently during development: `uv run pytest`
- Tests should be:
  - **Isolated**: Each test should be independent
  - **Fast**: Unit tests should run quickly
  - **Deterministic**: Same input = same output, every time
  - **Readable**: Tests serve as documentation

**Test organization:**
```
tests/
├── test_models.py
├── test_registry.py
├── test_validation.py
├── test_decorator.py
├── test_cli.py
└── test_exceptions.py
```

**Example test structure:**
```python
def test_register_valid_function():
    """Test that a properly typed function can be registered."""
    # Arrange
    clear_registry()

    @register(title="Test", description="Test function")
    def test_func(x: int) -> str:
        return str(x)

    # Act
    registry = get_registry()

    # Assert
    assert "test_module.test_func" in registry
    assert registry["test_module.test_func"].metadata.title == "Test"
```

### 2. Always Include Type Hints

**All functions must have complete type annotations.**

This is especially critical for wt-registry since we rely on type information to generate JSON schemas.

- Annotate all function parameters
- Annotate return types (including `-> None`)
- Use `typing` module for complex types (`list[str]`, `dict[str, Any]`, etc.)
- Use `|` for union types (Python 3.10+): `str | None` instead of `Optional[str]`
- Use `from __future__ import annotations` if needed for forward references

**Good:**
```python
def register_entry(entry: RegistryEntry) -> None:
    """Add entry to global registry."""
    ...

def get_registry() -> MappingProxyType[str, RegistryEntry]:
    """Return immutable view of registry."""
    ...
```

**Bad:**
```python
def register_entry(entry):  # Missing type hints
    ...

def get_registry():  # Missing return type
    ...
```

### 3. Write Docstrings with Examples

**Every public function, class, and module must have a docstring.**

- Use Google-style or NumPy-style docstrings
- Include a brief summary (one line)
- Document parameters, return values, and exceptions
- Add examples section with doctests where appropriate
- Examples should demonstrate typical usage and edge cases

**Docstring format:**
```python
def register(
    *,
    title: str,
    description: str,
    tags: list[str] | None = None,
    deprecated: bool = False,
    deprecation_message: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Register a function in the global registry with metadata.

    The decorated function must have complete type annotations for all
    parameters and return type. The function is registered immediately
    when the decorator is applied (at import time).

    Args:
        title: Human-readable title for the function
        description: Detailed description of what the function does
        tags: Optional list of categorization tags
        deprecated: Whether this function is deprecated (default: False)
        deprecation_message: Optional message explaining the deprecation

    Returns:
        The original function, unchanged

    Raises:
        ValidationError: If the function signature is not fully typed
        DuplicateRegistrationError: If the function is already registered
        SchemaGenerationError: If JSON schema generation fails

    Examples:
        Basic registration:

        >>> @register(
        ...     title="Add Numbers",
        ...     description="Add two integers together"
        ... )
        ... def add(a: int, b: int) -> int:
        ...     return a + b
        >>> registry = get_registry()
        >>> "mymodule.add" in registry
        True

        With tags:

        >>> @register(
        ...     title="Calculate Mean",
        ...     description="Calculate arithmetic mean",
        ...     tags=["statistics", "math"]
        ... )
        ... def mean(values: list[float]) -> float:
        ...     return sum(values) / len(values)
    """
    ...
```

### 4. Running Doctests

Doctests should be integrated into the test suite to ensure examples stay up-to-date.

**Enable doctest in pytest configuration (`pyproject.toml`):**
```toml
[tool.pytest.ini_options]
testpaths = ["tests", "src/wt_registry"]
python_files = ["test_*.py"]
addopts = "--doctest-modules --doctest-continue-on-failure"
```

**Run tests including doctests:**
```bash
uv run pytest --doctest-modules
```

## Additional Best Practices

### Code Quality Tools

- **Type checking**: Run `uv run mypy src/wt_registry` before committing
- **Linting**: Run `uv run ruff check src/wt_registry` to catch issues
- **Formatting**: Use `uv run ruff format src/wt_registry` for consistent style

### Error Messages

- Provide clear, actionable error messages
- Include context (function name, parameter values, etc.)
- Suggest how to fix the problem when possible

**Good:**
```python
raise ValidationError(
    f"Function {func.__module__}.{func.__qualname__} has untyped parameters: "
    f"{', '.join(untyped_params)}. All parameters must have type annotations."
)
```

**Bad:**
```python
raise ValidationError("Invalid function")
```

### Imports

- Group imports: stdlib, third-party, local
- Use absolute imports within the package
- Avoid circular imports

```python
# Standard library
import inspect
import types
from typing import Any, Callable

# Third-party
from pydantic import BaseModel, Field

# Local
from wt_registry.exceptions import RegistryError
from wt_registry.models import RegistryEntry
```

## Testing Checklist

Before considering a feature complete:

- [ ] All functions have type hints
- [ ] All public functions have docstrings with examples
- [ ] Unit tests written and passing
- [ ] Doctests passing (if applicable)
- [ ] Type checking passes (`mypy`)
- [ ] Linting passes (`ruff check`)
- [ ] Code is formatted (`ruff format`)
- [ ] Error cases are tested
- [ ] Edge cases are considered

## Development Workflow

1. Write/update tests first (TDD approach)
2. Implement feature with full type hints
3. Add comprehensive docstrings with examples
4. Run tests: `uv run pytest`
5. Run type checker: `uv run mypy src/wt_registry`
6. Run linter: `uv run ruff check src/wt_registry`
7. Format code: `uv run ruff format src/wt_registry`
8. Commit changes

## Mandatory Rules

### Imports must be at the top of the module (ruff PLC0415)

The ruff rule `PLC0415` (`import-outside-top-level`) is enabled. Every
`import` / `from … import …` statement must live at module top level
unless there is a clear, documented justification for keeping it local.

Acceptable justifications include:
- **Avoiding a circular import** that cannot be resolved by restructuring
  (use a `TYPE_CHECKING` guard first if the import is only needed for
  type hints).
- **Exercising optional-dependency presence** inside a test that must
  import the optional package as the thing under test.
- **Genuinely deferring an expensive or side-effecting import** behind a
  rarely-taken code path (rare — prefer hoisting).

When a local import is justified, add an inline noqa with the reason
on the same line as the import:

    from .async_task import AsyncTask  # noqa: PLC0415  # circular import: AsyncTask imports _Task

If you cannot articulate a clear justification, the rule must be
followed — hoist the import to the top of the module. "It was already
written this way" is not a justification.

### Make only the edits the prompt or plan requires

Every edit must be strictly required by the plan or prompt being
implemented, or required by the linter / type checker / test runner.
Do not perform unprompted "cleanup", "tidying", reformatting, comment
rewrites, docstring polish, import reordering, or refactoring while
working on an unrelated task. If you notice something that looks worth
fixing, mention it to the human — do not silently change it.

This rule is about *unprompted* changes. When the human explicitly asks
for cleanup, reformatting, or a refactor, that work is in-scope and the
rule does not restrict it.

## Questions?

When in doubt:
- Prioritize clarity over cleverness
- Write code that is easy to test
- Document the "why" not just the "what"
- Be explicit rather than implicit
