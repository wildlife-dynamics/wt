# @register Decorator

Module: `wt_registry.decorator`

```python
from wt_registry import register
```

## Signature

```python
def register(
    *,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    deprecated: bool = False,
    deprecation_message: str | None = None,
) -> Callable[[F], F]:
    ...
```

All parameters are keyword-only.

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `title` | `str \| None` | `None` | Human-readable title for the function. If `None`, auto-generated from the function name by converting `snake_case` to `Title Case` (e.g., `get_patrol_observations` becomes `"Get Patrol Observations"`). |
| `description` | `str \| None` | `None` | Detailed description of what the function does. |
| `tags` | `list[str] \| None` | `None` | Optional list of categorization tags. Stored as an empty list if `None`. |
| `deprecated` | `bool` | `False` | Whether this function is deprecated. |
| `deprecation_message` | `str \| None` | `None` | Optional message explaining the deprecation (e.g., `"Use new_function instead"`). |

## Return Value

Returns the original function unchanged. The decorator has no effect on the function's runtime behavior -- it only registers it in the global registry as a side effect.

## Behavior

When `@register(...)` is applied to a function:

1. **Extracts** `module_path` from `func.__module__` and `function_name` from `func.__qualname__`.
2. **Auto-generates the title** from the function name if `title` is not provided (via `snake_case` to `Title Case` conversion).
3. **Creates a `RegistryEntry`** with the provided metadata and a reference to the function. No validation or schema generation occurs at this point.
4. **Registers the entry** in the global registry via `register_entry()`. Raises `DuplicateRegistrationError` if a function with the same fully-qualified name is already registered.
5. **Returns the original function** without modification.

## Exceptions

| Exception | When Raised |
|-----------|-------------|
| `DuplicateRegistrationError` | A function with the same `module_path.function_name` is already registered. Raised at decoration time. |
| `ValidationError` | The function has missing type annotations (untyped parameters, missing return type) or is async/a class. Raised at schema access time (not at decoration time). |
| `SchemaGenerationError` | Pydantic's `TypeAdapter` cannot generate a JSON Schema from the function's type annotations. Raised at schema access time. |

!!! note "Deferred validation"
    `ValidationError` and `SchemaGenerationError` are **not** raised when the decorator is applied. They are raised later when `RegistryEntry.json_schema` is accessed -- typically during `wt-registry` CLI export. This keeps import-time overhead minimal.

## Examples

### Minimal Registration

When no `title` is provided, it is auto-generated from the function name:

```python
from wt_registry import register, get_registry

@register()
def get_patrol_observations(x: int) -> str:
    return str(x)

entry = list(get_registry().values())[0]
assert entry.metadata.title == "Get Patrol Observations"
```

### Explicit Title and Description

```python
@register(
    title="Add Numbers",
    description="Add two integers together",
)
def add(a: int, b: int) -> int:
    return a + b
```

### With Tags

```python
@register(tags=["io", "network"])
def fetch_data(url: str) -> dict:
    ...
```

### Deprecated Function

```python
@register(
    title="Old Function",
    description="Legacy function",
    deprecated=True,
    deprecation_message="Use new_function instead",
)
def old_func(x: int) -> int:
    return x * 2
```

## Requirements for Registered Functions

The following requirements are enforced at schema-generation time (when `json_schema` is accessed):

- **All parameters must have type annotations.** Parameters without annotations cause a `ValidationError`.
- **The return type must be annotated.** A missing `-> ...` annotation causes a `ValidationError`.
- **Async functions are not supported.** Coroutine functions cause a `ValidationError`.
- **Classes are not supported.** Only functions can be registered.
- **Types must be JSON-schema-compatible.** Pydantic must be able to generate a JSON Schema from the annotations.

### Valid

```python
@register()
def process(x: int, y: str = "default") -> bool:
    return True
```

### Invalid (will fail at export time)

```python
# Missing parameter type
@register()
def bad_func(x) -> str:  # 'x' has no type annotation
    return str(x)

# Missing return type
@register()
def no_return(x: int):  # no '-> ...' annotation
    pass

# Async function
@register()
async def async_func(x: int) -> str:
    return str(x)
```
