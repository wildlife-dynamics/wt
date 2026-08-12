"""Tests for spec.py - Spec and TaskInstance models."""

from pathlib import Path

import pytest
import ruamel.yaml
from pydantic import ValidationError

from wt_compiler.spec import (
    InlineValue,
    KnownTask,
    Maintainer,
    Metadata,
    PyPIRequirement,
    SkipIf,
    Spec,
    SpecRequirement,
    TaskIdVariable,
    TaskInstance,
    TaskTag,
    VariableValuesDict,
    VariableValuesList,
    _conda_or_pypi,
    _find_task_id_vars,
    known_tasks,
)
from wt_compiler.spec import known_tasks as global_known_tasks


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

    def test_parameters_jsonschema_returns_independent_copies(self):
        """Test that multiple calls return independent dicts, not shared references.

        When two task instances share the same KnownTask (e.g., maybe_skip_df used
        by both skip_map_generation and skip_attachment_download), mutations to one
        schema must not affect the other. Regression test for #128.
        """
        task = KnownTask(
            importable_reference="mod.maybe_skip_df",
            json_schema={
                "properties": {
                    "skip": {"type": "boolean", "default": False, "description": "original"},
                },
            },
        )

        schema1 = task.parameters_jsonschema()
        schema2 = task.parameters_jsonschema()

        # Mutate schema1's nested property
        schema1["properties"]["skip"]["default"] = True
        schema1["properties"]["skip"]["description"] = "mutated"

        # schema2 must be unaffected
        assert schema2["properties"]["skip"]["default"] is False
        assert schema2["properties"]["skip"]["description"] == "original"


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


