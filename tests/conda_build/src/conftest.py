"""Pytest configuration and fixtures for conda build tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from helpers.channel import ChannelInfo, validate_channel
from helpers.pixi import (
    PixiWorkspace,
    create_workspace,
    install_packages,
    install_test_deps,
)

if TYPE_CHECKING:
    from collections.abc import Generator

# All wt packages in the monorepo (dependency order)
WT_PACKAGES = [
    "wt-contracts",
    "wt-registry",
    "wt-task",
    "wt-compiler",
    "wt-invokers",
    "wt-runner",
]

DEFAULT_CHANNEL_PATH = Path("/tmp/wt-conda-channel")


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom CLI options for conda build tests."""
    group = parser.getgroup("conda-build")

    group.addoption(
        "--channel-path",
        action="store",
        default=None,
        help=(
            f"Path to local conda channel "
            f"(default: $WT_CONDA_CHANNEL or {DEFAULT_CHANNEL_PATH})"
        ),
    )

    group.addoption(
        "--smoke-test",
        action="store_true",
        default=False,
        help="Run quick smoke tests only (import checks, no full unit tests)",
    )

    group.addoption(
        "--skip-unit-tests",
        action="store_true",
        default=False,
        help="Skip running package unit tests (channel/install validation only)",
    )

    group.addoption(
        "--package",
        action="store",
        default=None,
        help="Test only a specific package (e.g., 'wt-registry')",
    )


@pytest.fixture(scope="session")
def channel_path(request: pytest.FixtureRequest) -> Path:
    """Get the conda channel path from CLI options or environment."""
    cli_path = request.config.getoption("--channel-path")
    if cli_path:
        return Path(cli_path)

    env_path = os.environ.get("WT_CONDA_CHANNEL")
    if env_path:
        return Path(env_path)

    return DEFAULT_CHANNEL_PATH


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Get the repository root path."""
    # tests/conda_build/src/conftest.py -> repo root
    return Path(__file__).parent.parent.parent.parent


@pytest.fixture(scope="session")
def smoke_test_mode(request: pytest.FixtureRequest) -> bool:
    """Check if running in smoke test mode."""
    return request.config.getoption("--smoke-test")


@pytest.fixture(scope="session")
def skip_unit_tests(request: pytest.FixtureRequest) -> bool:
    """Check if unit tests should be skipped."""
    return request.config.getoption("--skip-unit-tests")


def get_packages_to_test(config: pytest.Config) -> list[str]:
    """Get list of packages to test based on CLI options."""
    single_package = config.getoption("--package")
    if single_package:
        if single_package not in WT_PACKAGES:
            raise pytest.UsageError(
                f"Unknown package '{single_package}'. "
                f"Available: {', '.join(WT_PACKAGES)}"
            )
        return [single_package]
    return WT_PACKAGES


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Generate test parameters for package-based tests."""
    if "package_name" in metafunc.fixturenames:
        packages = get_packages_to_test(metafunc.config)
        metafunc.parametrize("package_name", packages, ids=packages)


@pytest.fixture(scope="session")
def validated_channel(channel_path: Path) -> ChannelInfo:
    """
    Validate the conda channel exists and is properly indexed.

    Returns ChannelInfo with paths to all package files.
    Raises pytest.skip if channel is not available.
    """
    return validate_channel(channel_path, WT_PACKAGES)


@pytest.fixture(scope="session")
def pixi_workspace(
    tmp_path_factory: pytest.TempPathFactory,
    validated_channel: ChannelInfo,
) -> Generator[PixiWorkspace, None, None]:
    """
    Create a pixi workspace with all wt packages installed.

    This is session-scoped to avoid reinstalling for each test.
    """
    workspace_path = tmp_path_factory.mktemp("pixi-workspace")

    # Create workspace
    workspace = create_workspace(workspace_path, validated_channel.path)

    # Install all wt packages
    install_packages(workspace, WT_PACKAGES)

    # Install test dependencies
    install_test_deps(workspace)

    yield workspace


@pytest.fixture
def fresh_pixi_workspace(
    tmp_path: Path,
    validated_channel: ChannelInfo,
) -> PixiWorkspace:
    """
    Create a fresh pixi workspace for isolation.

    Function-scoped for tests that need isolated environments.
    """
    return create_workspace(tmp_path, validated_channel.path)
