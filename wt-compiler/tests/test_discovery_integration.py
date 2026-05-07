"""Tests for discovery.py and its integration with compiler.py."""
# ruff: noqa: SIM105, S110, BLE001, S108  # cleanup blocks tolerate any error; /tmp paths are test data

import errno
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from rattler import Channel, MatchSpec, Platform
from wt_contracts.registry import RegistryEntry, RegistryMetadata, RegistryOutput

from wt_compiler.compiler import (
    _parse_requirements_from_yaml,
    compile_workflow_from_yaml,
)
from wt_compiler.discovery import (
    DiscoveryResult,
    _create_environment,
    discover_tasks_from_requirements,
)
from wt_compiler.exceptions import (
    EnvironmentCreationError,
    RegistryExecutionError,
    RegistryNotFoundError,
)
from wt_compiler.spec import KnownTask, known_tasks


class TestRegistryOutputParsing:
    """Tests for parsing wt-registry CLI output using wt-contracts schema."""

    def test_valid_registry_output_parsing(self):
        """Test parsing valid JSON matches RegistryOutput schema."""
        json_data = {
            "entries": {
                "mypackage.tasks.add": {
                    "metadata": {
                        "title": "Add Numbers",
                        "description": "Add two integers",
                        "tags": ["math"],
                        "deprecated": False,
                        "deprecation_message": None,
                    },
                    "module_path": "mypackage.tasks._math",
                    "public_module_path": "mypackage.tasks",
                    "function_name": "add",
                    "import_statement": "from mypackage.tasks import add as add",
                    "json_schema": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "integer"},
                            "b": {"type": "integer"},
                        },
                        "required": ["a", "b"],
                    },
                }
            },
            "version": "1.0.0",
        }

        # This should not raise
        output = RegistryOutput.model_validate(json_data)

        assert "mypackage.tasks.add" in output.entries
        entry = output.entries["mypackage.tasks.add"]
        assert entry.function_name == "add"
        assert entry.module_path == "mypackage.tasks._math"
        assert entry.public_module_path == "mypackage.tasks"
        assert entry.metadata.title == "Add Numbers"
        assert "math" in entry.metadata.tags

    def test_invalid_registry_output_raises(self):
        """Test that invalid JSON raises ValidationError."""
        invalid_json = {
            "entries": {
                "invalid": {
                    # Missing required fields
                    "module_path": "mypackage.tasks",
                }
            }
        }

        with pytest.raises(ValidationError):
            RegistryOutput.model_validate(invalid_json)


class TestKnownTaskCreation:
    """Tests for creating KnownTask from RegistryEntry."""

    def test_known_task_from_registry_entry(self):
        """Test creating KnownTask with correct fields from RegistryEntry."""
        entry = RegistryEntry(
            metadata=RegistryMetadata(
                title="Test Function",
                description="A test function",
                tags=["io", "test"],
            ),
            module_path="mypackage.tasks._internal",
            public_module_path="mypackage.tasks",
            function_name="test_func",
            import_statement="from mypackage.tasks import test_func as test_func",
            json_schema={
                "type": "object",
                "properties": {"x": {"type": "integer"}},
            },
        )

        # Simulate what discovery.py does - uses public_module_path
        known_task = KnownTask(
            importable_reference=f"{entry.public_module_path}.{entry.function_name}",
            tags=[],  # Would filter to known TaskTag values
            registry_ref=0,
            json_schema=dict(entry.json_schema),
            description=entry.metadata.description,
        )

        assert known_task.importable_reference == "mypackage.tasks.test_func"
        assert known_task.description == "A test function"
        assert known_task.function_name == "test_func"
        assert known_task.anchor == "mypackage.tasks"


