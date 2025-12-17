# CLI Implementation Plan

## Overview
Implement a command-line interface (CLI) for the wt-registry package that allows users to export the registry to JSON or a human-readable format, with optional filtering by function names.

## Requirements

### Command Syntax
```bash
wt-registry [--format json|pretty] [--function NAME]...
```

### Features
1. **Output Formats**:
   - `json` (default): Machine-readable JSON output to stdout
   - `pretty`: Human-readable multi-line text format

2. **Filtering**:
   - `--function NAME`: Filter by function name (multiple allowed)
   - Filters by function name only (not fully qualified name)
   - Silently skips function names that don't exist (no error)
   - **Performance optimization**: Only resolves JSON schema for selected functions

3. **Implementation Requirements**:
   - Use builtin `argparse` (no additional dependencies)
   - Use `get_registry()` for registry access
   - **Don't use `to_json()`** - manually serialize to avoid computing schemas for filtered-out functions
   - Follow existing code patterns and testing conventions
   - Complete type hints and comprehensive docstrings

## Critical Files

### New Files
- **`src/wt_registry/cli.py`** - CLI implementation
- **`tests/test_cli.py`** - CLI tests

### Reference Files
- `src/wt_registry/registry.py` - Use `get_registry()`
- `src/wt_registry/models.py` - Access RegistryEntry structure
- `pyproject.toml` - CLI entry point already configured at line 30

## Implementation Details

### 1. CLI Module Structure (`src/wt_registry/cli.py`)

```python
"""Command-line interface for wt-registry."""

import argparse
import json
import sys
from typing import Any
from types import MappingProxyType

from wt_registry.models import RegistryEntry
from wt_registry.registry import get_registry


def filter_by_function_names(
    registry: MappingProxyType[str, RegistryEntry],
    function_names: list[str] | None = None,
) -> dict[str, RegistryEntry]:
    """Filter registry entries by function names."""
    # Implementation


def serialize_entries(
    entries: dict[str, RegistryEntry],
) -> dict[str, dict[str, Any]]:
    """
    Serialize registry entries to JSON-compatible dict.

    Only generates JSON schema for entries being serialized (performance optimization).
    """
    # Implementation


def format_pretty(entries: dict[str, RegistryEntry]) -> str:
    """Format registry entries as human-readable text."""
    # Implementation


def main() -> None:
    """Main CLI entry point."""
    # Implementation
```

### 2. Filtering Logic

#### Function Name Filtering
```python
# If function_names filter is specified, only include entries with matching function names
if function_names:
    filtered = {}
    for fqn, entry in registry.items():
        if entry.function_name in function_names:
            filtered[fqn] = entry
    return filtered
else:
    # No filter, return all entries as dict
    return dict(registry)
```

**Key points:**
- Filter by `entry.function_name` (just the function name, not the FQN)
- Silently skip function names that don't exist in registry (no error)
- If no filter specified, include all entries

### 3. Output Formats

#### JSON Format
- **Don't use `to_json()`** - manually serialize to optimize performance
- Call `entry.model_dump(mode='json')` for each selected entry
- Manually add `entry.json_schema` (lazy generation only for selected functions)
- Output with `json.dumps(data, indent=2)` for readability

**Performance optimization:**
```python
# Only generate JSON schema for selected functions
registry_data = {}
for fqn, entry in filtered_entries.items():
    data = entry.model_dump(mode="json")
    data["json_schema"] = entry.json_schema  # Lazy generation here
    registry_data[fqn] = data
```

#### Pretty Format
Multi-line text with sections for each entry:
```
=== module.function ===
Title: Calculate Statistics
Description: Calculate mean, median, and stdev of numeric values
Tags: statistics, analysis
Deprecated: No
Import: from module import function

=== another.module.function ===
Title: ...
...
```

For deprecated functions:
```
Deprecated: Yes (Use new_function instead)
```

**Note:** Pretty format doesn't include JSON schema for readability

### 4. Integration with Existing Code

The CLI will:
1. Import `get_registry()` from `wt_registry.registry`
2. Call `get_registry()` to get MappingProxyType of entries
3. Apply function name filter to get subset of entries
4. For JSON format: manually serialize selected entries (triggering lazy schema generation only for selected functions)
5. For pretty format: format selected entries without generating schemas
6. Output to stdout

**Why not use `to_json()`?**
The existing `to_json()` function generates JSON schemas for ALL functions in the registry. When filtering is applied, we want to avoid this unnecessary computation. By manually serializing only the filtered entries, we only trigger `entry.json_schema` property for selected functions.

## Testing Strategy (`tests/test_cli.py`)

### Test Cases

**Basic Functionality:**
1. `test_cli_json_format_default()` - Default JSON output (no filtering)
2. `test_cli_json_format_explicit()` - Explicit `--format json`
3. `test_cli_pretty_format()` - `--format pretty` output
4. `test_cli_empty_registry()` - Handle empty registry gracefully

**Function Name Filtering:**
5. `test_cli_filter_single_function()` - Filter by one function name
6. `test_cli_filter_multiple_functions()` - Multiple function names
7. `test_cli_filter_function_not_found()` - Function name doesn't exist (should not error, just skip)
8. `test_cli_filter_function_partial_match()` - Some functions exist, some don't
9. `test_cli_filter_no_functions_match()` - All specified functions don't exist (empty output)

**Performance/Schema Generation:**
10. `test_cli_filter_only_generates_schema_for_selected()` - Verify JSON schema only generated for selected functions

**Edge Cases:**
11. `test_cli_deprecated_function_json()` - Deprecated function in JSON output
12. `test_cli_deprecated_function_pretty()` - Deprecated function in pretty format
13. `test_cli_function_with_no_tags()` - Function with empty tags list
14. `test_cli_duplicate_function_names_different_modules()` - Two functions with same name but different modules (both should be included)

## Key Design Decisions

1. **Don't use `to_json()`**: Manually serialize to avoid generating JSON schemas for filtered-out functions (performance optimization)
2. **Filter by function name only**: Simple, focused filtering by `entry.function_name`
3. **Silently skip missing functions**: If a function name doesn't exist, just skip it (no error)
4. **Lazy schema generation optimization**: Only call `entry.json_schema` for selected functions when outputting JSON
5. **Multiple function names**: Allow multiple `--function` arguments to select multiple functions
6. **Pretty format without JSON schema**: For readability, don't include full JSON schema in pretty output
7. **Empty registry handling**: Output valid JSON `{}` for machine-readable format

## Example Usage

```bash
# Export entire registry as JSON
wt-registry > registry.json

# Export in human-readable format
wt-registry --format pretty

# Filter by function names
wt-registry --function calculate_mean
wt-registry --function func1 --function func2

# Filter in pretty format
wt-registry --format pretty --function calculate_statistics

# Non-existent function names are silently skipped
wt-registry --function real_func --function fake_func  # Only outputs real_func
```

## Notes

- Entry point is already configured in `pyproject.toml` line 30
- CLI doesn't need to modify registry, only read and display
- **Performance optimization**: By not using `to_json()`, we avoid generating schemas for all functions
- JSON schema generation is expensive (uses Pydantic TypeAdapter), so only do it for selected functions
- All filtering is done in-memory after loading full registry
- Function name filter matches on `entry.function_name` (not FQN), so functions from different modules with same name will both be included
