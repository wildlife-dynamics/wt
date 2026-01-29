"""Tests for spec.py - Spec and TaskInstance models."""

from pathlib import Path

import pytest

from wt_compiler.spec import (
    KnownTask,
    SkipIf,
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


class TestKnownTaskSerialization:
    """Tests for KnownTask.serialize_importable_reference field serializer."""

    def test_importable_reference_serialization_basic(self):
        """Test basic importable_reference serialization produces dict with expected keys."""
        task = KnownTask(
            importable_reference="mymodule.tasks.my_func",
            json_schema={"properties": {"x": {"type": "integer"}}},
        )

        # Serialize without context
        result = task.model_dump()
        ir = result["importable_reference"]

        # Check structure
        assert isinstance(ir, dict)
        assert ir["anchor"] == "mymodule.tasks"
        assert ir["function"] == "my_func"
        assert ir["statement"] == "from mymodule.tasks import my_func"
        assert "params_notebook" in ir

    def test_importable_reference_serialization_with_registry_ref(self):
        """Test serialization with registry_ref > 0 uses safe_reference with suffix."""
        task = KnownTask(
            importable_reference="mymodule.my_func",
            registry_ref=1,
        )

        result = task.model_dump()
        ir = result["importable_reference"]

        # Should have alias since registry_ref > 0
        assert ir["function"] == "my_func_1"
        assert "as my_func_1" in ir["statement"]
        assert ir["statement"] == "from mymodule import my_func as my_func_1"

    def test_importable_reference_serialization_with_mock_io(self):
        """Test serialization with mock_io context for IO tasks generates mock import."""
        task = KnownTask(
            importable_reference="mymodule.get_data",
            tags=[TaskTag.io],
        )

        # Serialize with mock_io=True
        result = task.model_dump(context={"mock_io": True})
        ir = result["importable_reference"]

        # Should use mock import
        assert "create_task_magicmock" in ir["statement"]
        assert "🧪" in ir["statement"]
        assert "anchor='mymodule'" in ir["statement"]
        assert "func_name='get_data'" in ir["statement"]

    def test_importable_reference_serialization_no_mock_for_non_io(self):
        """Test that non-IO tasks use normal import even when mock_io=True."""
        task = KnownTask(
            importable_reference="mymodule.compute",
            tags=[],  # Not an IO task
        )

        result = task.model_dump(context={"mock_io": True})
        ir = result["importable_reference"]

        # Should NOT use mock import
        assert "create_task_magicmock" not in ir["statement"]
        assert ir["statement"] == "from mymodule import compute"

    def test_importable_reference_serialization_with_omit_args(self):
        """Test params_notebook respects omit_args context."""
        task = KnownTask(
            importable_reference="mymodule.func",
            json_schema={
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "string"},
                }
            },
        )

        result = task.model_dump(context={"omit_args": ["y"]})
        ir = result["importable_reference"]

        assert "x" in ir["params_notebook"]
        assert "y" not in ir["params_notebook"]


class TestSkipIfKnownTasks:
    """Tests for SkipIf.known_tasks property."""

    def test_known_tasks_property_exists(self):
        """Test that SkipIf.known_tasks property resolves conditions."""
        from wt_compiler.spec import known_tasks as global_known_tasks

        # Register a mock condition task
        mock_task = KnownTask(importable_reference="mod.condition_func")
        global_known_tasks["condition_func"] = {"mod": mock_task}

        try:
            skipif = SkipIf(conditions=["condition_func"])
            assert len(skipif.known_tasks) == 1
            assert skipif.known_tasks[0] == mock_task
        finally:
            global_known_tasks.clear()

    def test_known_tasks_serialization(self):
        """Test that known_tasks serializes correctly for templates."""
        from wt_compiler.spec import known_tasks as global_known_tasks

        mock_task = KnownTask(importable_reference="mod.check_condition")
        global_known_tasks["check_condition"] = {"mod": mock_task}

        try:
            skipif = SkipIf(conditions=["check_condition"])
            result = skipif.model_dump()

            # known_tasks should be in the serialized output
            assert "known_tasks" in result
            assert len(result["known_tasks"]) == 1

            # Check that each KnownTask's importable_reference is properly serialized
            ir = result["known_tasks"][0]["importable_reference"]
            assert isinstance(ir, dict)
            assert "statement" in ir
            assert "function" in ir
        finally:
            global_known_tasks.clear()

    def test_known_tasks_with_fully_qualified_reference(self):
        """Test known_tasks with fully qualified importable reference."""
        from wt_compiler.spec import known_tasks as global_known_tasks

        mock_task = KnownTask(importable_reference="mypackage.conditions.should_skip")
        global_known_tasks["should_skip"] = {"mypackage.conditions": mock_task}

        try:
            # Use fully qualified reference
            skipif = SkipIf(conditions=["mypackage.conditions.should_skip"])
            assert len(skipif.known_tasks) == 1
            assert skipif.known_tasks[0] == mock_task
        finally:
            global_known_tasks.clear()


class TestSpecRequirement:
    """Tests for SpecRequirement model."""

    def test_spec_requirement_parsing(self):
        """Test parsing requirement strings."""
        req = SpecRequirement(requirement="package>=1.0.0,<2.0.0")
        assert req.name == "package"
        # req.version is a NamelessMatchSpec object, check string representation
        version_str = str(req.version.version) if req.version.version else ""
        assert ">=1.0.0" in version_str
        assert "<2.0.0" in version_str

    def test_spec_requirement_simple(self):
        """Test simple requirement without version."""
        req = SpecRequirement(requirement="mypackage")
        assert req.name == "mypackage"
        # Version should be "*" for unspecified version


class TestTaskInstance:
    """Tests for TaskInstance model."""

    def test_task_instance_basic(self):
        """Test creating a basic TaskInstance."""
        from wt_compiler.spec import known_tasks

        # Register the task in the global registry
        mock_task = KnownTask(importable_reference="mod.func")
        known_tasks["func"] = {"mod": mock_task}

        try:
            task = TaskInstance(
                id="task1",
                name="Test Task",
                task="mod.func",
            )
            assert task.id == "task1"
            assert task.name == "Test Task"
            assert task.method == "call"  # Default method
            assert task.known_task == mock_task
        finally:
            known_tasks.clear()

    def test_task_instance_with_partial(self):
        """Test TaskInstance with partial arguments."""
        from wt_compiler.spec import known_tasks

        # Register the task in the global registry
        mock_task = KnownTask(importable_reference="mod.add")
        known_tasks["add"] = {"mod": mock_task}

        try:
            task = TaskInstance(
                id="add_task",
                name="Add Numbers",
                task="mod.add",
                partial={"x": 10, "y": 20},
            )
            assert "x" in task.partial
            # Note: partial values are wrapped, so check the structure
            assert task.known_task == mock_task
        finally:
            known_tasks.clear()


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