class TestPyPIRequirement:
    """Tests for PyPIRequirement model."""

    def test_git_basic(self):
        """Test basic git requirement."""
        req = PyPIRequirement(name="foo", git="https://github.com/org/foo.git")
        assert req.to_pixi_dict() == {"git": "https://github.com/org/foo.git"}

    def test_git_with_rev(self):
        """Test git requirement with rev."""
        req = PyPIRequirement(name="foo", git="https://github.com/org/foo.git", rev="abc123")
        assert req.to_pixi_dict() == {"git": "https://github.com/org/foo.git", "rev": "abc123"}

    def test_git_with_branch(self):
        """Test git requirement with branch."""
        req = PyPIRequirement(name="foo", git="https://github.com/org/foo.git", branch="main")
        assert req.to_pixi_dict() == {"git": "https://github.com/org/foo.git", "branch": "main"}

    def test_git_with_tag(self):
        """Test git requirement with tag."""
        req = PyPIRequirement(name="foo", git="https://github.com/org/foo.git", tag="v1.0")
        assert req.to_pixi_dict() == {"git": "https://github.com/org/foo.git", "tag": "v1.0"}

    def test_path_basic(self):
        """Test basic path requirement."""
        req = PyPIRequirement(name="foo", path="/opt/foo")
        assert req.to_pixi_dict() == {"path": "/opt/foo"}

    def test_path_editable(self):
        """Test editable path requirement."""
        req = PyPIRequirement(name="foo", path="/opt/foo", editable=True)
        assert req.to_pixi_dict() == {"path": "/opt/foo", "editable": True}

    def test_url(self):
        """Test URL requirement."""
        req = PyPIRequirement(name="foo", url="https://example.com/foo-1.0.whl")
        assert req.to_pixi_dict() == {"url": "https://example.com/foo-1.0.whl"}

    def test_extras(self):
        """Test requirement with extras."""
        req = PyPIRequirement(
            name="foo", git="https://github.com/org/foo.git", extras=["dev", "test"]
        )
        d = req.to_pixi_dict()
        assert d["extras"] == ["dev", "test"]
        assert d["git"] == "https://github.com/org/foo.git"

    def test_subdirectory(self):
        """Test requirement with subdirectory."""
        req = PyPIRequirement(
            name="foo", git="https://github.com/org/monorepo.git", subdirectory="packages/foo"
        )
        d = req.to_pixi_dict()
        assert d["subdirectory"] == "packages/foo"

    def test_validate_no_source(self):
        """Test that no source and no version raises error."""
        with pytest.raises(
            ValueError, match="must declare one of 'git', 'path', 'url', or 'version'"
        ):
            PyPIRequirement(name="foo")

    def test_validate_multiple_sources(self):
        """Test that multiple sources raises error."""
        with pytest.raises(ValueError, match="At most one"):
            PyPIRequirement(name="foo", git="https://github.com/org/foo.git", path="/opt/foo")

    def test_validate_rev_without_git(self):
        """Test that rev without git raises error."""
        with pytest.raises(ValueError, match="only valid with 'git'"):
            PyPIRequirement(name="foo", path="/opt/foo", rev="abc123")

    def test_validate_editable_without_path(self):
        """Test that editable without path raises error."""
        with pytest.raises(ValueError, match="only valid with 'path'"):
            PyPIRequirement(name="foo", git="https://github.com/org/foo.git", editable=True)

    def test_validate_multiple_git_refs(self):
        """Test that multiple git refs raises error."""
        with pytest.raises(ValueError, match="At most one"):
            PyPIRequirement(
                name="foo", git="https://github.com/org/foo.git", rev="abc", branch="main"
            )

    def test_validate_path_file_url_rejected(self):
        """Test that file:// URL in path raises error."""
        with pytest.raises(ValueError, match="not a file:// URL"):
            PyPIRequirement(name="foo", path="file:///home/user/foo")

    def test_validate_path_relative_rejected(self):
        """Test that relative path raises error."""
        with pytest.raises(ValueError, match="must be an absolute filesystem path"):
            PyPIRequirement(name="foo", path="./foo")

    def test_to_pip_install_arg_git(self):
        """Test pip install arg for git requirement."""
        req = PyPIRequirement(name="foo", git="https://github.com/org/foo.git", tag="v1.0")
        assert req.to_pip_install_arg() == "foo @ git+https://github.com/org/foo.git@v1.0"

    def test_to_pip_install_arg_git_with_extras(self):
        """Test pip install arg for git requirement with extras."""
        req = PyPIRequirement(name="foo", git="https://github.com/org/foo.git", extras=["dev"])
        assert req.to_pip_install_arg() == "foo[dev] @ git+https://github.com/org/foo.git"

    def test_to_pip_install_arg_path(self):
        """Test pip install arg for path requirement."""
        req = PyPIRequirement(name="foo", path="/opt/foo")
        assert req.to_pip_install_arg() == "/opt/foo"

    def test_to_pip_install_arg_path_editable(self):
        """Test pip install arg for editable path requirement."""
        req = PyPIRequirement(name="foo", path="/opt/foo", editable=True)
        assert req.to_pip_install_arg() == "-e /opt/foo"

    def test_to_pip_install_arg_path_with_extras(self):
        """Test pip install arg for path requirement with extras."""
        req = PyPIRequirement(name="foo", path="/opt/foo", extras=["platform"])
        assert req.to_pip_install_arg() == "/opt/foo[platform]"

    def test_to_pip_install_arg_path_editable_with_extras(self):
        """Test pip install arg for editable path requirement with extras."""
        req = PyPIRequirement(
            name="foo", path="/opt/foo", editable=True, extras=["platform", "dev"]
        )
        assert req.to_pip_install_arg() == "-e /opt/foo[platform,dev]"

    def test_to_pip_install_arg_url(self):
        """Test pip install arg for URL requirement."""
        req = PyPIRequirement(name="foo", url="https://example.com/foo-1.0.whl")
        assert req.to_pip_install_arg() == "foo @ https://example.com/foo-1.0.whl"


class TestCondaOrPypiDiscriminator:
    """Tests for the _conda_or_pypi discriminator function."""

    def test_string_is_conda(self):
        """Test that a string value routes to conda."""
        assert _conda_or_pypi("package>=1.0") == "conda"

    def test_dict_with_git_is_pypi(self):
        """Test that dict with git key routes to pypi."""
        assert _conda_or_pypi({"name": "foo", "git": "https://..."}) == "pypi"

    def test_dict_with_path_is_pypi(self):
        """Test that dict with path key routes to pypi."""
        assert _conda_or_pypi({"name": "foo", "path": "./foo"}) == "pypi"

    def test_dict_with_url_is_pypi(self):
        """Test that dict with url key routes to pypi."""
        assert _conda_or_pypi({"name": "foo", "url": "https://..."}) == "pypi"

    def test_dict_without_pypi_keys_is_conda(self):
        """Test that dict without pypi keys routes to conda."""
        assert _conda_or_pypi({"requirement": "package>=1.0"}) == "conda"
        assert _conda_or_pypi({"name": "package", "version": ">=1.0"}) == "conda"

    def test_validated_models(self):
        """Test that already-validated models route correctly."""
        conda_req = SpecRequirement(requirement="package>=1.0")
        pypi_req = PyPIRequirement(name="foo", git="https://github.com/org/foo.git")
        assert _conda_or_pypi(conda_req) == "conda"
        assert _conda_or_pypi(pypi_req) == "pypi"


