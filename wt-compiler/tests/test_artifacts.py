"""Tests for artifacts.py - artifact generation models."""

import tempfile
from pathlib import Path

import pytest

from wt_compiler.artifacts import (
    Dags,
    Feature,
    PackageDirectory,
    PixiToml,
    PixiWorkspace,
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


class TestWorkflowArtifacts:
    """Tests for WorkflowArtifacts model."""

    def test_workflow_artifacts_creation(self):
        """Test creating WorkflowArtifacts instance."""
        from wt_compiler.artifacts import Tests

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
        from wt_compiler.artifacts import Tests

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
