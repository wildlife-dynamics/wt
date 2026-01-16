"""Helper functions for conda channel validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class ChannelInfo:
    """Information about a validated conda channel."""

    path: Path
    packages: dict[str, Path]  # package_name -> .conda file path


class ChannelError(Exception):
    """Error related to conda channel validation."""


def validate_channel(channel_path: Path, expected_packages: list[str]) -> ChannelInfo:
    """
    Validate a local conda channel exists and contains expected packages.

    Args:
        channel_path: Path to the conda channel directory
        expected_packages: List of package names that must exist

    Returns:
        ChannelInfo with validated channel details

    Raises:
        pytest.skip: If channel doesn't exist (with helpful message)
        ChannelError: If channel exists but is invalid
    """
    if not channel_path.exists():
        pytest.skip(
            f"Conda channel not found at {channel_path}. "
            f"Run ./scripts/build-conda-packages.sh first."
        )

    noarch_dir = channel_path / "noarch"
    if not noarch_dir.exists():
        raise ChannelError(f"Channel noarch directory not found: {noarch_dir}")

    # Check for repodata.json (channel must be indexed)
    repodata_path = noarch_dir / "repodata.json"
    if not repodata_path.exists():
        raise ChannelError(
            f"Channel not indexed (repodata.json missing). "
            f"Run: rattler-index fs {channel_path}"
        )

    # Validate repodata is valid JSON
    try:
        with open(repodata_path) as f:
            json.load(f)
    except json.JSONDecodeError as e:
        raise ChannelError(f"Invalid repodata.json: {e}") from e

    # Find each expected package
    packages: dict[str, Path] = {}
    missing: list[str] = []

    for pkg_name in expected_packages:
        # Look for .conda files matching the package name pattern
        conda_files = list(noarch_dir.glob(f"{pkg_name}-*.conda"))
        if not conda_files:
            missing.append(pkg_name)
        else:
            # Take the most recent (by name, which includes version)
            packages[pkg_name] = sorted(conda_files)[-1]

    if missing:
        raise ChannelError(
            f"Missing packages in channel: {', '.join(missing)}. "
            f"Run ./scripts/build-conda-packages.sh to build all packages."
        )

    return ChannelInfo(path=channel_path, packages=packages)


def get_package_version_from_channel(
    channel_info: ChannelInfo,
    package_name: str,
) -> str:
    """
    Extract the version of a package from its .conda filename.

    Args:
        channel_info: Validated channel information
        package_name: Name of the package

    Returns:
        Version string (e.g., "0.1.0")
    """
    conda_file = channel_info.packages[package_name]
    # Filename format: {name}-{version}-{build}.conda
    # e.g., wt-contracts-0.1.0-py310_0.conda
    stem = conda_file.stem  # wt-contracts-0.1.0-py310_0
    parts = stem.split("-")
    # Package name may contain hyphens, version is second-to-last
    # For wt-contracts-0.1.0-py310_0, parts = ["wt", "contracts", "0.1.0", "py310_0"]
    # We need to find where the version starts
    for part in parts:
        if part and part[0].isdigit():
            return part
    raise ValueError(f"Could not extract version from {conda_file.name}")
