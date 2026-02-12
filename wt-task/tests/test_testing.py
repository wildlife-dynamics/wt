"""Tests for wt_task.testing module."""

from __future__ import annotations

import importlib.metadata
import json
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wt_task.testing import (
    _discover_loaders,
    _env_var_name,
    _find_example_return_path,
    _import_func,
    _load_example_return,
    create_func_magicmock,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sample_func(x: int, y: str = "hello") -> str:
    """A plain registered function used for testing."""
    return f"{y}: {x}"


# ---------------------------------------------------------------------------
# _import_func
# ---------------------------------------------------------------------------


def test_import_func():
    """_import_func successfully imports a plain registered function."""
    fake_module = types.ModuleType("fake_anchor_module")
    fake_module.my_func = _sample_func  # type: ignore[attr-defined]

    with patch.dict("sys.modules", {"fake_anchor_module": fake_module}):
        result = _import_func("fake_anchor_module", "my_func")

    assert callable(result)
    assert result is _sample_func


def test_import_func_not_callable():
    """_import_func raises AssertionError for non-callable attributes."""
    fake_module = types.ModuleType("fake_module_bad")
    fake_module.not_a_func = "just a string"  # type: ignore[attr-defined]

    with patch.dict("sys.modules", {"fake_module_bad": fake_module}):
        with pytest.raises(AssertionError, match="expected callable"):
            _import_func("fake_module_bad", "not_a_func")


# ---------------------------------------------------------------------------
# _discover_loaders
# ---------------------------------------------------------------------------


def test_discover_loaders_includes_json():
    """Built-in JSON loader is always present."""
    _discover_loaders.cache_clear()
    loaders = _discover_loaders()
    assert ".json" in loaders


def test_discover_loaders_picks_up_entry_points():
    """Mock an entry point; verify it's discovered."""
    _discover_loaders.cache_clear()

    fake_loader = MagicMock(return_value="fake data")
    fake_ep = MagicMock(spec=importlib.metadata.EntryPoint)
    fake_ep.name = "csv"
    fake_ep.load.return_value = fake_loader

    with patch(
        "wt_task.testing.importlib.metadata.entry_points",
        return_value=[fake_ep],
    ):
        loaders = _discover_loaders()

    assert ".csv" in loaders
    assert loaders[".csv"] is fake_loader
    # Clean up for other tests
    _discover_loaders.cache_clear()


# ---------------------------------------------------------------------------
# _load_example_return
# ---------------------------------------------------------------------------


def test_load_example_return_json(tmp_path: Path):
    """Load a .json fixture file."""
    _discover_loaders.cache_clear()
    fixture = tmp_path / "data.json"
    fixture.write_text(json.dumps({"key": "value"}))

    result = _load_example_return(fixture)
    assert result == {"key": "value"}


def test_load_example_return_unknown_extension(tmp_path: Path):
    """Raises ValueError for unregistered extensions."""
    _discover_loaders.cache_clear()
    fixture = tmp_path / "data.xyz"
    fixture.write_text("stuff")

    with pytest.raises(ValueError, match="No loader registered for extension '.xyz'"):
        _load_example_return(fixture)


# ---------------------------------------------------------------------------
# _find_example_return_path
# ---------------------------------------------------------------------------


def test_find_example_return_path_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Env var override works."""
    override_path = tmp_path / "override.json"
    override_path.write_text("{}")
    env_var = _env_var_name("some.module", "my_func")
    monkeypatch.setenv(env_var, str(override_path))

    result = _find_example_return_path("some.module", "my_func")
    assert result == override_path


def test_find_example_return_path_from_package_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Discovery via importlib.resources.files."""
    # Ensure the env var is NOT set
    env_var = _env_var_name("test.anchor", "get_data")
    monkeypatch.delenv(env_var, raising=False)

    # Create a fake file matching the convention: get-data.example-return.json
    fake_file = tmp_path / "get-data.example-return.json"
    fake_file.write_text("{}")

    # A non-matching file to ensure filtering works
    other_file = tmp_path / "other-func.example-return.json"
    other_file.write_text("{}")

    # Mock importlib.resources.files to return the tmp_path contents
    with patch("wt_task.testing.importlib.resources.files") as mock_files:
        mock_files.return_value = tmp_path
        result = _find_example_return_path("test.anchor", "get_data")

    assert result.name == "get-data.example-return.json"


# ---------------------------------------------------------------------------
# create_func_magicmock (end-to-end)
# ---------------------------------------------------------------------------


def test_create_func_magicmock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """End-to-end: creates MagicMock callable that returns example data with correct attributes."""
    # Set up example return file via env var
    example_data = {"result": [1, 2, 3]}
    example_file = tmp_path / "sample-task.example-return.json"
    example_file.write_text(json.dumps(example_data))

    env_var = _env_var_name("fake_pkg.tasks", "sample_task")
    monkeypatch.setenv(env_var, str(example_file))

    # Create a fake module with our plain function
    fake_module = types.ModuleType("fake_pkg.tasks")
    fake_module.sample_task = _sample_func  # type: ignore[attr-defined]

    _discover_loaders.cache_clear()

    with patch.dict("sys.modules", {"fake_pkg.tasks": fake_module}):
        mock_func = create_func_magicmock("fake_pkg.tasks", "sample_task")

    # It should be a plain callable MagicMock
    assert callable(mock_func)
    assert isinstance(mock_func, MagicMock)

    # Function attributes should be copied from the real function
    assert mock_func.__name__ == _sample_func.__name__
    assert mock_func.__module__ == _sample_func.__module__

    # Calling it directly should return the example data
    result = mock_func(x=1, y="test")
    assert result == example_data
