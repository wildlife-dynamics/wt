# Registry Models

::: wt_contracts.registry

Module: `wt_contracts.registry`

These Pydantic models define the schema for wt-registry CLI output. `wt-registry` serializes registered functions into this format, and `wt-compiler` deserializes and validates against it.

---

## RegistryMetadata

```python
from wt_contracts import RegistryMetadata
```

Metadata for a registered function. Populated from the `@register` decorator arguments.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | `str \| None` | `None` | Human-readable title. Auto-generated from the function name by `@register` if not provided. |
| `description` | `str \| None` | `None` | Detailed description of what the function does. |
| `tags` | `list[str]` | `[]` | Categorization tags (e.g., `["statistics", "dataframe"]`). |
| `deprecated` | `bool` | `False` | Whether this function is deprecated. |
| `deprecation_message` | `str \| None` | `None` | Optional message explaining the deprecation. |

### Example

```python
from wt_contracts import RegistryMetadata

# All fields explicit
metadata = RegistryMetadata(
    title="Calculate Mean",
    description="Calculate arithmetic mean of values",
    tags=["statistics", "math"],
    deprecated=False,
)

# Minimal (all fields have defaults)
minimal = RegistryMetadata()
assert minimal.title is None
assert minimal.tags == []
```

---

## RegistryEntry

```python
from wt_contracts import RegistryEntry
```

A complete registry entry representing a single discovered function. Contains everything `wt-compiler` needs to generate import statements and validate parameter schemas.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `metadata` | `RegistryMetadata` | *required* | Function metadata (title, description, tags, etc.). |
| `module_path` | `str` | *required* | Private Python module path where the function is defined (e.g., `"mypackage.tasks._internal"`). |
| `public_module_path` | `str` | *required* | Public module path for imports, discovered via `__init__.py` re-exports (e.g., `"mypackage.tasks"`). Falls back to `module_path` if the function is not re-exported. |
| `function_name` | `str` | *required* | The function name (e.g., `"calculate_stats"`). |
| `import_statement` | `str` | *required* | Complete Python import statement (e.g., `"from mypackage.tasks import calculate_stats as calculate_stats"`). |
| `json_schema` | `dict[str, object]` | *required* | JSON Schema describing the function's parameter types and return type. |

### Example

```python
from wt_contracts import RegistryMetadata, RegistryEntry

entry = RegistryEntry(
    metadata=RegistryMetadata(
        title="Add Numbers",
        description="Add two integers",
    ),
    module_path="mypackage.tasks._math",
    public_module_path="mypackage.tasks",
    function_name="add",
    import_statement="from mypackage.tasks import add as add",
    json_schema={
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"},
        },
        "required": ["a", "b"],
        "return": {"type": "integer"},
    },
)
```

!!! note "Private vs. public module paths"
    `module_path` reflects where the function is physically defined (e.g., a private `_internal` submodule). `public_module_path` is the shortest public path from which the function can be imported, discovered by traversing `__init__.py` re-exports. The `import_statement` uses the public path.

---

## RegistryOutput

```python
from wt_contracts import RegistryOutput
```

Top-level schema for the JSON output of the `wt-registry` CLI. This is the contract between `wt-registry` (producer) and `wt-compiler` (consumer).

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `entries` | `dict[str, RegistryEntry]` | *required* | Mapping from fully-qualified name (FQN) to `RegistryEntry`. The FQN format is `"{module_path}.{function_name}"`. |
| `version` | `str` | `"1.0.0"` | Schema version string for forward-compatibility tracking. |

### Example

```python
from wt_contracts import RegistryMetadata, RegistryEntry, RegistryOutput

output = RegistryOutput(
    entries={
        "mypackage.tasks.add": RegistryEntry(
            metadata=RegistryMetadata(title="Add", description="Add two numbers"),
            module_path="mypackage.tasks._math",
            public_module_path="mypackage.tasks",
            function_name="add",
            import_statement="from mypackage.tasks import add as add",
            json_schema={"type": "object", "properties": {}},
        ),
    },
    version="1.0.0",
)

# Serialize to JSON (used by wt-registry CLI)
json_str = output.model_dump_json(indent=2)
```

### JSON Output Structure

When serialized, `RegistryOutput` produces JSON with this structure:

```json
{
  "entries": {
    "mypackage.tasks.add": {
      "metadata": {
        "title": "Add",
        "description": "Add two numbers",
        "tags": [],
        "deprecated": false,
        "deprecation_message": null
      },
      "module_path": "mypackage.tasks._math",
      "public_module_path": "mypackage.tasks",
      "function_name": "add",
      "import_statement": "from mypackage.tasks import add as add",
      "json_schema": { ... }
    }
  },
  "version": "1.0.0"
}
```
