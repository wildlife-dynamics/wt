"""Tests for compiler.py - DagCompiler functionality."""

import email.parser
import subprocess
import zipfile
from unittest.mock import MagicMock

import pytest
import ruamel.yaml

from wt_compiler.artifacts import (
    Dags,
    PackageDirectory,
    PixiToml,
    PixiWorkspace,
    Tests,
    WorkflowArtifacts,
)
from wt_compiler.compiler import (
    DagCompiler,
    Fingerprint,
    ParsedRequirements,
    _build_installed_requirements,
    _load_default_injections,
    _parse_requirements_from_yaml,
    _remove_functionally_irrelevant_keys,
    compute_merged_default_feature,
)
from wt_compiler.env_overrides import load_env_overrides_file
from wt_compiler.requirements import WT_LOCAL_CHANNEL
from wt_compiler.spec import (
    KnownTask,
    Spec,
    SpecRequirement,
    TaskInstance,
    TaskTag,
    known_tasks,
)


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
        # Create a minimal spec (spec ID must be valid Python identifier)
        spec = Spec(
            id="my_workflow",
            requirements=[],
            workflow=[],
        )
        compiler = DagCompiler(spec=spec)
        # Release name: prefix-{id with _ replaced by -}-workflow
        assert compiler.release_name == "wt-my-workflow-workflow"
        # Package name: release name with - replaced by _
        assert compiler.package_name == "wt_my_workflow_workflow"

    def test_custom_pkg_name_prefix(self):
        """Test custom package name prefix."""
        spec = Spec(
            id="my_workflow",
            requirements=[],
            workflow=[],
        )
        compiler = DagCompiler(
            spec=spec,
            pkg_name_prefix="custom",
        )
        assert compiler.release_name == "custom-my-workflow-workflow"
        assert compiler.package_name == "custom_my_workflow_workflow"

    def test_per_taskinstance_omit_args(self):
        """Test omit_args calculation for task instances."""
        # Register tasks in the global registry
        task1 = KnownTask(
            importable_reference="mod.func1",
            json_schema={"properties": {"x": {"type": "integer"}}},
        )
        task2 = KnownTask(
            importable_reference="mod.func2",
            json_schema={"properties": {"y": {"type": "integer"}}},
        )
        known_tasks["func1"] = {"mod": task1}
        known_tasks["func2"] = {"mod": task2}

        try:
            instance1 = TaskInstance(
                id="task1",
                name="Task 1",
                task="mod.func1",
                partial={"x": 10},
            )
            instance2 = TaskInstance(
                id="task2",
                name="Task 2",
                task="mod.func2",
                partial={},
            )

            spec = Spec(
                id="test_spec",
                requirements=[],
                workflow=[instance1, instance2],
            )
            compiler = DagCompiler(spec=spec)

            omit_args = compiler.per_taskinstance_omit_args
            assert "task1" in omit_args
            assert "return" in omit_args["task1"]
            assert "x" in omit_args["task1"]  # x is in partial
        finally:
            known_tasks.clear()

    def test_build_pydot_graph(self):
        """Test building a pydot graph from spec."""
        task1 = KnownTask(
            importable_reference="mod.func1",
            json_schema={"properties": {}},
        )
        known_tasks["func1"] = {"mod": task1}

        try:
            instance1 = TaskInstance(
                id="task1",
                name="Task 1",
                task="mod.func1",
            )

            spec = Spec(
                id="test_spec",
                requirements=[],
                workflow=[instance1],
            )
            compiler = DagCompiler(spec=spec)

            graph = compiler.build_pydot_graph()
            assert graph.get_name() == "test_spec"
            # Check that nodes were created
            nodes = graph.get_nodes()
            assert len(nodes) > 0
        finally:
            known_tasks.clear()

    def test_get_pixi_toml(self, merged_default_feature):
        """Test pixi.toml generation."""
        spec = Spec(
            id="test_spec",
            requirements=[
                SpecRequirement(requirement="python>=3.10"),
                SpecRequirement(requirement="pandas>=2.0"),
            ],
            workflow=[],
        )
        compiler = DagCompiler(spec=spec)
        pixi_toml = compiler.get_pixi_toml(merged_default_feature=merged_default_feature)

        # Workspace name should be the release name (underscores replaced by dashes)
        assert pixi_toml.workspace.name == "wt-test-spec-workflow"
        assert "python" in pixi_toml.dependencies
        assert "pandas" in pixi_toml.dependencies

        # Check system requirements
        assert pixi_toml.system_requirements == {"linux": "4.4.0"}

        # Check environments
        assert "default" in pixi_toml.environments
        assert "runner" in pixi_toml.environments
        assert "test" in pixi_toml.environments

        # Check features
        assert "runner" in pixi_toml.feature
        assert "test" in pixi_toml.feature

        # Check tasks (task name is the release_name)
        assert "wt-test-spec-workflow" in pixi_toml.tasks

    def test_get_pixi_toml_with_wt_registry(self, merged_default_feature):
        """Test pixi.toml generation with wt-registry dependency."""

        spec = Spec(
            id="my_workflow",
            requirements=[
                SpecRequirement(requirement=f"{WT_LOCAL_CHANNEL.base_url}::wt-registry>=0.1.0"),
            ],
            workflow=[],
        )
        compiler = DagCompiler(spec=spec)
        pixi_toml = compiler.get_pixi_toml(merged_default_feature=merged_default_feature)

        # Runner feature should have wt-runner
        assert "runner" in pixi_toml.feature
        assert "wt-runner" in pixi_toml.feature["runner"].dependencies

        # Test feature should have test dependencies
        assert "test" in pixi_toml.feature
        assert "pytest" in pixi_toml.feature["test"].dependencies
        assert "pandas" in pixi_toml.feature["test"].dependencies

        # Test tasks should exist
        assert "test-all" in pixi_toml.feature["test"].tasks
        assert "playwright-install" in pixi_toml.feature["test"].tasks

    def test_get_pixi_toml_with_pypi_deps(self, merged_default_feature):
        """Test pixi.toml generation with mixed conda and pypi requirements."""
        spec = Spec(
            id="test_spec",
            requirements=[
                {"requirement": "python>=3.10"},
                {"name": "foo", "git": "https://github.com/org/foo.git", "tag": "v1.0"},
                {"name": "bar", "path": "/opt/bar", "editable": True},
            ],
            workflow=[],
        )
        compiler = DagCompiler(spec=spec)
        pixi_toml = compiler.get_pixi_toml(merged_default_feature=merged_default_feature)

        # Conda deps should be in dependencies
        assert "python" in pixi_toml.dependencies

        # PyPI deps should be in pypi_dependencies
        assert "foo" in pixi_toml.pypi_dependencies
        assert pixi_toml.pypi_dependencies["foo"]["git"] == "https://github.com/org/foo.git"
        assert pixi_toml.pypi_dependencies["foo"]["tag"] == "v1.0"
        assert "bar" in pixi_toml.pypi_dependencies
        assert pixi_toml.pypi_dependencies["bar"]["path"] == "/opt/bar"
        assert pixi_toml.pypi_dependencies["bar"]["editable"] is True

    def test_get_pixi_toml_no_pypi_deps(self, merged_default_feature):
        """Test pixi.toml with no pypi deps doesn't include pypi-dependencies section."""
        spec = Spec(
            id="test_spec",
            requirements=[{"requirement": "python>=3.10"}],
            workflow=[],
        )
        compiler = DagCompiler(spec=spec)
        pixi_toml = compiler.get_pixi_toml(merged_default_feature=merged_default_feature)

        assert pixi_toml.pypi_dependencies == {}
        toml_str = pixi_toml.to_toml()
        assert "pypi-dependencies" not in toml_str

    def test_get_pixi_toml_with_env_overrides_default_pypi(self, tmp_path):
        """Override file replaces auto-injected wt-task in default deps with a pypi entry."""
        wt_task_dir = tmp_path / "wt-task"
        wt_task_dir.mkdir()
        override_file = tmp_path / "wt-compiler-env-overrides.toml"
        override_file.write_text(
            '[feature.default.pypi-dependencies]\nwt-task = { path = "wt-task", editable = true }\n'
        )
        env_overrides = load_env_overrides_file(override_file)

        spec = Spec(
            id="test_spec",
            requirements=[{"requirement": "python>=3.10"}],
            workflow=[],
        )
        merged_default = compute_merged_default_feature(
            _load_default_injections(),
            spec_supplied_names={"python"},
            env_overrides=env_overrides,
        )
        compiler = DagCompiler(
            spec=spec,
            env_overrides=env_overrides,
        )
        pixi_toml = compiler.get_pixi_toml(merged_default_feature=merged_default)

        # wt-task is now in pypi_dependencies, not in conda dependencies
        assert "wt-task" in pixi_toml.pypi_dependencies
        assert pixi_toml.pypi_dependencies["wt-task"]["path"] == str(wt_task_dir)
        assert pixi_toml.pypi_dependencies["wt-task"]["editable"] is True
        assert "wt-task" not in pixi_toml.dependencies

    def test_get_pixi_toml_with_env_overrides_runner_pypi(self, tmp_path, merged_default_feature):
        """Override file replaces auto-injected wt-runner in runner deps with a pypi entry."""
        wt_runner_dir = tmp_path / "wt-runner"
        wt_runner_dir.mkdir()
        override_file = tmp_path / "wt-compiler-env-overrides.toml"
        override_file.write_text(
            "[feature.runner.pypi-dependencies]\n"
            'wt-runner = { path = "wt-runner", editable = true, extras = ["gcp"] }\n'
        )
        env_overrides = load_env_overrides_file(override_file)

        spec = Spec(
            id="test_spec",
            requirements=[{"requirement": "python>=3.10"}],
            workflow=[],
        )
        compiler = DagCompiler(
            spec=spec,
            env_overrides=env_overrides,
        )
        pixi_toml = compiler.get_pixi_toml(merged_default_feature=merged_default_feature)

        runner_feature = pixi_toml.feature["runner"]
        assert "wt-runner" in runner_feature.pypi_dependencies
        assert runner_feature.pypi_dependencies["wt-runner"]["path"] == str(wt_runner_dir)
        assert runner_feature.pypi_dependencies["wt-runner"]["extras"] == ["gcp"]
        assert "wt-runner" not in runner_feature.dependencies

    def test_get_pixi_toml_defaults_always_injected(self, merged_default_feature):
        """The bundled default-env-injections.toml is always layered in."""
        spec = Spec(
            id="test_spec",
            requirements=[
                {"name": "foo", "git": "https://github.com/org/foo.git", "tag": "v1.0"},
            ],
            workflow=[],
        )
        compiler = DagCompiler(spec=spec)
        pixi_toml = compiler.get_pixi_toml(merged_default_feature=merged_default_feature)

        # Defaults always provide wt-task in the default feature and wt-runner
        # in the runner feature.
        assert "wt-task" in pixi_toml.dependencies
        assert "wt-runner" in pixi_toml.feature["runner"].dependencies

    def test_get_pixi_toml_spec_requirements_suppress_defaults(self):
        """A spec.yaml requirements: entry with the same name suppresses the default."""
        spec = Spec(
            id="test_spec",
            requirements=[
                {"requirement": "pydantic >=2.5,<3.0"},
            ],
            workflow=[],
        )
        merged_default = compute_merged_default_feature(
            _load_default_injections(),
            spec_supplied_names={"pydantic"},
        )
        compiler = DagCompiler(spec=spec)
        pixi_toml = compiler.get_pixi_toml(merged_default_feature=merged_default)

        assert "pydantic" in pixi_toml.dependencies
        # Spec-supplied version wins over the bundled default's >=2.0,<3.0.
        assert ">=2.5" in str(pixi_toml.dependencies["pydantic"].version)

    def test_variant_suffix_applied_after_override_merge(self, tmp_path):
        """A pypi override of wt-task suppresses wt-task-gcp under --variant=gcp.

        The variant suffix is applied to the merged result, not to the
        bundled base. So an env-overrides entry for ``wt-task`` (path
        source, with ``extras = ["gcp"]``) displaces the bundled
        ``wt-task`` entry by un-suffixed name BEFORE the suffix rewrite
        — preventing both the path source and a phantom ``wt-task-gcp``
        conda entry from landing in the compiled pixi.toml.
        """
        wt_task_dir = tmp_path / "wt-task"
        wt_task_dir.mkdir()
        override_file = tmp_path / "wt-compiler-env-overrides.toml"
        override_file.write_text(
            "[feature.default.pypi-dependencies]\n"
            f'wt-task = {{ path = "{wt_task_dir}", extras = ["gcp"] }}\n'
        )
        env_overrides = load_env_overrides_file(override_file)

        spec = Spec(
            id="test_spec",
            requirements=[{"requirement": "python>=3.10"}],
            workflow=[],
        )
        merged_default = compute_merged_default_feature(
            _load_default_injections(),
            spec_supplied_names={"python"},
            env_overrides=env_overrides,
        )
        compiler = DagCompiler(
            spec=spec,
            env_overrides=env_overrides,
            variant="gcp",
        )
        pixi_toml = compiler.get_pixi_toml(merged_default_feature=merged_default)

        # The pypi-side path entry is what landed.
        assert "wt-task" in pixi_toml.pypi_dependencies
        assert pixi_toml.pypi_dependencies["wt-task"]["extras"] == ["gcp"]
        # The conda side has neither wt-task nor wt-task-gcp — the override
        # displaces the bundled entry before the suffix rewrite.
        assert "wt-task" not in pixi_toml.dependencies
        assert "wt-task-gcp" not in pixi_toml.dependencies

    def test_variant_suffix_without_override_still_applied(self, merged_default_feature):
        """Without an override, --variant=gcp still rewrites wt-task to wt-task-gcp."""
        spec = Spec(
            id="test_spec",
            requirements=[{"requirement": "python>=3.10"}],
            workflow=[],
        )
        compiler = DagCompiler(spec=spec, variant="gcp")
        pixi_toml = compiler.get_pixi_toml(merged_default_feature=merged_default_feature)

        assert "wt-task-gcp" in pixi_toml.dependencies
        assert "wt-task" not in pixi_toml.dependencies
        assert "wt-runner-gcp" in pixi_toml.feature["runner"].dependencies

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
        known_tasks["func"] = {"mod": task}

        try:
            instance = TaskInstance(
                id="my_task",
                name="My Task",
                task="mod.func",
            )

            props, defs = DagCompiler._props_and_defs_from_task_instance(instance, omit_args=["y"])

            assert "my_task" in props
            assert "x" in props["my_task"]["properties"]
            assert "y" not in props["my_task"]["properties"]  # Omitted
            assert "z" in props["my_task"]["properties"]
            assert "MyType" in defs
        finally:
            known_tasks.clear()


