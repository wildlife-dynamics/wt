"""Compile a spec to a persistent, addressable workflow package on disk.

This is the shared "compile" half used by both endpoints: ``/compile`` builds a
package and returns its ``build_id``; ``/run`` either reuses an existing build
by id or builds one on the fly from a spec. Compilation is in-process against
the resident ``known_tasks`` registry (no discovery, no solve).

Builds are written under a stable root (``WT_COMPILER_SERVICE__BUILD_ROOT``,
default a temp subdirectory) keyed by a content hash, so a repeated spec maps to
the same ``build_id`` and directory. The in-memory registry is process-local: a
``build_id`` is addressable for the life of the process.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ruamel.yaml
from wt_compiler.artifacts import VersionYaml, _params_sha256_from_readme
from wt_compiler.compiler import compile_spec_in_process
from wt_compiler.spec import Spec

logger = logging.getLogger(__name__)

_yaml = ruamel.yaml.YAML(typ="safe")

_BUILD_ROOT = (
    Path(os.environ.get("WT_COMPILER_SERVICE__BUILD_ROOT") or tempfile.gettempdir())
    / "wt-compiler-service-builds"
)

# Per-workflow-id version registry (id -> {version, params_sha256}), persisted
# so a workflow's version evolves across compiles: a major bump when its
# parameter schema changes, a minor bump otherwise (mirroring `dump --update`,
# but WITHOUT the pixi.lock carry-over).
_VERSIONS_DIR = _BUILD_ROOT / ".versions"

# The env var the compiled CLI reads for its results URL. Sourced from the same
# knob the invoker uses to *set* it (WT_INVOKERS__RESULTS_ENV_VAR), so compile
# and run agree — e.g. set it to ECOSCOPE_WORKFLOWS_RESULTS for ecoscope deploys.
_RESULTS_ENV_VAR = os.environ.get("WT_INVOKERS__RESULTS_ENV_VAR") or "WT_RESULTS"


@dataclass(frozen=True)
class Build:
    """A compiled workflow package on disk, addressable by ``build_id``."""

    build_id: str
    release_name: str
    package_name: str
    release_dir: Path
    dag: str
    params_schema: dict[str, Any]
    n_tasks: int
    results_env_var: str
    version: str


# Process-local registry: build_id -> Build.
_BUILDS: dict[str, Build] = {}


def _spec_key(data: dict[str, Any], variant: str | None, pkg_name_prefix: str) -> str:
    """Return a short content hash for a (spec, variant, prefix) triple."""
    payload = json.dumps(
        {"spec": data, "variant": variant, "prefix": pkg_name_prefix},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _bump_version(release_name: str, release_dir: Path) -> str:
    """Bump and persist the workflow's version, writing its VERSION.yaml.

    Reads the freshly compiled README's params fingerprint, compares it to the
    per-id registry's prior fingerprint, bumps (major on params-schema change,
    minor otherwise), overwrites ``release_dir/VERSION.yaml``, and persists the
    new record. First compile of a workflow starts at ``0.1.0``.

    Args:
        release_name: The workflow's release name (versioning key).
        release_dir: The compiled package directory (holds README.md and where
            VERSION.yaml is written).

    Returns:
        The new version as a ``"MAJ.MIN.PATCH"`` string.
    """
    new_sha = _params_sha256_from_readme((release_dir / "README.md").read_text())
    registry_file = _VERSIONS_DIR / f"{release_name}.json"
    if registry_file.exists():
        record = json.loads(registry_file.read_text())
        prior_version = VersionYaml(**record["version"])
        prior_sha = record["params_sha256"]
    else:
        # Seed so the first compile is a minor bump to 0.1.0.
        prior_version = VersionYaml(MAJ=0, MIN=0)
        prior_sha = new_sha

    new_version = VersionYaml.bump_from(prior_version, prior_sha, new_sha)
    new_version.dump(release_dir / "VERSION.yaml")

    _VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(
        json.dumps({"version": new_version.model_dump(), "params_sha256": new_sha})
    )
    return f"{new_version.MAJ}.{new_version.MIN}.{new_version.PATCH}"


def build(
    data: dict[str, Any],
    *,
    variant: str | None = None,
    pkg_name_prefix: str = "wt",
) -> tuple[Build, bool]:
    """Compile a spec to a package on disk and register it by ``build_id``.

    Args:
        data: The workflow spec as a dict.
        variant: Optional platform variant suffix (e.g. ``"gcp"``).
        pkg_name_prefix: Package name prefix for the generated artifacts.

    Returns:
        A ``(Build, cached)`` tuple; ``cached`` is True when an existing build
        for the same content was reused.
    """
    build_id = _spec_key(data, variant, pkg_name_prefix)
    existing = _BUILDS.get(build_id)
    if existing is not None:
        logger.info(
            "Reusing build %s (%s) at %s", build_id, existing.release_name, existing.release_dir
        )
        return existing, True

    spec = Spec.model_validate(data)

    build_dir = _BUILD_ROOT / build_id
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)
    spec_path = build_dir / "spec.yaml"
    with spec_path.open("w") as f:
        _yaml.dump(data, f)

    artifacts = compile_spec_in_process(
        spec,
        spec_relpath=str(spec_path),
        variant=variant,
        pkg_name_prefix=pkg_name_prefix,
        results_env_var=_RESULTS_ENV_VAR,
    )
    artifacts.dump(clobber=True)
    version = _bump_version(artifacts.release_name, artifacts.release_dir)
    logger.info(
        "Compiled workflow %s v%s (build %s) to %s",
        artifacts.release_name,
        version,
        build_id,
        artifacts.release_dir,
    )

    pkg_dir = artifacts.release_dir / artifacts.package_name
    result = Build(
        build_id=build_id,
        release_name=artifacts.release_name,
        package_name=artifacts.package_name,
        release_dir=artifacts.release_dir,
        dag=(pkg_dir / "dags" / "run_sequential.py").read_text(),
        params_schema=json.loads((pkg_dir / "params.json").read_text()),
        n_tasks=len(spec.flat_workflow),
        results_env_var=_RESULTS_ENV_VAR,
        version=version,
    )
    _BUILDS[build_id] = result
    return result, False


def get_build(build_id: str) -> Build | None:
    """Return a previously-registered build by id, or None if unknown."""
    return _BUILDS.get(build_id)
