# Error Handling Patterns: Quick Reference

A practical guide to the error handling patterns demonstrated in the wt-registry discovery fix.

---

## The Problem and Solution at a Glance

### What Went Wrong
```
User installs task package without wt-registry dependency
↓
Ephemeral environment created without wt-registry CLI
↓
subprocess.run() fails with cryptic exit code (127, ENOENT)
↓
User sees: CalledProcessError: Command [...] returned non-zero exit status
↓
User is confused: "What dependency is missing? Where do I even look?"
```

### The Fix
```
Add explicit existence checks and domain-specific exceptions
↓
subprocess.run() never called if executable missing
↓
RegistryNotFoundError raised with complete context
↓
User sees: "wt-registry executable not found. To fix this, add wt-registry
           as a dependency to your package"
↓
User knows exactly what to do
```

---

## Pattern 1: Precondition Checking

### Before
```python
def discover_tasks(env_path, requirements):
    wt_registry_exe = env_path / "bin" / "wt-registry"

    # Hope the executable exists, subprocess will fail if not
    result = subprocess.run(
        [str(wt_registry_exe), "--format", "json"],
        check=True  # This raises CalledProcessError with confusing exit code
    )
    return parse_output(result.stdout)
```

### After
```python
def discover_tasks(env_path, requirements):
    wt_registry_exe = env_path / "bin" / "wt-registry"

    # Check precondition before expensive subprocess call
    if not wt_registry_exe.exists():
        raise RegistryNotFoundError(
            executable_path=wt_registry_exe,
            requirements=requirements,
        )

    # Now it's safe to call subprocess
    result = subprocess.run(
        [str(wt_registry_exe), "--format", "json"],
        capture_output=True,
        text=True,
        check=False  # We'll check the return code explicitly
    )

    if result.returncode != 0:
        raise RegistryExecutionError(...)

    return parse_output(result.stdout)
```

**Key differences:**
- `exists()` check before subprocess
- `check=False` to handle errors explicitly
- `capture_output=True` to get stderr for debugging
- Custom exceptions with rich context

---

## Pattern 2: Rich Error Context

### Before
```python
try:
    result = subprocess.run(
        [executable],
        check=True,
    )
except subprocess.CalledProcessError as e:
    raise RuntimeError(f"Task discovery failed: {e}")
    # User sees: "Task discovery failed: Command [...] returned non-zero exit status 1"
    # User has no idea what went wrong or how to fix it
```

### After
```python
class RegistryNotFoundError(DiscoveryError):
    """Raised when wt-registry CLI is not found in the ephemeral environment."""

    def __init__(
        self,
        executable_path: Path,
        requirements: list[MatchSpec],
    ) -> None:
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

# Usage
if not wt_registry_exe.exists():
    raise RegistryNotFoundError(
        executable_path=wt_registry_exe,
        requirements=requirements,
    )
```

**Error message structure:**
1. **Problem statement:** "wt-registry executable not found at '...'"
2. **Context:** What was installed (helps users understand the gap)
3. **Diagnosis:** Why it happened (missing dependency)
4. **Solution:** Actionable next steps (add to dependencies)

---

## Pattern 3: Exception Hierarchy

### Design Principle
Create exceptions that mirror your problem domain, not Python's built-in exceptions.

```python
# Bad: Reusing built-in exceptions
raise RuntimeError("Task discovery failed")
raise CalledProcessError("...")
raise ValueError("...")
# Problem: Callers can't distinguish between different failure types

# Good: Domain-specific hierarchy
class DiscoveryError(Exception):
    """Base exception for all task discovery errors."""
    pass

class RegistryNotFoundError(DiscoveryError):
    """Executable is missing (usually a missing dependency)."""
    pass

class RegistryExecutionError(DiscoveryError):
    """Executable exists but fails (version mismatch, missing imports)."""
    pass

# Callers can now handle different error types appropriately
try:
    await discover_tasks_from_requirements(reqs)
except RegistryNotFoundError as e:
    # Missing dependency - user action needed
    logger.error(f"Missing dependency: {e}")
    suggest_install_command(e.requirements)
except RegistryExecutionError as e:
    # Execution failed - might be transient
    logger.error(f"Execution failed: {e}")
    # Could retry or suggest debugging
except DiscoveryError as e:
    # Unknown discovery issue
    logger.error(f"Discovery failed: {e}")
```

