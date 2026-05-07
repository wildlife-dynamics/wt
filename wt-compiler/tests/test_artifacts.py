"""Tests for artifacts.py - artifact generation models."""

import tempfile
import warnings
from pathlib import Path
from unittest.mock import MagicMock

import pydot
import pytest

from wt_compiler.artifacts import (
    Dags,
    Feature,
    PackageDirectory,
    PixiToml,
    PixiWorkspace,
    Tests,
    WorkflowArtifacts,
)


class TestDags:
    """Tests for Dags model."""

    def test_dags_creation(self):
        """Test creating a Dags instance."""
        dags = Dags(
            **{
                "__init__.py": "# Init",
                "run_sequential_mock_io.py": "# Sequential mock",
                "run_sequential.py": "# Sequential",
            }
        )
        assert dags.init_dot_py == "# Init"


class TestPixiToml:
    """Tests for PixiToml model."""

    def test_pixi_toml_creation(self):
        """Test creating a PixiToml instance."""
        workspace = PixiWorkspace(name="test-workflow")
        pixi_toml = PixiToml(
            workspace=workspace,
            dependencies={"python": ">=3.10"},
        )
        assert pixi_toml.workspace.name == "test-workflow"
        assert "python" in pixi_toml.dependencies

    def test_pixi_toml_with_features(self):
        """Test PixiToml with features."""
        workspace = PixiWorkspace(name="test-workflow")
        feature = Feature(
            dependencies={"pandas": ">=2.0.0"},
            tasks={"test": "pytest"},
        )
        pixi_toml = PixiToml(
            workspace=workspace,
            dependencies={"python": ">=3.10"},
            feature={"dev": feature},
        )
        assert "dev" in pixi_toml.feature
        assert "pandas" in pixi_toml.feature["dev"].dependencies

    def test_pixi_toml_serialization(self):
        """Test PixiToml serialization to TOML."""
        workspace = PixiWorkspace(name="test-workflow")
        pixi_toml = PixiToml(
            workspace=workspace,
            dependencies={"python": ">=3.10"},
        )
        toml_str = pixi_toml.to_toml()
        assert "test-workflow" in toml_str
        assert "python" in toml_str

    def test_pixi_toml_roundtrip(self):
        """Test PixiToml serialization and deserialization roundtrip."""
        workspace = PixiWorkspace(name="roundtrip-test")
        original = PixiToml(
            workspace=workspace,
            dependencies={"python": ">=3.10", "numpy": ">=1.20"},
        )

        # Serialize to TOML
        toml_str = original.to_toml()

        # Write to temp file and read back
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(toml_str)
            temp_path = f.name

        try:
            loaded = PixiToml.from_file(temp_path)
            assert loaded.workspace.name == "roundtrip-test"
            assert "python" in loaded.dependencies
            assert "numpy" in loaded.dependencies
        finally:
            Path(temp_path).unlink()


    def test_pixi_toml_with_pypi_dependencies(self):
        """Test PixiToml with pypi-dependencies."""
        workspace = PixiWorkspace(name="test-workflow")
        pixi_toml = PixiToml(
            workspace=workspace,
            dependencies={"python": ">=3.10"},
            **{"pypi-dependencies": {
                "foo": {"git": "https://github.com/org/foo.git", "tag": "v1.0"},
                "bar": {"path": "./bar", "editable": True},
            }},
        )
        assert "foo" in pixi_toml.pypi_dependencies
        assert "bar" in pixi_toml.pypi_dependencies
        toml_str = pixi_toml.to_toml()
        assert "pypi-dependencies" in toml_str
        assert "foo" in toml_str

    def test_pixi_toml_empty_pypi_dependencies_excluded(self):
        """Test that empty pypi-dependencies is excluded from TOML output."""
        workspace = PixiWorkspace(name="test-workflow")
        pixi_toml = PixiToml(
            workspace=workspace,
            dependencies={"python": ">=3.10"},
        )
        toml_str = pixi_toml.to_toml()
        assert "pypi-dependencies" not in toml_str

    def test_pixi_toml_pypi_dependencies_roundtrip(self):
        """Test pypi-dependencies survive a serialization roundtrip."""
        workspace = PixiWorkspace(name="test")
        original = PixiToml(
            workspace=workspace,
            dependencies={"python": ">=3.10"},
            **{"pypi-dependencies": {
                "foo": {"git": "https://github.com/org/foo.git"},
            }},
        )
        toml_str = original.to_toml()
        loaded = PixiToml.from_text(toml_str)
        assert "foo" in loaded.pypi_dependencies
        assert loaded.pypi_dependencies["foo"]["git"] == "https://github.com/org/foo.git"


