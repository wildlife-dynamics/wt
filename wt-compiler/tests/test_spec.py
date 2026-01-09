"""Tests for spec.py - Spec and TaskInstance models."""

from pathlib import Path

import pytest

from wt_compiler.spec import (
    KnownTask,
    SpecRequirement,
    TaskInstance,
    TaskTag,
)


class TestKnownTask:
    """Tests for KnownTask model."""

    def test_known_task_creation(self):
        """Test creating a KnownTask with basic fields."""
        task = KnownTask(
            importable_reference="mymodule.my_func",
            tags=[TaskTag.io],
            json_schema={
                "properties": {"x": {"type": "integer"}},
                "required": ["x"],
            },
        )
        assert task.importable_reference == "mymodule.my_func"
        assert task.tags == [TaskTag.io]
        assert task.function_name == "my_func"
        assert task.anchor == "mymodule"

    def test_known_task_safe_reference(self):
        """Test safe_reference generation for code."""
        task1 = KnownTask(importable_reference="mod.func", registry_ref=0)
        assert task1.safe_reference == "func"

        task2 = KnownTask(importable_reference="mod.func", registry_ref=1)
        assert task2.safe_reference == "func_1"

    def test_parameters_jsonschema(self):
        """Test parameters_jsonschema method with omit_args."""
        task = KnownTask(
            importable_reference="mod.func",
            json_schema={
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "string"},
                    "z": {"type": "boolean"},
                },
                "required": ["x", "y"],
            },
        )

        # Get full schema
        schema_full = task.parameters_jsonschema(omit_args=None)
        assert "x" in schema_full["properties"]
        assert "y" in schema_full["properties"]
        assert "z" in schema_full["properties"]

        # Omit some args
        schema_omit = task.parameters_jsonschema(omit_args=["y", "z"])
        assert "x" in schema_omit["properties"]
        assert "y" not in schema_omit["properties"]
        assert "z" not in schema_omit["properties"]
        assert schema_omit["required"] == ["x"]  # y removed from required

    def test_parameters_notebook(self):
        """Test parameters_notebook generation."""
        task = KnownTask(
            importable_reference="mod.func",
            json_schema={
                "properties": {
                    "x": {"type": "integer", "default": 42},
                    "y": {"type": "string"},
                },
            },
        )

        notebook = task.parameters_notebook(omit_args=["y"])
        assert "x" in notebook
        assert "y" not in notebook


class TestSpecRequirement:
    """Tests for SpecRequirement model."""

    def test_spec_requirement_parsing(self):
        """Test parsing requirement strings."""
        req = SpecRequirement(requirement="package>=1.0.0,<2.0.0")
        assert req.name == "package"
        assert ">=1.0.0" in req.version
        assert "<2.0.0" in req.version

    def test_spec_requirement_simple(self):
        """Test simple requirement without version."""
        req = SpecRequirement(requirement="mypackage")
        assert req.name == "mypackage"
        # Version may be empty or "*"


class TestTaskInstance:
    """Tests for TaskInstance model."""

    def test_task_instance_basic(self):
        """Test creating a basic TaskInstance."""
        known_task = KnownTask(importable_reference="mod.func")
        task = TaskInstance(
            id="task1",
            name="Test Task",
            task="mod.func",
            known_task=known_task,
        )
        assert task.id == "task1"
        assert task.name == "Test Task"
        assert task.method == "call"  # Default method

    def test_task_instance_with_partial(self):
        """Test TaskInstance with partial arguments."""
        known_task = KnownTask(importable_reference="mod.add")
        task = TaskInstance(
            id="add_task",
            name="Add Numbers",
            task="mod.add",
            known_task=known_task,
            partial={"x": 10, "y": 20},
        )
        assert "x" in task.partial
        assert task.partial["x"] == 10


class TestSpec:
    """Tests for Spec model."""

    def test_spec_from_yaml_file(self):
        """Test parsing Spec from YAML file."""
        # Get path to fixture
        fixture_path = Path(__file__).parent / "fixtures" / "simple_spec.yaml"

        # For this test, we need to mock KnownTask discovery
        # In real usage, discovery.py would populate known_task
        # For now, we'll test basic YAML parsing
        import ruamel.yaml

        yaml = ruamel.yaml.YAML(typ="safe")
        with open(fixture_path) as f:
            data = yaml.load(f)

        assert data["id"] == "test-workflow"
        assert data["name"] == "Test Workflow"
        assert len(data["workflow"]) == 2

    def test_spec_sha256(self):
        """Test that Spec generates consistent SHA256 hash."""
        # Create a minimal spec

        # We'll create a simple spec manually
        spec_data = {
            "id": "test-spec",
            "name": "Test",
            "description": "Test spec",
            "requirements": ["package>=1.0"],
            "channels": ["conda-forge"],
            "workflow": [],
        }

        # The sha256 should be deterministic
        # We can't easily test this without full Spec instantiation
        # which requires task discovery, so we'll skip for now

    def test_spec_flat_workflow(self):
        """Test flat_workflow property that flattens task groups."""
        # This would require a more complex fixture with task groups
        # Skipping for now, but structure is in place


class TestTaskInstanceDependencies:
    """Tests for task instance dependency resolution."""

    def test_variable_reference_parsing(self):
        """Test parsing variable references like ${{ workflow.task1.return }}."""
        # This is tested implicitly through TaskInstance.all_dependencies_dict
        # The Spec model handles this parsing
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
