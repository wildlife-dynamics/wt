"""Tests for package installation from local channel."""

from __future__ import annotations

import pytest

from conftest import WT_PACKAGES
from helpers.channel import ChannelInfo
from helpers.pixi import (
    PixiWorkspace,
    install_packages,
    verify_package_importable,
)


@pytest.mark.requires_channel
class TestPackageInstallation:
    """Test suite for package installation."""

    def test_package_installs(
        self,
        fresh_pixi_workspace: PixiWorkspace,
        package_name: str,
    ) -> None:
        """Verify each package can be installed from the local channel."""
        try:
            install_packages(fresh_pixi_workspace, [package_name])
        except Exception as e:
            pytest.fail(f"Failed to install {package_name}: {e}")

    def test_package_importable(
        self,
        pixi_workspace: PixiWorkspace,
        package_name: str,
    ) -> None:
        """Verify each package can be imported after installation."""
        success, message = verify_package_importable(pixi_workspace, package_name)
        assert success, message

    def test_all_packages_coinstallable(
        self,
        fresh_pixi_workspace: PixiWorkspace,
        validated_channel: ChannelInfo,
    ) -> None:
        """Verify all packages can be installed together without conflicts."""
        try:
            install_packages(fresh_pixi_workspace, WT_PACKAGES)
        except Exception as e:
            pytest.fail(f"Failed to co-install all packages: {e}")

        # Verify all are importable
        for pkg in WT_PACKAGES:
            success, message = verify_package_importable(fresh_pixi_workspace, pkg)
            assert success, f"Package {pkg} not importable after co-install: {message}"


@pytest.mark.requires_channel
class TestDependencyResolution:
    """Test suite for verifying dependency relationships."""

    def test_contracts_has_no_wt_dependencies(
        self,
        fresh_pixi_workspace: PixiWorkspace,
    ) -> None:
        """Verify wt-contracts installs without other wt packages."""
        install_packages(fresh_pixi_workspace, ["wt-contracts"])
        success, message = verify_package_importable(
            fresh_pixi_workspace, "wt-contracts"
        )
        assert success, message

    def test_registry_pulls_contracts(
        self,
        fresh_pixi_workspace: PixiWorkspace,
    ) -> None:
        """Verify wt-registry installation also installs wt-contracts."""
        install_packages(fresh_pixi_workspace, ["wt-registry"])

        # Both should be importable
        for pkg in ["wt-contracts", "wt-registry"]:
            success, message = verify_package_importable(fresh_pixi_workspace, pkg)
            assert success, f"{pkg}: {message}"

    def test_runner_pulls_all_dependencies(
        self,
        fresh_pixi_workspace: PixiWorkspace,
    ) -> None:
        """Verify wt-runner installation pulls wt-contracts and wt-invokers."""
        install_packages(fresh_pixi_workspace, ["wt-runner"])

        # wt-runner depends on wt-contracts and wt-invokers
        for pkg in ["wt-contracts", "wt-invokers", "wt-runner"]:
            success, message = verify_package_importable(fresh_pixi_workspace, pkg)
            assert success, f"{pkg}: {message}"