class TestWorkflowArtifacts:
    """Tests for WorkflowArtifacts model."""

    def test_workflow_artifacts_creation(self):
        """Test creating WorkflowArtifacts instance."""

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
                "params.py": "# Params",
                "formdata.py": "# FormData",
                "cli.py": "# CLI",
                "dispatch.py": "# Dispatch",
                "metadata.py": "# Metadata",
                "response.py": "# Response",
                "__init__.py": "",
            },
        )
        workspace = PixiWorkspace(name="test")
        pixi_toml = PixiToml(workspace=workspace, dependencies={})
        tests = Tests(**{
            "conftest.py": "# conftest",
            "test_metadata.py": "# test metadata",
            "test_results.py": "# test results",
        })

        artifacts = WorkflowArtifacts(
            spec_relpath="spec.yaml",
            release_name="wf-test",
            package_name="wf_test",
            package=package,
            tests=tests,
            pydot_graph=None,
            **{
                "pixi.toml": pixi_toml,
                "Dockerfile": "# Dockerfile",
                ".dockerignore": "*.pyc",
            },
        )
        assert artifacts.release_name == "wf-test"
        assert artifacts.package_name == "wf_test"

    def test_workflow_artifacts_dump_and_load(self):
        """Test WorkflowArtifacts with all required fields."""

        dags = Dags(
            **{
                "__init__.py": "# Init",
                "run_sequential_mock_io.py": "# Sequential mock",
                "run_sequential.py": "# Sequential",
            }
        )
        package = PackageDirectory(
            dags=dags,
            **{
                "rjsf.json": {"title": "Test"},
                "params.json": {"properties": {}},
                "params.py": "# Params",
                "formdata.py": "# FormData",
                "cli.py": "# CLI",
                "dispatch.py": "# Dispatch",
                "metadata.py": "# Metadata",
                "response.py": "# Response",
                "__init__.py": "",
            },
        )
        workspace = PixiWorkspace(name="test")
        pixi_toml = PixiToml(workspace=workspace, dependencies={"python": ">=3.10"})
        tests = Tests(**{
            "conftest.py": "# conftest",
            "test_metadata.py": "# test metadata",
            "test_results.py": "# test results",
        })

        artifacts = WorkflowArtifacts(
            spec_relpath="spec.yaml",
            release_name="wf-test",
            package_name="wf_test",
            package=package,
            tests=tests,
            pydot_graph=None,
            **{
                "pixi.toml": pixi_toml,
                "Dockerfile": "FROM python:3.10",
                ".dockerignore": "*.pyc",
            },
        )

        # Test model was created correctly
        assert artifacts.release_name == "wf-test"
        assert artifacts.package_name == "wf_test"
        assert artifacts.tests is not None
        # Note: dump() uses release_dir computed from spec_relpath, not a target parameter


class TestWorkflowArtifactsDump:
    """Tests for WorkflowArtifacts.dump() with missing Graphviz."""

    def _make_artifacts(self, pydot_graph=None):
        """Helper to create a minimal WorkflowArtifacts for dump testing."""

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
                "params.py": "# Params",
                "formdata.py": "# FormData",
                "cli.py": "# CLI",
                "dispatch.py": "# Dispatch",
                "metadata.py": "# Metadata",
                "response.py": "# Response",
                "__init__.py": "",
            },
        )
        workspace = PixiWorkspace(name="test")
        pixi_toml = PixiToml(workspace=workspace, dependencies={"python": ">=3.10"})
        tests = Tests(
            **{
                "conftest.py": "# conftest",
                "test_metadata.py": "# test metadata",
                "test_results.py": "# test results",
            }
        )
        return WorkflowArtifacts(
            spec_relpath="spec.yaml",
            release_name="wf-test",
            package_name="wf_test",
            package=package,
            tests=tests,
            pydot_graph=pydot_graph,
            **{
                "pixi.toml": pixi_toml,
                "Dockerfile": "FROM python:3.10",
                ".dockerignore": "*.pyc",
                "README.md": "# Test <!-- params_sha256: abc123 -->",
            },
        )

    def test_dump_succeeds_when_pydot_graph_is_none(self, tmp_path, monkeypatch):
        """Test that dump() succeeds when pydot_graph is None."""
        monkeypatch.chdir(tmp_path)
        artifacts = self._make_artifacts(pydot_graph=None)
        artifacts.dump()

        release_dir = tmp_path / "wf-test"
        assert release_dir.exists()
        assert (release_dir / "Dockerfile").exists()
        assert (release_dir / "README.md").exists()
        assert not (release_dir / "graph.png").exists()

    def test_dump_warns_when_dot_binary_missing(self, tmp_path, monkeypatch):
        """Test that dump() emits a warning when write_png raises FileNotFoundError."""

        monkeypatch.chdir(tmp_path)
        mock_graph = MagicMock(spec=pydot.Dot)
        mock_graph.write_png.side_effect = FileNotFoundError("dot not found")

        artifacts = self._make_artifacts(pydot_graph=None)
        # Bypass Pydantic validation by setting the attribute directly
        object.__setattr__(artifacts, "pydot_graph", mock_graph)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            artifacts.dump()

        release_dir = tmp_path / "wf-test"
        assert release_dir.exists()
        assert (release_dir / "Dockerfile").exists()
        assert (release_dir / "README.md").exists()
        assert not (release_dir / "graph.png").exists()

        assert len(w) > 0, "Expected a warning about missing Graphviz"
        warning_messages = [str(warning.message) for warning in w]
        assert any("Graphviz" in msg for msg in warning_messages)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
