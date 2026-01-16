"""Tests that run each package's unit test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.pixi import PixiWorkspace


@pytest.mark.requires_channel
@pytest.mark.slow
class TestPackageUnitTests:
    """
    Test suite that runs unit tests for each package.

    These tests verify that the installed conda packages work correctly
    by running their original unit test suites.
    """

    def test_package_unit_tests(
        self,
        pixi_workspace: PixiWorkspace,
        repo_root: Path,
        package_name: str,
        skip_unit_tests: bool,
        smoke_test_mode: bool,
    ) -> None:
        """
        Run the unit tests for a package against the conda-installed version.

        This test runs pytest on the package's tests directory using the
        pixi workspace where the package is installed from the local channel.
        """
        if skip_unit_tests:
            pytest.skip("Unit tests skipped (--skip-unit-tests)")

        if smoke_test_mode:
            pytest.skip("Smoke test mode - skipping full unit tests")

        # Find the package's test directory
        test_dir = repo_root / package_name / "tests"
        if not test_dir.exists():
            pytest.skip(f"No tests directory found for {package_name}")

        # Run pytest for this package's tests
        result = pixi_workspace.run_pytest(
            test_path=test_dir,
            timeout=600,
        )

        if result.returncode != 0:
            # Collect failure information
            pytest.fail(
                f"Unit tests failed for {package_name}\n"
                f"Exit code: {result.returncode}\n"
                f"STDOUT:\n{result.stdout}\n"
                f"STDERR:\n{result.stderr}"
            )


@pytest.mark.requires_channel
class TestSmokeTests:
    """Quick smoke tests for basic functionality."""

    def test_import_and_version(
        self,
        pixi_workspace: PixiWorkspace,
        package_name: str,
    ) -> None:
        """Verify package imports and has a __version__ attribute."""
        module_name = package_name.replace("-", "_")

        result = pixi_workspace.run_pixi(
            [
                "run",
                "python",
                "-c",
                f"import {module_name}; "
                f"print(f'{module_name}: {{getattr({module_name}, \"__version__\", \"no version\")}}')",
            ],
            check=False,
        )

        assert result.returncode == 0, (
            f"Failed to import {module_name} or get version:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_registry_cli_available(
        self,
        pixi_workspace: PixiWorkspace,
    ) -> None:
        """Verify wt-registry CLI is available."""
        result = pixi_workspace.run_pixi(
            ["run", "wt-registry", "--help"],
            check=False,
        )

        assert result.returncode == 0, (
            f"wt-registry CLI not available:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_compiler_cli_available(
        self,
        pixi_workspace: PixiWorkspace,
    ) -> None:
        """Verify wt-compiler module is runnable."""
        result = pixi_workspace.run_pixi(
            ["run", "python", "-m", "wt_compiler", "--help"],
            check=False,
        )

        assert result.returncode == 0, (
            f"wt-compiler CLI not available:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
