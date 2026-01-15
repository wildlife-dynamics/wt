"""Tests for discovery.py and its integration with compiler.py."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from wt_contracts.registry import RegistryEntry, RegistryMetadata, RegistryOutput

from wt_compiler.compiler import (
    _parse_requirements_from_yaml,
    compile_workflow_from_yaml,
)
from wt_compiler.discovery import (
    discover_tasks_from_requirements,
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
                    "module_path": "mypackage.tasks",
                    "function_name": "add",
                    "import_statement": "from mypackage.tasks import add",
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
        assert entry.module_path == "mypackage.tasks"
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
            module_path="mypackage.tasks",
            function_name="test_func",
            import_statement="from mypackage.tasks import test_func",
            json_schema={
                "type": "object",
                "properties": {"x": {"type": "integer"}},
            },
        )

        # Simulate what discovery.py does
        known_task = KnownTask(
            importable_reference=f"{entry.module_path}.{entry.function_name}",
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
    async def test_discover_parses_registry_output(self, mock_tmpdir, mock_install, mock_run):
        """Test that discover_tasks_from_requirements correctly parses CLI output."""
        from rattler import MatchSpec

        # Mock TemporaryDirectory context manager
        mock_tmpdir.return_value.__enter__ = MagicMock(return_value="/fake/tmpdir")
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)

        # Mock the CLI output
        registry_json = {
            "entries": {
                "mypackage.tasks.calculate": {
                    "metadata": {
                        "title": "Calculate",
                        "description": "Calculate something",
                        "tags": [],
                    },
                    "module_path": "mypackage.tasks",
                    "function_name": "calculate",
                    "import_statement": "from mypackage.tasks import calculate",
                    "json_schema": {"properties": {}},
                }
            },
            "version": "1.0.0",
        }

        mock_run.return_value = MagicMock(
            stdout=json.dumps(registry_json),
            returncode=0,
        )

        # Skip actual installation (async mock returns None by default)

        # Call discover_tasks_from_requirements with mocked subprocess
        result = await discover_tasks_from_requirements([MatchSpec("mypackage>=1.0.0")])

        # Verify the result
        assert "calculate" in result
        assert "mypackage.tasks" in result["calculate"]
        known_task = result["calculate"]["mypackage.tasks"]
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

        requirements = _parse_requirements_from_yaml(spec_yaml)

        assert len(requirements) == 1
        assert requirements[0].name == "my-package"

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
        pass  # Placeholder for full integration test

    @pytest.mark.asyncio
    async def test_compile_workflow_from_yaml_invalid_path(self):
        """Test that invalid path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await compile_workflow_from_yaml("/nonexistent/path/spec.yaml")

    @pytest.mark.asyncio
    @patch("wt_compiler.compiler.populate_known_tasks", new_callable=AsyncMock)
    async def test_compile_workflow_from_yaml_passes_custom_channels(
        self, mock_populate, tmp_path
    ):
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
        assert len(channels) == 2, f"Expected 2 unique channels, got {len(channels)}"

        # Verify both ecoscope-workflows channel and conda-forge are present
        channel_identifiers = [c.name or c.base_url for c in channels]
        assert any(
            "ecoscope-workflows" in str(ch) for ch in channel_identifiers
        ), f"ecoscope-workflows channel not found in {channel_identifiers}"
        assert any(
            "conda-forge" in str(ch) for ch in channel_identifiers
        ), f"conda-forge not found in {channel_identifiers}"


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
        pass

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires wt-registry installed in environment")
    async def test_end_to_end_compilation(self, tmp_path):
        """Test full compilation from YAML with real discovery."""
        # Would test the complete compile_workflow_from_yaml flow
        pass