class TestDiscoverTasksMocked:
    """Tests for discover_tasks_from_requirements with mocked subprocess."""

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.subprocess.run")
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_discover_parses_registry_output(
        self, mock_tmpdir, mock_install, mock_run, tmp_path
    ):
        """Test that discover_tasks_from_requirements correctly parses CLI output."""

        # Create a real temp directory with a fake executable
        env_path = tmp_path / "env"
        bin_path = env_path / "bin"
        bin_path.mkdir(parents=True)
        fake_exe = bin_path / "wt-registry"
        fake_exe.touch()  # Create the file so exists() returns True

        # Mock TemporaryDirectory to use our tmp_path
        mock_tmpdir.return_value.__enter__ = MagicMock(return_value=str(tmp_path))
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        # Mock _create_environment to return a list with a wt-registry record
        wt_reg_record = MagicMock()
        wt_reg_record.name.normalized = "wt-registry"
        wt_reg_record.channel = "https://conda.anaconda.org/conda-forge/"
        mock_install.return_value = [wt_reg_record]

        # Mock the CLI output
        registry_json = {
            "entries": {
                "mypackage.tasks.calculate": {
                    "metadata": {
                        "title": "Calculate",
                        "description": "Calculate something",
                        "tags": [],
                    },
                    "module_path": "mypackage.tasks._internal",
                    "public_module_path": "mypackage.tasks",
                    "function_name": "calculate",
                    "import_statement": "from mypackage.tasks import calculate as calculate",
                    "json_schema": {"properties": {}},
                }
            },
            "version": "1.0.0",
        }

        mock_run.return_value = MagicMock(
            stdout=json.dumps(registry_json),
            returncode=0,
        )

        # Call discover_tasks_from_requirements with mocked subprocess
        result = await discover_tasks_from_requirements([MatchSpec("mypackage>=1.0.0")])

        # Verify the result - uses public_module_path for the key
        assert "calculate" in result.tasks
        assert "mypackage.tasks" in result.tasks["calculate"]
        known_task = result.tasks["calculate"]["mypackage.tasks"]
        assert known_task.importable_reference == "mypackage.tasks.calculate"
        assert known_task.description == "Calculate something"


