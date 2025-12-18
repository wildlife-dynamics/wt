# Plan: Integrate discovery.py into compiler.py

## Summary

`compiler.py` does NOT use the discovery mechanism in `discovery.py`. The `known_tasks` global dict is empty, so any `Spec` validation fails when trying to resolve task names. This plan integrates task discovery into the compilation workflow.

## Key Findings

1. **discovery.py** provides `populate_known_tasks()` which fills the global `known_tasks` dict in `spec.py`
2. **spec.py** line 149: `known_tasks: dict[str, dict[str, KnownTask]] = {}` - empty by default
3. **spec.py** `TaskInstance.known_task` (line 719) calls `_resolve_task_from_name_or_reference()` which requires `known_tasks` to be populated
4. **compiler.py** never imports or calls any discovery function
5. **wt-contracts** already exists with `RegistryOutput` schema (line 16 of pyproject.toml shows dependency)

## The Problem

When a `Spec` is validated via Pydantic, it triggers `TaskInstance.known_task` validation for each task, which looks up the global `known_tasks` dict. Since nothing populates this dict, validation fails with "Task 'X' not found in known tasks".

## User Requirements (from clarifying questions)

1. Discovery should happen **before Spec validation**
2. Use **wt-contracts** `RegistryOutput` for type-safe deserialization
3. **No caching** for now
4. `compile_workflow()` should **automatically trigger discovery**

## Implementation Plan

### Step 1: Update discovery.py to use wt-contracts

**File:** `wt/wt-compiler/src/wt_compiler/discovery.py`

1. Add import: `from wt_contracts.registry import RegistryOutput, RegistryEntry`
2. Update `discover_tasks_from_requirements()`:
   - Replace `json.loads(result.stdout)` with `RegistryOutput.model_validate_json(result.stdout)`
   - Remove manual "entries" key validation (Pydantic handles it)
   - Update KnownTask creation to use typed `RegistryEntry` fields

**Changes:**
```python
# Line ~8: Add import
from wt_contracts.registry import RegistryOutput, RegistryEntry

# Line ~108: Replace JSON parsing
# OLD:
registry_data = json.loads(result.stdout)
if "entries" not in registry_data:
    raise ValueError(...)

# NEW:
registry_output = RegistryOutput.model_validate_json(result.stdout)

# Line ~119: Update loop
# OLD:
for fqn, entry in registry_data["entries"].items():
    module_path = entry.get("module_path", "")
    ...

# NEW:
for fqn, entry in registry_output.entries.items():
    # entry is now typed as RegistryEntry
    module_path = entry.module_path
    function_name = entry.function_name
    ...
```

### Step 2: Create two-phase YAML loading in compiler.py

**File:** `wt/wt-compiler/src/wt_compiler/compiler.py`

The challenge: `Spec` validation requires `known_tasks` to be populated, but we need to parse the YAML to know the requirements. Solution: two-phase loading.

1. Add new function `_parse_requirements_from_yaml()` that extracts just the requirements list without full Spec validation
2. Add new function `compile_workflow_from_yaml()` that:
   - Phase 1: Parse requirements from YAML
   - Phase 2: Call `populate_known_tasks()` with those requirements
   - Phase 3: Validate full `Spec` (now works because known_tasks is populated)
   - Phase 4: Compile
3. Update `compile_workflow()` to accept either `Spec` or `Path` and auto-detect

**New code to add:**

```python
# Add imports at top
from pathlib import Path
from wt_compiler.discovery import populate_known_tasks, discover_tasks_from_spec_requirements

def _parse_requirements_from_yaml(yaml_path: Path) -> list[SpecRequirement]:
    """Parse just the requirements from a spec YAML without full validation.

    This enables discovery before Spec validation.
    """
    with open(yaml_path) as f:
        data = yaml.load(f)

    # Parse only requirements - minimal validation
    requirements = []
    for req_data in data.get("requirements", []):
        # Create SpecRequirement without full Spec validation
        requirements.append(SpecRequirement.model_validate(req_data))

    return requirements


def compile_workflow_from_yaml(
    yaml_path: str | Path,
    **compiler_kwargs: Any,
) -> WorkflowArtifacts:
    """Compile a workflow from a spec.yaml file.

    This function handles the complete workflow:
    1. Parse requirements from YAML
    2. Discover tasks via wt-registry CLI
    3. Validate full Spec (with known_tasks now populated)
    4. Compile to artifacts

    Args:
        yaml_path: Path to spec.yaml file
        **compiler_kwargs: Additional arguments for DagCompiler

    Returns:
        Compiled workflow artifacts
    """
    yaml_path = Path(yaml_path)

    # Phase 1: Parse requirements
    requirements = _parse_requirements_from_yaml(yaml_path)

    # Phase 2: Discover tasks and populate known_tasks
    discover_tasks_from_spec_requirements(requirements)

    # Phase 3: Now we can safely validate the full Spec
    with open(yaml_path) as f:
        data = yaml.load(f)
    spec = Spec.model_validate(data)

    # Phase 4: Compile
    spec_relpath = str(yaml_path)
    return compile_workflow(spec, spec_relpath, **compiler_kwargs)
```

### Step 3: Update compile_workflow() for backward compatibility

Keep existing `compile_workflow(spec, spec_relpath)` signature but add warning if called directly:

```python
def compile_workflow(
    spec: Spec,
    spec_relpath: str,
    **compiler_kwargs: Any,
) -> WorkflowArtifacts:
    """Compile a workflow from a validated Spec.

    Note: If calling with a Spec directly, ensure known_tasks is populated
    first via discovery. For automatic discovery, use compile_workflow_from_yaml().
    """
    compiler = DagCompiler(spec=spec, **compiler_kwargs)
    return compiler.compile(spec_relpath)
```

### Step 4: Update __init__.py exports

**File:** `wt/wt-compiler/src/wt_compiler/__init__.py`

Add exports for the new functions:
```python
from wt_compiler.compiler import compile_workflow, compile_workflow_from_yaml
from wt_compiler.discovery import (
    discover_tasks_from_requirements,
    populate_known_tasks,
    discover_tasks_from_spec_requirements,
)
```

### Step 5: Add tests

**File:** `wt/wt-compiler/tests/test_discovery_integration.py` (new file)

```python
"""Integration tests for discovery + compilation."""

def test_compile_workflow_from_yaml_discovers_tasks():
    """Test that compile_workflow_from_yaml populates known_tasks."""
    ...

def test_discovery_uses_wt_contracts_schema():
    """Test that discovery validates against RegistryOutput."""
    ...
```

## Files to Modify

1. `wt/wt-compiler/src/wt_compiler/discovery.py` - Use wt-contracts types
2. `wt/wt-compiler/src/wt_compiler/compiler.py` - Add `compile_workflow_from_yaml()`
3. `wt/wt-compiler/src/wt_compiler/__init__.py` - Export new functions
4. `wt/wt-compiler/tests/test_discovery_integration.py` - New test file

## Order of Changes

1. discovery.py (use wt-contracts) - isolated change
2. compiler.py (add new functions) - depends on #1
3. __init__.py (exports) - depends on #2
4. tests - depends on all above

## Risk Considerations

- **Breaking change for direct Spec users**: If anyone creates a `Spec` directly without discovery, it will fail. Mitigation: Document that `compile_workflow_from_yaml()` is the preferred entry point.
- **Discovery performance**: Creating rattler environments is slow (~10-30s). No caching per user request, but could add later.
- **wt-registry CLI availability**: If wt-registry is not installed in the target environment, discovery fails. Current error handling is adequate.
