# Testing Error Paths: Comprehensive Guide

How to write tests that catch subprocess-related errors and ensure your error messages are actually helpful.

---

## Why Test Error Cases?

Error cases are just as important as happy paths because:

1. **Users encounter errors more than you think** - Configuration mistakes, missing dependencies, version conflicts
2. **Cryptic errors cost support time** - Each unclear error message generates questions
3. **Error messages are documentation** - They teach users how to use your system
4. **Error handling is behavior** - If not tested, it changes silently

The original issue: `subprocess.run()` failed silently with exit code 127, and users had no way to understand what was missing.

---

## Test Structure: The Four-Part Pattern

Every error path test should have four parts:

### 1. Setup: Create conditions for the error
```python
@pytest.mark.asyncio
@patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
@patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
async def test_registry_not_found_raises_error(self, mock_tmpdir, mock_install):
    """Test that missing wt-registry is detected."""

    # SETUP: Create fake environment without wt-registry
    mock_tmpdir.return_value.__enter__ = MagicMock(return_value="/fake/tmpdir")
    mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)
    # The key: /fake/tmpdir/env/bin/wt-registry will not exist
```

### 2. Act: Call the function that should error
```python
    # ACT: Try to discover tasks from a non-existent executable
    with pytest.raises(RegistryNotFoundError) as exc_info:
        await discover_tasks_from_requirements([MatchSpec("some-package>=1.0.0")])
```

### 3. Assert: Verify the exception type
```python
    # ASSERT: Correct exception was raised
    error = exc_info.value
    assert isinstance(error, RegistryNotFoundError)
    assert error.executable_path is not None
    assert error.requirements is not None
```

### 4. Verify: Check that error message is helpful
```python
    # VERIFY: Error message is user-readable and actionable
    error_msg = str(error)
    assert "wt-registry executable not found" in error_msg
    assert "some-package" in error_msg  # Context about what was installed
    assert "wt-registry" in error_msg  # Fix suggestion
```

---

## Complete Error Path Tests

### Test 1: Missing Executable

**Scenario:** Environment created but wt-registry CLI not installed

```python
class TestMissingExecutable:
    """Tests for when wt-registry executable is not found."""

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_missing_executable_raises_not_found_error(
        self, mock_tmpdir, mock_install
    ):
        """Test that missing executable raises RegistryNotFoundError.

        This is the most common error - user didn't add wt-registry as a
        dependency, so it's not in the ephemeral environment.
        """
        from pathlib import Path
        from rattler import MatchSpec

        # SETUP: Fake temporary directory without wt-registry
        mock_tmpdir.return_value.__enter__ = MagicMock(return_value="/fake/tmpdir")
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        # ACT: Try to discover tasks
        with pytest.raises(RegistryNotFoundError) as exc_info:
            await discover_tasks_from_requirements([MatchSpec("my-package>=1.0.0")])

        # ASSERT: Correct exception type
        error = exc_info.value
        assert isinstance(error, RegistryNotFoundError)
        assert error.executable_path == Path("/fake/tmpdir/env/bin/wt-registry")
        assert len(error.requirements) == 1

        # VERIFY: Error message is helpful
        error_msg = str(error)
        assert "wt-registry executable not found" in error_msg
        assert "my-package" in error_msg  # Show what was installed
        assert "Add 'wt-registry'" in error_msg  # Show how to fix
        assert "conda dependencies" in error_msg
        assert "spec.yaml" in error_msg

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_error_message_lists_all_requirements(
        self, mock_tmpdir, mock_install
    ):
        """Test that error message includes all installed packages."""
        # SETUP: Multiple requirements
        reqs = [
            MatchSpec("package-a>=1.0.0"),
            MatchSpec("package-b>=2.0.0"),
            MatchSpec("python>=3.10"),
        ]

        mock_tmpdir.return_value.__enter__ = MagicMock(return_value="/fake/tmpdir")
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        # ACT & ASSERT
        with pytest.raises(RegistryNotFoundError) as exc_info:
            await discover_tasks_from_requirements(reqs)

        # VERIFY: All packages are listed
        error_msg = str(exc_info.value)
        assert "package-a" in error_msg
        assert "package-b" in error_msg
        assert "python" in error_msg  # Even Python version is shown
        # This helps user understand the gap

    def test_registry_not_found_error_stores_attributes(self):
        """Test that exception stores all context for programmatic access."""
        # Some callers might want to programmatically check attributes
        path = Path("/tmp/env/bin/wt-registry")
        reqs = [MatchSpec("my-package>=1.0.0")]

        error = RegistryNotFoundError(
            executable_path=path,
            requirements=reqs,
        )

        # Callers can access structured data
        assert error.executable_path == path
        assert error.requirements == reqs
        # This enables sophisticated error handling if needed
```