class TestSpecRequirementsUnion:
    """Tests for Spec.requirements with mixed conda and pypi deps."""

    def test_spec_with_only_conda_requirements(self):
        """Test backwards compatibility: spec with only conda requirements."""
        spec = Spec(
            id="my_workflow",
            requirements=[
                {"requirement": "python>=3.10"},
                {"requirement": "pandas>=2.0"},
            ],
            workflow=[],
        )
        assert len(spec.requirements) == 2
        assert all(isinstance(r, SpecRequirement) for r in spec.requirements)
        assert len(spec.conda_requirements) == 2
        assert len(spec.pypi_requirements) == 0

    def test_spec_with_mixed_requirements(self):
        """Test spec with both conda and pypi requirements."""
        spec = Spec(
            id="my_workflow",
            requirements=[
                {"requirement": "python>=3.10"},
                {"name": "foo", "git": "https://github.com/org/foo.git"},
                {"requirement": "pandas>=2.0"},
                {"name": "bar", "path": "/opt/bar", "editable": True},
            ],
            workflow=[],
        )
        assert len(spec.requirements) == 4
        assert len(spec.conda_requirements) == 2
        assert len(spec.pypi_requirements) == 2
        assert spec.pypi_requirements[0].name == "foo"
        assert spec.pypi_requirements[1].name == "bar"

    def test_spec_with_only_pypi_requirements(self):
        """Test spec with only pypi requirements."""
        spec = Spec(
            id="my_workflow",
            requirements=[
                {"name": "foo", "git": "https://github.com/org/foo.git"},
            ],
            workflow=[],
        )
        assert len(spec.conda_requirements) == 0
        assert len(spec.pypi_requirements) == 1


class TestTaskInstance:
    """Tests for TaskInstance model."""

    def test_task_instance_basic(self):
        """Test creating a basic TaskInstance."""

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


class TestInlineValue:
    """Tests for InlineValue.serialize()."""

    def test_plain_string(self):
        """Simple string is repr'd with surrounding quotes."""
        val = InlineValue(value="hello")
        result = val.model_dump()
        assert result["asstr"] == "'hello'"
        assert result["is_inline_value"] is True

    def test_string_with_single_quote(self):
        """String containing a single quote uses double-quote delimiters via repr."""
        val = InlineValue(value="it's a test")
        result = val.model_dump()
        # repr() produces "it's a test" (double-quoted) rather than the broken 'it's a test'
        assert result["asstr"] == repr("it's a test")
        assert result["asstr"] == '"it\'s a test"'

    def test_string_with_double_quote(self):
        """String containing a double quote is safely repr'd."""
        val = InlineValue(value='say "hi"')
        result = val.model_dump()
        assert result["asstr"] == repr('say "hi"')

    def test_string_with_both_quote_types(self):
        """String with both quote types is safely repr'd with escaping."""
        val = InlineValue(value='it\'s a "test"')
        result = val.model_dump()
        assert result["asstr"] == repr('it\'s a "test"')

    def test_integer(self):
        """Integer value uses f-string formatting (no quotes)."""
        val = InlineValue(value=42)
        result = val.model_dump()
        assert result["asstr"] == "42"

    def test_float(self):
        """Float value uses f-string formatting."""
        val = InlineValue(value=3.14)
        result = val.model_dump()
        assert result["asstr"] == "3.14"

    def test_bool_true(self):
        """Boolean True serializes as 'True'."""
        val = InlineValue(value=True)
        result = val.model_dump()
        assert result["asstr"] == "True"

    def test_bool_false(self):
        """Boolean False serializes as 'False'."""
        val = InlineValue(value=False)
        result = val.model_dump()
        assert result["asstr"] == "False"

    def test_none(self):
        """None serializes as 'None'."""
        val = InlineValue(value=None)
        result = val.model_dump()
        assert result["asstr"] == "None"

    def test_list(self):
        """List value uses f-string formatting."""
        val = InlineValue(value=[1, 2, 3])
        result = val.model_dump()
        assert result["asstr"] == "[1, 2, 3]"

    def test_dict(self):
        """Dict value uses f-string formatting."""
        val = InlineValue(value={"key": "value"})
        result = val.model_dump()
        assert result["asstr"] == "{'key': 'value'}"


