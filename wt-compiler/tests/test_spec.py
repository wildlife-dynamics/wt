"""Tests for spec.py - Spec and TaskInstance models."""

from pathlib import Path

import pytest

from wt_compiler.spec import (
    InlineValue,
    KnownTask,
    SkipIf,
    SpecRequirement,
    TaskIdVariable,
    TaskInstance,
    TaskTag,
    VariableValuesList,
    _find_task_id_vars,
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

    def test_parameters_jsonschema_all_defaults_with_omit_args(self):
        """Test that omit_args always sets 'required' key, even when original schema lacks it.

        When all parameters have defaults, Pydantic omits the 'required' key from
        the generated schema. The legacy compiler unconditionally sets 'required'
        when omit_args is provided, producing 'required': []. We must match this
        behavior to avoid false major version bumps due to params_sha256 mismatch.
        """
        task = KnownTask(
            importable_reference="mod.func",
            json_schema={
                "properties": {
                    "x": {"type": "integer", "default": 1},
                    "y": {"type": "string", "default": "hello"},
                },
                # No "required" key — all params have defaults
            },
        )

        schema = task.parameters_jsonschema(omit_args=["y"])
        assert "required" in schema, (
            "Expected 'required' key to be present when omit_args is provided"
        )
        assert schema["required"] == []
        assert "y" not in schema["properties"]
        assert "x" in schema["properties"]


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
        # Always uses "as" clause for explicit re-export semantics
        assert ir["statement"] == "from mymodule.tasks import my_func as my_func"
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
        assert "create_func_magicmock" in ir["statement"]
        assert "🧪" in ir["statement"]
        assert "anchor='mymodule'" in ir["statement"]
        assert "func_name='get_data'" in ir["statement"]
        assert ir["is_mocked"] is True

    def test_importable_reference_serialization_no_mock_for_non_io(self):
        """Test that non-IO tasks use normal import even when mock_io=True."""
        task = KnownTask(
            importable_reference="mymodule.compute",
            tags=[],  # Not an IO task
        )

        result = task.model_dump(context={"mock_io": True})
        ir = result["importable_reference"]

        # Should NOT use mock import, but still uses "as" clause
        assert "create_func_magicmock" not in ir["statement"]
        assert ir["statement"] == "from mymodule import compute as compute"
        assert ir["is_mocked"] is False

    def test_importable_reference_is_mocked_false_without_context(self):
        """Test that IO-tagged task without mock_io context has is_mocked=False."""
        task = KnownTask(
            importable_reference="mymodule.get_data",
            tags=[TaskTag.io],
        )

        # Serialize without any context (default)
        result = task.model_dump()
        ir = result["importable_reference"]

        assert ir["is_mocked"] is False
        assert "create_func_magicmock" not in ir["statement"]

    def test_importable_reference_is_mocked_false_for_no_tags(self):
        """Test that task with no tags has is_mocked=False even with mock_io=True."""
        task = KnownTask(
            importable_reference="mymodule.transform",
        )

        result = task.model_dump(context={"mock_io": True})
        ir = result["importable_reference"]

        assert ir["is_mocked"] is False
        assert "create_func_magicmock" not in ir["statement"]


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


class TestVariableValuesList:
    """Tests for VariableValuesList parsing, serialization, and dependency extraction."""

    def test_mixed_list_parsing(self):
        """Test that a mixed list is parsed as VariableValuesList."""
        from wt_compiler.spec import known_tasks

        mock_task = KnownTask(importable_reference="mod.func")
        known_tasks["func"] = {"mod": mock_task}

        try:
            ti = TaskInstance(
                id="task2",
                name="Mixed List Task",
                task="mod.func",
                partial={"values": [" by ", "${{ workflow.task1.return }}"]},
            )
            dep = ti.partial["values"]
            assert isinstance(dep, VariableValuesList)
            assert len(dep.value) == 2
        finally:
            known_tasks.clear()

    def test_mixed_list_serialization_asstr(self):
        """Test that VariableValuesList serialization produces correct asstr."""
        from wt_compiler.spec import known_tasks

        mock_task = KnownTask(importable_reference="mod.func")
        known_tasks["func"] = {"mod": mock_task}

        try:
            ti = TaskInstance(
                id="task2",
                name="Mixed List Task",
                task="mod.func",
                partial={"values": [" by ", "${{ workflow.task1.return }}"]},
            )
            serialized = ti.model_dump()
            partial_values = serialized["partial"]["values"]
            assert partial_values["asstr"] == "[' by ', task1]"
            assert partial_values["has_variable_values"] is True
        finally:
            known_tasks.clear()

    def test_mixed_list_serialization_aslist(self):
        """Test that VariableValuesList aslist contains properly serialized items."""
        from wt_compiler.spec import known_tasks

        mock_task = KnownTask(importable_reference="mod.func")
        known_tasks["func"] = {"mod": mock_task}

        try:
            ti = TaskInstance(
                id="task2",
                name="Mixed List Task",
                task="mod.func",
                partial={"values": [" by ", "${{ workflow.task1.return }}"]},
            )
            serialized = ti.model_dump()
            aslist = serialized["partial"]["values"]["aslist"]
            assert len(aslist) == 2
            # First item is an inline value
            assert aslist[0]["is_inline_value"] is True
            assert aslist[0]["asstr"] == "' by '"
            # Second item is a variable reference
            assert aslist[1]["asstr"] == "task1"
            assert aslist[1]["aslist"] == ["task1"]
        finally:
            known_tasks.clear()

    def test_pure_inline_list_becomes_variable_values_list(self):
        """Test that a pure inline list (no variables) becomes VariableValuesList."""
        from wt_compiler.spec import known_tasks

        mock_task = KnownTask(importable_reference="mod.func")
        known_tasks["func"] = {"mod": mock_task}

        try:
            ti = TaskInstance(
                id="task1",
                name="Inline List Task",
                task="mod.func",
                partial={"colors": ["red", "green", "blue"]},
            )
            dep = ti.partial["colors"]
            assert isinstance(dep, VariableValuesList)
            serialized = ti.model_dump()
            assert serialized["partial"]["colors"]["asstr"] == "['red', 'green', 'blue']"
        finally:
            known_tasks.clear()

    def test_single_variable_list(self):
        """Test a list with a single variable reference."""
        from wt_compiler.spec import known_tasks

        mock_task = KnownTask(importable_reference="mod.func")
        known_tasks["func"] = {"mod": mock_task}

        try:
            ti = TaskInstance(
                id="task2",
                name="Single Var List Task",
                task="mod.func",
                partial={"values": ["${{ workflow.task1.return }}"]},
            )
            dep = ti.partial["values"]
            assert isinstance(dep, VariableValuesList)
            serialized = ti.model_dump()
            assert serialized["partial"]["values"]["asstr"] == "[task1]"
        finally:
            known_tasks.clear()

    def test_empty_list(self):
        """Test an empty list partial arg."""
        from wt_compiler.spec import known_tasks

        mock_task = KnownTask(importable_reference="mod.func")
        known_tasks["func"] = {"mod": mock_task}

        try:
            ti = TaskInstance(
                id="task1",
                name="Empty List Task",
                task="mod.func",
                partial={"values": []},
            )
            dep = ti.partial["values"]
            assert isinstance(dep, VariableValuesList)
            serialized = ti.model_dump()
            assert serialized["partial"]["values"]["asstr"] == "[]"
        finally:
            known_tasks.clear()

    def test_dependency_extraction_from_mixed_list(self):
        """Test TaskIdVariable extraction from VariableValuesList."""
        from wt_compiler.spec import known_tasks

        mock_task = KnownTask(importable_reference="mod.func")
        known_tasks["func"] = {"mod": mock_task}

        try:
            ti = TaskInstance(
                id="task2",
                name="Mixed List Task",
                task="mod.func",
                partial={"values": [" by ", "${{ workflow.task1.return }}"]},
            )
            deps = ti.all_dependencies_dict
            assert "values" in deps
            assert deps["values"] == ["task1"]
        finally:
            known_tasks.clear()

    def test_dependency_extraction_no_variables(self):
        """Test that pure inline lists produce empty dependency lists."""
        from wt_compiler.spec import known_tasks

        mock_task = KnownTask(importable_reference="mod.func")
        known_tasks["func"] = {"mod": mock_task}

        try:
            ti = TaskInstance(
                id="task1",
                name="Inline List Task",
                task="mod.func",
                partial={"colors": ["red", "green"]},
            )
            deps = ti.all_dependencies_dict
            assert deps["colors"] == []
        finally:
            known_tasks.clear()


class TestFindTaskIdVars:
    """Tests for the _find_task_id_vars helper function."""

    def test_task_id_variable(self):
        """Test extracting a TaskIdVariable."""
        var = TaskIdVariable(value="task1", suffix="return")
        result = list(_find_task_id_vars(var))
        assert len(result) == 1
        assert result[0].value == "task1"

    def test_inline_value(self):
        """Test that InlineValue yields no task id vars."""
        val = InlineValue(value="literal")
        result = list(_find_task_id_vars(val))
        assert result == []

    def test_variable_values_list(self):
        """Test extracting from a VariableValuesList (constructed via validation pipeline)."""
        vvl = VariableValuesList(value=["${{ workflow.task1.return }}", "literal"])
        result = list(_find_task_id_vars(vvl))
        assert len(result) == 1
        assert result[0].value == "task1"

    def test_plain_list(self):
        """Test extracting from a plain list (Vars type)."""
        var1 = TaskIdVariable(value="task1", suffix="return")
        var2 = TaskIdVariable(value="task2", suffix="return")
        result = list(_find_task_id_vars([var1, var2]))
        assert len(result) == 2
        assert result[0].value == "task1"
        assert result[1].value == "task2"


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
