# Prevention Strategies & Best Practices: Subprocess-Based Discovery Errors

## Problem Context

Users received cryptic errors when the `wt-registry` CLI wasn't available in ephemeral environments during task discovery. The wt-compiler package creates temporary conda environments to discover registered tasks by invoking the `wt-registry` CLI as a subprocess. When users didn't include `wt-registry` as a dependency, the executable was silently missing, leading to confusing error messages.

**What went wrong:**
```python
# Before: Vague subprocess failure
subprocess.run([str(wt_registry_exe), "--format", "json"], check=True)
# CalledProcessError: Command '[...] failed with exit code 127'
```

**What changed:**
```python
# After: Explicit checks with actionable guidance
if not wt_registry_exe.exists():
    raise RegistryNotFoundError(
        executable_path=wt_registry_exe,
        requirements=requirements,
    )
# RegistryNotFoundError: wt-registry executable not found at '...'
# The ephemeral environment was created with the following packages:
#   - my-tasks>=1.0.0
# ...
# To fix this issue, ensure your task packages include wt-registry as a dependency:
#   1. Add 'wt-registry' to your package's conda dependencies, OR
#   2. Add 'wt-registry' to the requirements in your spec.yaml
```

---

## Prevention Strategies

### 1. **Explicit Existence Checks Before Subprocess Calls**

**Strategy:** Always verify that executables and required files exist before invoking subprocesses, rather than relying on subprocess error codes.

**Implementation:**
```python
# Good: Check before running
executable_path = env_path / "bin" / "wt-registry"
if not executable_path.exists():
    raise RegistryNotFoundError(
        executable_path=executable_path,
        requirements=requirements,
    )
result = subprocess.run([str(executable_path), "--format", "json"], ...)

# Bad: Let subprocess fail
result = subprocess.run([str(executable_path), "--format", "json"], check=True)
# This produces cryptic exit codes like 127 or "file not found"
```

**Why this works:**
- File system checks are faster than subprocess startup
- Enables custom exception handling specific to the problem
- Allows proactive error messaging before command execution

**When to apply:**
- Any subprocess invocation that depends on external executables
- Ephemeral environment patterns where dependencies might be missing
- Batch processing where early detection saves time

---

### 2. **Comprehensive Context in Error Messages**

**Strategy:** Include all relevant context that helps users understand what went wrong and how to fix it.

**Implementation:**
```python
class RegistryNotFoundError(DiscoveryError):
    """Include: (1) what failed, (2) why it failed, (3) how to fix it"""

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
```