### Test 2: Executable Fails at Runtime

**Scenario:** wt-registry exists but returns non-zero exit code

```python
class TestExecutionFailure:
    """Tests for when wt-registry CLI fails to execute."""

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.subprocess.run")
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_subprocess_failure_raises_execution_error(
        self, mock_tmpdir, mock_install, mock_run, tmp_path
    ):
        """Test that wt-registry failure raises RegistryExecutionError.

        This happens when wt-registry is installed but has an incompatible
        version or the registered task has missing dependencies.
        """
        from rattler import MatchSpec

        # SETUP: Create fake executable that exists but fails
        env_path = tmp_path / "env"
        bin_path = env_path / "bin"
        bin_path.mkdir(parents=True)
        (bin_path / "wt-registry").touch()  # Create the file

        mock_tmpdir.return_value.__enter__ = MagicMock(return_value=str(tmp_path))
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        # Mock subprocess failure
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="ImportError: No module named 'some_missing_dep'",
        )

        # ACT: Try to discover tasks
        with pytest.raises(RegistryExecutionError) as exc_info:
            await discover_tasks_from_requirements([MatchSpec("my-package>=1.0.0")])

        # ASSERT: Correct exception type
        error = exc_info.value
        assert isinstance(error, RegistryExecutionError)
        assert error.returncode == 1
        assert error.stdout == ""
        assert "ImportError" in error.stderr

        # VERIFY: Error message includes diagnostic info
        error_msg = str(error)
        assert "exit code 1" in error_msg
        assert "ImportError" in error_msg
        assert "No module named" in error_msg  # User can see the root cause
        assert "incompatible version" in error_msg
        assert "Missing dependencies" in error_msg

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.subprocess.run")
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_error_includes_stdout_and_stderr(
        self, mock_tmpdir, mock_install, mock_run, tmp_path
    ):
        """Test that both stdout and stderr are included in error message."""
        # SETUP
        env_path = tmp_path / "env"
        (env_path / "bin").mkdir(parents=True)
        (env_path / "bin" / "wt-registry").touch()

        mock_tmpdir.return_value.__enter__ = MagicMock(return_value=str(tmp_path))
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        # Mock subprocess with both stdout and stderr
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="partial output here",
            stderr="error details in stderr",
        )

        # ACT & ASSERT
        with pytest.raises(RegistryExecutionError) as exc_info:
            await discover_tasks_from_requirements([MatchSpec("pkg>=1.0")])

        # VERIFY: Both outputs are in the error message
        error_msg = str(exc_info.value)
        assert "partial output here" in error_msg
        assert "error details in stderr" in error_msg

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.subprocess.run")
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_empty_output_shown_clearly(
        self, mock_tmpdir, mock_install, mock_run, tmp_path
    ):
        """Test that empty stdout/stderr is shown as '(empty)'."""
        # SETUP
        env_path = tmp_path / "env"
        (env_path / "bin").mkdir(parents=True)
        (env_path / "bin" / "wt-registry").touch()

        mock_tmpdir.return_value.__enter__ = MagicMock(return_value=str(tmp_path))
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        # Mock subprocess with no output
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="",
        )

        # ACT & ASSERT
        with pytest.raises(RegistryExecutionError) as exc_info:
            await discover_tasks_from_requirements([MatchSpec("pkg>=1.0")])

        # VERIFY: Empty output is clearly marked
        error_msg = str(exc_info.value)
        assert "(empty)" in error_msg  # Should appear at least once
```

### Test 3: Invalid Output Format

**Scenario:** wt-registry returns success but invalid JSON

