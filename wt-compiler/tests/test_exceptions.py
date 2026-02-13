"""Tests for wt_compiler.exceptions module."""

from pathlib import Path

import pytest
from rattler import MatchSpec

from wt_compiler.exceptions import (
    DiscoveryError,
    RegistryExecutionError,
    RegistryNotFoundError,
)


class TestDiscoveryError:
    """Tests for base DiscoveryError."""

    def test_is_exception(self):
        """Test DiscoveryError is an Exception."""
        assert issubclass(DiscoveryError, Exception)

    def test_can_raise_and_catch(self):
        """Test DiscoveryError can be raised and caught."""
        with pytest.raises(DiscoveryError):
            raise DiscoveryError("test error")


class TestRegistryNotFoundError:
    """Tests for RegistryNotFoundError."""

    def test_inherits_from_discovery_error(self):
        """Test RegistryNotFoundError inherits from DiscoveryError."""
        assert issubclass(RegistryNotFoundError, DiscoveryError)

    def test_stores_attributes(self):
        """Test attributes are stored correctly."""
        path = Path("/fake/path")
        reqs = [MatchSpec("pkg>=1.0")]

        error = RegistryNotFoundError(
            executable_path=path,
            requirements=reqs,
        )

        assert error.executable_path == path
        assert error.requirements == reqs

    def test_message_includes_path_and_packages(self):
        """Test error message includes all relevant context."""
        error = RegistryNotFoundError(
            executable_path=Path("/tmp/env/bin/wt-registry"),
            requirements=[MatchSpec("my-tasks>=1.0.0")],
        )
        msg = str(error)
        assert "/tmp/env/bin/wt-registry" in msg
        assert "my-tasks" in msg
        assert "wt-registry" in msg  # Fix suggestion

    def test_message_lists_multiple_packages(self):
        """Test error message lists all packages in requirements."""
        error = RegistryNotFoundError(
            executable_path=Path("/tmp/env/bin/wt-registry"),
            requirements=[
                MatchSpec("package-a>=1.0.0"),
                MatchSpec("package-b>=2.0.0"),
                MatchSpec("python>=3.10"),
            ],
        )
        msg = str(error)
        assert "package-a" in msg
        assert "package-b" in msg
        assert "python" in msg

    def test_message_includes_fix_suggestions(self):
        """Test error message includes actionable fix suggestions."""
        error = RegistryNotFoundError(
            executable_path=Path("/tmp/env/bin/wt-registry"),
            requirements=[MatchSpec("my-tasks>=1.0.0")],
        )
        msg = str(error)
        assert "Add 'wt-registry'" in msg
        assert "conda dependencies" in msg
        assert "spec.yaml" in msg


class TestRegistryExecutionError:
    """Tests for RegistryExecutionError."""

    def test_inherits_from_discovery_error(self):
        """Test RegistryExecutionError inherits from DiscoveryError."""
        assert issubclass(RegistryExecutionError, DiscoveryError)

    def test_stores_subprocess_output(self):
        """Test stderr and stdout are stored."""
        error = RegistryExecutionError(
            executable_path=Path("/fake"),
            returncode=1,
            stdout="out",
            stderr="err",
            requirements=[MatchSpec("pkg>=1.0")],
        )

        assert error.stdout == "out"
        assert error.stderr == "err"
        assert error.returncode == 1
        assert error.executable_path == Path("/fake")

    def test_message_includes_stderr(self):
        """Test error message includes stderr content."""
        error = RegistryExecutionError(
            executable_path=Path("/tmp/env/bin/wt-registry"),
            returncode=1,
            stdout="",
            stderr="ImportError: No module named 'foo'",
            requirements=[MatchSpec("my-tasks>=1.0.0")],
        )
        msg = str(error)
        assert "exit code 1" in msg
        assert "ImportError" in msg

    def test_message_includes_stdout_when_present(self):
        """Test error message includes stdout when non-empty."""
        error = RegistryExecutionError(
            executable_path=Path("/tmp/env/bin/wt-registry"),
            returncode=2,
            stdout="partial output here",
            stderr="error details",
            requirements=[MatchSpec("my-tasks>=1.0.0")],
        )
        msg = str(error)
        assert "partial output here" in msg
        assert "error details" in msg

    def test_message_shows_empty_for_no_output(self):
        """Test error message shows (empty) when no stdout/stderr."""
        error = RegistryExecutionError(
            executable_path=Path("/tmp/env/bin/wt-registry"),
            returncode=1,
            stdout="",
            stderr="",
            requirements=[MatchSpec("my-tasks>=1.0.0")],
        )
        msg = str(error)
        assert "(empty)" in msg

    def test_message_includes_possible_causes(self):
        """Test error message lists possible causes."""
        error = RegistryExecutionError(
            executable_path=Path("/tmp/env/bin/wt-registry"),
            returncode=1,
            stdout="",
            stderr="",
            requirements=[MatchSpec("my-tasks>=1.0.0")],
        )
        msg = str(error)
        assert "incompatible version" in msg
        assert "Missing dependencies" in msg
