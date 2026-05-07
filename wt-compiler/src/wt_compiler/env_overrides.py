"""Per-feature environment overrides for wt-compiler.

This module parses an explicit pixi-style toml fragment that declares conda
and/or pypi dependencies to merge into a compiled package's pixi.toml on a
per-feature basis. It is intended for development and testing of wt feature
branches.

The override file is read by wt-compiler only — it is never handed to pixi.
Conventional filename: ``wt-compiler-env-overrides.toml``.

Recognized features:
    - ``default``: emitted as top-level ``[pypi-dependencies]`` /
      ``[dependencies]`` in the compiled pixi.toml.
    - ``runner``: emitted as ``[feature.runner.*]`` in the compiled pixi.toml.
    - ``test``: emitted as ``[feature.test.*]`` in the compiled pixi.toml.
    - ``discovery``: pseudo-feature interpreted by wt-compiler only; deps are
      overlaid into the discovery env via ``uv pip install`` with
      ``--reinstall-package``. Never emitted into the compiled pixi.toml.

Path-based PyPI dependencies are resolved relative to the override file's own
directory (matching pixi.toml semantics).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rattler import MatchSpec

from wt_compiler.spec import PyPIRequirement

RECOGNIZED_FEATURES: tuple[str, ...] = ("default", "runner", "test", "discovery")


@dataclass
class FeatureOverride:
    """Parsed conda + pypi deps for one feature in the override file.

    Attributes:
        conda: Conda match-specs (rattler ``MatchSpec``) declared under
            ``[feature.<name>.dependencies]``.
        pypi: PyPI requirements declared under
            ``[feature.<name>.pypi-dependencies]``. Path-form requirements
            have already been resolved to absolute paths.
    """

    conda: list[MatchSpec] = field(default_factory=list)
    pypi: list[PyPIRequirement] = field(default_factory=list)


@dataclass
class EnvOverrides:
    """Parsed wt-compiler env-overrides file.

    Use :meth:`from_file` to load and validate an override file.

    Attributes:
        source_path: Absolute path of the override file (used for diagnostics
            and as the anchor for relative path resolution).
        features: Mapping of feature name (one of
            :data:`RECOGNIZED_FEATURES`) to its parsed
            :class:`FeatureOverride`.
    """

    source_path: Path
    features: dict[str, FeatureOverride] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> EnvOverrides:
        """Load and parse an override file.

        Args:
            path: Path to the override toml file. May be absolute or relative
                to the current working directory.

        Returns:
            An :class:`EnvOverrides` instance with all paths resolved to
            absolute.

        Raises:
            FileNotFoundError: If the override file does not exist.
            ValueError: If the file declares an unrecognized feature, or if
                a malformed pypi/conda dep dict is found.

        Examples:
            >>> # overrides = EnvOverrides.from_file("wt-compiler-env-overrides.toml")
            >>> # overrides.get_feature_pypi_deps("default")  # doctest: +SKIP
            [...]
        """
        source_path = Path(path).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Env-overrides file not found: {source_path}")
        with source_path.open("rb") as f:
            data = tomllib.load(f)
        return cls._parse(source_path, data)

    @classmethod
    def _parse(cls, source_path: Path, data: dict[str, Any]) -> EnvOverrides:
        """Parse a loaded toml dict into an EnvOverrides instance.

        Args:
            source_path: Absolute path of the override file (anchor for
                relative pypi paths).
            data: Parsed toml dict.

        Returns:
            An :class:`EnvOverrides` instance.
        """
        feature_section = data.get("feature", {})
        if not isinstance(feature_section, dict):
            raise ValueError(f"Env-overrides file {source_path} has malformed [feature.*] section.")

        unknown = set(feature_section) - set(RECOGNIZED_FEATURES)
        if unknown:
            raise ValueError(
                f"Env-overrides file {source_path} declares unrecognized feature(s): "
                f"{sorted(unknown)}. Recognized features: {list(RECOGNIZED_FEATURES)}."
            )

        anchor_dir = source_path.parent
        features: dict[str, FeatureOverride] = {}
        for feat_name, feat_data in feature_section.items():
            if not isinstance(feat_data, dict):
                raise ValueError(
                    f"Env-overrides file {source_path}: [feature.{feat_name}] "
                    f"must be a table, got {type(feat_data).__name__}."
                )

            override = FeatureOverride()

            conda_deps = feat_data.get("dependencies", {})
            if not isinstance(conda_deps, dict):
                raise ValueError(
                    f"Env-overrides file {source_path}: "
                    f"[feature.{feat_name}.dependencies] must be a table."
                )
            for name, version in conda_deps.items():
                if not isinstance(version, str):
                    raise ValueError(
                        f"Env-overrides file {source_path}: "
                        f"[feature.{feat_name}.dependencies] entry for {name!r} "
                        f"must be a version string, got {type(version).__name__}."
                    )
                spec_str = f"{name} {version}".strip() if version != "*" else name
                override.conda.append(MatchSpec(spec_str))

            pypi_deps = feat_data.get("pypi-dependencies", {})
            if not isinstance(pypi_deps, dict):
                raise ValueError(
                    f"Env-overrides file {source_path}: "
                    f"[feature.{feat_name}.pypi-dependencies] must be a table."
                )
            for name, value in pypi_deps.items():
                override.pypi.append(_parse_pypi_entry(name, value, anchor_dir))

            features[feat_name] = override

        return cls(source_path=source_path, features=features)

    def get_feature(self, name: str) -> FeatureOverride:
        """Get the :class:`FeatureOverride` for *name*, or an empty one.

        Args:
            name: Feature name (one of :data:`RECOGNIZED_FEATURES`).

        Returns:
            The parsed :class:`FeatureOverride`, or an empty one if the
            feature is not declared in the file.
        """
        return self.features.get(name, FeatureOverride())

    def get_feature_pypi_deps(self, name: str) -> list[PyPIRequirement]:
        """Get the pypi requirements for *name*, or an empty list."""
        return list(self.get_feature(name).pypi)

    def get_feature_conda_deps(self, name: str) -> list[MatchSpec]:
        """Get the conda match-specs for *name*, or an empty list."""
        return list(self.get_feature(name).conda)


def _parse_pypi_entry(
    name: str,
    value: Any,  # noqa: ANN401  # pixi-style entries are dynamic dicts/strings
    anchor_dir: Path,
) -> PyPIRequirement:
    """Convert a pixi-style pypi-dependencies entry to a PyPIRequirement.

    Args:
        name: Package name (toml key).
        value: Either a version string (e.g. ``"*"``, ``">=1.0"``) or a
            pixi-style table such as ``{path="...", editable=True}``.
        anchor_dir: Directory used to resolve relative ``path`` values to
            absolute paths.

    Returns:
        A :class:`PyPIRequirement` with absolute paths.

    Raises:
        ValueError: If the entry shape is not supported.
    """
    if isinstance(value, str):
        raise ValueError(
            f"Env-overrides pypi-dependencies entry for {name!r} uses bare-version "
            f"shorthand ({value!r}). Provide a table with one of: "
            f"path, git, or url."
        )
    if not isinstance(value, dict):
        raise ValueError(
            f"Env-overrides pypi-dependencies entry for {name!r} must be a table, "
            f"got {type(value).__name__}."
        )

    kwargs: dict[str, Any] = {"name": name}
    for key in ("git", "rev", "branch", "tag", "url", "subdirectory"):
        if key in value:
            kwargs[key] = value[key]
    if "extras" in value:
        kwargs["extras"] = list(value["extras"])
    if "editable" in value:
        kwargs["editable"] = bool(value["editable"])
    if "path" in value:
        raw_path = Path(str(value["path"]))
        abs_path = raw_path if raw_path.is_absolute() else (anchor_dir / raw_path).resolve()
        kwargs["path"] = str(abs_path)

    return PyPIRequirement(**kwargs)
