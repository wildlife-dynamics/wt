"""Tests for PyPI dependency discovery in wt-compiler.

This module tests the PyPI integration path in discovery.py:
- End-to-end tests that actually pip-install a minimal test package
- Error handling when pip install fails (PyPIInstallError)
- Task module derivation from PyPI requirement names
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rattler import MatchSpec

from wt_compiler.discovery import discover_tasks_from_requirements
from wt_compiler.exceptions import PyPIInstallError
from wt_compiler.spec import PyPIRequirement

# Monorepo root for constructing local paths to wt-registry / wt-contracts
MONOREPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Fixture: minimal installable package with a @register-decorated task
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def test_disco_pkg(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a minimal installable Python package that registers one task.

    The package depends on wt-registry (via local path) so that pip-installing
    it into a conda env transitively provides the ``wt-registry`` entry point.
    """
    pkg_dir = tmp_path_factory.mktemp("test_disco_pkg_src") / "test-disco-pkg"
    src_dir = pkg_dir / "src" / "test_disco_pkg"
    src_dir.mkdir(parents=True)

    wt_registry_path = MONOREPO_ROOT / "wt-registry"
    wt_contracts_path = MONOREPO_ROOT / "wt-contracts"

    # pyproject.toml — declares wt_registry entry point for auto-discovery
    (pkg_dir / "pyproject.toml").write_text(f"""\
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"

[project]
name = "test-disco-pkg"
version = "0.0.1"
requires-python = ">=3.10"
dependencies = [
    "wt-registry @ file://{wt_registry_path}",
    "wt-contracts @ file://{wt_contracts_path}",
]

[project.entry-points."wt_registry"]
test-disco-pkg = "test_disco_pkg.tasks"

[tool.setuptools.packages.find]
where = ["src"]
""")

    # __init__.py  — re-exports the task so wt-registry can find the public path
    (src_dir / "__init__.py").write_text("from test_disco_pkg.tasks import add\n")

    # tasks.py — one @register-decorated function
    (src_dir / "tasks.py").write_text("""\
from wt_registry import register


@register(title="Add Numbers", description="Add two integers")
def add(a: int, b: int) -> int:
    return a + b
""")

    return pkg_dir


