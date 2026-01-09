"""Tests for compiler.py - DagCompiler functionality."""

import pytest

from wt_compiler.compiler import (
    DagCompiler,
    Fingerprint,
    _remove_functionally_irrelevant_keys,
)
from wt_compiler.spec import KnownTask, Spec, SpecRequirement, TaskInstance


class TestRemoveFunctionallyIrrelevantKeys:
    """Tests for _remove_functionally_irrelevant_keys helper."""

    def test_remove_title_and_description(self):
        """Test removing documentation keys."""
        schema = {
            "title": "My Field",
            "description": "A field",
            "type": "string",
            "default": "foo",
        }
        cleaned = _remove_functionally_irrelevant_keys(schema)
        assert "title" not in cleaned
        assert "description" not in cleaned
        assert "default" not in cleaned
        assert "type" in cleaned

    def test_nested_dict_cleaning(self):
        """Test cleaning nested dictionaries."""
        schema = {
            "properties": {
                "field1": {
                    "title": "Field 1",
                    "type": "string",
                    "description": "First field",
                },
                "field2": {"type": "integer"},
            }
        }
        cleaned = _remove_functionally_irrelevant_keys(schema)
        assert "title" not in cleaned["properties"]["field1"]
        assert "type" in cleaned["properties"]["field1"]

    def test_list_cleaning(self):
        """Test cleaning lists."""
        schema = {
            "oneOf": [
                {"title": "Option 1", "const": "A"},
                {"title": "Option 2", "const": "B"},
            ]
        }
        cleaned = _remove_functionally_irrelevant_keys(schema)
        assert "title" not in cleaned["oneOf"][0]
        assert "const" in cleaned["oneOf"][0]


class TestDagCompiler:
    """Tests for DagCompiler class."""

    def test_package_name_generation(self):
        """Test package name generation from spec ID."""
        # Create a minimal spec
        spec = Spec(
            id="my-workflow",
            name="My Workflow",
            description="Test",
            requirements=[],
            channels=[],
            workflow=[],
        )
        compiler = DagCompiler(spec=spec)
        assert compiler.release_name == "wf-my-workflow"
        assert compiler.package_name == "wf_my_workflow"

    def test_per_taskinstance_omit_args(self):
        """Test omit_args calculation for task instances."""
        # Create tasks with dependencies
        task1 = KnownTask(
            importable_reference="mod.func1",
            json_schema={"properties": {"x": {"type": "integer"}}},
        )
        task2 = KnownTask(
            importable_reference="mod.func2",
            json_schema={"properties": {"y": {"type": "integer"}}},
        )

        instance1 = TaskInstance(
            id="task1",
            name="Task 1",
            task="mod.func1",
            known_task=task1,
            partial={"x": 10},
        )
        instance2 = TaskInstance(
            id="task2",
            name="Task 2",
            task="mod.func2",
            known_task=task2,
            partial={},
        )

        spec = Spec(
            id="test-spec",
            name="Test",
            description="Test",
            requirements=[],
            channels=[],
            workflow=[instance1, instance2],
        )
        compiler = DagCompiler(spec=spec)

        omit_args = compiler.per_taskinstance_omit_args
        assert "task1" in omit_args
        assert "return" in omit_args["task1"]
        assert "x" in omit_args["task1"]  # x is in partial

    def test_build_pydot_graph(self):
        """Test building a pydot graph from spec."""
        task1 = KnownTask(
            importable_reference="mod.func1",
            json_schema={"properties": {}},
        )
        instance1 = TaskInstance(
            id="task1",
            name="Task 1",
            task="mod.func1",
            known_task=task1,
        )

        spec = Spec(
            id="test-spec",
            name="Test",
            description="Test",
            requirements=[],
            channels=[],
            workflow=[instance1],
        )
        compiler = DagCompiler(spec=spec)

        graph = compiler.build_pydot_graph()
        assert graph.get_name() == "test-spec"
        # Check that nodes were created
        nodes = graph.get_nodes()
        assert len(nodes) > 0

    def test_get_pixi_toml(self):
        """Test pixi.toml generation."""
        spec = Spec(
            id="test-spec",
            name="Test",
            description="Test",
            requirements=[
                SpecRequirement(requirement="python>=3.10"),
                SpecRequirement(requirement="pandas>=2.0"),
            ],
            channels=["conda-forge"],
            workflow=[],
        )
        compiler = DagCompiler(spec=spec)
        pixi_toml = compiler.get_pixi_toml()

        assert pixi_toml.workspace.name == "wf_test_spec"
        assert "python" in pixi_toml.dependencies
        assert "pandas" in pixi_toml.dependencies

    def test_props_and_defs_from_task_instance(self):
        """Test extracting properties and definitions from a task instance."""
        task = KnownTask(
            importable_reference="mod.func",
            json_schema={
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "string"},
                    "z": {"$ref": "#/$defs/MyType"},
                },
                "$defs": {"MyType": {"type": "object", "properties": {"a": {"type": "int"}}}},
            },
        )
        instance = TaskInstance(
            id="my_task",
            name="My Task",
            task="mod.func",
            known_task=task,
        )

        props, defs = DagCompiler._props_and_defs_from_task_instance(instance, omit_args=["y"])

        assert "my_task" in props
        assert "x" in props["my_task"]["properties"]
        assert "y" not in props["my_task"]["properties"]  # Omitted
        assert "z" in props["my_task"]["properties"]
        assert "MyType" in defs


