# Examples Directory Restructuring Plan

## Overview
Create a proper `examples/` directory with standalone uv scripts that demonstrate wt-registry features. Each script should be self-contained and runnable via `uv run`.

## Current State
- `example_module.py` - Module with registered functions (top-level)
- `test_cli_demo.py` - Demo script that imports example_module (top-level)
- These are useful but not well-organized or documented

## Goals
1. Create `examples/` directory at repository root
2. Convert existing examples to standalone uv scripts
3. Each script should be fully self-contained with:
   - uv-style script dependencies (inline metadata)
   - Function registration code
   - CLI invocation
   - All in one file
4. Update documentation to reference examples
5. Establish pattern for future feature examples

## Implementation Plan

### 1. Create Examples Directory Structure

```
examples/
├── README.md                 # Overview of examples, how to run them
├── basic_registration.py     # Simple registration example
├── cli_json_output.py        # CLI with JSON output
├── cli_pretty_output.py      # CLI with pretty format
├── filtering_functions.py    # CLI filtering by function name
├── deprecated_functions.py   # Deprecated function example
└── multiple_modules.py       # Functions from different "modules" (simulated)
```

### 2. Script Format (uv inline script metadata)

Each script should follow this structure:

```python
#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "wt-registry",  # Will use local version when run from repo
# ]
# ///
"""
Example: Basic Function Registration

This example demonstrates how to register functions with wt-registry
and view them using the CLI.

Run with: uv run examples/basic_registration.py
"""

from wt_registry import register

# Register functions with metadata
@register(
    title="Add Two Numbers",
    description="Calculate the sum of two integers",
    tags=["math", "basic"]
)
def add(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b

# More registrations...

if __name__ == "__main__":
    # Invoke CLI to show registered functions
    from wt_registry.cli import main
    import sys

    # Set CLI arguments programmatically
    sys.argv = ["example", "--format", "pretty"]
    main()
```

### 3. Individual Example Scripts

#### `examples/basic_registration.py`
- Simple example with 2-3 basic functions
- Demonstrates minimal registration with title and description
- Shows pretty output format
- Good "getting started" example

#### `examples/cli_json_output.py`
- Same functions but outputs JSON format
- Demonstrates JSON schema generation
- Shows structure of JSON output
- Useful for integration scenarios

#### `examples/cli_pretty_output.py`
- Multiple functions with rich metadata (tags, descriptions)
- Demonstrates pretty format capabilities
- Shows how metadata is displayed

#### `examples/filtering_functions.py`
- Register 4-5 functions
- Demonstrates filtering by function name
- Shows multiple CLI invocations with different filters
- Prints before/after to show filtering effect

#### `examples/deprecated_functions.py`
- Mix of current and deprecated functions
- Shows deprecation_message usage
- Demonstrates how deprecated functions appear in output

#### `examples/multiple_modules.py`
- Simulate functions from different modules using nested classes or tricks
- Show how FQN works across "modules"
- Demonstrate filtering functions with same name from different modules

### 4. examples/README.md

Create comprehensive README for examples directory:

```markdown
# wt-registry Examples

This directory contains standalone examples demonstrating wt-registry features.

## Running Examples

All examples are standalone uv scripts. Run them directly with:

```bash
uv run examples/basic_registration.py
```

No installation or setup required! Each script is self-contained.

## Available Examples

### Getting Started

- **basic_registration.py** - Start here! Basic function registration and CLI usage
- **cli_json_output.py** - JSON output format for programmatic use
- **cli_pretty_output.py** - Human-readable output format

### Advanced Features

- **filtering_functions.py** - Filter registry by function names
- **deprecated_functions.py** - Mark functions as deprecated
- **multiple_modules.py** - Work with functions from multiple modules

## Example Structure

Each example follows this pattern:
1. Function definitions with @register decorator
2. Metadata (title, description, tags, etc.)
3. CLI invocation to display registered functions

## Contributing Examples

When adding significant features to wt-registry, please add corresponding examples here!
```

### 5. Update Project Documentation

#### Update `README.md`
Add early in README (before or after installation):

```markdown
## Quick Start with Examples

The fastest way to see wt-registry in action:

```bash
# Clone the repository
git clone https://github.com/USERNAME/wt-registry.git
cd wt-registry

# Run an example (no installation needed!)
uv run examples/basic_registration.py
```

See [examples/README.md](examples/README.md) for more examples.
```

#### Update `docs/plan.md` or create `docs/contributing.md`
Add section on examples:

```markdown
## Adding Examples

When implementing significant new features, add a corresponding example:

1. Create a standalone uv script in `examples/`
2. Use inline script metadata for dependencies
3. Include docstring explaining the feature
4. Register functions demonstrating the feature
5. Invoke CLI to show output
6. Update `examples/README.md` with description

Examples serve as both documentation and integration tests.
```

### 6. Clean Up Root Directory

After creating examples/ directory:
- Delete `example_module.py`
- Delete `test_cli_demo.py`
- These will be replaced by better organized examples/

### 7. Update .gitignore (if needed)

Ensure examples don't generate unwanted files:
```
# Example outputs (if any scripts write files)
examples/*.json
examples/*.txt
```

## Implementation Steps

1. Create `examples/` directory
2. Create `examples/README.md`
3. Write `examples/basic_registration.py`
4. Write `examples/cli_json_output.py`
5. Write `examples/cli_pretty_output.py`
6. Write `examples/filtering_functions.py`
7. Write `examples/deprecated_functions.py`
8. Write `examples/multiple_modules.py`
9. Test each example: `uv run examples/<script>.py`
10. Update main `README.md` with Quick Start section
11. Add note to `docs/plan.md` or `docs/contributing.md`
12. Delete `example_module.py` and `test_cli_demo.py`
13. Commit changes

## Testing Plan

For each example script:
1. Run with `uv run examples/<script>.py`
2. Verify output is correct and readable
3. Verify no errors or warnings
4. Check that dependencies are properly declared

## Key Design Decisions

1. **Standalone uv scripts**: Each example is self-contained and runnable
2. **Inline script metadata**: Uses PEP 723 format for dependencies
3. **No external files**: Each example is a single .py file
4. **CLI invocation in script**: Examples demonstrate full workflow
5. **Progressive complexity**: Start simple, build to advanced features
6. **Self-documenting**: Docstrings explain what each example shows

## Benefits

- **Easy onboarding**: New users can run examples immediately
- **Living documentation**: Examples are always up-to-date
- **Pattern for contributions**: Clear template for adding feature examples
- **No setup required**: uv handles everything
- **Discoverable**: Clearly organized in examples/ directory

## Files to Create/Modify

### New Files
- `examples/README.md`
- `examples/basic_registration.py`
- `examples/cli_json_output.py`
- `examples/cli_pretty_output.py`
- `examples/filtering_functions.py`
- `examples/deprecated_functions.py`
- `examples/multiple_modules.py`

### Modified Files
- `README.md` - Add Quick Start section
- `docs/plan.md` or `docs/contributing.md` - Add examples guidance

### Deleted Files
- `example_module.py`
- `test_cli_demo.py`

## Success Criteria

- [ ] examples/ directory created with 6 example scripts
- [ ] Each example runs successfully with `uv run`
- [ ] examples/README.md provides clear overview
- [ ] Main README.md has Quick Start section
- [ ] Documentation updated with examples guidance
- [ ] Old example files cleaned up
- [ ] All examples are self-contained and documented
