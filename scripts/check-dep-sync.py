#!/usr/bin/env python3
"""Check that pip dependencies and pixi run-dependencies are in sync.

For each package in the monorepo, compares [project.dependencies] against
[tool.pixi.package.run-dependencies] and reports mismatches. Also checks
that the Python version constraint is consistent between requires-python
and the pixi python run-dependency.

Exit 0 if in sync, exit 1 if mismatches found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parent.parent

PACKAGES = [
    "wt-contracts",
    "wt-registry",
    "wt-task",
    "wt-task-gcp",
    "wt-compiler",
    "wt-invokers",
    "wt-invokers-gcp",
    "wt-runner",
    "wt-runner-gcp",
]


def normalize_name(name: str) -> str:
    """Normalize a package name: lowercase, underscores to hyphens."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_pip_dep(dep: str) -> tuple[str, str, bool]:
    """Parse a PEP 508 dependency string.

    Returns (normalized_name, version_spec, has_marker).
    Strips environment markers and URL sources.
    """
    # Strip environment markers
    has_marker = ";" in dep
    dep_no_marker = dep.split(";")[0].strip()

    # Strip URL source (e.g., "pkg @ git+https://...")
    if " @ " in dep_no_marker:
        name = dep_no_marker.split(" @ ")[0].strip()
        return normalize_name(name), "", has_marker

    # Split name from version specifier
    match = re.match(r"^([a-zA-Z0-9_.-]+)(.*)", dep_no_marker)
    if match:
        name = match.group(1)
        version = match.group(2).strip()
        return normalize_name(name), version, has_marker
    return normalize_name(dep_no_marker), "", has_marker


def parse_pixi_deps(
    pixi_deps: dict[str, str],
) -> dict[str, str]:
    """Parse pixi run-dependencies into {normalized_name: version_spec}."""
    result: dict[str, str] = {}
    for name, version in pixi_deps.items():
        result[normalize_name(name)] = version
    return result


def check_package(pkg_dir: Path) -> list[str]:
    """Check a single package for dependency sync issues.

    Returns a list of issue strings (empty if in sync).
    """
    pyproject_path = pkg_dir / "pyproject.toml"
    if not pyproject_path.exists():
        return [f"  pyproject.toml not found"]

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    project = data.get("project", {})
    pixi_pkg = data.get("tool", {}).get("pixi", {}).get("package", {})

    pip_deps_raw: list[str] = project.get("dependencies", [])
    pixi_run_deps: dict[str, str] = pixi_pkg.get("run-dependencies", {})

    if not pixi_run_deps:
        return ["  No pixi run-dependencies found"]

    issues: list[str] = []

    # Check Python version consistency
    requires_python = project.get("requires-python", "")
    pixi_python = pixi_run_deps.get("python", "")
    if requires_python and pixi_python:
        # Normalize for comparison: pixi uses ">=3.10,<3.16", pip uses ">=3.10"
        # We just check that the pixi constraint starts with the pip constraint
        pip_py_norm = requires_python.replace(" ", "")
        pixi_py_norm = pixi_python.replace(" ", "")
        if not pixi_py_norm.startswith(pip_py_norm.rstrip(",")):
            # Allow pixi to add an upper bound that pip doesn't have
            pip_parts = set(pip_py_norm.split(","))
            pixi_parts = set(pixi_py_norm.split(","))
            if not pip_parts.issubset(pixi_parts):
                issues.append(
                    f"  Python version mismatch: pip={requires_python!r} vs pixi={pixi_python!r}"
                )

    # Parse pip deps
    pip_deps: dict[str, tuple[str, bool]] = {}  # name -> (version_spec, has_marker)
    for dep_str in pip_deps_raw:
        name, version, has_marker = parse_pip_dep(dep_str)
        pip_deps[name] = (version, has_marker)

    # Parse pixi deps (exclude python, already checked)
    pixi_deps = parse_pixi_deps(pixi_run_deps)
    pixi_deps.pop("python", None)

    # Check for deps in pip but not pixi
    for name, (version, has_marker) in pip_deps.items():
        if name not in pixi_deps:
            if has_marker:
                # Conditional deps (e.g., typing-extensions; python_version < '3.11')
                # are acceptable to omit from pixi — warn only
                issues.append(
                    f"  WARNING: {name} (conditional) in pip but not pixi (acceptable)"
                )
            else:
                issues.append(f"  MISMATCH: {name} in pip but not pixi")

    # Check for deps in pixi but not pip
    for name in pixi_deps:
        if name not in pip_deps:
            issues.append(f"  MISMATCH: {name} in pixi but not pip")

    # Check version range mismatches for shared deps
    for name in pip_deps:
        if name in pixi_deps:
            pip_version, _ = pip_deps[name]
            pixi_version = pixi_deps[name]
            if pip_version and pixi_version:
                # Normalize: remove spaces for comparison
                pip_v = pip_version.replace(" ", "")
                pixi_v = pixi_version.replace(" ", "")
                if pip_v != pixi_v:
                    issues.append(
                        f"  VERSION: {name} pip={pip_version!r} vs pixi={pixi_version!r}"
                    )

    return issues


def main() -> None:
    """Check all packages for dependency sync."""
    has_errors = False
    has_warnings = False

    for pkg_name in PACKAGES:
        pkg_dir = REPO_ROOT / pkg_name
        if not pkg_dir.exists():
            continue

        issues = check_package(pkg_dir)
        if issues:
            real_issues = [i for i in issues if "WARNING" not in i]
            warnings = [i for i in issues if "WARNING" in i]

            if real_issues:
                has_errors = True
                print(f"\n{pkg_name}: FAIL")
                for issue in real_issues:
                    print(issue)
            elif warnings:
                has_warnings = True
                print(f"\n{pkg_name}: WARN")

            for warning in warnings:
                print(warning)
        else:
            print(f"{pkg_name}: OK")

    if has_errors:
        print("\nDependency sync check FAILED")
        sys.exit(1)
    elif has_warnings:
        print("\nDependency sync check PASSED (with warnings)")
    else:
        print("\nDependency sync check PASSED")


if __name__ == "__main__":
    main()
