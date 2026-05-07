"""Tests for running the generated workflow tests."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from conftest import PixiInstallResult, Workspace


class TestGenerated:
    """Test suite for running generated workflow tests."""

    @pytest.fixture
    def generated_package_path(self, compiled_workspace: Workspace) -> Path:
        """Get the path to the generated package."""
        compile_result = compiled_workspace.compile_result

        if compile_result is None or not compile_result.success:
            pytest.skip("Compilation failed, skipping generated tests")

        if compile_result.generated_path is None:
            pytest.skip("Generated path not determined")

        return compile_result.generated_path

    def test_pixi_install_succeeds(
        self,
        pixi_installed_workspace: tuple[Workspace, PixiInstallResult],
        request: pytest.FixtureRequest,
    ) -> None:
        """Verify that pixi install succeeds in the generated package.

        This test ensures the generated pixi.toml is valid and dependencies
        can be resolved.
        """
        if request.config.getoption("--skip-generated-tests"):
            pytest.skip("Skipping generated tests (--skip-generated-tests)")

        workspace, pixi_result = pixi_installed_workspace

        if workspace.compile_result is None or not workspace.compile_result.success:
            pytest.skip("Compilation failed, skipping generated tests")

        if not pixi_result.success:
            pytest.fail(
                f"pixi install failed\nSTDOUT:\n{pixi_result.stdout}\nSTDERR:\n{pixi_result.stderr}"
            )

    def test_generated_tests_pass(
        self,
        pixi_installed_workspace: tuple[Workspace, PixiInstallResult],
        test_cases: list[str],
        request: pytest.FixtureRequest,
    ) -> None:
        """Run pytest on the generated workflow tests for each test case.

        This test executes the generated test suite to verify the workflow
        works correctly after recompilation.
        """
        if request.config.getoption("--skip-generated-tests"):
            pytest.skip("Skipping generated tests (--skip-generated-tests)")

        if not test_cases:
            pytest.skip("No test cases found in test-cases.yaml")

        workspace, pixi_result = pixi_installed_workspace

        if workspace.compile_result is None or not workspace.compile_result.success:
            pytest.skip("Compilation failed, skipping generated tests")

        if not pixi_result.success:
            pytest.skip(f"pixi install failed, cannot run tests\nSTDERR:\n{pixi_result.stderr}")

        generated_package_path = workspace.compile_result.generated_path

        # Run tests for each case
        failed_cases = []
        for case in test_cases:
            result = subprocess.run(
                ["pixi", "run", "-e", "test", "test-app-sequential-mock-io", f"--case={case}"],
                cwd=generated_package_path,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes per case
            )

            if result.returncode != 0:
                failed_cases.append(
                    {
                        "case": case,
                        "exit_code": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )

        if failed_cases:
            failure_report = "\n\n".join(
                f"CASE: {fc['case']}\n"
                f"Exit code: {fc['exit_code']}\n"
                f"STDOUT:\n{fc['stdout']}\n"
                f"STDERR:\n{fc['stderr']}"
                for fc in failed_cases
            )
            pytest.fail(
                f"{len(failed_cases)}/{len(test_cases)} test cases failed:\n\n{failure_report}"
            )

    def test_metadata_valid(
        self,
        pixi_installed_workspace: tuple[Workspace, PixiInstallResult],
        test_cases: list[str],
        request: pytest.FixtureRequest,
    ) -> None:
        """Run the generated metadata tests.

        This test specifically runs test_metadata.py to verify workflow
        metadata is correctly generated.
        """
        if request.config.getoption("--skip-generated-tests"):
            pytest.skip("Skipping generated tests (--skip-generated-tests)")

        workspace, pixi_result = pixi_installed_workspace

        if workspace.compile_result is None or not workspace.compile_result.success:
            pytest.skip("Compilation failed, skipping generated tests")

        if not pixi_result.success:
            pytest.skip(
                f"pixi install failed, cannot run metadata tests\nSTDERR:\n{pixi_result.stderr}"
            )

        generated_package_path = workspace.compile_result.generated_path
        tests_dir = generated_package_path / "tests"
        metadata_test = tests_dir / "test_metadata.py"

        if not metadata_test.exists():
            pytest.skip("test_metadata.py not found")

        result = subprocess.run(
            ["pixi", "run", "-e", "test", "test-app-metadata", f"--case={test_cases[0]}"],
            cwd=generated_package_path,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            pytest.fail(
                f"Metadata tests failed with exit code {result.returncode}\n"
                f"STDOUT:\n{result.stdout}\n"
                f"STDERR:\n{result.stderr}"
            )