```python
class TestInvalidOutput:
    """Tests for when wt-registry returns invalid output."""

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.subprocess.run")
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_invalid_json_raises_error(
        self, mock_tmpdir, mock_install, mock_run, tmp_path
    ):
        """Test that non-JSON output is detected and reported."""
        # SETUP
        env_path = tmp_path / "env"
        (env_path / "bin").mkdir(parents=True)
        (env_path / "bin" / "wt-registry").touch()

        mock_tmpdir.return_value.__enter__ = MagicMock(return_value=str(tmp_path))
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        # Mock subprocess returning non-JSON
        mock_run.return_value = MagicMock(
            returncode=0,  # Success code, but...
            stdout="This is not JSON\nit's just text",
            stderr="",
        )

        # ACT & ASSERT: Should raise some kind of error
        with pytest.raises(Exception):  # Could be JSONDecodeError or DiscoveryError
            await discover_tasks_from_requirements([MatchSpec("pkg>=1.0")])

        # Note: This is an edge case - subprocess claims success but returns garbage
        # The fix depends on implementation - might be JSONDecodeError from Pydantic

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.subprocess.run")
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_invalid_schema_raises_validation_error(
        self, mock_tmpdir, mock_install, mock_run, tmp_path
    ):
        """Test that JSON with wrong schema is caught."""
        # SETUP
        env_path = tmp_path / "env"
        (env_path / "bin").mkdir(parents=True)
        (env_path / "bin" / "wt-registry").touch()

        mock_tmpdir.return_value.__enter__ = MagicMock(return_value=str(tmp_path))
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        # Mock subprocess returning valid JSON but wrong schema
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"wrong": "schema"}',  # Missing required fields
            stderr="",
        )

        # ACT & ASSERT
        with pytest.raises(ValidationError):
            await discover_tasks_from_requirements([MatchSpec("pkg>=1.0")])
```

### Test 4: Exception Hierarchy

**Scenario:** Verify that exceptions can be caught selectively

```python
class TestExceptionHierarchy:
    """Tests for exception inheritance and selective catching."""

    def test_registry_not_found_is_discovery_error(self):
        """Test that specific exceptions inherit from base class."""
        error = RegistryNotFoundError(
            executable_path=Path("/fake"),
            requirements=[MatchSpec("pkg>=1.0")],
        )
        assert isinstance(error, DiscoveryError)
        assert isinstance(error, Exception)

    def test_registry_execution_error_is_discovery_error(self):
        """Test that execution errors inherit from base class."""
        error = RegistryExecutionError(
            executable_path=Path("/fake"),
            returncode=1,
            stdout="",
            stderr="",
            requirements=[MatchSpec("pkg>=1.0")],
        )
        assert isinstance(error, DiscoveryError)
        assert isinstance(error, Exception)

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_can_catch_by_base_exception(self, mock_tmpdir, mock_install):
        """Test that callers can catch DiscoveryError to catch all discovery issues."""
        mock_tmpdir.return_value.__enter__ = MagicMock(return_value="/fake")
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        # This allows: except DiscoveryError: to catch all discovery errors
        with pytest.raises(DiscoveryError):
            await discover_tasks_from_requirements([MatchSpec("pkg>=1.0")])

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_can_catch_specific_exception(self, mock_tmpdir, mock_install):
        """Test that callers can catch specific exception types."""
        mock_tmpdir.return_value.__enter__ = MagicMock(return_value="/fake")
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        # This allows: except RegistryNotFoundError: to handle just this case
        with pytest.raises(RegistryNotFoundError):
            await discover_tasks_from_requirements([MatchSpec("pkg>=1.0")])
```

---

## Test Coverage Checklist

Use this checklist to ensure you've covered all error paths:

### Precondition Errors
- [ ] Empty requirements list
- [ ] None as requirements
- [ ] Invalid MatchSpec format
- [ ] Missing channels when required

### Executable Missing
- [ ] Environment created but executable missing
- [ ] Executable path on Unix (bin/executable)
- [ ] Executable path on Windows (Scripts/executable.exe)
- [ ] Error message lists all requirements
- [ ] Error message includes fix suggestions

### Execution Failures
- [ ] Non-zero exit code
- [ ] Subprocess timeout
- [ ] Subprocess killed by signal
- [ ] Error message includes stdout
- [ ] Error message includes stderr
- [ ] Error message includes exit code

### Output Validation
- [ ] Non-JSON output
- [ ] Invalid JSON
- [ ] Valid JSON but wrong schema
- [ ] Valid JSON but missing required fields
- [ ] Empty output

### Exception Hierarchy
- [ ] Correct exception type is raised
- [ ] Exception stores context attributes
- [ ] Exception inherits from correct base class
- [ ] Can catch by specific exception type
- [ ] Can catch by base exception type