**Benefits:**
- Semantic clarity: Exception name describes the problem
- Proper handling: Callers can respond appropriately
- Easy to test: Can verify specific exception types

---

## Pattern 4: Three-Layer Error Handling

Structure your error handling in three layers:

### Layer 1: Preconditions (Before subprocess)
Check all requirements before expensive operations.

```python
async def discover_tasks_from_requirements(
    requirements: list[MatchSpec],
    channels: list[Channel] | None = None,
) -> dict[str, dict[str, KnownTask]]:
    """Layer 1: Validate preconditions"""

    # Check input validity
    if not requirements:
        raise ValueError("At least one requirement must be specified")

    # Create ephemeral environment (expensive!)
    with tempfile.TemporaryDirectory() as tmpdir:
        env_path = Path(tmpdir) / "env"
        await _create_environment(env_path, requirements, channels)

        # Layer 2: Check subprocess preconditions
        wt_registry_exe = env_path / "bin" / "wt-registry"
        if not wt_registry_exe.exists():
            raise RegistryNotFoundError(
                executable_path=wt_registry_exe,
                requirements=requirements,
            )

        # Layer 2: Execute subprocess safely
        result = subprocess.run(
            [str(wt_registry_exe), "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise RegistryExecutionError(
                executable_path=wt_registry_exe,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                requirements=requirements,
            )

        # Layer 3: Validate output
        try:
            registry_output = RegistryOutput.model_validate_json(result.stdout)
        except json.JSONDecodeError as e:
            raise DiscoveryError(
                f"wt-registry returned invalid JSON: {e}\n\nOutput:\n{result.stdout}"
            ) from e
        except ValidationError as e:
            raise DiscoveryError(
                f"wt-registry output doesn't match expected schema: {e}"
            ) from e

        return convert_to_known_tasks(registry_output)
```

**Why three layers:**
1. **Preconditions:** Fail fast before expensive work (environment creation)
2. **Execution:** Handle subprocess failures with captured output
3. **Output validation:** Ensure the result is what we expect

---

## Pattern 4: Subprocess Safety

### Anti-patterns to avoid
```python
# Bad: No error handling, hope subprocess succeeds
result = subprocess.run(cmd)

# Bad: Use check=True, get confusing CalledProcessError
result = subprocess.run(cmd, check=True)

# Bad: Don't capture output, can't debug
result = subprocess.run(cmd, capture_output=False)

# Bad: Return bytes, not text
result = subprocess.run(cmd, text=False)
```

### Best practice pattern
```python
# Good: Capture, don't auto-raise, check explicitly, use text
result = subprocess.run(
    cmd,
    capture_output=True,  # Capture stdout and stderr
    text=True,            # Return strings, not bytes
    check=False,          # Don't auto-raise CalledProcessError
    timeout=30,           # Prevent hanging indefinitely
)

# Now handle the result explicitly
if result.returncode != 0:
    raise RegistryExecutionError(
        executable_path=executable,
        returncode=result.returncode,
        stdout=result.stdout,  # Include for debugging
        stderr=result.stderr,  # Include for debugging
        requirements=requirements,
    )
```

**Checklist:**
- ✓ `capture_output=True` - Get stdout and stderr
- ✓ `text=True` - Work with strings, not bytes
- ✓ `check=False` - Handle errors explicitly
- ✓ `timeout=...` - Don't hang indefinitely
- ✓ Check `returncode` explicitly before using output
- ✓ Include stdout/stderr in exceptions

---

## Pattern 5: Docstring Template for Error-Prone Functions