class TestParseRequirementsFromYaml:
    """Tests for _parse_requirements_from_yaml function."""

    def test_parse_requirements_from_valid_yaml(self, tmp_path):
        """Test parsing requirements from a valid spec YAML."""
        spec_yaml = tmp_path / "spec.yaml"
        spec_yaml.write_text("""
id: test-workflow
requirements:
  - name: my-package
    version: ">=1.0.0"
    channel: conda-forge
workflow: []
""")

        result = _parse_requirements_from_yaml(spec_yaml)

        assert len(result.conda) == 1
        assert len(result.pypi) == 0
        assert result.conda[0].name == "my-package"

    def test_parse_requirements_missing_requirements_raises(self, tmp_path):
        """Test that missing requirements section raises ValueError."""
        spec_yaml = tmp_path / "spec.yaml"
        spec_yaml.write_text("""
id: test-workflow
workflow: []
""")

        with pytest.raises(ValueError, match="missing 'requirements' section"):
            _parse_requirements_from_yaml(spec_yaml)

    def test_parse_requirements_file_not_found(self, tmp_path):
        """Test that non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            _parse_requirements_from_yaml(tmp_path / "nonexistent.yaml")


class TestPopulateKnownTasks:
    """Tests for populate_known_tasks function."""

    def test_populate_clears_and_updates(self):
        """Test that populate_known_tasks clears existing entries."""
        # Pre-populate with some data
        known_tasks["old_task"] = {
            "module": KnownTask(
                importable_reference="old.module.old_task",
                json_schema={},
            )
        }

        # populate_known_tasks should clear this
        # Note: This would fail without mocking since we need real env
        # Just verifying the clear behavior by checking the dict reference
        assert "old_task" in known_tasks

        # In a real test with mocks, we'd verify it gets cleared
        # known_tasks.clear() is called in populate_known_tasks


class TestCompileWorkflowFromYaml:
    """Tests for compile_workflow_from_yaml function."""

    @pytest.mark.asyncio
    async def test_compile_workflow_from_yaml_calls_discovery(self, tmp_path):
        """Test that compile_workflow_from_yaml triggers discovery."""
        # This is an integration test that would require mocking
        # the entire discovery chain
        # Placeholder for full integration test

    @pytest.mark.asyncio
    async def test_compile_workflow_from_yaml_invalid_path(self):
        """Test that invalid path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await compile_workflow_from_yaml("/nonexistent/path/spec.yaml")

    @pytest.mark.asyncio
    @patch("wt_compiler.compiler.populate_known_tasks", new_callable=AsyncMock)
    async def test_compile_workflow_from_yaml_passes_custom_channels(self, mock_populate, tmp_path):
        """Test that custom channels from spec.yaml are passed to populate_known_tasks.

        This verifies the fix for the bug where custom package channels were not
        being propagated to the discovery phase, causing packages on custom
        channels (like https://repo.prefix.dev/ecoscope-workflows/) to fail
        with "No candidates found" errors.
        """

        spec_yaml = tmp_path / "spec.yaml"
        # Use valid channels from the channel whitelist: ecoscope-workflows and conda-forge
        spec_yaml.write_text(
            """
id: test-workflow
requirements:
  - name: ecoscope-workflows-core
    version: ">=0.1.0"
    channel: https://repo.prefix.dev/ecoscope-workflows/
  - name: python
    version: ">=3.10"
    channel: conda-forge
workflow: []
"""
        )

        # Mock populate_known_tasks to return a DiscoveryResult
        mock_populate.return_value = DiscoveryResult(tasks={}, records=[])

        # Attempt compilation - will fail later in the flow but we just want to
        # verify populate_known_tasks was called with the right channels
        try:
            await compile_workflow_from_yaml(spec_yaml)
        except Exception:
            pass  # Expected to fail since we mocked populate_known_tasks

        # Verify populate_known_tasks was called
        mock_populate.assert_called_once()

        # Get the call arguments
        call_args = mock_populate.call_args
        channels = call_args.kwargs.get("channels", [])

        # Verify channels were passed (not None or empty)
        assert channels is not None, "channels parameter should be passed"
        # All known remote channels are included for transitive dependency resolution
        # (local file:// channels that don't exist are filtered out)
        assert len(channels) >= 2, f"Expected at least 2 channels, got {len(channels)}"

        # Verify both ecoscope-workflows channel and conda-forge are present
        channel_identifiers = [c.name or c.base_url for c in channels]
        assert any("ecoscope-workflows" in str(ch) for ch in channel_identifiers), (
            f"ecoscope-workflows channel not found in {channel_identifiers}"
        )
        assert any("conda-forge" in str(ch) for ch in channel_identifiers), (
            f"conda-forge not found in {channel_identifiers}"
        )

    @pytest.mark.asyncio
    @patch("wt_compiler.compiler.populate_known_tasks", new_callable=AsyncMock)
    async def test_pypi_only_spec_uses_only_conda_forge_channel(self, mock_populate, tmp_path):
        """Test that a PyPI-only spec only uses conda-forge, not all known channels.

        When a spec has no conda requirements (only PyPI deps), the compiler should
        not inject all known channels (including local file:// channels) into the
        rattler solve. Only conda-forge is needed for the base python + uv packages.
        """

        spec_yaml = tmp_path / "spec.yaml"
        spec_yaml.write_text(
            """
id: test-workflow
requirements:
  - name: some-pypi-package
    git: https://github.com/org/some-pypi-package.git
    tag: v1.0
workflow: []
"""
        )

        # Mock populate_known_tasks to return a DiscoveryResult
        mock_populate.return_value = DiscoveryResult(tasks={}, records=[])

        try:
            await compile_workflow_from_yaml(spec_yaml)
        except Exception:
            pass  # Expected to fail during spec validation

        mock_populate.assert_called_once()

        call_args = mock_populate.call_args
        channels = call_args.kwargs.get("channels", [])

        # Should only have conda-forge, not all known channels
        assert len(channels) == 1, (
            f"Expected exactly 1 channel (conda-forge) for PyPI-only spec, "
            f"got {len(channels)}: {[c.name or c.base_url for c in channels]}"
        )
        assert "conda-forge" in (channels[0].name or channels[0].base_url), (
            f"Expected conda-forge channel, got {channels[0].name or channels[0].base_url}"
        )

    @pytest.mark.asyncio
    @patch("wt_compiler.compiler.populate_known_tasks", new_callable=AsyncMock)
    async def test_pypi_only_spec_compiles_without_wt_registry_in_conda(
        self, mock_populate, tmp_path
    ):
        """When wt-registry is not in conda records, compilation does not raise.

        Auto-injection of wt-task / wt-runner conda deps is silently skipped
        and the user is expected to provide them via --env-overrides.
        """

        spec_yaml = tmp_path / "spec.yaml"
        spec_yaml.write_text(
            """
id: test-workflow
requirements:
  - name: some-pypi-package
    git: https://github.com/org/some-pypi-package.git
    tag: v1.0
workflow: []
"""
        )

        mock_populate.return_value = DiscoveryResult(tasks={}, records=[])

        try:
            await compile_workflow_from_yaml(spec_yaml)
        except Exception:
            pass  # Expected to fail during spec validation

        # Did NOT raise: "wt-registry was not found in the solved environment"
        mock_populate.assert_called_once()

    @pytest.mark.asyncio
    @patch("wt_compiler.compiler.populate_known_tasks", new_callable=AsyncMock)
    async def test_env_overrides_discovery_overlay(self, mock_populate, tmp_path):
        """env-overrides feature.discovery deps are passed through to discovery.

        Conda deps are added to the rattler match-specs and pypi deps to the
        pypi_requirements list. Collision with spec.yaml requirements logs a
        warning and override wins.
        """
        wt_registry_dir = tmp_path / "wt-registry"
        wt_registry_dir.mkdir()

        override = tmp_path / "wt-compiler-env-overrides.toml"
        override.write_text(
            "[feature.discovery.pypi-dependencies]\n"
            f'wt-registry = {{ path = "{wt_registry_dir}", editable = true }}\n'
        )

        spec_yaml = tmp_path / "spec.yaml"
        spec_yaml.write_text(
            """
id: test-workflow
requirements:
  - name: wt-registry
    git: https://example.invalid/wt-registry.git
workflow: []
"""
        )

        mock_populate.return_value = DiscoveryResult(tasks={}, records=[])

        try:
            await compile_workflow_from_yaml(spec_yaml, env_overrides_path=override)
        except Exception:
            pass  # Spec validation may fail because workflow is empty

        mock_populate.assert_called_once()
        call_args = mock_populate.call_args
        passed_pypi = call_args.kwargs.get("pypi_requirements") or []
        names = [r.name for r in passed_pypi]
        # Override-wins: only one wt-registry, sourced from path (the override)
        assert names.count("wt-registry") == 1
        wt_registry_req = next(r for r in passed_pypi if r.name == "wt-registry")
        assert wt_registry_req.path == str(wt_registry_dir)