**Error message structure (WHAT-WHY-HOW):**
1. **WHAT:** "wt-registry executable not found at '...'"
2. **CONTEXT:** List all packages that were installed (helps users realize their package isn't a dependency)
3. **WHY:** "wt-registry CLI is required for task discovery but was not installed because..."
4. **HOW:** "To fix this issue, ensure your task packages include wt-registry as a dependency"

**When to apply:**
- All exceptions in critical paths
- Any error that indicates a misconfiguration or missing dependency
- Errors where the user's action caused the problem

---

### 3. **Exception Hierarchy for Distinguishing Error Types**

**Strategy:** Create a domain-specific exception hierarchy so callers can handle different error types appropriately.

**Implementation:**
```python
class DiscoveryError(Exception):
    """Base exception for all task discovery errors."""
    pass

class RegistryNotFoundError(DiscoveryError):
    """Executable is missing (dependency issue)"""
    pass

class RegistryExecutionError(DiscoveryError):
    """Executable exists but fails to run (version/compatibility issue)"""
    pass
```

**Benefits:**
- Callers can `except RegistryNotFoundError` vs `except RegistryExecutionError`
- Each exception type can provide type-specific debugging info
- Clear semantic meaning for different failure modes

**Usage pattern:**
```python
try:
    tasks = await discover_tasks_from_requirements(reqs)
except RegistryNotFoundError as e:
    # Missing dependency - user action needed
    logger.error(f"Missing dependency: {e}")
    sys.exit(1)
except RegistryExecutionError as e:
    # Version mismatch or internal error - might be transient
    logger.error(f"Execution failed: {e}")
    # Could retry or suggest debugging steps
except DiscoveryError as e:
    # Catch-all for other discovery issues
    logger.error(f"Discovery failed: {e}")
```

---

### 4. **Pair Error Checking with Input Validation**

**Strategy:** Validate requirements and dependencies early, before creating ephemeral environments.

**Implementation:**
```python
async def discover_tasks_from_requirements(
    requirements: list[MatchSpec],
    channels: list[Channel] | None = None,
    platform: Platform | None = None,
) -> dict[str, dict[str, KnownTask]]:
    """Validate inputs before time-consuming environment creation."""

    # Check 1: Ensure requirements are non-empty
    if not requirements:
        raise ValueError("At least one requirement must be specified")

    # Check 2: Ensure wt-registry is in requirements
    registry_in_reqs = any(
        "wt-registry" in str(spec) for spec in requirements
    )
    if not registry_in_reqs:
        logger.warning(
            "wt-registry not in requirements; it will be discovered as a transitive dependency. "
            "If it's missing, ensure your packages depend on wt-registry."
        )

    # Check 3: Create environment (this is expensive)
    await _create_environment(env_path, requirements, channels, platform)

    # Check 4: Verify executable exists before subprocess
    if not wt_registry_exe.exists():
        raise RegistryNotFoundError(...)
```

**Why this matters:**
- Prevents wasting time on environment creation if inputs are invalid
- Early warning about likely misconfigurations
- Gives users a chance to fix problems before expensive operations

---

### 5. **Test the Unhappy Path**

**Strategy:** Write tests for every error condition, not just the happy path.

**Implementation:**
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
        mock_tmpdir.return_value.__enter__ = MagicMock(return_value="/fake/tmpdir")
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(RegistryNotFoundError) as exc_info:
            await discover_tasks_from_requirements([MatchSpec("some-package>=1.0.0")])

        error = exc_info.value
        error_msg = str(error)
        assert "wt-registry executable not found" in error_msg
        assert "some-package" in error_msg  # Requirements listed
        assert "wt-registry" in error_msg  # Fix suggestion included

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.subprocess.run")
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_registry_execution_failure_raises_descriptive_error(
        self, mock_tmpdir, mock_install, mock_run, tmp_path
    ):
        """Test that wt-registry failure raises RegistryExecutionError with stderr."""
        # Setup: executable exists but fails
        env_path = tmp_path / "env"
        bin_path = env_path / "bin"
        bin_path.mkdir(parents=True)
        (bin_path / "wt-registry").touch()

        mock_tmpdir.return_value.__enter__ = MagicMock(return_value=str(tmp_path))
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="ImportError: No module named 'some_dep'",
        )

        with pytest.raises(RegistryExecutionError) as exc_info:
            await discover_tasks_from_requirements([MatchSpec("my-package>=1.0.0")])

        error = exc_info.value
        error_msg = str(error)
        assert "exit code 1" in error_msg
        assert "ImportError" in error_msg  # stderr included
```

**Test coverage checklist:**
- ✓ Executable not found
- ✓ Executable exists but returns non-zero exit code
- ✓ Executable returns invalid JSON
- ✓ Executable returns valid JSON but wrong schema
- ✓ Environment creation fails
- ✓ Multiple requirements with some missing dependencies

---

## Best Practices for Subprocess-Based Discovery Patterns

### 1. **Three-Layer Error Handling**

Implement error handling at three layers:

**Layer 1: Preconditions (Before subprocess)**
```python
# Check everything that must exist before running subprocess
if not wt_registry_exe.exists():
    raise RegistryNotFoundError(...)

if not env_path.exists():
    raise EnvironmentNotFoundError(...)