```python
async def discover_tasks_from_requirements(
    requirements: list[MatchSpec],
    channels: list[Channel] | None = None,
    platform: Platform | None = None,
) -> dict[str, dict[str, KnownTask]]:
    """Discover tasks by creating an ephemeral rattler environment.

    This async function:
    1. Creates a temporary directory
    2. Uses py-rattler to solve and install the requirements
    3. Calls wt-registry CLI in that environment
    4. Parses the JSON output
    5. Returns a dictionary of task name -> {module -> KnownTask}

    Args:
        requirements: List of package requirements to install
        channels: Optional list of channels (defaults to conda-forge)
        platform: Optional Platform object (defaults to current platform)

    Returns:
        Dictionary mapping task names to {module: KnownTask} dicts

    Raises:
        RegistryNotFoundError: If wt-registry is not installed in the environment
        RegistryExecutionError: If wt-registry CLI returns non-zero exit code
        json.JSONDecodeError: If CLI output is not valid JSON
        ValueError: If CLI output doesn't match expected schema

    Examples:
        >>> from rattler import MatchSpec
        >>> reqs = [MatchSpec("wt-registry>=0.1.0")]
        >>> # tasks = await discover_tasks_from_requirements(reqs)  # doctest: +SKIP
        >>> # "my_task" in tasks  # doctest: +SKIP
        True
    """
    ...
```

**Key sections:**
- Clear description of what the function does
- Numbered steps for multi-step processes
- Full type annotations in signature
- **Args:** Parameter descriptions
- **Returns:** What to expect in success case
- **Raises:** All exceptions that can be raised (with conditions)
- **Examples:** Show typical usage and expected behavior

---

## Testing Patterns

### Pattern: Test the error case explicitly

```python
class TestDiscoveryErrors:
    """Tests for discovery error handling."""

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_registry_not_found_raises_descriptive_error(
        self, mock_tmpdir, mock_install
    ):
        """Test that missing wt-registry raises RegistryNotFoundError with helpful message."""
        from pathlib import Path
        from rattler import MatchSpec

        # Setup: Create a fake environment without wt-registry
        mock_tmpdir.return_value.__enter__ = MagicMock(return_value="/fake/tmpdir")
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        # Act & Assert
        with pytest.raises(RegistryNotFoundError) as exc_info:
            await discover_tasks_from_requirements([MatchSpec("some-package>=1.0.0")])

        # Verify error contains all necessary information
        error = exc_info.value
        error_msg = str(error)

        assert "wt-registry executable not found" in error_msg
        assert "some-package" in error_msg  # Requirements are listed
        assert "wt-registry" in error_msg  # Fix suggestion is present
```

**Test structure:**
1. **Setup:** Create conditions that trigger the error
2. **Act & Assert:** Call the function and assert the exception
3. **Verify message:** Check that error message contains useful info

---

## Code Review Checklist

When reviewing subprocess-based code, ensure:

### Before Subprocess Calls
- [ ] All required executables are checked with `exists()` or similar
- [ ] All input parameters are validated
- [ ] No expensive operations happen before validation

### Subprocess Call Itself
- [ ] Uses `capture_output=True` to get stdout/stderr
- [ ] Uses `text=True` to get strings, not bytes
- [ ] Uses `check=False` to handle errors explicitly
- [ ] Has a `timeout` parameter to prevent hanging
- [ ] Calls subprocess on a validated path

### After Subprocess Call
- [ ] Checks `returncode` before using output
- [ ] Raises domain-specific exceptions (not `CalledProcessError`)
- [ ] Includes stdout/stderr in exception for debugging
- [ ] Includes request context (what was being requested)

### Error Handling
- [ ] Custom exception hierarchy exists
- [ ] Exceptions have rich context (not just error code)
- [ ] Error messages follow WHAT-WHY-HOW structure
- [ ] All possible exceptions are documented in docstrings
- [ ] Each error case has a corresponding test

---

## Real-World Example: Complete Implementation