class TestFingerprint:
    """Tests for Fingerprint class."""

    def test_fingerprint_creation(self):
        """Test creating a fingerprint."""
        from wt_compiler.artifacts import (
            Dags,
            PackageDirectory,
            PixiToml,
            PixiWorkspace,
            WorkflowArtifacts,
        )

        # Create minimal artifacts
        spec = Spec(
            id="test",
            name="Test",
            description="Test",
            requirements=[],
            channels=[],
            workflow=[],
        )

        dags = Dags(
            **{
                "__init__.py": "",
                "jupytext.py": "",
                "run_async_mock_io.py": "",
                "run_async.py": "",
                "run_sequential_mock_io.py": "",
                "run_sequential.py": "",
            }
        )
        package = PackageDirectory(
            dags=dags,
            **{
                "rjsf.json": {},
                "params.json": {},
                "params.py": "",
                "formdata.py": "",
                "cli.py": "",
                "dispatch.py": "",
                "metadata.py": "",
                "response.py": "",
                "__init__.py": "",
            },
        )
        pixi_toml = PixiToml(workspace=PixiWorkspace(name="test"), dependencies={})

        artifacts = WorkflowArtifacts(
            spec_relpath="spec.yaml",
            release_name="wf-test",
            package_name="wf_test",
            package=package,
            tests=None,  # type: ignore[arg-type]
            pydot_graph=None,  # type: ignore[arg-type]
            **{"pixi.toml": pixi_toml, "Dockerfile": "", ".dockerignore": ""},
        )

        fingerprint = Fingerprint(spec=spec, wa=artifacts)
        assert fingerprint.spec_sha256  # Should generate a hash
        assert fingerprint.params_sha256  # Should generate a hash
        assert fingerprint.artifacts_sha256_basic  # Should generate a hash

    def test_fingerprint_to_yaml(self):
        """Test fingerprint YAML serialization."""
        from wt_compiler.artifacts import (
            Dags,
            PackageDirectory,
            PixiToml,
            PixiWorkspace,
            WorkflowArtifacts,
        )

        spec = Spec(
            id="test",
            name="Test",
            description="Test",
            requirements=[],
            channels=[],
            workflow=[],
        )

        dags = Dags(
            **{
                "__init__.py": "",
                "jupytext.py": "",
                "run_async_mock_io.py": "",
                "run_async.py": "",
                "run_sequential_mock_io.py": "",
                "run_sequential.py": "",
            }
        )
        package = PackageDirectory(
            dags=dags,
            **{
                "rjsf.json": {},
                "params.json": {},
                "params.py": "",
                "formdata.py": "",
                "cli.py": "",
                "dispatch.py": "",
                "metadata.py": "",
                "response.py": "",
                "__init__.py": "",
            },
        )
        pixi_toml = PixiToml(workspace=PixiWorkspace(name="test"), dependencies={})

        artifacts = WorkflowArtifacts(
            spec_relpath="spec.yaml",
            release_name="wf-test",
            package_name="wf_test",
            package=package,
            tests=None,  # type: ignore[arg-type]
            pydot_graph=None,  # type: ignore[arg-type]
            **{"pixi.toml": pixi_toml, "Dockerfile": "", ".dockerignore": ""},
        )

        fingerprint = Fingerprint(spec=spec, wa=artifacts)
        yaml_str = fingerprint.to_yaml()

        assert "spec_sha256" in yaml_str
        assert "params_sha256" in yaml_str
        assert "artifacts_sha256_basic" in yaml_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
