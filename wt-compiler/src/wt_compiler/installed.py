"""Check a spec's requirements against the environment the compiler is running in.

A solve-free compile (``--from-env``) discovers tasks from whatever is installed,
so nothing else guarantees that the installed task libraries are the versions
the spec declares. This module is that guarantee: a compile against the wrong
environment fails here, before any task library is imported.
"""

from __future__ import annotations

import json
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING

from rattler import Version, VersionSpec

from wt_compiler.exceptions import InstalledRequirementsError
from wt_compiler.spec import PyPIRequirement, SpecRequirement

if TYPE_CHECKING:
    from collections.abc import Iterable


def _conda_record(prefix: Path, name: str) -> dict[str, str] | None:
    # The glob also matches longer names sharing the prefix (foo-bar-1.0-0.json
    # for "foo"), hence the name check.
    for path in (prefix / "conda-meta").glob(f"{name}-*.json"):
        record: dict[str, str] = json.loads(path.read_text())
        if record.get("name") == name:
            return record
    return None


def resolve_installed_requirements(
    requirements: Iterable[SpecRequirement | PyPIRequirement],
    prefix: Path | None = None,
) -> list[SpecRequirement]:
    """Pin each conda requirement to its installed version, failing on any mismatch.

    Conda packages are read from ``<prefix>/conda-meta``, falling back to
    ``importlib.metadata`` for packages installed by pip or uv (which only sees
    the running interpreter's environment). Only the version is checked, not the
    channel, so a locally built package satisfies a spec that names a remote
    channel. PyPI requirements carry no version constraint and are checked for
    presence only.

    Args:
        requirements: The spec's ``requirements:`` entries.
        prefix: Environment prefix to read; defaults to ``sys.prefix``.

    Returns:
        One ``==<installed>`` requirement per conda requirement, carrying the
        installed package's channel when known.

    Raises:
        InstalledRequirementsError: If any requirement is missing from the
            environment or installed at a version the spec does not admit. All
            problems are reported together.

    Examples:
        >>> resolve_installed_requirements([])
        []
    """
    prefix = Path(sys.prefix) if prefix is None else prefix
    pinned: list[SpecRequirement] = []
    problems: list[str] = []
    for req in requirements:
        record = _conda_record(prefix, req.name)
        if record is not None:
            installed: str | None = record["version"]
        elif req.name == "python":
            # Outside a conda env the interpreter has no record or distribution.
            installed = platform.python_version()
        else:
            try:
                installed = version(req.name)
            except PackageNotFoundError:
                installed = None
        if installed is None:
            problems.append(f"{req.name} is not installed")
            continue
        if isinstance(req, PyPIRequirement):
            continue
        spec = str(req.version.version or "*")
        if not VersionSpec(spec).matches(Version(installed)):
            problems.append(f"{req.name} {spec} is required, but {installed} is installed")
            continue
        pinned.append(
            SpecRequirement(
                name=req.name,
                version=f"=={installed}",  # type: ignore[arg-type]
                channel=(record or {}).get("channel") or req.channel.base_url,  # type: ignore[arg-type]
            )
        )
    if problems:
        raise InstalledRequirementsError(problems)
    return pinned
