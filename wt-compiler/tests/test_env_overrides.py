"""Tests for the env-overrides loader."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from wt_compiler.env_overrides import (
    load_env_overrides_file,
    validate_leaf_only_path_sources,
)
from wt_compiler.pixi_toml_fragment import PixiTomlFragment


class TestLoadEnvOverridesFile:
    """Tests for load_env_overrides_file."""

    def test_recognized_features(self, tmp_path):
        """All recognized features parse without error."""
        wt_task_dir = tmp_path / "wt-task"
        wt_task_dir.mkdir()
        wt_runner_dir = tmp_path / "wt-runner"
        wt_runner_dir.mkdir()
        f = tmp_path / "ov.toml"
        f.write_text(
            "[feature.default.pypi-dependencies]\n"
            f'wt-task = {{ path = "{wt_task_dir}", editable = true }}\n'
            "[feature.runner.pypi-dependencies]\n"
            f'wt-runner = {{ path = "{wt_runner_dir}", editable = true }}\n'
            "[feature.test.pypi-dependencies]\n"
        )
        fragment = load_env_overrides_file(f)
        assert {"default", "runner", "test"} <= set(fragment.features)
        assert fragment.get_feature("default").pypi[0].name == "wt-task"
        assert fragment.get_feature("runner").pypi[0].name == "wt-runner"
        assert fragment.get_feature("test").pypi == []

    def test_unknown_feature_rejected(self, tmp_path):
        """Unknown feature names produce a clear error."""
        f = tmp_path / "ov.toml"
        f.write_text("[feature.bogus.pypi-dependencies]\nfoo = '*'\n")
        with pytest.raises(ValueError, match="unrecognized feature"):
            load_env_overrides_file(f)

    def test_missing_file_raises(self, tmp_path):
        """A missing override file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_env_overrides_file(tmp_path / "nope.toml")

    def test_relative_path_resolves_against_override_dir(self, tmp_path):
        """Relative pypi paths resolve against the override file's directory."""
        sibling = tmp_path / "wt-task"
        sibling.mkdir()
        f = tmp_path / "ov.toml"
        f.write_text(
            '[feature.default.pypi-dependencies]\nwt-task = { path = "wt-task", editable = true }\n'
        )
        fragment = load_env_overrides_file(f)
        req = fragment.get_feature("default").pypi[0]
        assert req.path == str(sibling.resolve())
        assert req.editable is True

    def test_conda_dependencies_parsed(self, tmp_path):
        """[feature.<x>.dependencies] entries are parsed as MatchSpecs."""
        f = tmp_path / "ov.toml"
        f.write_text('[feature.default.dependencies]\nfoo = ">=1.0,<2.0"\nbar = "*"\n')
        fragment = load_env_overrides_file(f)
        conda = fragment.get_feature("default").conda
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
        fragment = load_env_overrides_file(f)
        req = fragment.get_feature("runner").pypi[0]
        assert req.extras == ["gcp"]


class TestLeafOnlyPathSourceGuard:
    """Tests for validate_leaf_only_path_sources."""

    def test_no_path_sources_passes_trivially(self, tmp_path):
        """An env-overrides file with no path sources passes the guard."""
        f = tmp_path / "ov.toml"
        f.write_text('[feature.default.pypi-dependencies]\nfoo = ">=1.0"\nbar = "*"\n')
        fragment = load_env_overrides_file(f)
        # Should not raise.
        validate_leaf_only_path_sources(fragment)

    def test_path_source_without_pyproject_skips(self, tmp_path):
        """A path source whose target lacks pyproject.toml is skipped."""
        sibling = tmp_path / "wt-task"
        sibling.mkdir()
        f = tmp_path / "ov.toml"
        f.write_text(f'[feature.default.pypi-dependencies]\nwt-task = {{ path = "{sibling}" }}\n')
        fragment = load_env_overrides_file(f)
        validate_leaf_only_path_sources(fragment)

    def test_path_source_without_uv_sources_passes(self, tmp_path):
        """A path source whose pyproject lacks [tool.uv.sources] passes."""
        sibling = tmp_path / "wt-task"
        sibling.mkdir()
        (sibling / "pyproject.toml").write_text("[project]\nname = 'wt-task'\n")
        f = tmp_path / "ov.toml"
        f.write_text(f'[feature.default.pypi-dependencies]\nwt-task = {{ path = "{sibling}" }}\n')
        fragment = load_env_overrides_file(f)
        validate_leaf_only_path_sources(fragment)

    def test_transitive_path_source_conflict_rejected(self, tmp_path):
        """Declaring both wt-task AND wt-contracts is rejected (wt-task brings wt-contracts via uv.sources)."""
        wt_task = tmp_path / "wt-task"
        wt_task.mkdir()
        (wt_task / "pyproject.toml").write_text(
            "[project]\nname = 'wt-task'\n\n"
            "[tool.uv.sources]\n"
            'wt-contracts = { path = "../wt-contracts", editable = true }\n'
        )
        wt_contracts = tmp_path / "wt-contracts"
        wt_contracts.mkdir()
        (wt_contracts / "pyproject.toml").write_text("[project]\nname = 'wt-contracts'\n")

        f = tmp_path / "ov.toml"
        f.write_text(
            "[feature.default.pypi-dependencies]\n"
            f'wt-task      = {{ path = "{wt_task}" }}\n'
            f'wt-contracts = {{ path = "{wt_contracts}" }}\n'
        )
        with pytest.raises(ValueError, match="wt-contracts") as exc_info:
            load_env_overrides_file(f)
        msg = str(exc_info.value)
        assert "wt-task" in msg
        assert "5847" in msg
        assert "uv.sources" in msg

    def test_self_referential_uv_source_does_not_trigger(self, tmp_path):
        """A package's own [tool.uv.sources] referencing itself is not flagged."""
        # Edge case: foo's pyproject says [tool.uv.sources] foo = "..."
        # That's a self-reference, not a peer-bringing-foo-in.
        wt_task = tmp_path / "wt-task"
        wt_task.mkdir()
        (wt_task / "pyproject.toml").write_text(
            "[project]\nname = 'wt-task'\n\n"
            "[tool.uv.sources]\n"
            'wt-task = { path = ".", editable = true }\n'
        )
        f = tmp_path / "ov.toml"
        f.write_text(f'[feature.default.pypi-dependencies]\nwt-task = {{ path = "{wt_task}" }}\n')
        fragment = load_env_overrides_file(f)
        # Should not raise: wt-task referencing itself is harmless.
        validate_leaf_only_path_sources(fragment)

    def test_monorepo_fixture_passes(self):
        """The repo's reverse-integration env-overrides fixture passes the guard.

        Sanity-check that the audited fixture continues to satisfy the
        leaf-only rule as the monorepo's uv.sources blocks evolve.
        """
        repo_root = Path(__file__).resolve().parents[2]
        fixture = repo_root / "tests" / "reverse_integration" / "wt-compiler-env-overrides.toml"
        if not fixture.exists():
            pytest.skip(f"reverse-integration fixture not found at {fixture}")
        with fixture.open("rb") as f:
            data = tomllib.load(f)
        fragment = PixiTomlFragment.from_data(
            data,
            source_path=fixture,
            diagnostic_label="reverse-integration fixture",
        )
        validate_leaf_only_path_sources(fragment)
