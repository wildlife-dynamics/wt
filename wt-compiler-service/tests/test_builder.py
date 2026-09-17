"""Tests for the builder: compile-to-disk + build registry (compile mocked)."""

from unittest.mock import MagicMock, patch

import pytest

from wt_compiler_service import builder


@pytest.fixture(autouse=True)
def _clear_registry():
    builder._BUILDS.clear()
    yield
    builder._BUILDS.clear()


def _fake_artifacts(release_dir):
    """A stand-in for WorkflowArtifacts whose dump() writes the files build() reads."""
    art = MagicMock()
    art.release_name = "wt-demo-workflow"
    art.package_name = "wt_demo_workflow"
    art.release_dir = release_dir

    def _dump(clobber=True):
        release_dir.mkdir(parents=True, exist_ok=True)
        # _bump_version reads the README's params fingerprint.
        (release_dir / "README.md").write_text(f"```yaml\nparams_sha256: {'a' * 64}\n```\n")
        pkg = release_dir / "wt_demo_workflow"
        (pkg / "dags").mkdir(parents=True, exist_ok=True)
        (pkg / "dags" / "run_sequential.py").write_text("DAG SOURCE\n")
        (pkg / "params.json").write_text('{"properties": {"a": {}}}')

    art.dump.side_effect = _dump
    return art


def test_build_compiles_and_registers(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "_BUILD_ROOT", tmp_path / "builds")
    monkeypatch.setattr(builder, "_VERSIONS_DIR", tmp_path / "versions")
    art = _fake_artifacts(tmp_path / "rel" / "wt-demo-workflow")
    fake_spec = MagicMock(flat_workflow=[1, 2])

    with (
        patch.object(builder, "compile_spec_in_process", return_value=art) as compile_fn,
        patch.object(builder.Spec, "model_validate", return_value=fake_spec),
    ):
        build, cached = builder.build({"id": "demo"}, variant="gcp")

    compile_fn.assert_called_once()
    assert cached is False
    assert len(build.build_id) == 16
    assert build.release_name == "wt-demo-workflow"
    assert build.package_name == "wt_demo_workflow"
    assert build.dag == "DAG SOURCE\n"
    assert build.params_schema == {"properties": {"a": {}}}
    assert build.n_tasks == 2
    assert build.results_env_var == "WT_RESULTS"  # default
    assert build.version == "0.1.0"  # first compile
    assert compile_fn.call_args.kwargs["results_env_var"] == "WT_RESULTS"
    assert builder.get_build(build.build_id) is build


def test_bump_version_evolves(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "_VERSIONS_DIR", tmp_path / "versions")
    release_dir = tmp_path / "rel"
    release_dir.mkdir()

    def _readme(sha: str) -> None:
        (release_dir / "README.md").write_text(f"```yaml\nparams_sha256: {sha}\n```\n")

    _readme("a" * 64)
    assert builder._bump_version("wf", release_dir) == "0.1.0"  # first compile
    _readme("a" * 64)
    assert builder._bump_version("wf", release_dir) == "0.2.0"  # same params -> minor
    _readme("b" * 64)
    assert builder._bump_version("wf", release_dir) == "1.0.0"  # params changed -> major
    assert (release_dir / "VERSION.yaml").exists()


def test_build_is_cached_by_content(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "_BUILD_ROOT", tmp_path / "builds")
    monkeypatch.setattr(builder, "_VERSIONS_DIR", tmp_path / "versions")
    art = _fake_artifacts(tmp_path / "rel" / "wt-demo-workflow")
    fake_spec = MagicMock(flat_workflow=[1])

    with (
        patch.object(builder, "compile_spec_in_process", return_value=art),
        patch.object(builder.Spec, "model_validate", return_value=fake_spec),
    ):
        first, cached1 = builder.build({"id": "demo"})

    # Second call for the same content must not recompile.
    with patch.object(builder, "compile_spec_in_process") as compile_fn:
        second, cached2 = builder.build({"id": "demo"})

    assert cached1 is False
    assert cached2 is True
    assert second is first
    compile_fn.assert_not_called()


def test_get_build_unknown_returns_none():
    assert builder.get_build("does-not-exist") is None
