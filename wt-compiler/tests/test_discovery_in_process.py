"""Tests for in-process (solve-free) task discovery."""

import platform
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from wt_contracts.registry import RegistryOutput

from wt_compiler.artifacts import WorkflowArtifacts
from wt_compiler.compiler import compile_workflow_from_env
from wt_compiler.discovery import (
    DiscoveryResult,
    _registry_output_to_known_tasks,
    discover_tasks_in_process,
    populate_known_tasks_in_process,
)
from wt_compiler.exceptions import InstalledRequirementsError
from wt_compiler.spec import known_tasks


def _registry_json(entries=None):
    """Build a minimal wt-registry output payload."""
    return {
        "entries": entries
        if entries is not None
        else {
            "mypackage.tasks.calculate": {
                "metadata": {
                    "title": "Calculate",
                    "description": "Calculate something",
                    "tags": [],
                },
                "module_path": "mypackage.tasks._internal",
                "public_module_path": "mypackage.tasks",
                "function_name": "calculate",
                "import_statement": "from mypackage.tasks import calculate as calculate",
                "json_schema": {"properties": {}},
            }
        },
        "version": "1.0.0",
    }


@pytest.fixture
def fake_wt_registry(monkeypatch):
    """Install a stub wt_registry package exposing the symbols discovery imports.

    discover_tasks_in_process imports wt_registry lazily inside the function,
    so the stub only has to exist in sys.modules at call time.
    """
    cli = types.ModuleType("wt_registry.cli")
    cli.auto_discover = MagicMock(return_value=["mypackage.tasks"])
    cli.serialize_entries = MagicMock(return_value=RegistryOutput.model_validate(_registry_json()))
    registry_mod = types.ModuleType("wt_registry.registry")
    registry_mod.get_registry = MagicMock(return_value={"sentinel": object()})
    pkg = types.ModuleType("wt_registry")

    monkeypatch.setitem(sys.modules, "wt_registry", pkg)
    monkeypatch.setitem(sys.modules, "wt_registry.cli", cli)
    monkeypatch.setitem(sys.modules, "wt_registry.registry", registry_mod)
    return cli, registry_mod


class TestRegistryOutputToKnownTasks:
    """Tests for the RegistryOutput -> known_tasks conversion shared by all paths."""

    def test_empty_output(self):
        out = RegistryOutput(entries={}, version="1.0.0")
        assert _registry_output_to_known_tasks(out) == {}

    def test_single_entry(self):
        out = RegistryOutput.model_validate(_registry_json())
        tasks = _registry_output_to_known_tasks(out)
        assert "calculate" in tasks
        assert "mypackage.tasks" in tasks["calculate"]
        assert tasks["calculate"]["mypackage.tasks"].registry_ref == 0

    def test_same_name_across_modules_disambiguated(self):
        entries = {
            "pkg_a.tasks.run": {
                "metadata": {"title": "A", "description": "a", "tags": []},
                "module_path": "pkg_a.tasks._a",
                "public_module_path": "pkg_a.tasks",
                "function_name": "run",
                "import_statement": "from pkg_a.tasks import run as run",
                "json_schema": {"properties": {}},
            },
            "pkg_b.tasks.run": {
                "metadata": {"title": "B", "description": "b", "tags": []},
                "module_path": "pkg_b.tasks._b",
                "public_module_path": "pkg_b.tasks",
                "function_name": "run",
                "import_statement": "from pkg_b.tasks import run as run",
                "json_schema": {"properties": {}},
            },
        }
        out = RegistryOutput.model_validate(_registry_json(entries))
        tasks = _registry_output_to_known_tasks(out)
        assert set(tasks["run"]) == {"pkg_a.tasks", "pkg_b.tasks"}
        assert {t.registry_ref for t in tasks["run"].values()} == {0, 1}


class TestDiscoverTasksInProcess:
    """Tests for discover_tasks_in_process."""

    def test_reads_resident_registry(self, fake_wt_registry):
        cli, registry_mod = fake_wt_registry

        result = discover_tasks_in_process()

        assert isinstance(result, DiscoveryResult)
        assert result.records == []  # no solve happened
        assert result.tasks["calculate"]["mypackage.tasks"].description == "Calculate something"
        cli.auto_discover.assert_called_once()
        registry_mod.get_registry.assert_called_once()

    def test_imports_extra_packages(self, fake_wt_registry):
        cli, _ = fake_wt_registry
        with patch("wt_compiler.discovery.importlib.import_module") as import_module:
            discover_tasks_in_process(packages=["extra.tasks"])
        import_module.assert_called_once_with("extra.tasks")
        # auto-discovered modules and the explicit one are both offered to the serializer
        assert cli.serialize_entries.call_args.kwargs["packages"] == [
            "mypackage.tasks",
            "extra.tasks",
        ]

    def test_explicit_package_already_auto_discovered_is_not_duplicated(self, fake_wt_registry):
        cli, _ = fake_wt_registry
        with patch("wt_compiler.discovery.importlib.import_module"):
            discover_tasks_in_process(packages=["mypackage.tasks"])
        assert cli.serialize_entries.call_args.kwargs["packages"] == ["mypackage.tasks"]

    def test_missing_wt_registry_raises_import_error(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "wt_registry", None)
        monkeypatch.setitem(sys.modules, "wt_registry.cli", None)
        with pytest.raises(ImportError):
            discover_tasks_in_process()