```python
# discovery.py
from pathlib import Path
from rattler import MatchSpec
import subprocess
import tempfile
from typing import Any

from wt_contracts.registry import RegistryOutput
from wt_compiler.exceptions import RegistryNotFoundError, RegistryExecutionError
from wt_compiler.spec import KnownTask


async def discover_tasks_from_requirements(
    requirements: list[MatchSpec],
    channels: list[Channel] | None = None,
) -> dict[str, dict[str, KnownTask]]:
    """Discover tasks by creating an ephemeral environment.

    Raises:
        RegistryNotFoundError: If wt-registry is not installed
        RegistryExecutionError: If wt-registry CLI fails
    """

    # Validate preconditions
    if not requirements:
        raise ValueError("At least one requirement must be specified")

    if channels is None:
        channels = [Channel("conda-forge")]

    # Create ephemeral environment
    with tempfile.TemporaryDirectory() as tmpdir:
        env_path = Path(tmpdir) / "env"

        # Step 1: Create environment
        await _create_environment(env_path, requirements, channels)

        # Step 2: Check precondition - executable must exist
        wt_registry_exe = env_path / "bin" / "wt-registry"
        if not wt_registry_exe.exists():
            raise RegistryNotFoundError(
                executable_path=wt_registry_exe,
                requirements=requirements,
            )

        # Step 3: Execute subprocess safely
        result = subprocess.run(
            [str(wt_registry_exe), "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        # Step 4: Check execution result
        if result.returncode != 0:
            raise RegistryExecutionError(
                executable_path=wt_registry_exe,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                requirements=requirements,
            )

        # Step 5: Validate and parse output
        try:
            registry_output = RegistryOutput.model_validate_json(result.stdout)
        except Exception as e:
            raise RegistryExecutionError(
                executable_path=wt_registry_exe,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=f"JSON parsing error: {e}",
                requirements=requirements,
            ) from e

        # Step 6: Convert to internal format
        discovered_tasks: dict[str, dict[str, KnownTask]] = {}

        for _, entry in registry_output.entries.items():
            known_task = KnownTask(
                importable_reference=f"{entry.module_path}.{entry.function_name}",
                tags=[],
                registry_ref=0,
                json_schema=dict(entry.json_schema),
                description=entry.metadata.description,
            )

            if entry.function_name not in discovered_tasks:
                discovered_tasks[entry.function_name] = {}

            discovered_tasks[entry.function_name][entry.module_path] = known_task

        return discovered_tasks


# exceptions.py
class DiscoveryError(Exception):
    """Base exception for all task discovery errors."""
    pass


class RegistryNotFoundError(DiscoveryError):
    """Raised when wt-registry CLI is not found."""

    def __init__(self, executable_path: Path, requirements: list[MatchSpec]) -> None:
        self.executable_path = executable_path
        self.requirements = requirements
        super().__init__(str(self))

    def __str__(self) -> str:
        req_list = "\n".join(f"  - {req}" for req in self.requirements)
        return f"""wt-registry executable not found at '{self.executable_path}'

The ephemeral environment was created with:
{req_list}

To fix: Add 'wt-registry' to your package's conda dependencies"""


class RegistryExecutionError(DiscoveryError):
    """Raised when wt-registry CLI fails."""

    def __init__(
        self,
        executable_path: Path,
        returncode: int,
        stdout: str,
        stderr: str,
        requirements: list[MatchSpec],
    ) -> None:
        self.executable_path = executable_path
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.requirements = requirements
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"""wt-registry CLI failed with exit code {self.returncode}

Command: {self.executable_path} --format json

stderr:
{self.stderr or "(empty)"}

This may indicate:
  - An incompatible version of wt-registry
  - Missing dependencies in the environment
  - A bug in wt-registry or registered task functions"""
```

---

## Summary

The key insight: **Always check preconditions explicitly and provide rich error context.**

Instead of hoping subprocess calls succeed and catching cryptic errors, this pattern:
1. ✓ Checks all preconditions before subprocess (fail fast)
2. ✓ Executes subprocess safely with proper output capture
3. ✓ Raises domain-specific exceptions with rich context
4. ✓ Provides actionable error messages users can understand
5. ✓ Tests all error paths, not just the happy path

This makes debugging and troubleshooting far easier for users.