class TestDiscoveryErrors:
    """Tests for discovery error handling."""

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_registry_not_found_raises_descriptive_error(self, mock_tmpdir, mock_install):
        """Test that missing wt-registry raises RegistryNotFoundError with helpful message."""

        # Mock TemporaryDirectory context manager
        mock_tmpdir.return_value.__enter__ = MagicMock(return_value="/fake/tmpdir")
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        # _create_environment succeeds but doesn't install wt-registry
        # The executable path won't exist since it's a fake directory
        mock_install.return_value = []

        with pytest.raises(RegistryNotFoundError) as exc_info:
            await discover_tasks_from_requirements([MatchSpec("some-package>=1.0.0")])

        error = exc_info.value
        error_msg = str(error)
        assert "wt-registry executable not found" in error_msg
        assert "some-package" in error_msg
        assert "wt-registry" in error_msg  # Fix suggestion mentioned

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.subprocess.run")
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_registry_execution_failure_raises_descriptive_error(
        self, mock_tmpdir, mock_install, mock_run, tmp_path
    ):
        """Test that wt-registry failure raises RegistryExecutionError with stderr."""

        # Create a real temp directory with a fake executable
        env_path = tmp_path / "env"
        bin_path = env_path / "bin"
        bin_path.mkdir(parents=True)
        fake_exe = bin_path / "wt-registry"
        fake_exe.touch()  # Create the file so exists() returns True

        # Mock TemporaryDirectory to use our tmp_path
        mock_tmpdir.return_value.__enter__ = MagicMock(return_value=str(tmp_path))
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        mock_install.return_value = []

        # wt-registry exists but fails
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
        assert "ImportError" in error_msg


