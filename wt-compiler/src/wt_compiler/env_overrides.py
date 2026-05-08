"""Loader for the user-supplied wt-compiler env-overrides file.

The env-overrides file shares its shape with the bundled
:mod:`wt_compiler.default-env-injections.toml` baseline — declaring
``[feature.<name>.dependencies]`` and ``[feature.<name>.pypi-dependencies]``
sections for the recognized features ``default``, ``runner``, and ``test``.
The compiler merges this file on top of the bundled baseline (and on top
of any spec-side suppressions) when emitting the compiled ``pixi.toml``.

The intended use is **development and testing of wt feature branches**:
forcing a compiled package and the wt-compiler discovery env to install
``wt-*`` siblings from a local monorepo checkout instead of from released
conda or PyPI packages. It should not be used in production.

The override file is read by wt-compiler only — it is never handed to
pixi. Conventional filename: ``wt-compiler-env-overrides.toml``.

Path-based PyPI dependencies are resolved relative to the override file's
own directory (matching pixi.toml semantics).

This loader also enforces the **leaf-only path source rule**: a package
declared as a path source in the env-overrides file must not also be
brought in transitively by a sibling path source's ``[tool.uv.sources]``
block. See :func:`validate_leaf_only_path_sources` and pixi
`#5847 <https://github.com/prefix-dev/pixi/issues/5847>`_.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

from wt_compiler.pixi_toml_fragment import PixiTomlFragment

logger = logging.getLogger(__name__)

_DIAGNOSTIC_LABEL = "Env-overrides file"


def load_env_overrides_file(path: str | Path) -> PixiTomlFragment:
    """Load and validate a wt-compiler env-overrides file.

    Parses the file into a :class:`PixiTomlFragment`, then runs the
    leaf-only path source check
    (:func:`validate_leaf_only_path_sources`).

    Args:
        path: Path to the override toml file. May be absolute or relative
            to the current working directory.

    Returns:
        The parsed :class:`PixiTomlFragment` with all paths resolved to
        absolute.

    Raises:
        FileNotFoundError: If the override file does not exist.
        ValueError: If the file declares an unrecognized feature, a
            malformed conda/pypi entry, the same package name in both
            the conda and pypi sections of one feature, or violates the
            leaf-only path source rule.
    """
    source_path = Path(path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"{_DIAGNOSTIC_LABEL} not found: {source_path}")

    # Catch ``[feature.discovery.*]`` ahead of the generic "unrecognized
    # feature" path so the error names the right replacement explicitly.
    with source_path.open("rb") as f:
        data = tomllib.load(f)
    feature_section = data.get("feature", {})
    if isinstance(feature_section, dict) and "discovery" in feature_section:
        raise ValueError(
            f"{_DIAGNOSTIC_LABEL} {source_path} declares [feature.discovery.*], "
            "which is not a recognized feature. Move these entries to "
            "[feature.default.*]: the merged default-feature dep set is fed "
            "into the discovery env so schema generation matches runtime."
        )

    fragment = PixiTomlFragment.from_data(
        data,
        source_path=source_path,
        diagnostic_label=_DIAGNOSTIC_LABEL,
    )
    validate_leaf_only_path_sources(fragment)
    return fragment


def validate_leaf_only_path_sources(fragment: PixiTomlFragment) -> None:
    """Reject env-overrides path sources that conflict with a peer's uv.sources.

    Pixi `#5847 <https://github.com/prefix-dev/pixi/issues/5847>`_ established
    that you cannot declare the same package as a path source in BOTH a
    pixi-side manifest entry AND in a sibling's ``[tool.uv.sources]``: pixi
    registers the path as non-editable into uv's resolver while uv's
    transitive build of the sibling registers it as editable, producing a
    "conflicting URLs" error.

    For env-overrides files this means: only **leaf** dependencies (those
    not transitively pulled in via another declared path source's
    ``[tool.uv.sources]``) may be declared as path sources. This guard
    enumerates every path-source entry across every feature in *fragment*,
    reads each path source's ``pyproject.toml``, parses its
    ``[tool.uv.sources]`` table, and raises if any package named there is
    also declared as a path source in the env-overrides file.

    Args:
        fragment: A parsed :class:`PixiTomlFragment` (typically the
            env-overrides file).

    Raises:
        ValueError: If an env-overrides path source is also brought in
            transitively via a peer's ``[tool.uv.sources]``.
    """
    path_sources: dict[str, Path] = {}
    for section in fragment.features.values():
        for req in section.pypi:
            if req.path is not None:
                path_sources[req.name] = Path(req.path)

    declared_names = set(path_sources)
    for declarer_name, declarer_path in path_sources.items():
        peer_sources = _read_uv_sources(declarer_path)
        if peer_sources is None:
            continue
        transitive_conflicts = sorted(declared_names & set(peer_sources) - {declarer_name})
        for conflicting_name in transitive_conflicts:
            raise ValueError(
                f"{_DIAGNOSTIC_LABEL} {fragment.source_path}: "
                f"{conflicting_name!r} is declared as a path source in "
                f"env-overrides but is also brought in transitively via "
                f"{declarer_name!r}'s [tool.uv.sources] "
                f"({declarer_path / 'pyproject.toml'}). This produces "
                f"conflicting URL forms in pixi's solve "
                f"(https://github.com/prefix-dev/pixi/issues/5847). "
                f"Remove {conflicting_name!r} from env-overrides; "
                f"{declarer_name!r} will pull it in editably via its own "
                f"uv.sources."
            )


def _read_uv_sources(package_dir: Path) -> dict[str, object] | None:
    """Return the parsed ``[tool.uv.sources]`` table, or ``None`` if absent.

    Args:
        package_dir: Directory expected to contain a ``pyproject.toml``.

    Returns:
        The ``[tool.uv.sources]`` table as a dict, an empty dict if the
        block is absent, or ``None`` if no ``pyproject.toml`` exists at
        *package_dir*.
    """
    pyproject = package_dir / "pyproject.toml"
    if not pyproject.exists():
        logger.debug(
            "leaf-only check: no pyproject.toml at %s; skipping uv.sources read",
            pyproject,
        )
        return None
    with pyproject.open("rb") as f:
        data = tomllib.load(f)
    tool = data.get("tool", {})
    if not isinstance(tool, dict):
        return {}
    uv = tool.get("uv", {})
    if not isinstance(uv, dict):
        return {}
    sources = uv.get("sources", {})
    if not isinstance(sources, dict):
        return {}
    return sources
