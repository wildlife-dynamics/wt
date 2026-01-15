---
title: Improve error messages when wt-registry CLI is not found during task discovery
category: runtime-errors
component: wt-compiler
symptoms:
  - FileNotFoundError when wt-registry CLI is not available
  - Cryptic subprocess errors during task discovery
  - Users unaware that task packages require wt-registry dependency
tags:
  - task-discovery
  - dependency-management
  - error-handling
  - wt-registry
  - subprocess-execution
  - conda-environments
date_solved: 2026-01-15
commit: 4158ff3
---

# wt-registry Not Found During Task Discovery

## Problem

When `wt-compiler` tried to discover tasks from packages that didn't include `wt-registry` as a dependency, users received cryptic Python errors with no context about what went wrong or how to fix it.

### Symptoms

- `FileNotFoundError` when running `wt-compiler compile`
- `subprocess.CalledProcessError` with exit code 127 (command not found)
- No indication that wt-registry needs to be a dependency

### Root Cause

The wt-compiler's task discovery process:
1. Creates an ephemeral conda environment from spec requirements
2. Installs only the packages listed in `spec.yaml`
3. Attempts to run `wt-registry --format json` in that environment

If the task packages don't depend on `wt-registry`, it won't be installed in the ephemeral environment, causing the subprocess call to fail with an unhelpful error.

## Solution

Added explicit existence checks and custom exception classes with descriptive error messages.

### Files Modified

| File | Action |
|------|--------|
| `wt-compiler/src/wt_compiler/exceptions.py` | Created |
| `wt-compiler/src/wt_compiler/discovery.py` | Modified |
| `wt-compiler/src/wt_compiler/__init__.py` | Modified |
| `wt-compiler/tests/test_exceptions.py` | Created |
| `wt-compiler/tests/test_discovery_integration.py` | Modified |

### Implementation

#### 1. New Exception Classes

```python
# wt-compiler/src/wt_compiler/exceptions.py

class DiscoveryError(Exception):
    """Base exception for all task discovery errors."""
    pass

class RegistryNotFoundError(DiscoveryError):
    """Raised when wt-registry CLI is not found in the ephemeral environment."""

    def __init__(self, executable_path: Path, requirements: list[MatchSpec]) -> None:
        self.executable_path = executable_path
        self.requirements = requirements
        super().__init__(str(self))

    def __str__(self) -> str:
        req_list = "\n".join(f"  - {req}" for req in self.requirements)
        return f"""wt-registry executable not found at '{self.executable_path}'

The ephemeral environment was created with the following packages:
{req_list}

The wt-registry CLI is required for task discovery but was not installed
because none of the specified packages depend on wt-registry.

To fix this issue, ensure your task packages include wt-registry as a dependency:
  1. Add 'wt-registry' to your package's conda dependencies, OR
  2. Add 'wt-registry' to the requirements in your spec.yaml"""

class RegistryExecutionError(DiscoveryError):
    """Raised when wt-registry CLI fails during execution."""
    # Includes returncode, stdout, stderr for debugging
```

#### 2. Discovery Logic Changes

```python
# wt-compiler/src/wt_compiler/discovery.py

# Before running subprocess, check executable exists
if not wt_registry_exe.exists():
    raise RegistryNotFoundError(
        executable_path=wt_registry_exe,
        requirements=requirements,
    )

# Handle errors explicitly instead of check=True
result = subprocess.run(
    [str(wt_registry_exe), "--format", "json"],
    capture_output=True,
    text=True,
    check=False,  # Handle errors explicitly
)

if result.returncode != 0:
    raise RegistryExecutionError(
        executable_path=wt_registry_exe,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        requirements=requirements,
    )
```

### Error Messages

**Before:**
```
CalledProcessError: Command '[...wt-registry...]' returned non-zero exit status 127
```

**After:**
```
wt-registry executable not found at '/tmp/.../env/bin/wt-registry'

The ephemeral environment was created with the following packages:
  - my-tasks>=1.0.0
  - python>=3.10

The wt-registry CLI is required for task discovery but was not installed
because none of the specified packages depend on wt-registry.

To fix this issue, ensure your task packages include wt-registry as a dependency:
  1. Add 'wt-registry' to your package's conda dependencies, OR
  2. Add 'wt-registry' to the requirements in your spec.yaml
```

## Prevention Strategies

### 1. Explicit Existence Checks
Always check if external executables exist before attempting to run them via subprocess.

### 2. WHAT-WHY-HOW Error Messages
Error messages should include:
- **WHAT**: What went wrong (executable not found)
- **WHY**: Why it happened (no dependency on wt-registry)
- **HOW**: How to fix it (add dependency)

### 3. Exception Hierarchy
Create domain-specific exceptions that inherit from a base exception class. This allows callers to catch specific errors or all errors of a type.

### 4. Test Error Paths
Write tests that verify error scenarios produce the expected exceptions and messages:

```python
@pytest.mark.asyncio
async def test_registry_not_found_raises_descriptive_error(self, ...):
    with pytest.raises(RegistryNotFoundError) as exc_info:
        await discover_tasks_from_requirements([MatchSpec("some-package>=1.0.0")])

    error_msg = str(exc_info.value)
    assert "wt-registry executable not found" in error_msg
    assert "some-package" in error_msg  # Context included
    assert "wt-registry" in error_msg   # Fix suggestion included
```

## Related

- `wt-compiler/src/wt_compiler/discovery.py` - Task discovery implementation
- `wt-compiler/README.md` - "Environment-Isolated Task Discovery" section
- Commit `3b22e92` - Related fix for custom channel propagation