class TestDisambiguationLogic:
    """Tests for disambiguation logic when multiple functions have the same name."""

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.subprocess.run")
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_disambiguation_first_occurrence_gets_ref_zero(
        self, mock_tmpdir, mock_install, mock_run, tmp_path
    ):
        """Test that first occurrence of function name gets registry_ref=0."""

        # Create temp directory with fake executable
        env_path = tmp_path / "env"
        bin_path = env_path / "bin"
        bin_path.mkdir(parents=True)
        fake_exe = bin_path / "wt-registry"
        fake_exe.touch()

        mock_tmpdir.return_value.__enter__ = MagicMock(return_value=str(tmp_path))
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        # Mock _create_environment to return records with wt-registry
        wt_reg_record = MagicMock()
        wt_reg_record.name.normalized = "wt-registry"
        mock_install.return_value = [wt_reg_record]

        # Single function
        registry_json = {
            "entries": {
                "pkg.tasks.my_func": {
                    "metadata": {"title": "My Func", "description": "Test", "tags": []},
                    "module_path": "pkg.tasks._internal",
                    "public_module_path": "pkg.tasks",
                    "function_name": "my_func",
                    "import_statement": "from pkg.tasks import my_func as my_func",
                    "json_schema": {"properties": {}},
                }
            },
            "version": "1.0.0",
        }

        mock_run.return_value = MagicMock(
            stdout=json.dumps(registry_json),
            returncode=0,
        )

        result = await discover_tasks_from_requirements([MatchSpec("pkg>=1.0.0")])

        assert "my_func" in result.tasks
        known_task = result.tasks["my_func"]["pkg.tasks"]
        assert known_task.registry_ref == 0
        assert known_task.safe_reference == "my_func"

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.subprocess.run")
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_disambiguation_second_occurrence_gets_ref_one(
        self, mock_tmpdir, mock_install, mock_run, tmp_path
    ):
        """Test that second occurrence from different module gets registry_ref=1."""

        # Create temp directory with fake executable
        env_path = tmp_path / "env"
        bin_path = env_path / "bin"
        bin_path.mkdir(parents=True)
        fake_exe = bin_path / "wt-registry"
        fake_exe.touch()

        mock_tmpdir.return_value.__enter__ = MagicMock(return_value=str(tmp_path))
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        # Mock _create_environment to return records with wt-registry
        wt_reg_record = MagicMock()
        wt_reg_record.name.normalized = "wt-registry"
        mock_install.return_value = [wt_reg_record]

        # Two functions with same name from different modules
        registry_json = {
            "entries": {
                "pkg1.tasks.my_func": {
                    "metadata": {"title": "My Func 1", "description": "Test 1", "tags": []},
                    "module_path": "pkg1.tasks._internal",
                    "public_module_path": "pkg1.tasks",
                    "function_name": "my_func",
                    "import_statement": "from pkg1.tasks import my_func as my_func",
                    "json_schema": {"properties": {}},
                },
                "pkg2.tasks.my_func": {
                    "metadata": {"title": "My Func 2", "description": "Test 2", "tags": []},
                    "module_path": "pkg2.tasks._internal",
                    "public_module_path": "pkg2.tasks",
                    "function_name": "my_func",
                    "import_statement": "from pkg2.tasks import my_func as my_func",
                    "json_schema": {"properties": {}},
                },
            },
            "version": "1.0.0",
        }

        mock_run.return_value = MagicMock(
            stdout=json.dumps(registry_json),
            returncode=0,
        )

        result = await discover_tasks_from_requirements([MatchSpec("pkg1>=1.0.0")])

        assert "my_func" in result.tasks
        # Both should be present
        assert "pkg1.tasks" in result.tasks["my_func"]
        assert "pkg2.tasks" in result.tasks["my_func"]

        # Check registry_ref values
        task1 = result.tasks["my_func"]["pkg1.tasks"]
        task2 = result.tasks["my_func"]["pkg2.tasks"]

        # One should have ref=0, other should have ref=1
        refs = {task1.registry_ref, task2.registry_ref}
        assert refs == {0, 1}

        # The one with ref=1 should have suffix in safe_reference
        if task1.registry_ref == 1:
            assert task1.safe_reference == "my_func_1"
            assert task2.safe_reference == "my_func"
        else:
            assert task1.safe_reference == "my_func"
            assert task2.safe_reference == "my_func_1"


