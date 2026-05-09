"""Generic loader for pixi.toml-shaped dependency fragments.

A pixi.toml fragment is a TOML file declaring per-feature conda and pypi
dependencies in the same shape pixi itself uses:

    [feature.<name>.dependencies]
    pkg = ">=1.0,<2.0"
    other = { version = "*", channel = "conda-forge" }

    [feature.<name>.pypi-dependencies]
    foo = { path = "../foo", editable = true }
    bar = { git = "https://example.invalid/bar.git", tag = "v1.0" }

This module provides parsing, named-channel resolution, conda↔pypi name
collision detection, and a per-feature merge helper that the compiler uses
to combine the bundled :mod:`wt_compiler.default-env-injections.toml`
baseline with a user-supplied ``--env-overrides`` file.

The recognized features are the real pixi.toml feature names —
``default``, ``runner``, and ``test``.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rattler import MatchSpec

from wt_compiler.requirements import (
    CONDA_FORGE_CHANNEL,
    MICROSOFT_CHANNEL,
    RELEASE_CHANNEL,
)
from wt_compiler.spec import PyPIRequirement

RECOGNIZED_FEATURES: tuple[str, ...] = ("default", "runner", "test")

_NAMED_CHANNELS = {
    name: channel
    for name, channel in (
        (CONDA_FORGE_CHANNEL.name, CONDA_FORGE_CHANNEL),
        (RELEASE_CHANNEL.name, RELEASE_CHANNEL),
        (MICROSOFT_CHANNEL.name, MICROSOFT_CHANNEL),
    )
    if name is not None
}
_DEFAULT_CONDA_CHANNEL_NAME = "conda-forge"


def _spec_name(spec: MatchSpec) -> str:
    """Return *spec*'s normalized package name.

    All ``MatchSpec`` instances produced by this module are built from a
    non-empty TOML key, so ``spec.name`` is expected to be set. A
    ``None`` here indicates an internal invariant violation (e.g. a
    refactor mistake or an unexpected rattler change), not a user input
    error — surface it loudly rather than silently filtering.

    Raises:
        ValueError: If ``spec.name`` is ``None``.
    """
    if spec.name is None:
        raise ValueError(
            f"Internal invariant violated: MatchSpec {spec!r} has no name. "
            f"MatchSpecs in this module must always carry the package name "
            f"from their source TOML key."
        )
    return str(spec.name.normalized)


@dataclass
class FeatureSection:
    """Parsed conda + pypi dependency section for one feature.

    Attributes:
        conda: Conda match-specs (rattler ``MatchSpec``) declared under
            ``[feature.<name>.dependencies]``. Each spec has its channel
            resolved to a ``base_url``.
        pypi: PyPI requirements declared under
            ``[feature.<name>.pypi-dependencies]``. Path-form requirements
            have already been resolved to absolute paths.
    """

    conda: list[MatchSpec] = field(default_factory=list)
    pypi: list[PyPIRequirement] = field(default_factory=list)

    def conda_by_name(self) -> dict[str, MatchSpec]:
        """Return conda specs keyed by normalized package name."""
        return {_spec_name(spec): spec for spec in self.conda}

    def pypi_by_name(self) -> dict[str, PyPIRequirement]:
        """Return pypi requirements keyed by package name."""
        return {req.name: req for req in self.pypi}


@dataclass
class PixiTomlFragment:
    """A parsed pixi.toml-shaped dependency fragment.

    Use :meth:`from_file` or :meth:`from_data` to load a fragment.

    Attributes:
        source_path: Absolute path of the source file (used for diagnostics
            and as the anchor for relative pypi ``path`` entries). For
            in-memory fragments built via :meth:`from_data`, this is the
            anchor directory passed by the caller.
        features: Mapping of feature name to its parsed
            :class:`FeatureSection`.
    """

    source_path: Path
    features: dict[str, FeatureSection] = field(default_factory=dict)

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        recognized_features: tuple[str, ...] = RECOGNIZED_FEATURES,
        diagnostic_label: str = "pixi.toml fragment",
    ) -> PixiTomlFragment:
        """Load and parse a fragment file.

        Args:
            path: Path to the TOML file. May be absolute or relative to the
                current working directory.
            recognized_features: Allowed top-level feature names. Subclasses
                / wrappers may extend this set (e.g. to admit the
                wt-compiler-only ``discovery`` pseudo-feature).
            diagnostic_label: Short human label used in error messages
                (e.g. ``"env-overrides file"``).

        Returns:
            A :class:`PixiTomlFragment` with all paths resolved to absolute.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file declares an unrecognized feature, or if
                a malformed conda/pypi entry is found, or if the same
                package name appears in both ``[dependencies]`` and
                ``[pypi-dependencies]`` of the same feature.
        """
        source_path = Path(path).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"{diagnostic_label} not found: {source_path}")
        with source_path.open("rb") as f:
            data = tomllib.load(f)
        return cls.from_data(
            data,
            source_path=source_path,
            recognized_features=recognized_features,
            diagnostic_label=diagnostic_label,
        )

    @classmethod
    def from_data(
        cls,
        data: dict[str, Any],
        *,
        source_path: Path,
        recognized_features: tuple[str, ...] = RECOGNIZED_FEATURES,
        diagnostic_label: str = "pixi.toml fragment",
    ) -> PixiTomlFragment:
        """Parse an already-loaded TOML dict into a fragment.

        Args:
            data: Parsed TOML dict.
            source_path: Absolute path used as anchor for relative pypi
                ``path`` entries and for diagnostics.
            recognized_features: Allowed feature names.
            diagnostic_label: Short human label for error messages.

        Returns:
            A :class:`PixiTomlFragment`.

        Raises:
            ValueError: If the fragment is malformed.
        """
        feature_section = data.get("feature", {})
        if not isinstance(feature_section, dict):
            raise ValueError(f"{diagnostic_label} {source_path} has malformed [feature.*] section.")

        unknown = set(feature_section) - set(recognized_features)
        if unknown:
            raise ValueError(
                f"{diagnostic_label} {source_path} declares unrecognized feature(s): "
                f"{sorted(unknown)}. Recognized features: {list(recognized_features)}."
            )

        anchor_dir = source_path.parent
        features: dict[str, FeatureSection] = {}
        for feat_name, feat_data in feature_section.items():
            features[feat_name] = _parse_feature_section(
                feat_name=feat_name,
                feat_data=feat_data,
                source_path=source_path,
                anchor_dir=anchor_dir,
                diagnostic_label=diagnostic_label,
            )
        return cls(source_path=source_path, features=features)

    def get_feature(self, name: str) -> FeatureSection:
        """Get the :class:`FeatureSection` for *name*, or an empty one."""
        return self.features.get(name, FeatureSection())


def _parse_feature_section(
    *,
    feat_name: str,
    feat_data: Any,  # noqa: ANN401  # raw toml subtree
    source_path: Path,
    anchor_dir: Path,
    diagnostic_label: str,
) -> FeatureSection:
    """Parse a single ``[feature.<name>]`` block.

    Args:
        feat_name: Feature key.
        feat_data: Raw TOML value at ``feature.<name>``.
        source_path: Source file path (for diagnostics).
        anchor_dir: Directory used to resolve relative pypi ``path`` values.
        diagnostic_label: Short human label for error messages.

    Returns:
        A :class:`FeatureSection`.

    Raises:
        ValueError: If the section is malformed or has duplicated names
            across the conda and pypi sub-sections.
    """
    if not isinstance(feat_data, dict):
        raise ValueError(
            f"{diagnostic_label} {source_path}: [feature.{feat_name}] "
            f"must be a table, got {type(feat_data).__name__}."
        )
    section = FeatureSection()

    conda_deps = feat_data.get("dependencies", {})
    if not isinstance(conda_deps, dict):
        raise ValueError(
            f"{diagnostic_label} {source_path}: [feature.{feat_name}.dependencies] must be a table."
        )
    for name, value in conda_deps.items():
        section.conda.append(
            _parse_conda_entry(
                feat_name=feat_name,
                pkg_name=name,
                value=value,
                source_path=source_path,
                diagnostic_label=diagnostic_label,
            )
        )

    pypi_deps = feat_data.get("pypi-dependencies", {})
    if not isinstance(pypi_deps, dict):
        raise ValueError(
            f"{diagnostic_label} {source_path}: "
            f"[feature.{feat_name}.pypi-dependencies] must be a table."
        )
    for name, value in pypi_deps.items():
        section.pypi.append(
            _parse_pypi_entry(
                pkg_name=name,
                value=value,
                anchor_dir=anchor_dir,
            )
        )

    conda_names = {_spec_name(spec) for spec in section.conda}
    pypi_names = {req.name for req in section.pypi}
    overlap = sorted(conda_names & pypi_names)
    if overlap:
        raise ValueError(
            f"{diagnostic_label} {source_path}: feature {feat_name!r} declares "
            f"the same package name in both [feature.{feat_name}.dependencies] "
            f"and [feature.{feat_name}.pypi-dependencies]: {overlap}. Each "
            "package must appear in only one of the two sections."
        )
    return section


def _resolve_channel_to_base_url(channel: str) -> str:
    """Resolve a known channel name or pass through a base_url.

    Args:
        channel: Either a known channel name (``conda-forge``,
            ``ecoscope-workflows``, ``microsoft``) or a full base URL
            (containing ``://``).

    Returns:
        The channel's ``base_url`` if *channel* names a known channel, or
        *channel* itself if it already looks like a URL.

    Raises:
        ValueError: If *channel* is neither a URL nor a known named
            channel.
    """
    if "://" in channel:
        return channel
    known = _NAMED_CHANNELS.get(channel)
    if known is not None:
        return known.base_url
    raise ValueError(
        f"Unknown conda channel {channel!r}. Expected a full base URL "
        f"(containing '://') or one of the known names: "
        f"{sorted(_NAMED_CHANNELS)}."
    )


def _parse_conda_entry(
    *,
    feat_name: str,
    pkg_name: str,
    value: Any,  # noqa: ANN401  # toml entries are dynamic
    source_path: Path,
    diagnostic_label: str,
) -> MatchSpec:
    """Parse one ``[feature.<x>.dependencies]`` entry to a ``MatchSpec``.

    Accepts either:
        - a version string (e.g. ``">=1.0,<2.0"`` or ``"*"``); channel
          defaults to conda-forge.
        - a longform table ``{ version = "...", channel = "..." }``;
          channel may be a known name or a base URL.

    Args:
        feat_name: Feature name (for diagnostics).
        pkg_name: Package name (toml key).
        value: Either a version string or a longform table.
        source_path: Source file path (for diagnostics).
        diagnostic_label: Short human label for error messages.

    Returns:
        A rattler :class:`~rattler.MatchSpec` with channel resolved.

    Raises:
        ValueError: If the entry shape is not supported.
    """
    if isinstance(value, str):
        version = value
        channel_url = _resolve_channel_to_base_url(_DEFAULT_CONDA_CHANNEL_NAME)
    elif isinstance(value, dict):
        version = value.get("version", "*")
        if not isinstance(version, str):
            raise ValueError(
                f"{diagnostic_label} {source_path}: "
                f"[feature.{feat_name}.dependencies] entry for {pkg_name!r} "
                f"has non-string 'version', got {type(version).__name__}."
            )
        channel_raw = value.get("channel", _DEFAULT_CONDA_CHANNEL_NAME)
        if not isinstance(channel_raw, str):
            raise ValueError(
                f"{diagnostic_label} {source_path}: "
                f"[feature.{feat_name}.dependencies] entry for {pkg_name!r} "
                f"has non-string 'channel', got {type(channel_raw).__name__}."
            )
        channel_url = _resolve_channel_to_base_url(channel_raw)
    else:
        raise ValueError(
            f"{diagnostic_label} {source_path}: "
            f"[feature.{feat_name}.dependencies] entry for {pkg_name!r} "
            f"must be a version string or a table, got {type(value).__name__}."
        )

    spec_str = (
        f"{channel_url}::{pkg_name}" if version == "*" else f"{channel_url}::{pkg_name} {version}"
    )
    return MatchSpec(spec_str)


def _parse_pypi_entry(
    *,
    pkg_name: str,
    value: Any,  # noqa: ANN401  # pixi-style entries are dynamic
    anchor_dir: Path,
) -> PyPIRequirement:
    """Convert a pixi-style pypi-dependencies entry to a ``PyPIRequirement``.

    Args:
        pkg_name: Package name (toml key).
        value: Either a bare-version shorthand string (e.g. ``"*"``,
            ``">=1.0"``) or a pixi-style table such as
            ``{path="...", editable=True}``.
        anchor_dir: Directory used to resolve relative ``path`` values to
            absolute paths.

    Returns:
        A :class:`PyPIRequirement` with absolute paths.

    Raises:
        ValueError: If the entry shape is not supported.
    """
    if isinstance(value, str):
        return PyPIRequirement(name=pkg_name, version=value)
    if not isinstance(value, dict):
        raise ValueError(
            f"pypi-dependencies entry for {pkg_name!r} must be a table or version string, "
            f"got {type(value).__name__}."
        )

    kwargs: dict[str, Any] = {"name": pkg_name}
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
    if "version" in value and not any(k in kwargs for k in ("git", "path", "url")):
        kwargs["version"] = value["version"]

    return PyPIRequirement(**kwargs)


def merge_features(
    *,
    base: FeatureSection,
    overrides: FeatureSection,
    suppress_names: set[str],
) -> FeatureSection:
    """Merge a base + an overrides ``FeatureSection`` for one feature.

    Algorithm (in order):
        1. Start from *base*.
        2. Drop any base entry whose name is in *suppress_names* (these
           come from ``spec.yaml requirements:`` — direct or transitive —
           and take precedence over the bundled defaults).
        3. Apply *overrides* entries last. Per-name displacement is
           cross-section: a name declared in either *overrides*'
           ``[dependencies]`` or ``[pypi-dependencies]`` displaces a
           same-name entry on either side of the lower layer.

    Args:
        base: Lower-layer section (typically the bundled defaults).
        overrides: Upper-layer section (typically the user's
            ``--env-overrides`` file).
        suppress_names: Names from ``spec.yaml requirements:`` (and their
            solved-transitive closure) that should be dropped from the base
            layer regardless of whether they appear in overrides.

    Returns:
        A new :class:`FeatureSection` representing the merged result.
    """
    override_names = {
        *(req.name for req in overrides.pypi),
        *(_spec_name(spec) for spec in overrides.conda),
    }
    drop = suppress_names | override_names

    merged_conda: list[MatchSpec] = [spec for spec in base.conda if _spec_name(spec) not in drop]
    merged_pypi: list[PyPIRequirement] = [req for req in base.pypi if req.name not in drop]

    merged_conda.extend(overrides.conda)
    merged_pypi.extend(overrides.pypi)

    return FeatureSection(conda=merged_conda, pypi=merged_pypi)
