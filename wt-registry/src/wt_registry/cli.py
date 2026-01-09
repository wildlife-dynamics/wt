"""Command-line interface for wt-registry."""

import argparse
import sys
from types import MappingProxyType

# Import shared contracts from wt-contracts
from wt_contracts.registry import (
    RegistryEntry as ContractRegistryEntry,
)
from wt_contracts.registry import (
    RegistryOutput,
)

from wt_registry.models import RegistryEntry
from wt_registry.registry import get_registry


def filter_by_function_names(
    registry: MappingProxyType[str, RegistryEntry],
    function_names: list[str] | None = None,
) -> dict[str, RegistryEntry]:
    """
    Filter registry entries by function names.

    Args:
        registry: Full registry from get_registry()
        function_names: List of function names to include (None = include all)

    Returns:
        Filtered dictionary of FQN -> RegistryEntry

    Examples:
        >>> from wt_registry.models import RegistryMetadata, RegistryEntry
        >>> from wt_registry.registry import register_entry, clear_registry
        >>> from types import MappingProxyType
        >>> clear_registry()
        >>> def test_func(x: int) -> str:
        ...     return str(x)
        >>> metadata = RegistryMetadata(title="Test", description="Test")
        >>> entry = RegistryEntry(
        ...     metadata=metadata,
        ...     module_path="test",
        ...     function_name="test_func",
        ... )
        >>> entry._func_ref = test_func
        >>> register_entry(entry)
        >>> from wt_registry.registry import get_registry
        >>> registry = get_registry()
        >>> filtered = filter_by_function_names(registry, ["test_func"])
        >>> len(filtered)
        1
        >>> "test.test_func" in filtered
        True
    """
    if function_names is None:
        return dict(registry)

    filtered = {}
    for fqn, entry in registry.items():
        if entry.function_name in function_names:
            filtered[fqn] = entry
    return filtered


def serialize_entries(
    entries: dict[str, RegistryEntry],
) -> RegistryOutput:
    """
    Serialize registry entries to wt-contracts RegistryOutput format.

    Converts wt-registry RegistryEntry objects to wt-contracts format,
    generating JSON schema for each entry. Returns a RegistryOutput
    object that can be serialized to JSON for consumption by wt-compiler.

    Args:
        entries: Filtered registry entries

    Returns:
        RegistryOutput object (wt-contracts schema)

    Examples:
        >>> from wt_registry.models import RegistryMetadata, RegistryEntry
        >>> from wt_registry.registry import clear_registry
        >>> clear_registry()
        >>> def sample_func(x: int) -> str:
        ...     return str(x)
        >>> metadata = RegistryMetadata(title="Sample", description="Sample function")
        >>> entry = RegistryEntry(
        ...     metadata=metadata,
        ...     module_path="test",
        ...     function_name="sample_func",
        ... )
        >>> entry._func_ref = sample_func
        >>> entries = {"test.sample_func": entry}
        >>> output = serialize_entries(entries)
        >>> "test.sample_func" in output.entries
        True
        >>> output.entries["test.sample_func"].metadata.title
        'Sample'
        >>> output.version
        '1.0.0'
    """
    contract_entries = {}
    for fqn, entry in entries.items():
        # Convert to wt-contracts RegistryEntry format
        contract_entry = ContractRegistryEntry(
            metadata=entry.metadata,  # Already using wt-contracts RegistryMetadata
            module_path=entry.module_path,
            function_name=entry.function_name,
            import_statement=entry.import_statement,
            json_schema=entry.json_schema,  # Triggers lazy generation
        )
        contract_entries[fqn] = contract_entry

    return RegistryOutput(entries=contract_entries, version="1.0.0")


def format_pretty(entries: dict[str, RegistryEntry]) -> str:
    """
    Format registry entries as human-readable text.

    Args:
        entries: Filtered registry entries

    Returns:
        Multi-line formatted string

    Examples:
        >>> from wt_registry.models import RegistryMetadata, RegistryEntry
        >>> def pretty_func(x: int) -> str:
        ...     return str(x)
        >>> metadata = RegistryMetadata(
        ...     title="Pretty Function",
        ...     description="A function for pretty printing",
        ...     tags=["test", "pretty"]
        ... )
        >>> entry = RegistryEntry(
        ...     metadata=metadata,
        ...     module_path="test.module",
        ...     function_name="pretty_func",
        ... )
        >>> entry._func_ref = pretty_func
        >>> entries = {"test.module.pretty_func": entry}
        >>> output = format_pretty(entries)
        >>> "=== test.module.pretty_func ===" in output
        True
        >>> "Title: Pretty Function" in output
        True
        >>> "Tags: test, pretty" in output
        True
    """
    if not entries:
        return "No functions registered"

    lines = []
    for fqn, entry in entries.items():
        lines.append(f"=== {fqn} ===")
        lines.append(f"Title: {entry.metadata.title}")
        lines.append(f"Description: {entry.metadata.description}")

        if entry.metadata.tags:
            lines.append(f"Tags: {', '.join(entry.metadata.tags)}")

        if entry.metadata.deprecated:
            if entry.metadata.deprecation_message:
                lines.append(f"Deprecated: Yes ({entry.metadata.deprecation_message})")
            else:
                lines.append("Deprecated: Yes")
        else:
            lines.append("Deprecated: No")

        lines.append(f"Import: {entry.import_statement}")
        lines.append("")  # Empty line between entries

    return "\n".join(lines)


def main() -> None:
    """
    Main CLI entry point.

    Parses command-line arguments and exports the registry to stdout
    in either JSON or pretty format, with optional filtering by function names.
    """
    parser = argparse.ArgumentParser(
        description="Export wt-registry to JSON or human-readable format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--format",
        choices=["json", "pretty"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output with indentation (default: compact)",
    )
    parser.add_argument(
        "--function",
        action="append",
        dest="function_names",
        metavar="NAME",
        help="Filter by function name (can be specified multiple times)",
    )

    args = parser.parse_args()

    try:
        # Get registry
        registry = get_registry()

        # Apply filters
        filtered_entries = filter_by_function_names(registry, args.function_names)

        # Format and output
        if args.format == "json":
            registry_output = serialize_entries(filtered_entries)
            # Use Pydantic's model_dump_json for proper serialization
            if args.pretty:
                output = registry_output.model_dump_json(indent=2)
            else:
                output = registry_output.model_dump_json()
            print(output)
        else:  # pretty
            output = format_pretty(filtered_entries)
            print(output)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