class TestPopulateKnownTasksInProcess:
    """Tests for populate_known_tasks_in_process."""

    def test_clears_and_updates_global(self):
        known_tasks.clear()
        known_tasks["stale"] = {"old.module": MagicMock()}
        fake = DiscoveryResult(
            tasks=_registry_output_to_known_tasks(RegistryOutput.model_validate(_registry_json())),
            records=[],
        )
        with patch("wt_compiler.discovery.discover_tasks_in_process", return_value=fake) as disc:
            result = populate_known_tasks_in_process(packages=["pkg.tasks"])
        disc.assert_called_once_with(packages=["pkg.tasks"])
        assert "stale" not in known_tasks
        assert "calculate" in known_tasks
        assert result is fake


class TestCompileWorkflowFromEnv:
    """Tests for the solve-free compile entry point."""

    def test_compiles_without_solving(self, tmp_path):
        spec_yaml = tmp_path / "spec.yaml"
        spec_yaml.write_text(
            """
id: test_workflow
requirements:
  - name: python
    version: ">=3.10"
    channel: conda-forge
workflow: []
"""
        )

        with (
            patch(
                "wt_compiler.compiler.populate_known_tasks_in_process",
                return_value=DiscoveryResult(tasks={}, records=[]),
            ) as pop,
            patch("wt_compiler.discovery.solve") as solve,
        ):
            artifacts = compile_workflow_from_env(spec_yaml, progress=False)

        pop.assert_called_once()
        solve.assert_not_called()  # the whole point: no ephemeral dependency solve
        assert isinstance(artifacts, WorkflowArtifacts)

    def test_wrong_environment_fails_before_discovery(self, tmp_path):
        spec_yaml = tmp_path / "spec.yaml"
        spec_yaml.write_text(
            "id: test_workflow\n"
            "requirements:\n"
            "  - {name: python, version: '<3', channel: conda-forge}\n"
            "workflow: []\n"
        )

        with (
            patch("wt_compiler.compiler.populate_known_tasks_in_process") as pop,
            pytest.raises(InstalledRequirementsError, match="python <3 is required"),
        ):
            compile_workflow_from_env(spec_yaml, progress=False)

        pop.assert_not_called()

    def test_binds_the_package_to_the_installed_versions(self, tmp_path, monkeypatch):
        spec_yaml = tmp_path / "spec.yaml"
        spec_yaml.write_text(
            "id: test_workflow\n"
            "requirements:\n"
            "  - {name: python, version: '>=3.10', channel: conda-forge}\n"
            "workflow: []\n"
        )
        with patch(
            "wt_compiler.compiler.populate_known_tasks_in_process",
            return_value=DiscoveryResult(tasks={}, records=[]),
        ):
            artifacts = compile_workflow_from_env(spec_yaml, progress=False)
        installed = platform.python_version()

        assert f"=={installed}" in artifacts.readme_md  # fingerprint pins

        # Exercise the generated startup check. Only its helpers run, so a stub
        # click (absent from this venv) with a real exception class suffices.
        click = MagicMock()
        click.ClickException = type("ClickException", (Exception,), {})
        monkeypatch.setitem(sys.modules, "click", click)
        cli: dict = {}
        exec(compile(artifacts.package.cli, "cli.py", "exec"), cli)  # noqa: S102
        assert cli["COMPILED_AGAINST"] == {"python": installed}
        cli["_check_compiled_against"]()  # same environment: passes

        cli["COMPILED_AGAINST"]["python"] = "2.7.18"
        with pytest.raises(click.ClickException, match=r"compiled against 2\.7\.18"):
            cli["_check_compiled_against"]()

    def test_forwards_discover_packages(self, tmp_path):
        spec_yaml = tmp_path / "spec.yaml"
        spec_yaml.write_text("id: test_workflow\nrequirements: []\nworkflow: []\n")

        with patch(
            "wt_compiler.compiler.populate_known_tasks_in_process",
            return_value=DiscoveryResult(tasks={}, records=[]),
        ) as pop:
            compile_workflow_from_env(spec_yaml, progress=False, discover_packages=["pkg.tasks"])

        assert pop.call_args.kwargs["packages"] == ["pkg.tasks"]