# ---------------------------------------------------------------------------
# End-to-end integration tests (slow — require network + rattler)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestEndToEndPyPIDiscovery:
    """Integration tests that create real conda envs and pip-install packages."""

    @pytest.fixture(autouse=True)
    def _pretend_scm_version(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Force setuptools-scm to produce a PEP 440 release version so pip
        can resolve cross-package constraints from local file:// deps."""
        monkeypatch.setenv("SETUPTOOLS_SCM_PRETEND_VERSION", "0.1.0")

    @pytest.mark.asyncio
    async def test_pypi_only_discovery(self, test_disco_pkg: Path) -> None:
        """Discover a task from a locally uv-installed PyPI package."""
        pypi_req = PyPIRequirement(name="test-disco-pkg", path=str(test_disco_pkg))

        # python and uv are auto-injected when pypi_requirements is non-empty
        result = await discover_tasks_from_requirements(
            requirements=[MatchSpec("python>=3.10")],
            pypi_requirements=[pypi_req],
        )

        # The 'add' function should be discovered
        assert "add" in result.tasks, f"Expected 'add' in tasks, got: {list(result.tasks.keys())}"

        # Verify the KnownTask metadata
        task_modules = result.tasks["add"]
        assert len(task_modules) >= 1
        known_task = next(iter(task_modules.values()))
        assert known_task.function_name == "add"
        assert known_task.description == "Add two integers"
        # JSON schema should describe two integer params
        schema = known_task.json_schema
        assert "properties" in schema
        assert "a" in schema["properties"]
        assert "b" in schema["properties"]


# ---------------------------------------------------------------------------
# PyPIInstallError tests (mocked, fast)
# ---------------------------------------------------------------------------


class TestPyPIInstallErrorInDiscovery:
    """Tests for the error path when pip install fails."""

    @pytest.mark.asyncio
    @patch("wt_compiler.discovery.subprocess.run")
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_pypi_install_error_raised_on_failure(
        self,
        mock_tmpdir: MagicMock,
        mock_create_env: AsyncMock,
        mock_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        """PyPIInstallError is raised when uv pip install returns non-zero."""
        env_path = tmp_path / "env"
        bin_path = env_path / "bin"
        bin_path.mkdir(parents=True)
        # Create uv and python executables so the code finds them
        (bin_path / "uv").touch()
        (bin_path / "python").touch()

        mock_tmpdir.return_value.__enter__ = MagicMock(return_value=str(tmp_path))
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)
        mock_create_env.return_value = []

        # Simulate uv pip install failure
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="Collecting bad-package\n",
            stderr="ERROR: No matching distribution found for bad-package",
        )

        pypi_req = PyPIRequirement(name="bad-package", git="https://github.com/org/bad.git")

        with pytest.raises(PyPIInstallError) as exc_info:
            await discover_tasks_from_requirements(
                requirements=[MatchSpec("python>=3.10")],
                pypi_requirements=[pypi_req],
            )

        error = exc_info.value
        assert error.requirement is pypi_req
        assert error.returncode == 1
        assert "Collecting bad-package" in error.stdout
        assert "No matching distribution" in error.stderr

    def test_pypi_install_error_message_format(self) -> None:
        """str(PyPIInstallError) contains package name, exit code, pip arg, and output."""
        req = PyPIRequirement(name="foo-bar", git="https://github.com/org/foo-bar.git")
        error = PyPIInstallError(
            requirement=req,
            returncode=2,
            stdout="some stdout",
            stderr="some stderr",
        )

        msg = str(error)
        assert "foo-bar" in msg
        assert "exit code 2" in msg
        assert "git+https://github.com/org/foo-bar.git" in msg
        assert "some stdout" in msg
        assert "some stderr" in msg

    @pytest.mark.asyncio
    @patch("wt_compiler.pypi_source.detect_pypi_source", return_value=(None, "0.1.0"))
    @patch("wt_compiler.discovery.subprocess.run")
    @patch("wt_compiler.discovery._create_environment", new_callable=AsyncMock)
    @patch("wt_compiler.discovery.tempfile.TemporaryDirectory")
    async def test_wt_registry_called_without_package_args(
        self,
        mock_tmpdir: MagicMock,
        mock_create_env: AsyncMock,
        mock_run: MagicMock,
        mock_detect_pypi: MagicMock,
        tmp_path: Path,
    ) -> None:
        """wt-registry CLI is called without --package args (uses entry point auto-discovery)."""
        env_path = tmp_path / "env"
        bin_path = env_path / "bin"
        bin_path.mkdir(parents=True)
        (bin_path / "wt-registry").touch()
        (bin_path / "uv").touch()
        (bin_path / "python").touch()

        mock_tmpdir.return_value.__enter__ = MagicMock(return_value=str(tmp_path))
        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)
        mock_create_env.return_value = []

        # uv succeeds, wt-registry returns empty entries
        uv_success = MagicMock(returncode=0, stdout="", stderr="")
        registry_success = MagicMock(
            returncode=0,
            stdout=json.dumps({"entries": {}, "version": "1.0.0"}),
        )
        mock_run.side_effect = [uv_success, registry_success]

        pypi_req = PyPIRequirement(name="foo-bar", path="/some/path")

        await discover_tasks_from_requirements(
            requirements=[MatchSpec("python>=3.10")],
            pypi_requirements=[pypi_req],
        )

        # The second subprocess.run call is the wt-registry invocation
        wt_registry_call = mock_run.call_args_list[1]
        cli_args = wt_registry_call[0][0]
        # Should NOT contain any --package args
        assert "--package" not in cli_args
        # Should contain --format json
        assert "--format" in cli_args
        assert "json" in cli_args
