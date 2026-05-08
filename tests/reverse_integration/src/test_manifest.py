"""Unit tests for manifest parsing and ``RepoConfig`` id derivation."""

from __future__ import annotations

import pytest

from conftest import RepoConfig, get_repo_configs, load_manifest
from generate_matrix import generate_matrix


class TestRepoConfigId:
    """Tests for ``RepoConfig.id`` ``:env-overrides`` suffixing."""

    def _make(
        self,
        *,
        compile_flags: dict[str, str] | None = None,
        spec_name: str | None = None,
    ) -> RepoConfig:
        return RepoConfig(
            url="https://github.com/example/events",
            ref="main",
            spec_path="spec.yaml",
            generated_path="events-workflow",
            diff_allowlist=["README.md"],
            tests=["recompile"],
            spec_name=spec_name,
            compile_flags=compile_flags,
        )

    def test_bare_id_without_env_overrides(self) -> None:
        assert self._make().id == "events@main"

    def test_id_with_env_overrides(self) -> None:
        cfg = self._make(compile_flags={"env_overrides": "overrides.toml"})
        assert cfg.id == "events@main:env-overrides"

    def test_id_with_other_compile_flags_only(self) -> None:
        cfg = self._make(compile_flags={"variant": "gcp"})
        assert cfg.id == "events@main"

    def test_monorepo_id_with_env_overrides(self) -> None:
        cfg = self._make(
            spec_name="etl",
            compile_flags={"env_overrides": "overrides.toml"},
        )
        assert cfg.id == "events/etl@main:env-overrides"


class TestGetRepoConfigs:
    """Tests for ``get_repo_configs`` required-field validation."""

    def test_missing_diff_allowlist_raises(self) -> None:
        manifest = {
            "repos": [
                {
                    "url": "https://example.com/r",
                    "ref": "main",
                    "tests": ["recompile"],
                }
            ]
        }
        with pytest.raises(ValueError, match="diff_allowlist"):
            get_repo_configs(manifest)

    def test_missing_tests_raises(self) -> None:
        manifest = {
            "repos": [
                {
                    "url": "https://example.com/r",
                    "ref": "main",
                    "diff_allowlist": ["README.md"],
                }
            ]
        }
        with pytest.raises(ValueError, match="tests"):
            get_repo_configs(manifest)

    def test_minimal_valid_entry(self) -> None:
        manifest = {
            "repos": [
                {
                    "url": "https://example.com/r",
                    "ref": "main",
                    "diff_allowlist": ["README.md"],
                    "tests": ["recompile"],
                }
            ]
        }
        configs = get_repo_configs(manifest)
        assert len(configs) == 1
        assert configs[0].diff_allowlist == ["README.md"]
        assert configs[0].tests == ["recompile"]


class TestManifestAnchors:
    """Tests that the real ``manifest.yaml`` correctly applies its two
    merge-key anchors (``*compile_only`` / ``*env_overrides``) to every
    repo entry.
    """

    def test_compile_only_entries_use_strict_pixi_toml_allowlist(self) -> None:
        """Compile-only entries must restrict ``pixi.toml`` to the single
        ``version = "..."`` regex — no file-level allow, no extra patterns.
        """
        cfgs = get_repo_configs(load_manifest())
        compile_only = [c for c in cfgs if "env-overrides" not in c.id]
        assert compile_only, "Expected at least one compile-only entry"
        for cfg in compile_only:
            pixi_entries = [
                e
                for e in cfg.diff_allowlist
                if (isinstance(e, dict) and e.get("file") == "pixi.toml") or e == "pixi.toml"
            ]
            assert pixi_entries == [
                {"file": "pixi.toml", "allowed_variance": [r'(?<=version = ")[^"]*']}
            ], f"{cfg.id}: unexpected pixi.toml entry: {pixi_entries!r}"

    def test_env_overrides_entries_allow_pixi_toml_at_file_level(self) -> None:
        """Env-overrides entries must allow ``pixi.toml`` at the file level
        (string entry), since the injected blocks are too large to launder
        through line-by-line variance.
        """
        cfgs = get_repo_configs(load_manifest())
        env_over = [c for c in cfgs if "env-overrides" in c.id]
        assert env_over, "Expected at least one env-overrides entry"
        for cfg in env_over:
            assert "pixi.toml" in cfg.diff_allowlist, (
                f"{cfg.id}: expected unconditional 'pixi.toml' string entry"
            )


class TestGenerateMatrix:
    """Tests for the matrix generator."""

    def test_matrix_includes_tests_field(self) -> None:
        matrix = generate_matrix()
        entries = matrix["include"]
        assert entries, "Expected at least one matrix entry"
        for entry in entries:
            assert set(entry.keys()) == {"id", "name", "tests"}
            assert isinstance(entry["tests"], list)

    def test_matrix_has_compile_only_and_env_overrides_pairs(self) -> None:
        matrix = generate_matrix()
        ids = {entry["id"] for entry in matrix["include"]}
        # Each :env-overrides id should have a bare sibling.
        env_ids = {i for i in ids if i.endswith(":env-overrides")}
        assert env_ids, "Expected at least one :env-overrides matrix entry"
        for env_id in env_ids:
            bare = env_id.removesuffix(":env-overrides")
            assert bare in ids, f"Missing bare sibling for {env_id}"

    def test_env_overrides_entries_run_generated_tests(self) -> None:
        matrix = generate_matrix()
        for entry in matrix["include"]:
            if entry["id"].endswith(":env-overrides"):
                assert "generated" in entry["tests"]
            else:
                assert entry["tests"] == ["recompile"]