class TestParseRequirementsFromYaml:
    """Tests for _parse_requirements_from_yaml with mixed requirements."""

    def test_conda_only(self, tmp_path):
        """Test parsing YAML with only conda requirements."""

        yaml_file = tmp_path / "spec.yaml"
        yaml = ruamel.yaml.YAML()
        yaml.dump(
            {
                "id": "test",
                "requirements": [
                    {"requirement": "python>=3.10"},
                    {"requirement": "pandas>=2.0"},
                ],
                "workflow": [],
            },
            yaml_file.open("w"),
        )
        result = _parse_requirements_from_yaml(yaml_file)
        assert isinstance(result, ParsedRequirements)
        assert len(result.conda) == 2
        assert len(result.pypi) == 0

    def test_mixed_requirements(self, tmp_path):
        """Test parsing YAML with mixed conda and pypi requirements."""

        yaml_file = tmp_path / "spec.yaml"
        yaml = ruamel.yaml.YAML()
        yaml.dump(
            {
                "id": "test",
                "requirements": [
                    {"requirement": "python>=3.10"},
                    {"name": "foo", "git": "https://github.com/org/foo.git"},
                    {"name": "bar", "path": "/opt/bar", "editable": True},
                ],
                "workflow": [],
            },
            yaml_file.open("w"),
        )
        result = _parse_requirements_from_yaml(yaml_file)
        assert len(result.conda) == 1
        assert len(result.pypi) == 2
        assert result.pypi[0].name == "foo"
        assert result.pypi[1].name == "bar"

    def test_pypi_only(self, tmp_path):
        """Test parsing YAML with only pypi requirements."""

        yaml_file = tmp_path / "spec.yaml"
        yaml = ruamel.yaml.YAML()
        yaml.dump(
            {
                "id": "test",
                "requirements": [
                    {"name": "foo", "url": "https://example.com/foo.whl"},
                ],
                "workflow": [],
            },
            yaml_file.open("w"),
        )
        result = _parse_requirements_from_yaml(yaml_file)
        assert len(result.conda) == 0
        assert len(result.pypi) == 1