class TestVariableValuesList:
    """Tests for VariableValuesList parsing, serialization, and dependency extraction."""

    def test_mixed_list_parsing(self):
        """Test that a mixed list is parsed as VariableValuesList."""

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


class TestVariableValuesDict:
    """Tests for VariableValuesDict with nested dicts and lists containing variable refs."""

    def test_nested_dict_with_variable_ref(self):
        """Test that a variable ref inside a nested dict is parsed as TaskIdVariable."""

        mock_task = KnownTask(importable_reference="mod.func")
        known_tasks["func"] = {"mod": mock_task}

        try:
            ti = TaskInstance(
                id="task2",
                name="Nested Dict Task",
                task="mod.func",
                partial={
                    "context": {
                        "key": "value",
                        "ref": "${{ workflow.task1.return }}",
                    }
                },
            )
            dep = ti.partial["context"]
            assert isinstance(dep, VariableValuesDict)
            serialized = ti.model_dump()
            context = serialized["partial"]["context"]
            assert context["has_variable_values"] is True
            assert "task1" in context["asstr"]
            assert "'ref': task1" in context["asstr"]
            assert "'key': 'value'" in context["asstr"]
        finally:
            known_tasks.clear()

    def test_variable_ref_in_dict_in_list_in_dict(self):
        """Test ${{ }} ref inside dict → list → dict nesting."""

        mock_task = KnownTask(importable_reference="mod.func")
        known_tasks["func"] = {"mod": mock_task}

        try:
            ti = TaskInstance(
                id="report_task",
                name="Report Task",
                task="mod.func",
                partial={
                    "context": {
                        "items": [
                            {
                                "item_type": "timerange",
                                "key": "report_date",
                                "value": "${{ workflow.time_range.return }}",
                            },
                            {
                                "item_type": "table",
                                "key": "stats",
                                "value": "${{ workflow.stats_sql.return }}",
                            },
                        ]
                    }
                },
            )
            serialized = ti.model_dump()
            context = serialized["partial"]["context"]
            assert context["has_variable_values"] is True
            # The asstr should contain resolved variable names, not ${{ }} strings
            assert "time_range" in context["asstr"]
            assert "stats_sql" in context["asstr"]
            assert "${{" not in context["asstr"]
        finally:
            known_tasks.clear()

    def test_nested_variable_ref_in_asdict(self):
        """Test that asdict contains properly serialized nested variable refs."""

        mock_task = KnownTask(importable_reference="mod.func")
        known_tasks["func"] = {"mod": mock_task}

        try:
            ti = TaskInstance(
                id="task2",
                name="Nested Task",
                task="mod.func",
                partial={
                    "outer": {
                        "inner_list": [
                            {"ref": "${{ workflow.task1.return }}", "literal": "hello"},
                        ]
                    }
                },
            )
            serialized = ti.model_dump()
            outer = serialized["partial"]["outer"]
            # Walk into asdict → inner_list → aslist → first item → asdict → ref
            inner_list = outer["asdict"]["inner_list"]
            assert inner_list["has_variable_values"] is True
            first_item = inner_list["aslist"][0]
            assert first_item["has_variable_values"] is True
            ref_val = first_item["asdict"]["ref"]
            assert ref_val["asstr"] == "task1"
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

        yaml = ruamel.yaml.YAML(typ="safe")
        with fixture_path.open() as f:
            data = yaml.load(f)

        assert data["id"] == "test-workflow"
        assert data["name"] == "Test Workflow"
        assert len(data["workflow"]) == 2

    def test_spec_sha256(self):
        """Test that Spec generates consistent SHA256 hash."""
        # Create a minimal spec

        # We'll create a simple spec manually

        # The sha256 should be deterministic
        # We can't easily test this without full Spec instantiation
        # which requires task discovery, so we'll skip for now

    def test_spec_flat_workflow(self):
        """Test flat_workflow property that flattens task groups."""
        # This would require a more complex fixture with task groups
        # Skipping for now, but structure is in place


