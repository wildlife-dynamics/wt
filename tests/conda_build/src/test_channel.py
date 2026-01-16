"""Tests for conda channel validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import WT_PACKAGES
from helpers.channel import ChannelInfo


@pytest.mark.requires_channel
class TestChannelValidation:
    """Test suite for channel validation."""

    def test_channel_exists(self, channel_path: Path) -> None:
        """Verify the conda channel directory exists."""
        if not channel_path.exists():
            pytest.fail(
                f"Conda channel not found at {channel_path}. "
                f"Run ./scripts/build-conda-packages.sh first."
            )

    def test_channel_is_indexed(self, channel_path: Path) -> None:
        """Verify the channel has repodata.json (is indexed)."""
        if not channel_path.exists():
            pytest.skip("Channel does not exist")

        repodata = channel_path / "noarch" / "repodata.json"
        assert repodata.exists(), (
            f"Channel not indexed. Run: rattler-index fs {channel_path}"
        )

    def test_all_packages_present(
        self,
        validated_channel: ChannelInfo,
    ) -> None:
        """Verify all wt packages are present in the channel."""
        for pkg in WT_PACKAGES:
            assert pkg in validated_channel.packages, f"Package {pkg} not in channel"

    def test_package_file_exists(
        self,
        validated_channel: ChannelInfo,
        package_name: str,
    ) -> None:
        """Verify each package's .conda file exists."""
        conda_file = validated_channel.packages[package_name]
        assert conda_file.exists(), f"Package file not found: {conda_file}"

    def test_package_file_not_empty(
        self,
        validated_channel: ChannelInfo,
        package_name: str,
    ) -> None:
        """Verify each package's .conda file is not empty."""
        conda_file = validated_channel.packages[package_name]
        assert conda_file.stat().st_size > 0, f"Package file is empty: {conda_file}"
