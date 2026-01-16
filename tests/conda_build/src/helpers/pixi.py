"""Helper functions for pixi workspace management."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class PixiError(Exception):
    """Error related to pixi operations."""


@dataclass
class PixiWorkspace:
    """A pixi workspace for testing package installations."""

    path: Path
    channel_path: Path

    def run_pixi(
        self,
        args: list[str],
        timeout: int = 300,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a pixi command in this workspace."""
        cmd = ["pixi", *args]
        return subprocess.run(
            cmd,
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )

    def run_pytest(
        self,
        test_path: Path,
        extra_args: list[str] | None = None,
        timeout: int = 600,
    ) -> subprocess.CompletedProcess[str]:
        """Run pytest via pixi for a package's tests."""
        args = ["run", "pytest", str(test_path), "-v", "--tb=short"]
        if extra_args:
            args.extend(extra_args)
        return self.run_pixi(args, timeout=timeout, check=False)


def create_workspace(workspace_path: Path, channel_path: Path) -> PixiWorkspace:
    """
    Initialize a pixi workspace with the local channel.

    Args:
        workspace_path: Directory for the pixi project
        channel_path: Path to the local conda channel

    Returns:
        PixiWorkspace instance

    Raises:
        PixiError: If pixi init fails
    """
    workspace_path.mkdir(parents=True, exist_ok=True)

    # Initialize pixi with local channel first (higher priority)
    result = subprocess.run(
        [
            "pixi",
            "init",
            "--channel",
            f"file://{channel_path}",
            "--channel",
            "conda-forge",
        ],
        cwd=workspace_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise PixiError(
            f"pixi init failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    return PixiWorkspace(path=workspace_path, channel_path=channel_path)


def install_packages(workspace: PixiWorkspace, packages: list[str]) -> None:
    """
    Install packages into the pixi workspace.

    Args:
        workspace: The pixi workspace
        packages: List of package names to install

    Raises:
        PixiError: If installation fails
    """
    result = workspace.run_pixi(["add", *packages], check=False)

    if result.returncode != 0:
        raise PixiError(
            f"Failed to install packages {packages}:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )


def install_test_deps(workspace: PixiWorkspace) -> None:
    """
    Install test dependencies into the pixi workspace.

    Installs: pytest, pytest-cov, pytest-asyncio, httpx
    """
    test_deps = ["pytest", "pytest-cov", "pytest-asyncio", "httpx"]
    result = workspace.run_pixi(["add", *test_deps], check=False)

    if result.returncode != 0:
        raise PixiError(
            f"Failed to install test dependencies:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )


def verify_package_importable(
    workspace: PixiWorkspace,
    package_name: str,
) -> tuple[bool, str]:
    """
    Verify a package can be imported in the pixi environment.

    Args:
        workspace: The pixi workspace
        package_name: Package name (e.g., "wt-contracts")

    Returns:
        Tuple of (success, message)
    """
    # Convert package name to importable module name
    module_name = package_name.replace("-", "_")

    result = workspace.run_pixi(
        ["run", "python", "-c", f"import {module_name}; print({module_name}.__file__)"],
        check=False,
    )

    if result.returncode == 0:
        return True, f"Successfully imported {module_name}: {result.stdout.strip()}"
    else:
        return False, f"Failed to import {module_name}: {result.stderr}"
