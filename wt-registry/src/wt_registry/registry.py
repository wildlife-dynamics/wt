"""Global registry storage and access functions."""

import json
import types
from types import MappingProxyType

from wt_registry.exceptions import DuplicateRegistrationError
from wt_registry.models import RegistryEntry

# Internal mutable registry
_GLOBAL_REGISTRY: dict[str, RegistryEntry] = {}


def register_entry(entry: RegistryEntry) -> None:
    """
    Add an entry to the global registry.

    Args:
        entry: The registry entry to add

    Raises:
        DuplicateRegistrationError: If a function with the same fully
            qualified name is already registered

    Examples:
        >>> from wt_registry.models import RegistryMetadata, RegistryEntry
        >>> from wt_registry.registry import register_entry, clear_registry
        >>> clear_registry()  # Start fresh
        >>> metadata = RegistryMetadata(
        ...     title="Test Function",
        ...     description="A test function"
        ... )
        >>> entry = RegistryEntry(
        ...     metadata=metadata,
        ...     module_path="test_module",
        ...     function_name="test_func",
        ...     json_schema={"type": "object"}
        ... )
        >>> register_entry(entry)
        >>> len(get_registry())
        1

        Attempting to register the same function twice raises an error:

        >>> register_entry(entry)  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
            ...
        wt_registry.exceptions.DuplicateRegistrationError: Function test_module.test_func is already registered
    """
    fqn = entry.fully_qualified_name
    if fqn in _GLOBAL_REGISTRY:
        raise DuplicateRegistrationError(f"Function {fqn} is already registered")
    _GLOBAL_REGISTRY[fqn] = entry


def get_registry() -> MappingProxyType[str, RegistryEntry]:
    """
    Return an immutable view of the global registry.

    The returned MappingProxyType prevents external code from modifying
    the registry directly. Functions can only be added via register_entry().

    Returns:
        Immutable mapping of fully qualified names to registry entries

    Examples:
        >>> from wt_registry.models import RegistryMetadata, RegistryEntry
        >>> from wt_registry.registry import register_entry, get_registry, clear_registry
        >>> clear_registry()
        >>> def example_func(x: int) -> str:
        ...     return str(x)
        >>> metadata = RegistryMetadata(
        ...     title="Example",
        ...     description="An example function"
        ... )
        >>> entry = RegistryEntry(
        ...     metadata=metadata,
        ...     module_path="examples",
        ...     function_name="example_func",
        ... )
        >>> entry._func_ref = example_func
        >>> register_entry(entry)
        >>> registry = get_registry()
        >>> "examples.example_func" in registry
        True
        >>> registry["examples.example_func"].metadata.title
        'Example'

        The registry is immutable:

        >>> registry["new.func"] = entry  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
            ...
        TypeError: 'mappingproxy' object does not support item assignment
    """
    return types.MappingProxyType(_GLOBAL_REGISTRY)


def clear_registry() -> None:
    """
    Clear all entries from the global registry.

    This function is primarily intended for testing purposes to ensure
    test isolation. In production code, you typically would not clear
    the registry.

    Examples:
        >>> from wt_registry.models import RegistryMetadata, RegistryEntry
        >>> from wt_registry.registry import register_entry, get_registry, clear_registry
        >>> clear_registry()  # Start fresh
        >>> def test_func(x: int) -> str:
        ...     return str(x)
        >>> metadata = RegistryMetadata(title="Test", description="Test")
        >>> entry = RegistryEntry(
        ...     metadata=metadata,
        ...     module_path="test",
        ...     function_name="func",
        ... )
        >>> entry._func_ref = test_func
        >>> register_entry(entry)
        >>> len(get_registry())
        1
        >>> clear_registry()
        >>> len(get_registry())
        0
    """
    _GLOBAL_REGISTRY.clear()


def to_json(pretty: bool = False) -> str:
    """
    Serialize the entire registry to a JSON string.

    The registry is serialized using Pydantic's model_dump(mode='json')
    to ensure proper JSON serialization of all fields.

    Args:
        pretty: If True, output pretty-printed JSON with indentation.
            If False (default), output compact single-line JSON.

    Returns:
        JSON string representation of the registry

    Examples:
        Compact JSON (default):

        >>> from wt_registry.models import RegistryMetadata, RegistryEntry
        >>> from wt_registry.registry import register_entry, to_json, clear_registry
        >>> clear_registry()
        >>> def json_func(x: int) -> str:
        ...     return str(x)
        >>> metadata = RegistryMetadata(
        ...     title="JSON Example",
        ...     description="Function for JSON example",
        ...     tags=["example"]
        ... )
        >>> entry = RegistryEntry(
        ...     metadata=metadata,
        ...     module_path="examples",
        ...     function_name="json_func",
        ... )
        >>> entry._func_ref = json_func
        >>> register_entry(entry)
        >>> import json
        >>> data = json.loads(to_json())
        >>> "examples.json_func" in data
        True
        >>> data["examples.json_func"]["metadata"]["title"]
        'JSON Example'
        >>> data["examples.json_func"]["metadata"]["tags"]
        ['example']

        Pretty-printed JSON:

        >>> output = to_json(pretty=True)
        >>> "\\n" in output  # Has newlines for readability
        True
    """
    registry_data = {}
    for fqn, entry in _GLOBAL_REGISTRY.items():
        data = entry.model_dump(mode="json")
        # Manually add json_schema since it's a property, not a field
        data["json_schema"] = entry.json_schema
        registry_data[fqn] = data
    if pretty:
        return json.dumps(registry_data, indent=2)
    else:
        return json.dumps(registry_data, separators=(",", ":"))
