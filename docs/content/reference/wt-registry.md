# wt-registry

`wt-registry` provides the `@register` decorator that marks Python functions
as workflow tasks, a global registry for storing them, and a CLI for exporting
the registry as JSON.

**Modules:** `decorator` · `registry` · `cli`

**Public API:**

```python
from wt_registry import register, get_registry
from wt_registry.registry import clear_registry, to_json
```

---

## `@register` Decorator

```python
def register(
    *,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    deprecated: bool = False,
    deprecation_message: str | None = None,
) -> Callable[[F], F]
```

All parameters are keyword-only and optional.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `title` | `str \| None` | Auto-generated from function name | Human-readable title |
| `description` | `str \| None` | `None` | Detailed description |
| `tags` | `list[str] \| None` | `[]` | Categorization tags |
| `deprecated` | `bool` | `False` | Mark as deprecated |
| `deprecation_message` | `str \| None` | `None` | Explain what to use instead |

### Behavior

1. Extracts `module_path` and `function_name` from the function.
2. Auto-generates a title from the function name if not provided
   (`calculate_mean` → *Calculate Mean*).
3. Creates a `RegistryEntry` with metadata and function reference.
4. Registers the entry in the global registry (raises
   `DuplicateRegistrationError` if already registered).
5. Returns the original function unchanged.

### Validation

Validation is **deferred** to schema-generation time (when `entry.json_schema`
is first accessed). Rules:

- All parameters must have type annotations.
- Return type must be annotated.
- Async functions are not supported.
- Only functions can be registered (not classes).

---

## Registry API

The global registry is a module-level dictionary that stores all functions
decorated with `@register`.

### `get_registry()`

```python
def get_registry() -> MappingProxyType[str, RegistryEntry]
```

Returns an immutable view of all registered functions, keyed by fully qualified
name (e.g. `my_tasks.tasks.calculate_mean`).

### `register_entry(entry)`

```python
def register_entry(entry: RegistryEntry) -> None
```

Add an entry to the global registry. Raises `DuplicateRegistrationError` if
an entry with the same key already exists. Called internally by `@register`.

### `clear_registry()`

```python
def clear_registry() -> None
```

Remove all entries from the registry. **Testing only** — use this between test
cases to reset state.

### `to_json(pretty=False)`

```python
def to_json(pretty: bool = False) -> str
```

Serialize the registry to a JSON string conforming to the `RegistryOutput`
schema.

### Internal: `RegistryEntry`

The `RegistryEntry` model in `wt_registry.models` stores a reference to the
original function and computes `json_schema` as a lazy property (using
Pydantic's `TypeAdapter` under the hood).

---

## CLI Reference

The `wt-registry` CLI exports the global function registry to stdout. It is
consumed by `wt-compiler` for task discovery.

```bash
wt-registry [OPTIONS]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--format` | `json \| pretty` | `json` | Output format |
| `--pretty` | flag | off | Pretty-print JSON output |
| `--function NAME` | repeatable | *(all)* | Filter by function name |
| `--package PACKAGE` | repeatable | *(none)* | Import package before export |

### How it works

1. Imports each `--package` (triggers `@register` decorators at import time).
2. Filters entries if `--function` is provided.
3. Discovers public import paths by traversing `__init__.py` re-exports.
4. Serializes as `RegistryOutput` (json format) or human-readable text (pretty
   format).

### Examples

```bash
# JSON output (default, used by the compiler)
wt-registry --package my_tasks

# Human-readable output
wt-registry --package my_tasks --format pretty

# Filter to specific functions
wt-registry --package my_tasks --function calculate_mean --function fetch_events
```