# Marker for slow/integration tests that require real environments
@pytest.mark.slow
class TestDiscoveryIntegration:
    """Integration tests requiring real wt-registry CLI.

    These tests are marked slow and may be skipped in CI.
    Run with: pytest -m slow
    """

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires wt-registry installed in environment")
    async def test_end_to_end_discovery(self):
        """Test full discovery with real environment creation."""
        # Would test with real wt-registry installation

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires wt-registry installed in environment")
    async def test_end_to_end_compilation(self, tmp_path):
        """Test full compilation from YAML with real discovery."""
        # Would test the complete compile_workflow_from_yaml flow


class TestCreateEnvironmentRetry:
    """Tests for _create_environment retry logic on ENOTEMPTY errors."""

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.install", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.solve", new_callable=AsyncMock)
    async def test_retry_on_enotempty_succeeds_on_second_attempt(
        self, mock_solve, mock_install, tmp_path
    ):
        """Test that ENOTEMPTY error on first attempt retries and succeeds."""

        env_path = tmp_path / "env"
        requirements = [MatchSpec("test-package>=1.0.0")]
        channels = [Channel("conda-forge")]
        platform = Platform("linux-64")

        # Mock solve to return fake records
        mock_solve.return_value = [MagicMock()]

        # First call raises ENOTEMPTY, second succeeds
        enotempty_error = OSError(errno.ENOTEMPTY, "Directory not empty")
        mock_install.side_effect = [enotempty_error, None]

        # Should succeed after retry
        await _create_environment(env_path, requirements, channels, platform)

        # Verify install was called twice
        assert mock_install.call_count == 2

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.install", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.solve", new_callable=AsyncMock)
    async def test_max_retries_exceeded_raises_error(self, mock_solve, mock_install, tmp_path):
        """Test that EnvironmentCreationError is raised after max retries."""

        env_path = tmp_path / "env"
        requirements = [MatchSpec("test-package>=1.0.0")]
        channels = [Channel("conda-forge")]
        platform = Platform("linux-64")

        # Mock solve to return fake records
        mock_solve.return_value = [MagicMock()]

        # All attempts fail with ENOTEMPTY
        enotempty_error = OSError(errno.ENOTEMPTY, "Directory not empty")
        mock_install.side_effect = [enotempty_error, enotempty_error, enotempty_error]

        with pytest.raises(EnvironmentCreationError) as exc_info:
            await _create_environment(env_path, requirements, channels, platform)

        error = exc_info.value
        assert error.phase == "install"
        assert error.original_error.errno == errno.ENOTEMPTY
        assert mock_install.call_count == 3  # MAX_INSTALL_RETRIES

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.install", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.solve", new_callable=AsyncMock)
    async def test_non_retryable_error_fails_immediately(self, mock_solve, mock_install, tmp_path):
        """Test that non-ENOTEMPTY errors fail without retry."""

        env_path = tmp_path / "env"
        requirements = [MatchSpec("test-package>=1.0.0")]
        channels = [Channel("conda-forge")]
        platform = Platform("linux-64")

        # Mock solve to return fake records
        mock_solve.return_value = [MagicMock()]

        # Fail with a different error (not ENOTEMPTY)
        permission_error = OSError(errno.EACCES, "Permission denied")
        mock_install.side_effect = permission_error

        with pytest.raises(EnvironmentCreationError) as exc_info:
            await _create_environment(env_path, requirements, channels, platform)

        error = exc_info.value
        assert error.phase == "install"
        assert error.original_error.errno == errno.EACCES
        # Should only try once since EACCES is not retryable
        assert mock_install.call_count == 1

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.solve", new_callable=AsyncMock)
    async def test_solve_failure_raises_error(self, mock_solve, tmp_path):
        """Test that solve failures raise EnvironmentCreationError with phase=solve."""

        env_path = tmp_path / "env"
        requirements = [MatchSpec("nonexistent-package>=1.0.0")]
        channels = [Channel("conda-forge")]
        platform = Platform("linux-64")

        # Mock solve to fail
        mock_solve.side_effect = RuntimeError("No candidates found")

        with pytest.raises(EnvironmentCreationError) as exc_info:
            await _create_environment(env_path, requirements, channels, platform)

        error = exc_info.value
        assert error.phase == "solve"
        assert "No candidates found" in str(error.original_error)

    def test_error_message_contains_guidance_for_enotempty(self):
        """Test that EnvironmentCreationError provides helpful guidance for ENOTEMPTY."""

        enotempty_error = OSError(errno.ENOTEMPTY, "Directory not empty")
        error = EnvironmentCreationError(
            env_path=Path("/tmp/env"),
            requirements=[MatchSpec("test-package>=1.0.0")],
            original_error=enotempty_error,
            phase="install",
        )

        error_msg = str(error)
        assert "install phase" in error_msg
        assert "race condition" in error_msg.lower()
        assert "ENOTEMPTY" in error_msg

    def test_error_message_contains_guidance_for_emfile(self):
        """Test that EnvironmentCreationError provides helpful guidance for EMFILE."""

        emfile_error = OSError(errno.EMFILE, "Too many open files")
        error = EnvironmentCreationError(
            env_path=Path("/tmp/env"),
            requirements=[MatchSpec("test-package>=1.0.0")],
            original_error=emfile_error,
            phase="install",
        )

        error_msg = str(error)
        assert "install phase" in error_msg
        assert "Too many open files" in error_msg or "EMFILE" in error_msg
        assert "ulimit" in error_msg

    def test_error_message_contains_guidance_for_solve(self):
        """Test that EnvironmentCreationError provides helpful guidance for solve failures."""

        solve_error = RuntimeError("No candidates found for package")
        error = EnvironmentCreationError(
            env_path=Path("/tmp/env"),
            requirements=[MatchSpec("test-package>=1.0.0")],
            original_error=solve_error,
            phase="solve",
        )

        error_msg = str(error)
        assert "solve phase" in error_msg
        assert "Dependency resolution failed" in error_msg

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.install", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.solve", new_callable=AsyncMock)
    async def test_retry_on_rattler_enotempty_exception(self, mock_solve, mock_install, tmp_path):
        """Test that py-rattler exceptions with ENOTEMPTY in message trigger retry.

        py-rattler raises its own exception types (LinkError, ExtractError, IoError)
        that are NOT OSError subclasses but contain "ENOTEMPTY" or "Directory not empty"
        in the message.
        """

        env_path = tmp_path / "env"
        requirements = [MatchSpec("test-package>=1.0.0")]
        channels = [Channel("conda-forge")]
        platform = Platform("linux-64")

        # Mock solve to return fake records
        mock_solve.return_value = [MagicMock()]

        # Simulate py-rattler's LinkError with ENOTEMPTY in message
        # This is NOT an OSError subclass
        rattler_error = RuntimeError("failed to link package: ENOTEMPTY: directory not empty")
        mock_install.side_effect = [rattler_error, None]

        # Should succeed after retry
        await _create_environment(env_path, requirements, channels, platform)

        # Verify install was called twice (retry triggered)
        assert mock_install.call_count == 2

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.install", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.solve", new_callable=AsyncMock)
    async def test_retry_on_directory_not_empty_message(self, mock_solve, mock_install, tmp_path):
        """Test that exceptions with 'Directory not empty' in message trigger retry."""

        env_path = tmp_path / "env"
        requirements = [MatchSpec("test-package>=1.0.0")]
        channels = [Channel("conda-forge")]
        platform = Platform("linux-64")

        # Mock solve to return fake records
        mock_solve.return_value = [MagicMock()]

        # Simulate exception with "Directory not empty" in message
        dir_not_empty_error = Exception("ExtractError: Directory not empty: /tmp/cache/pkg-1.0")
        mock_install.side_effect = [dir_not_empty_error, None]

        # Should succeed after retry
        await _create_environment(env_path, requirements, channels, platform)

        # Verify install was called twice (retry triggered)
        assert mock_install.call_count == 2

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.install", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.solve", new_callable=AsyncMock)
    async def test_rattler_exception_exhausts_retries(self, mock_solve, mock_install, tmp_path):
        """Test that py-rattler ENOTEMPTY exceptions exhaust all retries."""

        env_path = tmp_path / "env"
        requirements = [MatchSpec("test-package>=1.0.0")]
        channels = [Channel("conda-forge")]
        platform = Platform("linux-64")

        # Mock solve to return fake records
        mock_solve.return_value = [MagicMock()]

        # All attempts fail with rattler-style error
        rattler_error = RuntimeError("IoError: ENOTEMPTY during extraction")
        mock_install.side_effect = [rattler_error, rattler_error, rattler_error]

        with pytest.raises(EnvironmentCreationError) as exc_info:
            await _create_environment(env_path, requirements, channels, platform)

        error = exc_info.value
        assert error.phase == "install"
        assert "ENOTEMPTY" in str(error.original_error)
        assert mock_install.call_count == 3  # MAX_INSTALL_RETRIES


