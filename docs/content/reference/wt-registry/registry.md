# Registry

Module: `wt_registry.registry`

The global registry is a module-level dictionary that stores all functions decorated with `@register`. Access is provided through a set of functions that control mutability.

## Architecture

Internally, the registry is a plain `dict[str, RegistryEntry]` stored in `_GLOBAL_REGISTRY`. External code interacts with it through:

- `get_registry()` -- returns an **immutable view** (`MappingProxyType`)
- `register_entry()` -- the only way to add entries
- `clear_registry()` -- removes all entries (testing only)
- `to_json()` -- serializes the registry to JSON

---

## get_registry

```python
from wt_registry import get_registry
```

```python
def get_registry() -> MappingProxyType[str, RegistryEntry]:
    ...
```

Returns an immutable view of the global registry. The returned `MappingProxyType` prevents external code from modifying the registry directly -- entries can only be added via `register_entry()`.

**Returns:** `MappingProxyType[str, RegistryEntry]` -- a read-only mapping from fully-qualified name (FQN) to `RegistryEntry`.

The FQN format is `"{module_path}.{function_name}"` (e.g., `"mypackage.tasks.calculate_mean"`).

### Example

```python
from wt_registry import register, get_registry

@register(title="Example")
def example_func(x: int) -> str:
    return str(x)

registry = get_registry()
assert "mymodule.example_func" in registry
assert registry["mymodule.example_func"].metadata.title == "Example"

# Immutable -- assignment raises TypeError
registry["new.func"] = ...  # TypeError: 'mappingproxy' object does not support item assignment
```

---

## register_entry

```python
from wt_registry.registry import register_entry
```

```python
def register_entry(entry: RegistryEntry) -> None:
    ...
```

Add an entry to the global registry. This is called internally by the `@register` decorator. You typically do not need to call it directly.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `entry` | `RegistryEntry` | The registry entry to add |

**Raises:** `DuplicateRegistrationError` if a function with the same fully-qualified name is already registered.

---

## clear_registry

```python
from wt_registry.registry import clear_registry
```

```python
def clear_registry() -> None:
    ...
```

Remove all entries from the global registry. Intended for **testing only** to ensure test isolation.

### Example

```python
from wt_registry.registry import clear_registry, get_registry

clear_registry()
assert len(get_registry()) == 0
```

---

## to_json

```python
from wt_registry.registry import to_json
```

```python
def to_json(pretty: bool = False) -> str:
    ...
```

Serialize the entire registry to a JSON string. Uses Pydantic's `model_dump(mode="json")` for each entry, and manually includes the `json_schema` property (since it is a computed property, not a Pydantic field).

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pretty` | `bool` | `False` | If `True`, output indented JSON. If `False`, output compact JSON. |

**Returns:** JSON string representation of the registry.

!!! note "Accessing `json_schema` triggers validation"
    Calling `to_json()` accesses `entry.json_schema` for every entry, which triggers signature validation and schema generation. Any functions with missing type annotations will raise `ValidationError` at this point.

### Example

```python
import json
from wt_registry.registry import to_json

data = json.loads(to_json())
# {"mymodule.example_func": {"metadata": {...}, "module_path": "...", ...}}

# Pretty-printed
print(to_json(pretty=True))
```

---

## Internal: RegistryEntry (wt_registry.models)

The `RegistryEntry` in `wt_registry.models` is distinct from the `RegistryEntry` in `wt_contracts.registry`. The wt-registry variant:

- Stores a **private function reference** (`_func_ref`) via Pydantic's `PrivateAttr`.
- Computes `json_schema` as a **lazy property** that validates the function signature and generates the schema on first access.
- Provides `fully_qualified_name` and `import_statement` as computed properties.

During CLI export, `wt_registry.cli.serialize_entries()` converts the internal `RegistryEntry` to the `wt_contracts.RegistryEntry` format for serialization.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `metadata` | `RegistryMetadata` | *required* | User-provided metadata from `@register`. |
| `module_path` | `str` | *required* | Full module path where the function is defined. |
| `function_name` | `str` | *required* | Function name (from `__qualname__`). |

### Computed Properties

| Property | Type | Description |
|----------|------|-------------|
| `fully_qualified_name` | `str` | `"{module_path}.{function_name}"` |
| `import_statement` | `str` | `"from {module_path} import {function_name}"` |
| `json_schema` | `dict[str, Any]` | JSON Schema generated from the function's type annotations. Triggers validation on access. |

---

## Exceptions

All exceptions inherit from `RegistryError`:

| Exception | Description |
|-----------|-------------|
| `RegistryError` | Base exception for all wt-registry errors. |
| `ValidationError` | Function signature validation failed (missing types, async, class). |
| `DuplicateRegistrationError` | Function with the same FQN is already registered. |
| `SchemaGenerationError` | Pydantic could not generate a JSON Schema from the function's types. |

```python
from wt_registry.exceptions import (
    RegistryError,
    ValidationError,
    DuplicateRegistrationError,
    SchemaGenerationError,
)
```
