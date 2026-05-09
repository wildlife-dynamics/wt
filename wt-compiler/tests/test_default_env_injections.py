"""Round-trip tests for the bundled default-env-injections.toml.

These tests pin the parsed shape of the bundled defaults to the same set of
match-specs the pre-refactor compiler emitted inline. They catch accidental
drift (a typo, a forgotten channel, a version bump) by failing loudly.
"""

from __future__ import annotations

import pytest
from rattler import MatchSpec

from wt_compiler.compiler import DEFAULT_INJECTIONS_PATH, _load_default_injections
from wt_compiler.requirements import (
    CONDA_FORGE_CHANNEL,
    MICROSOFT_CHANNEL,
    RELEASE_CHANNEL,
)

# Source-of-truth specs the pre-refactor compiler emitted inline.
EXPECTED_SPECS = {
    "default": [
        ("click", ">=8.0.0,<9.0.0", CONDA_FORGE_CHANNEL.base_url),
        ("obstore", ">=0.6.0,<0.7.0", CONDA_FORGE_CHANNEL.base_url),
        ("pydantic", ">=2.0.0,<3.0.0", CONDA_FORGE_CHANNEL.base_url),
        ("ruamel.yaml", ">=0.18.0,<0.19.0", CONDA_FORGE_CHANNEL.base_url),
        ("opentelemetry-api", ">=1.20.0,<2.0.0", CONDA_FORGE_CHANNEL.base_url),
        ("wt-task", ">=0.1.2,<1.0.0", RELEASE_CHANNEL.base_url),
    ],
    "runner": [
        ("wt-runner", ">=0.1.5,<1.0.0", RELEASE_CHANNEL.base_url),
    ],
    "test": [
        ("pandas", "*", CONDA_FORGE_CHANNEL.base_url),
        ("pyarrow", "*", CONDA_FORGE_CHANNEL.base_url),
        ("pytest", "*", CONDA_FORGE_CHANNEL.base_url),
        ("pytest-asyncio", "*", CONDA_FORGE_CHANNEL.base_url),
        ("pytest-check", "*", CONDA_FORGE_CHANNEL.base_url),
        ("pillow", "*", CONDA_FORGE_CHANNEL.base_url),
        ("scikit-image", "*", CONDA_FORGE_CHANNEL.base_url),
        ("syrupy", "*", CONDA_FORGE_CHANNEL.base_url),
        ("playwright", ">=1.52.0", MICROSOFT_CHANNEL.base_url),
    ],
}


def test_default_injections_file_exists():
    """The bundled toml is present alongside the package."""
    assert DEFAULT_INJECTIONS_PATH.exists()


@pytest.mark.parametrize("feature", sorted(EXPECTED_SPECS))
def test_default_injections_match_legacy_inline_specs(feature):
    """Every dep currently inline equals the loaded match-spec, byte-for-byte."""
    fragment = _load_default_injections()
    actual = {
        str(spec.name.normalized): spec
        for spec in fragment.get_feature(feature).conda
        if spec.name is not None
    }
    expected_names = [name for name, _, _ in EXPECTED_SPECS[feature]]
    assert sorted(actual) == sorted(expected_names), (
        f"feature {feature!r}: name set drift — got {sorted(actual)}"
    )

    for name, version, channel_url in EXPECTED_SPECS[feature]:
        spec = actual[name]
        legacy_str = (
            f"{channel_url}::{name}" if version == "*" else f"{channel_url}::{name} {version}"
        )
        legacy = MatchSpec(legacy_str)
        assert spec.channel.base_url == legacy.channel.base_url, (
            f"{name}: channel drift — got {spec.channel.base_url!r}, "
            f"expected {legacy.channel.base_url!r}"
        )
        assert str(spec.version) == str(legacy.version), (
            f"{name}: version drift — got {spec.version!r}, expected {legacy.version!r}"
        )


def test_default_injections_have_no_pypi_entries():
    """Bundled defaults are conda-only; pypi entries belong only in user overrides."""
    fragment = _load_default_injections()
    for feature in EXPECTED_SPECS:
        assert fragment.get_feature(feature).pypi == []