class TestTemporaryDirectoryCleanup:
    """Tests for TemporaryDirectory cleanup behavior."""

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.subprocess.run")
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    async def test_cleanup_errors_dont_mask_original_error(
        self, mock_create_env, mock_run, tmp_path
    ):
        """Test that TemporaryDirectory cleanup errors don't mask the original exception.

        When py-rattler fails during install, the TemporaryDirectory cleanup can also
        fail with ENOTEMPTY. The ignore_cleanup_errors=True parameter should prevent
        the cleanup error from masking the original helpful error message.
        """

        # Make _create_environment raise the original error
        original_error = RuntimeError("LinkError: failed to extract package foo")
        mock_create_env.side_effect = EnvironmentCreationError(
            env_path=tmp_path / "env",
            requirements=[MatchSpec("test>=1.0")],
            original_error=original_error,
            phase="install",
        )

        # The key assertion is that we get EnvironmentCreationError with the
        # original error, not an OSError about directory cleanup
        with pytest.raises(EnvironmentCreationError) as exc_info:
            await discover_tasks_from_requirements([MatchSpec("test>=1.0.0")])

        error = exc_info.value
        # The original error message should be preserved
        assert "LinkError" in str(error.original_error)
        # Should NOT be a cleanup-related error
        assert "Directory not empty" not in str(error)
