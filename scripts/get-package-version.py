#!/usr/bin/env python3
"""Extract package version from git tags for setuptools-scm pretend version.

This script extracts the version for a package from git tags matching the pattern
`<package>/v<version>`. It's used by the build script to set SETUPTOOLS_SCM_PRETEND_VERSION.

Usage:
    python get-package-version.py <package-name>

Example:
    $ python get-package-version.py wt-contracts
    1.0.0
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def get_version(package_name: str, repo_root: Path) -> str:
    """Get version for a package from git tags.

    Args:
        package_name: Name of the package (e.g., 'wt-contracts')
        repo_root: Path to the repository root

    Returns:
        Version string (e.g., '1.0.0' or '0.1.0.dev0' as fallback)
    """
    tag_pattern = f"{package_name}/v*"

    try:
        result = subprocess.run(
            ["git", "tag", "-l", tag_pattern, "--sort=-version:refname"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            check=True,
        )

        tags = result.stdout.strip().split("\n")
        if tags and tags[0]:
            # Extract version from tag (e.g., wt-contracts/v1.0.0 -> 1.0.0)
            tag = tags[0]
            version = tag.replace(f"{package_name}/v", "")
            return version
    except subprocess.CalledProcessError:
        pass

    # Fallback version
    return "0.1.0.dev0"


def main() -> None:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: get-package-version.py <package-name>", file=sys.stderr)
        print("Example: get-package-version.py wt-contracts", file=sys.stderr)
        sys.exit(1)

    package_name = sys.argv[1]
    repo_root = Path(__file__).parent.parent

    version = get_version(package_name, repo_root)
    print(version)


if __name__ == "__main__":
    main()
