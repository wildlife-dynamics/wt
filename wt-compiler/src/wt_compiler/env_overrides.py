"""Per-feature environment overrides for wt-compiler.

This module is a thin wrapper around :class:`PixiTomlFragment` that handles
the user-supplied ``--env-overrides`` file. The overrides file shares its
shape with the bundled :mod:`wt_compiler.default-env-injections.toml`
baseline — the wrapper exists only to recognize one additional feature
(``discovery``) that pixi itself does not understand and that wt-compiler
overlays onto its discovery env rather than emitting into the compiled
``pixi.toml``.

The intended use is **development and testing of wt feature branches**:
forcing a compiled package (and the wt-compiler discovery env) to install
``wt-*`` siblings from a local monorepo checkout instead of from released
conda or PyPI packages. It should not be used in production.

The override file is read by wt-compiler only — it is never handed to
pixi. Conventional filename: ``wt-compiler-env-overrides.toml``.

Recognized features:
    - ``default``: emitted as top-level ``[pypi-dependencies]`` /
      ``[dependencies]`` in the compiled pixi.toml.
    - ``runner``: emitted as ``[feature.runner.*]`` in the compiled pixi.toml.
    - ``test``: emitted as ``[feature.test.*]`` in the compiled pixi.toml.
    - ``discovery``: pseudo-feature interpreted by wt-compiler only; deps
      are overlaid into the discovery env via ``uv pip install`` with
      ``--reinstall-package``. Never emitted into the compiled pixi.toml.

Path-based PyPI dependencies are resolved relative to the override file's
own directory (matching pixi.toml semantics).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from wt_compiler.pixi_toml_fragment import (
    RECOGNIZED_FEATURES as _BASE_RECOGNIZED_FEATURES,
)
from wt_compiler.pixi_toml_fragment import (
    FeatureSection,
    PixiTomlFragment,
)

if TYPE_CHECKING:
    from rattler import MatchSpec

    from wt_compiler.spec import PyPIRequirement

DISCOVERY_FEATURE: str = "discovery"
RECOGNIZED_FEATURES: tuple[str, ...] = (*_BASE_RECOGNIZED_FEATURES, DISCOVERY_FEATURE)
_DIAGNOSTIC_LABEL = "Env-overrides file"


@dataclass
class EnvOverrides:
    """Parsed wt-compiler env-overrides file.

    Wraps a :class:`PixiTomlFragment` (covering the real pixi features
    ``default``, ``runner``, ``test``) plus a separate :class:`FeatureSection`
    for the wt-compiler-only ``discovery`` pseudo-feature.

    Use :meth:`from_file` to load and validate an override file.

    Attributes:
        fragment: The pixi-emitted portion of the file (``default``,
            ``runner``, ``test`` features). This is what the compiler
            merges into the compiled pixi.toml.
        discovery: The ``[feature.discovery.*]`` section, overlaid onto
            the wt-compiler discovery env. Empty when not declared.
    """

    fragment: PixiTomlFragment
    discovery: FeatureSection = field(default_factory=FeatureSection)

    @property
    def source_path(self) -> Path:
        """Absolute path of the override file."""
        return self.fragment.source_path

    @property
    def features(self) -> dict[str, FeatureSection]:
        """Mapping of feature name to its parsed section.

        Includes ``discovery`` when present, so callers can iterate over
        every declared feature uniformly.
        """
        result = dict(self.fragment.features)
        if self.discovery.conda or self.discovery.pypi:
            result[DISCOVERY_FEATURE] = self.discovery
        return result

    @classmethod
    def from_file(cls, path: str | Path) -> EnvOverrides:
        """Load and parse an override file.

        Args:
            path: Path to the override toml file. May be absolute or
                relative to the current working directory.

        Returns:
            An :class:`EnvOverrides` instance with all paths resolved to
            absolute.

        Raises:
            FileNotFoundError: If the override file does not exist.
            ValueError: If the file declares an unrecognized feature, a
                malformed conda/pypi entry, or has the same package name
                in both the conda and pypi sections of one feature.
        """
        source_path = Path(path).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"{_DIAGNOSTIC_LABEL} not found: {source_path}")
        with source_path.open("rb") as f:
            data = tomllib.load(f)

        feature_section = data.get("feature", {})
        if not isinstance(feature_section, dict):
            raise ValueError(
                f"{_DIAGNOSTIC_LABEL} {source_path} has malformed [feature.*] section."
            )
        unknown = set(feature_section) - set(RECOGNIZED_FEATURES)
        if unknown:
            raise ValueError(
                f"{_DIAGNOSTIC_LABEL} {source_path} declares unrecognized feature(s): "
                f"{sorted(unknown)}. Recognized features: {list(RECOGNIZED_FEATURES)}."
            )

        # Split out the wt-compiler-only `discovery` block before delegating to
        # PixiTomlFragment, which only admits real pixi features.
        discovery_data = feature_section.pop(DISCOVERY_FEATURE, None)
        fragment = PixiTomlFragment.from_data(
            {"feature": feature_section},
            source_path=source_path,
            diagnostic_label=_DIAGNOSTIC_LABEL,
        )
        if discovery_data is None:
            return cls(fragment=fragment)
        # Build a one-feature fragment for the discovery block, then steal its
        # FeatureSection. This routes the discovery block through the same
        # parsing rules (longform conda, bare-shorthand pypi, conda+pypi
        # collision detection) as the real features.
        discovery_fragment = PixiTomlFragment.from_data(
            {"feature": {DISCOVERY_FEATURE: discovery_data}},
            source_path=source_path,
            recognized_features=(DISCOVERY_FEATURE,),
            diagnostic_label=_DIAGNOSTIC_LABEL,
        )
        discovery_section = discovery_fragment.features.get(DISCOVERY_FEATURE, FeatureSection())
        return cls(fragment=fragment, discovery=discovery_section)

    def get_feature(self, name: str) -> FeatureSection:
        """Get the :class:`FeatureSection` for *name*, or an empty one.

        Args:
            name: Feature name (one of :data:`RECOGNIZED_FEATURES`).

        Returns:
            The parsed :class:`FeatureSection`, or an empty one if the
            feature is not declared in the file.
        """
        if name == DISCOVERY_FEATURE:
            return self.discovery
        return self.fragment.get_feature(name)

    def get_feature_pypi_deps(self, name: str) -> list[PyPIRequirement]:
        """Get the pypi requirements for *name*, or an empty list."""
        return list(self.get_feature(name).pypi)

    def get_feature_conda_deps(self, name: str) -> list[MatchSpec]:
        """Get the conda match-specs for *name*, or an empty list."""
        return list(self.get_feature(name).conda)
