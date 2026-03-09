"""Detect PyPI package source and derive sibling package requirements.

When wt-registry is installed via PyPI (not conda), this module detects how it
was installed (editable path, git, URL, or PyPI registry) using PEP 610
``direct_url.json``, then derives matching PyPI requirements for sibling
packages (wt-runner, wt-task) from the same monorepo.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from wt_compiler.spec import PyPIRequirement


def detect_pypi_source(
    package_name: str,
    env_path: Path,
) -> tuple[dict[str, Any] | None, str]:
    """Detect how a package was installed via PEP 610 direct_url.json.

    Runs Python in the ephemeral environment to read the package's
    ``direct_url.json`` metadata and version.

    Args:
        package_name: The package to inspect (e.g., ``"wt-registry"``)
        env_path: Path to the ephemeral conda/pip environment

    Returns:
        A tuple of (direct_url_dict, version_string).
        ``direct_url_dict`` is ``None`` when the package was installed from
        the PyPI registry (no ``direct_url.json``).

    Raises:
        RuntimeError: If the package is not installed or introspection fails.

    Examples:
        >>> # detect_pypi_source("wt-registry", Path("/tmp/env"))  # doctest: +SKIP
        ({"url": "file:///home/user/wt/wt-registry", "dir_info": {"editable": True}}, "0.1.0")
    """
    python_exe = (
        env_path / "Scripts" / "python.exe"
        if sys.platform == "win32"
        else env_path / "bin" / "python"
    )

    script = (
        "import importlib.metadata, json\n"
        f"dist = importlib.metadata.distribution('{package_name}')\n"
        "version = dist.metadata['Version']\n"
        "try:\n"
        "    raw = dist.read_text('direct_url.json')\n"
        "    direct_url = json.loads(raw) if raw else None\n"
        "except FileNotFoundError:\n"
        "    direct_url = None\n"
        "print(json.dumps({'direct_url': direct_url, 'version': version}))\n"
    )

    result = subprocess.run(
        [str(python_exe), "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to detect source for {package_name} in {env_path}: "
            f"{result.stderr.strip()}"
        )

    data = json.loads(result.stdout.strip())
    return data["direct_url"], data["version"]


def derive_sibling_pypi_requirement(
    source_pkg: str,
    target_pkg: str,
    direct_url: dict[str, Any] | None,
    version: str,
) -> PyPIRequirement | str:
    """Derive a PyPI requirement for a sibling package based on the source package's install method.

    Given how ``source_pkg`` (e.g., wt-registry) was installed, produce a
    matching ``PyPIRequirement`` (or version string) for ``target_pkg``
    (e.g., wt-runner or wt-task).

    Args:
        source_pkg: The source package name (e.g., ``"wt-registry"``)
        target_pkg: The sibling package name (e.g., ``"wt-runner"``)
        direct_url: Parsed ``direct_url.json`` dict, or ``None`` for PyPI registry
        version: Installed version of the source package

    Returns:
        A ``PyPIRequirement`` for path/git sources, or ``"*"`` for PyPI registry.

    Raises:
        ValueError: If the source is a direct URL (archive), which cannot be
            reliably mapped to sibling packages.

    Examples:
        Path install:

        >>> direct_url = {"url": "file:///home/user/wt/wt-registry", "dir_info": {"editable": True}}
        >>> req = derive_sibling_pypi_requirement("wt-registry", "wt-runner", direct_url, "0.1.0")
        >>> isinstance(req, PyPIRequirement)
        True
        >>> req.path
        '/home/user/wt/wt-runner'

        PyPI registry:

        >>> derive_sibling_pypi_requirement("wt-registry", "wt-runner", None, "0.1.0")
        '*'
    """
    if direct_url is None:
        # PyPI registry install — use wildcard version
        return "*"

    url = direct_url.get("url", "")

    # Path-based install (editable or not)
    if "dir_info" in direct_url:
        if not url.startswith("file://"):
            raise ValueError(
                f"Unexpected dir_info URL scheme for {source_pkg}: {url}"
            )
        source_path = Path(url.removeprefix("file://"))
        # Replace last path component: wt-registry → wt-runner
        target_path = source_path.parent / target_pkg
        editable = direct_url.get("dir_info", {}).get("editable", False)
        return PyPIRequirement(
            name=target_pkg,
            path=str(target_path),
            editable=editable or None,
        )

    # Git-based install
    if "vcs_info" in direct_url:
        vcs_info = direct_url["vcs_info"]
        git_url = url
        # Determine ref: prefer requested_revision, fall back to commit_id
        rev = vcs_info.get("requested_revision")
        commit_id = vcs_info.get("commit_id")

        # Replace subdirectory: wt-registry → wt-runner
        source_subdir = direct_url.get("subdirectory", source_pkg)
        target_subdir = target_pkg if source_subdir == source_pkg else None

        return PyPIRequirement(
            name=target_pkg,
            git=git_url,
            rev=commit_id if not rev else None,
            tag=rev if rev and not rev.startswith("refs/") else None,
            branch=rev if rev and rev.startswith("refs/") else None,
            subdirectory=target_subdir,
        )

    # URL-based install (archive/wheel) — cannot reliably map
    if "archive_info" in direct_url:
        raise ValueError(
            f"Cannot derive sibling package '{target_pkg}' from URL-based install "
            f"of '{source_pkg}' ({url}). URL installs cannot be reliably mapped "
            f"to sibling packages. Use git or path-based installs instead."
        )

    raise ValueError(
        f"Unrecognized direct_url.json format for {source_pkg}: {direct_url}"
    )