### Error Messages
- [ ] Includes problem statement
- [ ] Includes context (what was installed)
- [ ] Includes diagnosis (why it happened)
- [ ] Includes solution (how to fix)
- [ ] Message is readable (not a dump)
- [ ] Message fits on screen (not too long)

---

## Testing Patterns Summary

### Pattern 1: Mocking Preconditions
```python
@patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
async def test_something(mock_tmpdir):
    # Setup: Create the context manager mock
    mock_tmpdir.return_value.__enter__ = MagicMock(return_value="/fake/path")
    mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)
```

### Pattern 2: Mocking Async Functions
```python
@patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
async def test_something(mock_create_env):
    # AsyncMock handles both sync and async correctly
    mock_create_env.return_value = None  # Completes successfully
```

### Pattern 3: Mocking Subprocess
```python
@patch("wt_compiler.discovery.subprocess.run")
async def test_something(mock_run):
    # Setup subprocess result
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="output",
        stderr="error",
    )
```

### Pattern 4: Using Real Temp Directories in Tests
```python
async def test_something(tmp_path):
    # tmp_path is a pytest fixture that creates a real temporary directory
    env_path = tmp_path / "env"
    (env_path / "bin").mkdir(parents=True)
    (env_path / "bin" / "wt-registry").touch()
    # Now the executable actually exists on disk
```

---

## Common Testing Mistakes

### Mistake 1: Only testing the happy path
```python
# Bad: Only one test, and it's for success
def test_discover_tasks():
    result = await discover_tasks(...)
    assert len(result) > 0

# Good: Multiple tests for different scenarios
def test_discover_tasks_successfully():
    ...

def test_discover_tasks_raises_when_executable_missing():
    ...

def test_discover_tasks_raises_when_subprocess_fails():
    ...

def test_discover_tasks_raises_when_output_invalid():
    ...
```

### Mistake 2: Not verifying error messages
```python
# Bad: Just check that exception was raised
with pytest.raises(RegistryNotFoundError):
    await discover_tasks(...)

# Good: Verify the message is helpful
with pytest.raises(RegistryNotFoundError) as exc_info:
    await discover_tasks(...)

error_msg = str(exc_info.value)
assert "wt-registry executable not found" in error_msg
assert "my-package" in error_msg  # Show what was installed
assert "wt-registry" in error_msg  # Show how to fix
```

### Mistake 3: Not testing exception attributes
```python
# Bad: Ignore structured data in exception
with pytest.raises(RegistryNotFoundError) as exc_info:
    await discover_tasks(...)

# Good: Verify attributes are populated
error = exc_info.value
assert error.executable_path is not None
assert error.requirements is not None
assert len(error.requirements) > 0
```

---

## Debugging Tests That Fail

### Test passes locally but fails in CI

Common causes:
1. **Mocking is inconsistent** - Make sure all imports are mocked the same way
2. **Temp directory path differs** - Use `tmp_path` fixture instead of hardcoded paths
3. **Subprocess behavior differs** - Windows vs Linux use different executable paths

### Test is flaky (passes sometimes, fails sometimes)

Common causes:
1. **Race conditions** - Ensure mocks prevent any actual subprocess calls
2. **Import timing** - Mock before importing the module that uses it
3. **Temporary files** - Use `tmp_path` fixture for isolation between tests

---

## Measure Test Quality

### Coverage: Did you test all error paths?

```bash
# Check code coverage
pytest --cov=wt_compiler --cov-report=html tests/test_discovery_integration.py
# Open htmlcov/index.html to see which lines aren't tested
```

### Quality: Are your tests actually checking things?

```python
# Run tests with assertion introspection
pytest -vv tests/test_discovery_integration.py

# Each test should:
# 1. Print its test name (says what it tests)
# 2. Show assertions (verifies behavior)
# 3. Demonstrate the exact values involved
```

### Robustness: Do your tests work after code changes?

- Change the code to always raise an exception
- Tests should fail
- Change the code to never raise an exception
- Tests should fail
- If tests still pass, they're not actually testing the code

---

## Summary

Testing error paths is not optional—it's how you ensure your error messages are actually helpful. The pattern is simple:

1. **Setup:** Create conditions for the error
2. **Act:** Call the function
3. **Assert:** Verify exception type
4. **Verify:** Check error message is helpful

The original problem—cryptic subprocess errors—is solved by:
- Testing that missing executables are caught early
- Testing that error messages include context
- Testing that error messages include solutions
- Making sure these tests actually verify the behavior

This prevents silent failures and helps users understand what went wrong.