```

**Layer 2: Subprocess Execution (During subprocess)**
```python
result = subprocess.run(
    [str(wt_registry_exe), "--format", "json"],
    capture_output=True,
    text=True,
    check=False,  # Don't auto-raise CalledProcessError
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

**Layer 3: Output Validation (After subprocess)**
```python
try:
    registry_output = RegistryOutput.model_validate_json(result.stdout)
except ValidationError as e:
    raise DiscoveryError(
        f"wt-registry returned invalid JSON: {e}"
    ) from e
```

---

### 2. **Always Capture and Expose Subprocess Output**

**Do:**
```python
result = subprocess.run(
    cmd,
    capture_output=True,  # Capture both stdout and stderr
    text=True,  # Return strings, not bytes
    check=False,  # Handle errors explicitly
)

if result.returncode != 0:
    raise RegistryExecutionError(
        executable_path=executable,
        returncode=result.returncode,
        stdout=result.stdout,  # Include in exception
        stderr=result.stderr,  # Include in exception
        requirements=requirements,
    )
```

**Don't:**
```python
result = subprocess.run(cmd, check=True)  # Raises CalledProcessError
# CalledProcessError doesn't include stderr output by default
```

**Why:**
- Users need the actual error message to debug
- Stderr output provides crucial diagnostic information
- Capturing output prevents it from appearing elsewhere in logs

---

### 3. **Document All Failure Modes**

**In function docstrings:**
```python
async def discover_tasks_from_requirements(
    requirements: list[MatchSpec],
    channels: list[Channel] | None = None,
    platform: Platform | None = None,
) -> dict[str, dict[str, KnownTask]]:
    """Discover tasks by creating an ephemeral rattler environment.

    ...

    Raises:
        RegistryNotFoundError: If wt-registry is not installed in the environment
        RegistryExecutionError: If wt-registry CLI returns non-zero exit code
        json.JSONDecodeError: If CLI output is not valid JSON
        ValueError: If CLI output doesn't match expected schema

    Examples:
        >>> from rattler import MatchSpec
        >>> reqs = [MatchSpec("wt-registry>=0.1.0")]
        >>> # tasks = await discover_tasks_from_requirements(reqs)  # doctest: +SKIP
    """
```

**Document in module docstring:**
```python
"""Task discovery via py-rattler and wt-registry CLI.

This module provides the core innovation of the wt-compiler package:
discovering tasks by creating ephemeral rattler environments using py-rattler's
native async API (solve + install) and calling the wt-registry CLI, avoiding
direct Python import dependencies on task libraries.

Common failure modes:
1. wt-registry not installed: Add it to your package's conda dependencies
2. wt-registry version incompatible: Update wt-registry or the task package
3. Task package import error: The registered task has a missing dependency
"""
```

---

### 4. **Use Type-Safe Subprocess Patterns**

**Pattern: Subprocess wrapper class**
```python
class SubprocessRunner:
    """Wrapper for subprocess calls with proper error handling."""

    def run(
        self,
        cmd: list[str],
        *,
        require_success: bool = False,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a command with standard error handling."""
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

        if require_success and result.returncode != 0:
            self._handle_failure(result)

        return result

    def _handle_failure(self, result: subprocess.CompletedProcess[str]) -> None:
        """Convert subprocess failure to domain-specific exception."""
        raise RegistryExecutionError(...)
```

**Benefits:**
- Consistent error handling across all subprocess calls
- Easier to add new behavior (timeouts, retries, logging)
- One place to maintain subprocess best practices

---

### 5. **Environment-Aware Error Messages**

**Strategy:** Include information about the environment in error messages.

```python
class RegistryNotFoundError(DiscoveryError):
    def __str__(self) -> str:
        req_list = "\n".join(f"  - {req}" for req in self.requirements)
        return f"""wt-registry executable not found at '{self.executable_path}'

The ephemeral environment was created with the following packages:
{req_list}

Installed location:
  {self.executable_path.parent.parent}

The wt-registry CLI is required for task discovery but was not installed
because none of the specified packages depend on wt-registry.

To fix this issue, ensure your task packages include wt-registry as a dependency:
  1. Add 'wt-registry' to your package's conda dependencies, OR
  2. Add 'wt-registry' to the requirements in your spec.yaml"""
```

**Helpful context includes:**
- What packages were installed (helps users realize their package isn't a dependency)
- Where the environment was created
- Specific fix suggestions for their situation

---

## Testing Recommendations

### Test Categories

**1. Precondition Tests**
```python
def test_missing_executable_raises_not_found_error():
    """Test that missing executable is detected before subprocess call."""
    # Verify Path.exists() check happens
    # Verify subprocess.run is never called
```

**2. Subprocess Output Tests**
```python
def test_subprocess_failure_includes_stderr_in_error():
    """Test that error messages include subprocess output."""
    # Mock subprocess.run to return non-zero exit code
    # Verify RegistryExecutionError includes stderr
    # Verify error message is user-readable
```

**3. Output Validation Tests**
```python
def test_invalid_json_output_raises_validation_error():
    """Test that non-JSON subprocess output is caught."""
    # Mock subprocess.run to return invalid JSON
    # Verify ValidationError is raised with context
```

**4. Integration Tests (Slow)**
```python
@pytest.mark.slow
async def test_end_to_end_discovery_with_real_registry():
    """Test full discovery with actual wt-registry CLI."""
    # Uses real environment creation
    # Verifies all layers work together
    # Skip if wt-registry not installed
```

### Test Coverage Checklist

- [ ] Executable not found before subprocess call
- [ ] Executable found but returns non-zero exit code
- [ ] Executable returns invalid JSON
- [ ] Executable returns JSON with wrong schema
- [ ] Subprocess stdout and stderr are captured
- [ ] Error messages are user-readable and actionable
- [ ] Error messages include all relevant context
- [ ] Error inheritance hierarchy works correctly
- [ ] Preconditions are validated before expensive operations
- [ ] Integration test verifies all layers together

---

## Documentation Improvements

### 1. **Troubleshooting Guide**

Create a `TROUBLESHOOTING.md` section in the compiler README:

```markdown
## Troubleshooting Task Discovery

### Error: "wt-registry executable not found"

This error occurs when the ephemeral environment created for task discovery
doesn't contain the `wt-registry` CLI. This typically means your task package
doesn't depend on `wt-registry`.

**Solution:**
1. Ensure `wt-registry` is listed as a conda dependency in your package
2. Or add `wt-registry` explicitly to your `spec.yaml` requirements

**Example package.yaml:**
```yaml
dependencies:
  - python >=3.10
  - wt-registry >=0.1.0  # <-- Add this
```

### Error: "wt-registry CLI failed with exit code 1"

This error occurs when `wt-registry` is found but fails to execute.

Common causes:
- Incompatible version of `wt-registry`
- Missing dependencies in the environment
- A bug in `wt-registry` or your registered task functions

**Debug steps:**
1. Check stderr output in the error message
2. Try running `wt-registry --format json` manually in your environment
3. Verify all imports in your task package work correctly
```

### 2. **Architecture Decision Record (ADR)**

Document why subprocess-based discovery was chosen:

```markdown
## ADR: Subprocess-Based Task Discovery

**Context:** How should wt-compiler discover registered tasks without
requiring direct imports?

**Decision:** Use subprocess to invoke the wt-registry CLI in an ephemeral
environment created by py-rattler.

**Rationale:**
1. Avoids dependency conflicts (user can have different versions)
2. Ephemeral environments are isolated and clean
3. Subprocess pattern is more resilient to incompatible packages

**Consequences:**
1. Must detect missing wt-registry CLI early
2. Need clear error messages when CLI is absent
3. Subprocess output must be captured for debugging
4. Implementation is more complex than direct imports

**Mitigations:**
1. Explicit existence checks before subprocess invocation
2. Comprehensive error messages with fix suggestions
3. Three-layer error handling (preconditions, execution, output)
4. Extensive testing of failure modes
```

### 3. **Dependency Declaration Best Practices**

Document how to properly declare wt-registry as a dependency:

```markdown
## Declaring Dependencies on wt-registry

Task packages that are discovered by wt-compiler must depend on `wt-registry`
for the CLI to be available during discovery.

**Conda package (meta.yaml):**
```yaml
dependencies:
  - python >=3.10
  - wt-registry >=0.1.0
  - other-packages
```

**spec.yaml requirements:**
```yaml
requirements:
  - name: my-task-package
    version: ">=1.0.0"
  - name: wt-registry  # <-- Required for discovery
    version: ">=0.1.0"
```
```

---

## Summary: Prevention Checklist

When implementing subprocess-based patterns in your application:

- [ ] **Preconditions:** Check all required files/executables exist before subprocess
- [ ] **Error handling:** Handle subprocess failures with `check=False` and explicit checks
- [ ] **Output capture:** Always use `capture_output=True` and `text=True`
- [ ] **Custom exceptions:** Create domain-specific exceptions with rich context
- [ ] **Error messages:** Follow WHAT-WHY-HOW structure in error strings
- [ ] **Exception hierarchy:** Build inheritance tree matching problem domain
- [ ] **Documentation:** Document all failure modes in docstrings
- [ ] **Testing:** Test every error path, not just happy path
- [ ] **Input validation:** Validate inputs before expensive operations
- [ ] **Integration tests:** Test the full flow with mocks and real scenarios

---

## Related Commits

- **Commit 4158ff3:** Improve error messages when wt-registry CLI is not found
- **Commit 3b22e92:** Fix propagate custom channels to task discovery in wt-compiler
- **Commit c9ab8b7:** Feat use py-rattler native API for environment creation in discovery

---

## References

See implementation examples in:
- `/wt-compiler/src/wt_compiler/discovery.py` - Three-layer error handling
- `/wt-compiler/src/wt_compiler/exceptions.py` - Exception hierarchy and messages
- `/wt-compiler/tests/test_exceptions.py` - Comprehensive error testing
- `/wt-compiler/tests/test_discovery_integration.py` - Integration tests