class TestFingerprint:
    """Tests for Fingerprint class."""

    def test_fingerprint_creation(self):
        """Test creating a fingerprint."""

        # Create minimal artifacts
        spec = Spec(
            id="test",
            requirements=[],
            workflow=[],
        )

        dags = Dags(
            **{
                "__init__.py": "",
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
        tests = Tests(
            **{
                "conftest.py": "",
                "test_metadata.py": "",
                "test_results.py": "",
            }
        )

        artifacts = WorkflowArtifacts(
            spec_relpath="spec.yaml",
            release_name="wf-test",
            package_name="wf_test",
            package=package,
            tests=tests,
            pydot_graph=None,
            **{
                "pixi.toml": pixi_toml,
                "Dockerfile": "",
                ".dockerignore": "",
                "pyproject.toml": "",
                "hatch_build.py": "",
            },
        )

        fingerprint = Fingerprint(spec=spec, wa=artifacts)
        assert fingerprint.spec_sha256  # Should generate a hash
        assert fingerprint.params_sha256  # Should generate a hash
        assert fingerprint.artifacts_sha256_basic  # Should generate a hash

    def test_fingerprint_to_yaml(self):
        """Test fingerprint YAML serialization."""

        spec = Spec(
            id="test",
            requirements=[],
            workflow=[],
        )

        dags = Dags(
            **{
                "__init__.py": "",
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
        tests = Tests(
            **{
                "conftest.py": "",
                "test_metadata.py": "",
                "test_results.py": "",
            }
        )

        artifacts = WorkflowArtifacts(
            spec_relpath="spec.yaml",
            release_name="wf-test",
            package_name="wf_test",
            package=package,
            tests=tests,
            pydot_graph=None,
            **{
                "pixi.toml": pixi_toml,
                "Dockerfile": "",
                ".dockerignore": "",
                "pyproject.toml": "",
                "hatch_build.py": "",
            },
        )

        fingerprint = Fingerprint(spec=spec, wa=artifacts)
        yaml_str = fingerprint.to_yaml()

        assert "spec_sha256" in yaml_str
        assert "params_sha256" in yaml_str
        assert "artifacts_sha256_basic" in yaml_str

    def test_fingerprint_with_installed_requirements(self):
        """Test fingerprint YAML includes installed_requirements in block style."""

        spec = Spec(
            id="test",
            requirements=[],
            workflow=[],
        )

        dags = Dags(
            **{
                "__init__.py": "",
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
        tests = Tests(
            **{
                "conftest.py": "",
                "test_metadata.py": "",
                "test_results.py": "",
            }
        )

        artifacts = WorkflowArtifacts(
            spec_relpath="spec.yaml",
            release_name="wf-test",
            package_name="wf_test",
            package=package,
            tests=tests,
            pydot_graph=None,
            **{
                "pixi.toml": pixi_toml,
                "Dockerfile": "",
                ".dockerignore": "",
                "pyproject.toml": "",
                "hatch_build.py": "",
            },
        )

        installed_reqs = [
            SpecRequirement(name="pandas", version="==2.2.3", channel="conda-forge"),
            SpecRequirement(name="numpy", version="==1.26.4", channel="conda-forge"),
        ]

        fingerprint = Fingerprint(spec=spec, wa=artifacts, installed_requirements=installed_reqs)
        yaml_str = fingerprint.to_yaml()

        # Should include installed_requirements key
        assert "installed_requirements:" in yaml_str
        # Top-level fingerprint keys should be in block-style (not flow-style `{key: ...}`)
        # The first line should NOT start with `{`
        assert not yaml_str.startswith("{")
        # Should contain the package names
        assert "pandas" in yaml_str
        assert "numpy" in yaml_str

    def test_fingerprint_default_empty_installed_requirements(self):
        """Test fingerprint defaults to empty installed_requirements."""

        spec = Spec(
            id="test",
            requirements=[],
            workflow=[],
        )

        dags = Dags(
            **{
                "__init__.py": "",
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
        tests = Tests(
            **{
                "conftest.py": "",
                "test_metadata.py": "",
                "test_results.py": "",
            }
        )

        artifacts = WorkflowArtifacts(
            spec_relpath="spec.yaml",
            release_name="wf-test",
            package_name="wf_test",
            package=package,
            tests=tests,
            pydot_graph=None,
            **{
                "pixi.toml": pixi_toml,
                "Dockerfile": "",
                ".dockerignore": "",
                "pyproject.toml": "",
                "hatch_build.py": "",
            },
        )

        # No installed_requirements provided — should default to empty list
        fingerprint = Fingerprint(spec=spec, wa=artifacts)
        assert fingerprint.installed_requirements == []
        yaml_str = fingerprint.to_yaml()
        assert "installed_requirements: []" in yaml_str


class TestBuildInstalledRequirements:
    """Tests for _build_installed_requirements helper."""

    def test_matches_spec_requirements_to_records(self):
        """Test that spec requirements are matched to solved records."""

        # Create mock records mimicking RepoDataRecord
        record1 = MagicMock()
        record1.name.normalized = "pandas"
        record1.version = MagicMock(__str__=lambda self: "2.2.3")
        record1.channel = "https://conda.anaconda.org/conda-forge/"

        record2 = MagicMock()
        record2.name.normalized = "numpy"
        record2.version = MagicMock(__str__=lambda self: "1.26.4")
        record2.channel = "https://conda.anaconda.org/conda-forge/"

        records = [record1, record2]

        spec_reqs = [
            SpecRequirement(name="pandas", version=">=2.0", channel="conda-forge"),
            SpecRequirement(name="numpy", version=">=1.20", channel="conda-forge"),
        ]

        installed = _build_installed_requirements(spec_reqs, records)

        assert len(installed) == 2
        assert installed[0].name == "pandas"
        assert str(installed[0].version.version) == "==2.2.3"
        assert installed[1].name == "numpy"
        assert str(installed[1].version.version) == "==1.26.4"

    def test_skips_unresolved_requirements(self):
        """Test that requirements not found in records are skipped."""

        record = MagicMock()
        record.name.normalized = "pandas"
        record.version = MagicMock(__str__=lambda self: "2.2.3")
        record.channel = "https://conda.anaconda.org/conda-forge/"

        spec_reqs = [
            SpecRequirement(name="pandas", version=">=2.0", channel="conda-forge"),
            SpecRequirement(name="missing-pkg", version=">=1.0", channel="conda-forge"),
        ]

        installed = _build_installed_requirements(spec_reqs, [record])

        assert len(installed) == 1
        assert installed[0].name == "pandas"

    def test_empty_records(self):
        """Test with empty records list."""
        spec_reqs = [
            SpecRequirement(name="pandas", version=">=2.0", channel="conda-forge"),
        ]

        installed = _build_installed_requirements(spec_reqs, [])
        assert len(installed) == 0

    def test_empty_requirements(self):
        """Test with empty requirements list."""

        record = MagicMock()
        record.name.normalized = "pandas"
        record.version = MagicMock(__str__=lambda self: "2.2.3")
        record.channel = "https://conda.anaconda.org/conda-forge/"

        installed = _build_installed_requirements([], [record])
        assert len(installed) == 0


class TestRenderDag:
    """Tests for DagCompiler.render_dag with validate skipping for mocked IO tasks."""

    def _setup_tasks_and_compiler(self):
        """Register an IO task and a non-IO task, build a Spec and DagCompiler.

        Returns:
            DagCompiler instance with two tasks (one IO-tagged, one not).
        """

        io_task = KnownTask(
            importable_reference="mymod.io_func",
            tags=[TaskTag.io],
            json_schema={"properties": {"url": {"type": "string"}}},
        )
        non_io_task = KnownTask(
            importable_reference="mymod.non_io_func",
            json_schema={"properties": {"data": {"type": "string"}}},
        )
        known_tasks["io_func"] = {"mymod": io_task}
        known_tasks["non_io_func"] = {"mymod": non_io_task}

        spec = Spec(
            id="test_validate",
            requirements=[],
            workflow=[
                TaskInstance(
                    id="fetch_data",
                    name="Fetch Data",
                    task="mymod.io_func",
                ),
                TaskInstance(
                    id="process_data",
                    name="Process Data",
                    task="mymod.non_io_func",
                ),
            ],
        )
        return DagCompiler(spec=spec)

    def test_sequential_mock_io_skips_validate_for_io_tasks(self):
        """With mock_io=True, IO tasks should NOT have .validate(), non-IO tasks should."""
        try:
            compiler = self._setup_tasks_and_compiler()
            rendered = compiler.render_dag("sequential", mock_io=True)

            # Non-IO task should still have .validate()
            assert ".validate()" in rendered

            # But only once — the IO task should not have .validate()
            assert rendered.count(".validate()") == 1

            # The omitted-validate comment should appear for the IO task
            assert "validation omitted for mocked IO task" in rendered
        finally:
            known_tasks.clear()

    def test_sequential_no_mock_io_validates_all_tasks(self):
        """With mock_io=False, ALL tasks should have .validate()."""
        try:
            compiler = self._setup_tasks_and_compiler()
            rendered = compiler.render_dag("sequential", mock_io=False)

            # Both tasks should have .validate()
            assert rendered.count(".validate()") == 2

            # No omitted-validate comment
            assert "validation omitted for mocked IO task" not in rendered
        finally:
            known_tasks.clear()

    def test_async_mock_io_skips_validate_for_io_tasks(self):
        """With mock_io=True, async IO tasks should NOT have .validate()."""
        try:
            compiler = self._setup_tasks_and_compiler()
            rendered = compiler.render_dag("async", mock_io=True)

            # Non-IO task should still have .validate()
            assert ".validate()" in rendered

            # But only once — the IO task should not have .validate()
            assert rendered.count(".validate()") == 1

            # The omitted-validate comment should appear for the IO task
            assert "validation omitted for mocked IO task" in rendered
        finally:
            known_tasks.clear()

    def test_async_no_mock_io_validates_all_tasks(self):
        """With mock_io=False, async ALL tasks should have .validate()."""
        try:
            compiler = self._setup_tasks_and_compiler()
            rendered = compiler.render_dag("async", mock_io=False)

            # Both tasks should have .validate()
            assert rendered.count(".validate()") == 2

            # No omitted-validate comment
            assert "validation omitted for mocked IO task" not in rendered
        finally:
            known_tasks.clear()

    def _setup_realistic_workflow(self):
        """Register 4 non-IO + 1 IO task with a dependency chain.

        Returns:
            DagCompiler instance with 5 tasks (only load_data is IO-tagged).
        """

        load_data = KnownTask(
            importable_reference="mymod.load_data",
            tags=[TaskTag.io],
            json_schema={"properties": {"url": {"type": "string"}}},
        )
        transform = KnownTask(
            importable_reference="mymod.transform",
            json_schema={"properties": {"data": {"type": "string"}}},
        )
        validate_data = KnownTask(
            importable_reference="mymod.validate_data",
            json_schema={"properties": {"data": {"type": "string"}}},
        )
        aggregate = KnownTask(
            importable_reference="mymod.aggregate",
            json_schema={"properties": {"data": {"type": "string"}}},
        )
        render_output = KnownTask(
            importable_reference="mymod.render_output",
            json_schema={"properties": {"data": {"type": "string"}}},
        )
        known_tasks["load_data"] = {"mymod": load_data}
        known_tasks["transform"] = {"mymod": transform}
        known_tasks["validate_data"] = {"mymod": validate_data}
        known_tasks["aggregate"] = {"mymod": aggregate}
        known_tasks["render_output"] = {"mymod": render_output}

        spec = Spec(
            id="realistic_wf",
            requirements=[],
            workflow=[
                TaskInstance(id="step_load", name="Load", task="mymod.load_data"),
                TaskInstance(
                    id="step_transform",
                    name="Transform",
                    task="mymod.transform",
                    partial={"data": "${{ workflow.step_load.return }}"},
                ),
                TaskInstance(
                    id="step_validate",
                    name="Validate",
                    task="mymod.validate_data",
                    partial={"data": "${{ workflow.step_transform.return }}"},
                ),
                TaskInstance(
                    id="step_aggregate",
                    name="Aggregate",
                    task="mymod.aggregate",
                    partial={"data": "${{ workflow.step_validate.return }}"},
                ),
                TaskInstance(
                    id="step_render",
                    name="Render",
                    task="mymod.render_output",
                    partial={"data": "${{ workflow.step_aggregate.return }}"},
                ),
            ],
        )
        return DagCompiler(spec=spec)

    def test_sequential_realistic_validate_count(self):
        """mock_io=True: 4 .validate() calls and 1 'validation omitted' comment."""
        try:
            compiler = self._setup_realistic_workflow()
            rendered = compiler.render_dag("sequential", mock_io=True)

            assert rendered.count(".validate()") == 4
            assert rendered.count("validation omitted for mocked IO task") == 1
        finally:
            known_tasks.clear()

    def test_async_realistic_validate_count(self):
        """mock_io=True async: 4 .validate() calls and 1 'validation omitted' comment."""
        try:
            compiler = self._setup_realistic_workflow()
            rendered = compiler.render_dag("async", mock_io=True)

            assert rendered.count(".validate()") == 4
            assert rendered.count("validation omitted for mocked IO task") == 1
        finally:
            known_tasks.clear()

    def test_sequential_no_mock_realistic_validates_all(self):
        """mock_io=False: all 5 tasks should have .validate()."""
        try:
            compiler = self._setup_realistic_workflow()
            rendered = compiler.render_dag("sequential", mock_io=False)

            assert rendered.count(".validate()") == 5
            assert "validation omitted for mocked IO task" not in rendered
        finally:
            known_tasks.clear()

    def test_is_mocked_flag_in_serialized_dag_config(self):
        """Inspect get_dag_config() output: is_mocked=True only for the IO task."""
        try:
            compiler = self._setup_realistic_workflow()
            config = compiler.get_dag_config("sequential", mock_io=True)

            tasks = config["spec"]["flat_workflow"]
            mocked_ids = [
                t["id"] for t in tasks if t["known_task"]["importable_reference"]["is_mocked"]
            ]
            assert mocked_ids == ["step_load"]

            not_mocked_ids = [
                t["id"] for t in tasks if not t["known_task"]["importable_reference"]["is_mocked"]
            ]
            assert set(not_mocked_ids) == {
                "step_transform",
                "step_validate",
                "step_aggregate",
                "step_render",
            }
        finally:
            known_tasks.clear()

    def test_is_mocked_flag_false_when_mock_io_disabled(self):
        """All tasks have is_mocked=False when mock_io=False."""
        try:
            compiler = self._setup_realistic_workflow()
            config = compiler.get_dag_config("sequential", mock_io=False)

            tasks = config["spec"]["flat_workflow"]
            assert all(t["known_task"]["importable_reference"]["is_mocked"] is False for t in tasks)
        finally:
            known_tasks.clear()


class TestPyprojectTomlArtifact:
    """Tests for pyproject.toml and hatch_build.py in compiled artifacts."""

    def _compile_minimal_workflow(self):
        """Compile a minimal workflow and return the artifacts."""
        task = KnownTask(
            importable_reference="mymod.my_func",
            json_schema={"properties": {"x": {"type": "integer"}}},
        )
        known_tasks["my_func"] = {"mymod": task}
        try:
            spec = Spec(
                id="test_pyproject",
                requirements=[],
                workflow=[
                    TaskInstance(
                        id="step_one",
                        name="Step One",
                        task="mymod.my_func",
                    ),
                ],
            )
            compiler = DagCompiler(
                spec=spec,
                wt_runner_channel="https://repo.prefix.dev/ecoscope-workflows/",
            )
            return compiler.compile(spec_relpath="spec.yaml")
        finally:
            known_tasks.clear()

    def test_compile_produces_pyproject_toml_with_release_name(self):
        """Compilation produces a pyproject.toml containing the release name."""
        artifacts = self._compile_minimal_workflow()
        assert 'name = "wt-test-pyproject-workflow"' in artifacts.pyproject_toml
        assert 'dynamic = ["version"]' in artifacts.pyproject_toml

    def test_compile_produces_pyproject_toml_with_script_entry(self):
        """Compilation produces a pyproject.toml with the correct script entry point."""
        artifacts = self._compile_minimal_workflow()
        assert (
            'wt-test-pyproject-workflow = "wt_test_pyproject_workflow.cli:cli"'
            in artifacts.pyproject_toml
        )

    def test_compile_produces_pyproject_toml_with_hatch_hook(self):
        """Compilation produces a pyproject.toml referencing the custom Hatch hook."""
        artifacts = self._compile_minimal_workflow()
        assert "[tool.hatch.metadata.hooks.custom]" in artifacts.pyproject_toml
        assert 'path = "hatch_build.py"' in artifacts.pyproject_toml

    def test_compile_produces_hatch_build_py_with_version_hook(self):
        """Compilation produces a hatch_build.py containing VersionYamlHook."""
        artifacts = self._compile_minimal_workflow()
        assert "class VersionYamlHook" in artifacts.hatch_build_py
        assert "VERSION.yaml" in artifacts.hatch_build_py

    def test_pyproject_and_hatch_build_affect_fingerprint(self):
        """Changing pyproject_toml or hatch_build_py changes both fingerprint hashes."""
        artifacts = self._compile_minimal_workflow()

        spec = Spec(id="test_pyproject", requirements=[], workflow=[])
        fp_original = Fingerprint(spec=spec, wa=artifacts)
        original_basic = fp_original.artifacts_sha256_basic
        original_strict = fp_original.artifacts_sha256_strict

        # Mutate pyproject_toml
        object.__setattr__(artifacts, "pyproject_toml", artifacts.pyproject_toml + "\n# changed")
        fp_pyproject = Fingerprint(spec=spec, wa=artifacts)
        assert fp_pyproject.artifacts_sha256_basic != original_basic
        assert fp_pyproject.artifacts_sha256_strict != original_strict

        # Reset pyproject_toml and mutate hatch_build_py
        artifacts = self._compile_minimal_workflow()
        object.__setattr__(artifacts, "hatch_build_py", artifacts.hatch_build_py + "\n# changed")
        fp_hatch = Fingerprint(spec=spec, wa=artifacts)
        assert fp_hatch.artifacts_sha256_basic != original_basic
        assert fp_hatch.artifacts_sha256_strict != original_strict


class TestHatchDynamicVersion:
    """End-to-end: pyproject.toml + hatch_build.py resolve version from VERSION.yaml."""

    @pytest.mark.slow
    def test_hatch_dynamic_version_resolves_from_version_yaml(self, tmp_path, monkeypatch):
        """Build a wheel from the compiled release dir and verify VERSION.yaml-sourced version."""
        task = KnownTask(
            importable_reference="mymod.my_func",
            json_schema={"properties": {"x": {"type": "integer"}}},
        )
        known_tasks["my_func"] = {"mymod": task}
        try:
            spec = Spec(
                id="hatch_e2e",
                requirements=[],
                workflow=[
                    TaskInstance(
                        id="step_one",
                        name="Step One",
                        task="mymod.my_func",
                    ),
                ],
            )
            compiler = DagCompiler(
                spec=spec,
                wt_runner_channel="https://repo.prefix.dev/ecoscope-workflows/",
            )
            monkeypatch.chdir(tmp_path)
            artifacts = compiler.compile(spec_relpath="spec.yaml")
            artifacts.dump()
        finally:
            known_tasks.clear()

        release_dir = tmp_path / artifacts.release_name
        dist_dir = tmp_path / "dist"

        def _build_and_get_version(build_dir, out_dir):
            """Build a wheel and extract the Version from its metadata."""
            result = subprocess.run(  # noqa: S603  # static argv; building wheel from tmp dir under our control
                ["python", "-m", "build", "--wheel", "--no-isolation", f"--outdir={out_dir}"],  # noqa: S607  # python resolved via PATH
                check=False,
                cwd=build_dir,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, f"Build failed:\n{result.stderr}"
            wheels = list(out_dir.glob("*.whl"))
            assert len(wheels) == 1, f"Expected 1 wheel, got {len(wheels)}"
            with zipfile.ZipFile(wheels[0]) as zf:
                metadata_files = [n for n in zf.namelist() if n.endswith("/METADATA")]
                assert metadata_files, "No METADATA found in wheel"
                metadata_text = zf.read(metadata_files[0]).decode()
            parser = email.parser.Parser()
            msg = parser.parsestr(metadata_text)
            return msg["Version"]

        # Default VERSION.yaml has MAJ=0, MIN=0 → version 0.0.0
        version = _build_and_get_version(release_dir, dist_dir)
        assert version == "0.0.0"

        # Rewrite VERSION.yaml and rebuild
        yaml = ruamel.yaml.YAML()
        yaml.dump(
            {"MAJ": 1, "MIN": 3, "PATCH": 7},
            (release_dir / "VERSION.yaml").open("w"),
        )
        # Clean dist for second build
        for whl in dist_dir.glob("*.whl"):
            whl.unlink()

        version = _build_and_get_version(release_dir, dist_dir)
        assert version == "1.3.7"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
