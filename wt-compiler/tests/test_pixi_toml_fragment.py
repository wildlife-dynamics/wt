"""Tests for the generic pixi-toml fragment parser and merge helper."""

from __future__ import annotations

import pytest

from wt_compiler.pixi_toml_fragment import (
    FeatureSection,
    PixiTomlFragment,
    merge_features,
)
from wt_compiler.requirements import (
    CONDA_FORGE_CHANNEL,
    MICROSOFT_CHANNEL,
    RELEASE_CHANNEL,
)


class TestPixiTomlFragmentParsing:
    """Tests for PixiTomlFragment.from_file."""

    def test_default_recognized_features_only(self, tmp_path):
        """Only default/runner/test are accepted by the base fragment."""
        f = tmp_path / "frag.toml"
        f.write_text(
            "[feature.default.dependencies]\nfoo = '*'\n"
            "[feature.runner.dependencies]\nbar = '*'\n"
            "[feature.test.dependencies]\nbaz = '*'\n"
        )
        frag = PixiTomlFragment.from_file(f)
        assert set(frag.features) == {"default", "runner", "test"}

    def test_unknown_feature_rejected(self, tmp_path):
        """Unknown feature names (including discovery) are rejected by the base class."""
        f = tmp_path / "frag.toml"
        f.write_text("[feature.discovery.dependencies]\nfoo = '*'\n")
        with pytest.raises(ValueError, match="unrecognized feature"):
            PixiTomlFragment.from_file(f)

    def test_shorthand_conda_defaults_to_conda_forge(self, tmp_path):
        """`pkg = ">=1.0"` defaults the channel to conda-forge."""
        f = tmp_path / "frag.toml"
        f.write_text('[feature.default.dependencies]\nfoo = ">=1.0,<2.0"\n')
        frag = PixiTomlFragment.from_file(f)
        spec = frag.get_feature("default").conda[0]
        assert spec.channel.base_url == CONDA_FORGE_CHANNEL.base_url

    def test_longform_conda_with_named_channel(self, tmp_path):
        """Longform table with a known channel name resolves to its base_url."""
        f = tmp_path / "frag.toml"
        f.write_text(
            "[feature.default.dependencies]\n"
            'wt-task = { version = ">=0.1.2,<1.0.0", channel = "ecoscope-workflows" }\n'
            'playwright = { version = ">=1.0", channel = "microsoft" }\n'
        )
        frag = PixiTomlFragment.from_file(f)
        deps = {
            str(spec.name.normalized): spec.channel.base_url
            for spec in frag.get_feature("default").conda
            if spec.name is not None
        }
        assert deps["wt-task"] == RELEASE_CHANNEL.base_url
        assert deps["playwright"] == MICROSOFT_CHANNEL.base_url

    def test_longform_conda_with_url_channel(self, tmp_path):
        """A full URL channel is accepted as-is."""
        f = tmp_path / "frag.toml"
        f.write_text(
            "[feature.default.dependencies]\n"
            'foo = { version = ">=1.0", channel = "https://example.invalid/custom/" }\n'
        )
        frag = PixiTomlFragment.from_file(f)
        spec = frag.get_feature("default").conda[0]
        assert spec.channel.base_url == "https://example.invalid/custom/"

    def test_longform_conda_unknown_channel_rejected(self, tmp_path):
        """An unknown channel name (not a URL, not a known alias) is rejected."""
        f = tmp_path / "frag.toml"
        f.write_text(
            '[feature.default.dependencies]\nfoo = { version = ">=1.0", channel = "bogus" }\n'
        )
        with pytest.raises(ValueError, match="Unknown conda channel 'bogus'"):
            PixiTomlFragment.from_file(f)

    def test_longform_conda_default_channel(self, tmp_path):
        """Longform table with no channel defaults to conda-forge."""
        f = tmp_path / "frag.toml"
        f.write_text('[feature.default.dependencies]\nfoo = { version = ">=1.0" }\n')
        frag = PixiTomlFragment.from_file(f)
        spec = frag.get_feature("default").conda[0]
        assert spec.channel.base_url == CONDA_FORGE_CHANNEL.base_url

    def test_pypi_path_resolves_relative_to_source_dir(self, tmp_path):
        """Pypi `path = "..."` resolves relative to the fragment file's directory."""
        sibling = tmp_path / "sib"
        sibling.mkdir()
        f = tmp_path / "frag.toml"
        f.write_text(
            '[feature.default.pypi-dependencies]\nfoo = { path = "sib", editable = true }\n'
        )
        frag = PixiTomlFragment.from_file(f)
        req = frag.get_feature("default").pypi[0]
        assert req.path == str(sibling.resolve())

    def test_pypi_bare_shorthand_accepted(self, tmp_path):
        """Bare-string pypi entries become version-only PyPIRequirements."""
        f = tmp_path / "frag.toml"
        f.write_text('[feature.default.pypi-dependencies]\nfoo = "*"\nbar = ">=1.0"\n')
        frag = PixiTomlFragment.from_file(f)
        deps = {req.name: req for req in frag.get_feature("default").pypi}
        assert deps["foo"].version == "*"
        assert deps["bar"].version == ">=1.0"

    def test_conda_pypi_name_collision_rejected(self, tmp_path):
        """Same package name in both [dependencies] and [pypi-dependencies] is an error."""
        f = tmp_path / "frag.toml"
        f.write_text(
            "[feature.default.dependencies]\nwt-task = '*'\n"
            "[feature.default.pypi-dependencies]\n"
            'wt-task = { path = "/tmp/wt-task" }\n'
        )
        with pytest.raises(ValueError, match="same package name"):
            PixiTomlFragment.from_file(f)

    def test_missing_file_raises(self, tmp_path):
        """A missing fragment file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            PixiTomlFragment.from_file(tmp_path / "missing.toml")

    def test_recognized_features_kwarg_extension(self, tmp_path):
        """Callers may extend the recognized-feature set (for wrappers)."""
        f = tmp_path / "frag.toml"
        f.write_text("[feature.discovery.dependencies]\nfoo = '*'\n")
        frag = PixiTomlFragment.from_file(
            f, recognized_features=("default", "runner", "test", "discovery")
        )
        assert "discovery" in frag.features


class TestMergeFeatures:
    """Tests for merge_features."""

    def _make_fragment(self, dirpath, name: str, body: str) -> FeatureSection:
        """Write a single-feature fragment under *dirpath* and return its section."""
        dirpath.mkdir(parents=True, exist_ok=True)
        f = dirpath / f"{name}.toml"
        f.write_text(body)
        return PixiTomlFragment.from_file(f).get_feature("default")

    def test_overrides_displace_base_by_name(self, tmp_path):
        """Override entries replace base entries of the same name."""
        base = self._make_fragment(
            tmp_path / "base",
            "base",
            '[feature.default.dependencies]\npydantic = ">=2.0,<3.0"\nclick = ">=8.0"\n',
        )
        overrides = self._make_fragment(
            tmp_path / "ov",
            "ov",
            '[feature.default.dependencies]\npydantic = ">=2.5,<3.0"\n',
        )
        merged = merge_features(base=base, overrides=overrides, suppress_names=set())
        names = {str(s.name.normalized): str(s.version) for s in merged.conda if s.name}
        assert names == {"pydantic": ">=2.5,<3.0", "click": ">=8.0"}

    def test_suppress_names_drops_base(self, tmp_path):
        """suppress_names drops the matching base entry without adding anything."""
        base = self._make_fragment(
            tmp_path / "base",
            "base",
            '[feature.default.dependencies]\npydantic = ">=2.0,<3.0"\nclick = ">=8.0"\n',
        )
        merged = merge_features(base=base, overrides=FeatureSection(), suppress_names={"pydantic"})
        names = {str(s.name.normalized) for s in merged.conda if s.name}
        assert names == {"click"}

    def test_pypi_override_displaces_conda(self, tmp_path):
        """A pypi override entry displaces a same-name conda entry from the base."""
        base = self._make_fragment(
            tmp_path / "base",
            "base",
            '[feature.default.dependencies]\nwt-task = ">=0.1"\n',
        )
        sibling = tmp_path / "ov" / "wt-task"
        sibling.mkdir(parents=True)
        overrides = self._make_fragment(
            tmp_path / "ov",
            "ov",
            '[feature.default.pypi-dependencies]\nwt-task = { path = "wt-task" }\n',
        )
        merged = merge_features(base=base, overrides=overrides, suppress_names=set())
        assert all(
            spec.name is None or str(spec.name.normalized) != "wt-task" for spec in merged.conda
        )
        assert [r.name for r in merged.pypi] == ["wt-task"]