class TestMetadata:
    """Tests for the optional spec-level metadata section."""

    @staticmethod
    def _full_metadata() -> dict:
        return {
            "name": "Events Dashboard",
            "description": "Summarize EarthRanger events over a time range.",
            "maintainers": [
                {"name": "Jane Doe", "email": "jane@example.org"},
                {"name": "John Smith", "email": "john@example.org"},
            ],
            "license": "Apache-2.0",
            "repository": "https://github.com/wildlife-dynamics/events-workflow",
            "documentation": "https://example.org/workflows/events/docs",
            "readme": "README.md",
            "keywords": ["earthranger", "events", "dashboard"],
        }

    def test_metadata_omitted_is_none(self):
        """A spec without a metadata block validates; metadata is None."""
        spec = Spec(id="my_workflow", requirements=[], workflow=[])
        assert spec.metadata is None

    def test_metadata_full(self):
        """A fully populated metadata block validates and is accessible."""
        spec = Spec(
            id="my_workflow",
            requirements=[],
            metadata=self._full_metadata(),
            workflow=[],
        )
        assert spec.metadata is not None
        assert spec.metadata.name == "Events Dashboard"
        assert spec.metadata.license == "Apache-2.0"
        assert len(spec.metadata.maintainers) == 2
        assert spec.metadata.maintainers[0].name == "Jane Doe"
        assert spec.metadata.maintainers[0].email == "jane@example.org"
        assert spec.metadata.keywords == ["earthranger", "events", "dashboard"]

    def test_metadata_minimal_required_only(self):
        """Only the required fields are needed; optionals default sensibly."""
        metadata = Metadata(
            name="My Workflow",
            description="Does a thing.",
            maintainers=[{"name": "Jane Doe", "email": "jane@example.org"}],
            license="MIT",
        )
        assert metadata.repository is None
        assert metadata.documentation is None
        assert metadata.readme is None
        assert metadata.keywords == []

    @pytest.mark.parametrize("missing", ["name", "description", "maintainers", "license"])
    def test_metadata_missing_required_field_rejected(self, missing):
        """If metadata is provided, each required field must be present."""
        metadata = self._full_metadata()
        del metadata[missing]
        with pytest.raises(ValidationError):
            Spec(id="my_workflow", requirements=[], metadata=metadata, workflow=[])

    def test_maintainer_missing_required_field_rejected(self):
        """Each maintainer requires both name and email."""
        with pytest.raises(ValidationError):
            Maintainer(name="Jane Doe")
        with pytest.raises(ValidationError):
            Maintainer(email="jane@example.org")

    def test_metadata_optional_field_wrong_type_rejected(self):
        """Optional fields are type-enforced when provided."""
        metadata = self._full_metadata()
        metadata["readme"] = {"path": "README.md"}
        with pytest.raises(ValidationError):
            Spec(id="my_workflow", requirements=[], metadata=metadata, workflow=[])

        metadata = self._full_metadata()
        metadata["keywords"] = "not-a-list"
        with pytest.raises(ValidationError):
            Spec(id="my_workflow", requirements=[], metadata=metadata, workflow=[])

    def test_metadata_extra_fields_allowed_and_retained(self):
        """Unknown keys on metadata and maintainers are allowed and retained."""
        metadata = self._full_metadata()
        metadata["citations"] = ["doi:10.1234/example"]
        metadata["maintainers"][0]["organization"] = "Wildlife-Dynamics"

        spec = Spec(id="my_workflow", requirements=[], metadata=metadata, workflow=[])
        assert spec.metadata is not None
        assert spec.metadata.model_extra["citations"] == ["doi:10.1234/example"]
        assert spec.metadata.maintainers[0].model_extra["organization"] == "Wildlife-Dynamics"
        # Retained through serialization for downstream tooling.
        dumped = spec.metadata.model_dump()
        assert dumped["citations"] == ["doi:10.1234/example"]
        assert dumped["maintainers"][0]["organization"] == "Wildlife-Dynamics"

    def test_metadata_does_not_influence_sha256(self):
        """Metadata is excluded from the workflow hash: it must not change sha256."""
        without = Spec(id="my_workflow", requirements=[], workflow=[])
        with_metadata = Spec(
            id="my_workflow",
            requirements=[],
            metadata=self._full_metadata(),
            workflow=[],
        )
        assert without.sha256 == with_metadata.sha256

        # Mutating any metadata field also leaves the hash unchanged.
        other_metadata = self._full_metadata()
        other_metadata["name"] = "A Totally Different Name"
        other_metadata["keywords"] = ["something", "else"]
        with_other_metadata = Spec(
            id="my_workflow",
            requirements=[],
            metadata=other_metadata,
            workflow=[],
        )
        assert with_metadata.sha256 == with_other_metadata.sha256


class TestTaskInstanceDependencies:
    """Tests for task instance dependency resolution."""

    def test_variable_reference_parsing(self):
        """Test parsing variable references like ${{ workflow.task1.return }}."""
        # This is tested implicitly through TaskInstance.all_dependencies_dict
        # The Spec model handles this parsing


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
