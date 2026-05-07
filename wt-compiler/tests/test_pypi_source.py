"""Tests for pypi_source.py - PEP 610 detection and sibling derivation."""

import json
from unittest.mock import MagicMock, patch

import pytest

from wt_compiler.pypi_source import derive_sibling_pypi_requirement, detect_pypi_source
from wt_compiler.spec import PyPIRequirement


class TestDetectPypiSource:
    """Tests for detect_pypi_source function."""

    @patch("wt_compiler.pypi_source.subprocess.run")
    def test_detect_path_source(self, mock_run, tmp_path):
        """Test detecting a path-based (editable) install."""
        direct_url = {
            "url": "file:///home/user/wt/wt-registry",
            "dir_info": {"editable": True},
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"direct_url": direct_url, "version": "0.1.0"}),
        )

        result_url, version = detect_pypi_source("wt-registry", tmp_path / "env")

        assert result_url == direct_url
        assert version == "0.1.0"

    @patch("wt_compiler.pypi_source.subprocess.run")
    def test_detect_git_source(self, mock_run, tmp_path):
        """Test detecting a git-based install."""
        direct_url = {
            "url": "https://github.com/org/wt.git",
            "vcs_info": {
                "vcs": "git",
                "commit_id": "abc123",
                "requested_revision": "main",
            },
            "subdirectory": "wt-registry",
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"direct_url": direct_url, "version": "0.2.0"}),
        )

        result_url, version = detect_pypi_source("wt-registry", tmp_path / "env")

        assert result_url == direct_url
        assert version == "0.2.0"

    @patch("wt_compiler.pypi_source.subprocess.run")
    def test_detect_pypi_registry(self, mock_run, tmp_path):
        """Test detecting a PyPI registry install (no direct_url.json)."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"direct_url": None, "version": "1.0.0"}),
        )

        result_url, version = detect_pypi_source("wt-registry", tmp_path / "env")

        assert result_url is None
        assert version == "1.0.0"

    @patch("wt_compiler.pypi_source.subprocess.run")
    def test_detect_failure_raises(self, mock_run, tmp_path):
        """Test that subprocess failure raises RuntimeError."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="ModuleNotFoundError: No module named 'wt_registry'",
        )

        with pytest.raises(RuntimeError, match="Failed to detect source"):
            detect_pypi_source("wt-registry", tmp_path / "env")


class TestDeriveSiblingPypiRequirement:
    """Tests for derive_sibling_pypi_requirement function."""

    def test_derive_sibling_path(self):
        """Test deriving sibling from path-based install."""
        direct_url = {
            "url": "file:///home/user/wt/wt-registry",
            "dir_info": {"editable": True},
        }

        req = derive_sibling_pypi_requirement("wt-registry", "wt-runner", direct_url, "0.1.0")

        assert isinstance(req, PyPIRequirement)
        assert req.name == "wt-runner"
        assert req.path == "/home/user/wt/wt-runner"
        assert req.editable is True

    def test_derive_sibling_path_not_editable(self):
        """Test deriving sibling from non-editable path install."""
        direct_url = {
            "url": "file:///home/user/wt/wt-registry",
            "dir_info": {"editable": False},
        }

        req = derive_sibling_pypi_requirement("wt-registry", "wt-task", direct_url, "0.1.0")

        assert isinstance(req, PyPIRequirement)
        assert req.name == "wt-task"
        assert req.path == "/home/user/wt/wt-task"
        assert req.editable is None  # False → None (not set)

    def test_derive_sibling_git(self):
        """Test deriving sibling from git-based install with subdirectory."""
        direct_url = {
            "url": "https://github.com/org/wt.git",
            "vcs_info": {
                "vcs": "git",
                "commit_id": "abc123def456",
                "requested_revision": "v1.0",
            },
            "subdirectory": "wt-registry",
        }

        req = derive_sibling_pypi_requirement("wt-registry", "wt-runner", direct_url, "1.0.0")

        assert isinstance(req, PyPIRequirement)
        assert req.name == "wt-runner"
        assert req.git == "https://github.com/org/wt.git"
        assert req.tag == "v1.0"
        assert req.subdirectory == "wt-runner"

    def test_derive_sibling_git_commit_only(self):
        """Test deriving sibling from git install with only commit_id."""
        direct_url = {
            "url": "https://github.com/org/wt.git",
            "vcs_info": {
                "vcs": "git",
                "commit_id": "abc123def456",
            },
            "subdirectory": "wt-registry",
        }

        req = derive_sibling_pypi_requirement("wt-registry", "wt-task", direct_url, "0.1.0")

        assert isinstance(req, PyPIRequirement)
        assert req.name == "wt-task"
        assert req.git == "https://github.com/org/wt.git"
        assert req.rev == "abc123def456"
        assert req.tag is None
        assert req.subdirectory == "wt-task"

    def test_derive_sibling_pypi_registry(self):
        """Test deriving sibling from PyPI registry install returns wildcard."""
        result = derive_sibling_pypi_requirement("wt-registry", "wt-runner", None, "1.0.0")

        assert result == "*"

    def test_derive_sibling_url_raises(self):
        """Test that URL-based (archive) install raises ValueError."""
        direct_url = {
            "url": "https://files.pythonhosted.org/packages/wt-registry-1.0.tar.gz",
            "archive_info": {"hash": "sha256=abc123"},
        }

        with pytest.raises(ValueError, match="Cannot derive sibling package"):
            derive_sibling_pypi_requirement("wt-registry", "wt-runner", direct_url, "1.0.0")

    def test_derive_sibling_unrecognized_format_raises(self):
        """Test that unrecognized direct_url format raises ValueError."""
        direct_url = {"url": "https://example.com/unknown", "unknown_info": {}}

        with pytest.raises(ValueError, match=r"Unrecognized direct_url\.json format"):
            derive_sibling_pypi_requirement("wt-registry", "wt-runner", direct_url, "1.0.0")
