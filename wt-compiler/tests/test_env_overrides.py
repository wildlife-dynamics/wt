"""Tests for the env_overrides parser."""

from __future__ import annotations

import pytest

from wt_compiler.env_overrides import EnvOverrides
from wt_compiler.spec import PyPIRequirement


class TestEnvOverridesFromFile:
    """Tests for EnvOverrides.from_file."""

    def test_recognized_features(self, tmp_path):
        """All recognized features parse without error."""
        wt_task_dir = tmp_path / "wt-task"
        wt_task_dir.mkdir()
        wt_runner_dir = tmp_path / "wt-runner"
        wt_runner_dir.mkdir()
        f = tmp_path / "ov.toml"
        f.write_text(
            "[feature.discovery.pypi-dependencies]\n"
            f'wt-task = {{ path = "{wt_task_dir}", editable = true }}\n'
            "[feature.default.pypi-dependencies]\n"
            f'wt-task = {{ path = "{wt_task_dir}", editable = true }}\n'
            "[feature.runner.pypi-dependencies]\n"
            f'wt-runner = {{ path = "{wt_runner_dir}", editable = true }}\n'
            "[feature.test.pypi-dependencies]\n"
        )
        overrides = EnvOverrides.from_file(f)
        assert {"discovery", "default", "runner", "test"} <= set(overrides.features)
        assert overrides.get_feature_pypi_deps("default")[0].name == "wt-task"
        assert overrides.get_feature_pypi_deps("runner")[0].name == "wt-runner"
        assert overrides.get_feature_pypi_deps("test") == []

    def test_unknown_feature_rejected(self, tmp_path):
        """Unknown feature names produce a clear error."""
        f = tmp_path / "ov.toml"
        f.write_text("[feature.bogus.pypi-dependencies]\nfoo = '*'\n")
        with pytest.raises(ValueError, match="unrecognized feature"):
            EnvOverrides.from_file(f)

    def test_missing_file_raises(self, tmp_path):
        """A missing override file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            EnvOverrides.from_file(tmp_path / "nope.toml")

    def test_relative_path_resolves_against_override_dir(self, tmp_path):
        """Relative pypi paths resolve against the override file's directory."""
        sibling = tmp_path / "wt-task"
        sibling.mkdir()
        f = tmp_path / "ov.toml"
        f.write_text(
            '[feature.default.pypi-dependencies]\nwt-task = { path = "wt-task", editable = true }\n'
        )
        overrides = EnvOverrides.from_file(f)
        req = overrides.get_feature_pypi_deps("default")[0]
        assert isinstance(req, PyPIRequirement)
        assert req.path == str(sibling.resolve())
        assert req.editable is True

    def test_conda_dependencies_parsed(self, tmp_path):
        """[feature.<x>.dependencies] entries are parsed as MatchSpecs."""
        f = tmp_path / "ov.toml"
        f.write_text('[feature.default.dependencies]\nfoo = ">=1.0,<2.0"\nbar = "*"\n')
        overrides = EnvOverrides.from_file(f)
        conda = overrides.get_feature_conda_deps("default")
        names = sorted(str(spec.name.normalized) for spec in conda if spec.name)
        assert names == ["bar", "foo"]

    def test_pypi_with_extras(self, tmp_path):
        """Extras are forwarded to the resulting PyPIRequirement."""
        sibling = tmp_path / "wt-task"
        sibling.mkdir()
        f = tmp_path / "ov.toml"
        f.write_text(
            "[feature.runner.pypi-dependencies]\n"
            'wt-task = { path = "wt-task", editable = true, extras = ["gcp"] }\n'
        )
        overrides = EnvOverrides.from_file(f)
        req = overrides.get_feature_pypi_deps("runner")[0]
        assert req.extras == ["gcp"]

    def test_bare_version_string_rejected(self, tmp_path):
        """Bare version strings in pypi-dependencies are unsupported."""
        f = tmp_path / "ov.toml"
        f.write_text("[feature.default.pypi-dependencies]\nfoo = '*'\n")
        with pytest.raises(ValueError, match="bare-version shorthand"):
            EnvOverrides.from_file(f)

    def test_get_feature_returns_empty_for_undeclared(self, tmp_path):
        """get_feature for a feature not declared in the file returns empties."""
        f = tmp_path / "ov.toml"
        f.write_text("[feature.default.pypi-dependencies]\n")
        overrides = EnvOverrides.from_file(f)
        assert overrides.get_feature_pypi_deps("runner") == []
        assert overrides.get_feature_conda_deps("runner") == []
