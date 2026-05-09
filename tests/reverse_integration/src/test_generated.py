"""Tests for running the generated workflow tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from conftest import PixiInstallResult, Workspace


MONOREPO_ROOT = Path(__file__).resolve().parents[3]


# Packages and the envs that should resolve them to local sources when the
# reverse-integration env-overrides file is in effect.
#
# The env-overrides file declares the ``*-gcp`` metapackages as path sources;
# their ``[tool.uv.sources]`` redirects pull the base packages (and
# wt-contracts) from the local monorepo as well, so the path-sourced set
# extends transitively beyond what is named directly in the overrides file.
#
# wt-registry is only declared in the ``default`` feature of the env-overrides
# file. The ``runner`` and ``test`` envs are emitted with ``no_default_feature
# = True`` (see ``wt_compiler/compiler.py``) and neither wt-runner nor wt-task
# depends on wt-registry at runtime — it is a compile-time discovery library —
# so it is correctly absent from those envs.
_LOCAL_SOURCE_PARAMS = [
    ("default", "wt_task_gcp"),
    ("default", "wt_task"),
    ("default", "wt_registry"),
    ("default", "wt_contracts"),
    ("runner", "wt_runner_gcp"),
    ("runner", "wt_task_gcp"),
    ("runner", "wt_runner"),
    ("runner", "wt_task"),
    ("runner", "wt_contracts"),
    ("runner", "wt_invokers"),
    ("runner", "wt_invokers_gcp"),
    ("test", "wt_runner_gcp"),
    ("test", "wt_task_gcp"),
    ("test", "wt_runner"),
    ("test", "wt_task"),
    ("test", "wt_contracts"),
    ("test", "wt_invokers"),
    ("test", "wt_invokers_gcp"),
]


def _has_env_overrides(workspace: Workspace) -> bool:
    flags = workspace.repo_config.compile_flags or {}
    return "env_overrides" in flags


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
    ) -> None:
        """Verify that pixi install succeeds in the generated package.

        This test ensures the generated pixi.toml is valid and dependencies
        can be resolved.
        """
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
    ) -> None:
        """Run pytest on the generated workflow tests for each test case.

        This test executes the generated test suite to verify the workflow
        works correctly after recompilation.
        """
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
    ) -> None:
        """Run the generated metadata tests.

        This test specifically runs test_metadata.py to verify workflow
        metadata is correctly generated.
        """
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

    @pytest.mark.parametrize(("env_name", "pkg"), _LOCAL_SOURCE_PARAMS)
    def test_wt_package_direct_url_points_to_monorepo(
        self,
        pixi_installed_workspace: tuple[Workspace, PixiInstallResult],
        env_name: str,
        pkg: str,
    ) -> None:
        """Each wt-* dist-info ``direct_url.json`` must point under the monorepo root.

        Together with ``test_wt_package_dist_info_is_path_source`` this forms an
        airtight pair: ``dist_info`` proves "installed from a directory at all,"
        and this test proves "that directory is under the wt monorepo root."

        Note that ``<module>.__file__`` is not a usable probe here. Per pixi
        issue #5847, pixi registers path sources as non-editable URLs into uv's
        resolver, so even when the install came from a local path the package
        is materialized into ``.pixi/envs/.../site-packages/`` and ``__file__``
        resolves there rather than to the source tree. The ``url`` field of
        ``direct_url.json`` retains the original ``file://`` source location
        and is the correct invariant to assert against.
        """
        workspace, pixi_result = pixi_installed_workspace
        if not _has_env_overrides(workspace):
            pytest.skip("Repo does not declare env_overrides — local-source check N/A")
        if workspace.compile_result is None or not workspace.compile_result.success:
            pytest.skip("Compilation failed, skipping local-source check")
        if not pixi_result.success:
            pytest.skip(f"pixi install failed: {pixi_result.stderr}")

        generated_path = workspace.compile_result.generated_path
        dist_name = pkg.replace("_", "-")
        script = (
            "import importlib.metadata, json\n"
            f"d = importlib.metadata.distribution({dist_name!r})\n"
            "raw = d.read_text('direct_url.json') or ''\n"
            "print(raw)\n"
        )
        result = subprocess.run(
            ["pixi", "run", "-e", env_name, "python", "-c", script],
            cwd=generated_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            pytest.fail(
                f"Failed to read direct_url.json for {pkg} in env={env_name}: {result.stderr}"
            )
        raw = result.stdout.strip()
        assert raw, (
            f"{pkg} in env={env_name} has no direct_url.json — installed from "
            f"registry instead of local path."
        )
        direct_url = json.loads(raw)
        url = direct_url.get("url", "")
        assert url.startswith("file://"), (
            f"{pkg} in env={env_name} direct_url.json url is not a file:// URL: {url!r}"
        )
        assert str(MONOREPO_ROOT) in url, (
            f"{pkg} in env={env_name} direct_url.json url={url!r} does not point "
            f"under monorepo root {MONOREPO_ROOT}"
        )

    @pytest.mark.parametrize(("env_name", "pkg"), _LOCAL_SOURCE_PARAMS)
    def test_wt_package_dist_info_is_path_source(
        self,
        pixi_installed_workspace: tuple[Workspace, PixiInstallResult],
        env_name: str,
        pkg: str,
    ) -> None:
        """Each wt-* dist-info must record a path source in direct_url.json.

        This is the second half of the airtight check: even if a stale ``.pyc``
        on ``sys.path`` would pass the ``__file__`` test, the package's
        ``direct_url.json`` is what uv writes when it installs from a path,
        so the presence of ``dir_info`` proves the install came from local
        path and not from the registry.
        """
        workspace, pixi_result = pixi_installed_workspace
        if not _has_env_overrides(workspace):
            pytest.skip("Repo does not declare env_overrides — local-source check N/A")
        if workspace.compile_result is None or not workspace.compile_result.success:
            pytest.skip("Compilation failed, skipping direct_url check")
        if not pixi_result.success:
            pytest.skip(f"pixi install failed: {pixi_result.stderr}")

        generated_path = workspace.compile_result.generated_path
        dist_name = pkg.replace("_", "-")
        script = (
            "import importlib.metadata, json\n"
            f"d = importlib.metadata.distribution({dist_name!r})\n"
            "raw = d.read_text('direct_url.json') or ''\n"
            "print(raw)\n"
        )
        result = subprocess.run(
            ["pixi", "run", "-e", env_name, "python", "-c", script],
            cwd=generated_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            pytest.fail(
                f"Failed to read direct_url.json for {pkg} in env={env_name}: {result.stderr}"
            )
        raw = result.stdout.strip()
        assert raw, (
            f"{pkg} in env={env_name} has no direct_url.json — installed from "
            f"registry instead of local path."
        )
        direct_url = json.loads(raw)
        assert "dir_info" in direct_url, (
            f"{pkg} in env={env_name} has no dir_info in direct_url.json — "
            f"resolved from registry instead of local path. direct_url={direct_url}"
        )
