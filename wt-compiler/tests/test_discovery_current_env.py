"""Tests for current-environment (solve-free) task discovery."""

import json
from unittest.mock import MagicMock, patch

import pytest
from wt_contracts.registry import RegistryOutput

from wt_compiler.artifacts import WorkflowArtifacts
from wt_compiler.compiler import compile_workflow_from_env
from wt_compiler.discovery import (
    DiscoveryResult,
    _registry_output_to_known_tasks,
    discover_tasks_from_current_env,
    populate_known_tasks_from_current_env,
)
from wt_compiler.exceptions import RegistryExecutionError, RegistryNotFoundInEnvError
from wt_compiler.spec import known_tasks


def _registry_json(entries=None):
    """Build a minimal wt-registry --format json payload."""
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


class TestRegistryOutputToKnownTasks:
    """Tests for the shared RegistryOutput -> known_tasks conversion helper."""

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


class TestDiscoverTasksFromCurrentEnv:
    """Tests for discover_tasks_from_current_env."""

    @patch("wt_compiler.discovery.subprocess.run")
    def test_parses_registry_output(self, mock_run, tmp_path):
        fake_exe = tmp_path / "wt-registry"
        fake_exe.touch()
        mock_run.return_value = MagicMock(
            stdout=json.dumps(_registry_json()), stderr="", returncode=0
        )

        result = discover_tasks_from_current_env(registry_exe=fake_exe)

        assert isinstance(result, DiscoveryResult)
        assert result.records == []  # no solve happened
        assert result.tasks["calculate"]["mypackage.tasks"].description == "Calculate something"
        # No solve/install path should be invoked -- only the registry subprocess.
        mock_run.assert_called_once()

    @patch("wt_compiler.discovery.subprocess.run")
    def test_resolves_exe_from_path(self, mock_run, tmp_path):
        fake_exe = tmp_path / "wt-registry"
        fake_exe.touch()
        mock_run.return_value = MagicMock(
            stdout=json.dumps(_registry_json()), stderr="", returncode=0
        )
        with patch("wt_compiler.discovery.shutil.which", return_value=str(fake_exe)) as which:
            discover_tasks_from_current_env()
        which.assert_called_once_with("wt-registry")

    @patch("wt_compiler.discovery.subprocess.run")
    def test_forwards_package_flags(self, mock_run, tmp_path):
        fake_exe = tmp_path / "wt-registry"
        fake_exe.touch()
        mock_run.return_value = MagicMock(
            stdout=json.dumps(_registry_json()), stderr="", returncode=0
        )
        discover_tasks_from_current_env(
            packages=["pkg.tasks", "other.tasks"], registry_exe=fake_exe
        )
        cli_args = mock_run.call_args[0][0]
        assert cli_args[:3] == [str(fake_exe), "--format", "json"]
        assert "--package" in cli_args
        assert "pkg.tasks" in cli_args
        assert "other.tasks" in cli_args

    def test_missing_on_path_raises(self):
        with (
            patch("wt_compiler.discovery.shutil.which", return_value=None),
            pytest.raises(RegistryNotFoundInEnvError),
        ):
            discover_tasks_from_current_env()

    def test_explicit_missing_exe_raises(self, tmp_path):
        with pytest.raises(RegistryNotFoundInEnvError):
            discover_tasks_from_current_env(registry_exe=tmp_path / "nope")

    @patch("wt_compiler.discovery.subprocess.run")
    def test_nonzero_exit_raises(self, mock_run, tmp_path):
        fake_exe = tmp_path / "wt-registry"
        fake_exe.touch()
        mock_run.return_value = MagicMock(stdout="", stderr="boom", returncode=1)
        with pytest.raises(RegistryExecutionError):
            discover_tasks_from_current_env(registry_exe=fake_exe)


class TestPopulateKnownTasksFromCurrentEnv:
    """Tests for populate_known_tasks_from_current_env."""

    def test_clears_and_updates_global(self):
        known_tasks.clear()
        known_tasks["stale"] = {"old.module": MagicMock()}
        fake = DiscoveryResult(
            tasks=_registry_output_to_known_tasks(RegistryOutput.model_validate(_registry_json())),
            records=[],
        )
        with patch(
            "wt_compiler.discovery.discover_tasks_from_current_env", return_value=fake
        ) as disc:
            result = populate_known_tasks_from_current_env(packages=["pkg.tasks"])
        disc.assert_called_once()
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
                "wt_compiler.compiler.populate_known_tasks_from_current_env",
                return_value=DiscoveryResult(tasks={}, records=[]),
            ) as pop,
            patch("wt_compiler.discovery.solve") as solve,
        ):
            artifacts = compile_workflow_from_env(spec_yaml, progress=False)

        pop.assert_called_once()
        solve.assert_not_called()  # the whole point: no ephemeral dependency solve
        assert isinstance(artifacts, WorkflowArtifacts)

    def test_forwards_discover_packages(self, tmp_path):
        spec_yaml = tmp_path / "spec.yaml"
        spec_yaml.write_text("id: test_workflow\nrequirements: []\nworkflow: []\n")

        with patch(
            "wt_compiler.compiler.populate_known_tasks_from_current_env",
            return_value=DiscoveryResult(tasks={}, records=[]),
        ) as pop:
            compile_workflow_from_env(spec_yaml, progress=False, discover_packages=["pkg.tasks"])

        assert pop.call_args.kwargs["packages"] == ["pkg.tasks"]
