"""Testing utilities for wt-task.

This module provides utilities for mocking task functions during testing,
including a plugin system for loading example return data from files.

Loaders for non-JSON formats (e.g., parquet) are discovered via the
``wt_task.mock_loaders`` entry point group, keeping wt-task free of
heavy dependencies like pandas/geopandas.
"""

from __future__ import annotations

import functools
import importlib
import importlib.metadata
import importlib.resources
import inspect
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from .sync_task import SyncTask


class MockSyncTask(SyncTask[..., Any, Any, Any]):
    """A SyncTask subclass for testing that skips Pydantic validation.

    Mock functions don't have real type annotations, so calling
    ``validate()`` on them would fail.  This subclass makes ``validate()``
    a no-op that returns ``self`` unchanged.

    Examples:
        >>> from wt_task.testing import MockSyncTask
        >>> mock = MockSyncTask(
        ...     func=lambda: 42,
        ...     tags=[],
        ...     description=None,
        ...     task_instance_id=None,
        ... )
        >>> mock.validate() is mock
        True
    """

    def validate(self) -> MockSyncTask:
        """No-op validation for mock tasks.

        Returns:
            self, unchanged.
        """
        return self


def _import_task(anchor: str, func_name: str) -> SyncTask[..., Any, Any, Any]:
    """Import a task-decorated function from a module.

    Args:
        anchor: Dotted module path (e.g. ``"ecoscope_workflows_ext_ecoscope.tasks.io"``).
        func_name: Attribute name within the module (e.g. ``"get_subjectgroup_observations"``).

    Returns:
        The ``SyncTask`` instance bound to *func_name* in *anchor*.

    Raises:
        AssertionError: If the attribute is not a ``SyncTask`` instance.

    Examples:
        >>> from wt_task.testing import _import_task
        >>> # (would normally import a real registered task)
    """
    module = importlib.import_module(anchor)
    attr = getattr(module, func_name)
    assert isinstance(attr, SyncTask), (
        f"{anchor}.{func_name} is {type(attr).__name__}, expected SyncTask"
    )
    return attr


def _env_var_name(anchor: str, func_name: str) -> str:
    """Construct the environment variable name for an example-return override.

    The naming convention is::

        WT_TASK_MOCK_IO__{ANCHOR}_{FUNC_NAME}

    where dots in *anchor* are replaced with underscores and everything is
    uppercased.

    Args:
        anchor: Dotted module path.
        func_name: Function name.

    Returns:
        Environment variable name.

    Examples:
        >>> from wt_task.testing import _env_var_name
        >>> _env_var_name("ecoscope_workflows_ext_ecoscope.tasks.io", "get_obs")
        'WT_TASK_MOCK_IO__ECOSCOPE_WORKFLOWS_EXT_ECOSCOPE_TASKS_IO_GET_OBS'
    """
    return f"WT_TASK_MOCK_IO__{anchor.replace('.', '_').upper()}_{func_name.upper()}"


def _find_example_return_path(anchor: str, func_name: str) -> Path:
    """Locate the example-return file for a given task.

    Resolution order:

    1. **Environment variable override** -- if the env var returned by
       :func:`_env_var_name` is set, its value is used as the file path.
    2. **Package resources** -- ``importlib.resources.files(anchor)`` is
       searched for a file whose stem matches
       ``{func_name_dashed}.example-return`` (underscores in *func_name*
       are converted to dashes).

    Args:
        anchor: Dotted module path that owns the task.
        func_name: Name of the task function.

    Returns:
        Path to the example-return file.

    Raises:
        AssertionError: If zero or more than one matching file is found
            via package resources.
    """
    env_var = _env_var_name(anchor, func_name)
    override = os.environ.get(env_var)
    if override:
        return Path(override)

    func_name_dashed = func_name.replace("_", "-")
    expected_stem = f"{func_name_dashed}.example-return"

    matches = [
        p
        for p in importlib.resources.files(anchor).iterdir()
        if hasattr(p, "name") and Path(p.name).stem == expected_stem
    ]
    assert len(matches) == 1, (
        f"Expected exactly 1 example-return file matching '{expected_stem}.*' "
        f"in {anchor}, found {len(matches)}: {[m.name for m in matches]}"
    )
    # importlib.resources traversables may not be real Paths; resolve via str
    return Path(str(matches[0]))


def _load_json(path: Path) -> Any:
    """Load a JSON file.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON content.
    """
    with open(path) as f:
        return json.load(f)


@functools.lru_cache(maxsize=1)
def _discover_loaders() -> dict[str, Callable[[Path], Any]]:
    """Discover example-return loaders from entry points.

    Built-in loaders:
        - ``.json`` -- always available (stdlib ``json``).

    Additional loaders are discovered from the ``wt_task.mock_loaders``
    entry point group.  Each entry point's *name* is used (with a leading
    dot) as the file extension key.

    Returns:
        Mapping from file extension (e.g. ``".json"``, ``".parquet"``)
        to a callable that accepts a :class:`~pathlib.Path` and returns
        the loaded data.

    Examples:
        >>> from wt_task.testing import _discover_loaders
        >>> loaders = _discover_loaders()
        >>> ".json" in loaders
        True
    """
    loaders: dict[str, Callable[[Path], Any]] = {".json": _load_json}
    for ep in importlib.metadata.entry_points(group="wt_task.mock_loaders"):
        loaders[f".{ep.name}"] = ep.load()
    return loaders


def _load_example_return(path: Path) -> Any:
    """Load example-return data by dispatching on file extension.

    Args:
        path: Path to the example-return file.

    Returns:
        The loaded data.

    Raises:
        ValueError: If no loader is registered for the file's extension.
    """
    loaders = _discover_loaders()
    ext = path.suffix
    if ext not in loaders:
        registered = ", ".join(sorted(loaders.keys()))
        raise ValueError(
            f"No loader registered for extension '{ext}'. "
            f"Registered loaders: {registered}. "
            f"Install a package that provides a 'wt_task.mock_loaders' "
            f"entry point for '{ext}' files."
        )
    return loaders[ext](path)


def create_task_magicmock(anchor: str, func_name: str) -> MockSyncTask:
    """Create a mock task that returns pre-loaded example data.

    This is the main entry point for mocking I/O tasks during testing.
    It imports the real task to obtain its function signature, loads
    example return data from a file, and returns a :class:`MockSyncTask`
    whose underlying function is a :class:`~unittest.mock.MagicMock`
    with the correct call signature and a fixed return value.

    Args:
        anchor: Dotted module path containing the real task
            (e.g. ``"ecoscope_workflows_ext_ecoscope.tasks.io"``).
        func_name: Name of the task function
            (e.g. ``"get_subjectgroup_observations"``).

    Returns:
        A ``MockSyncTask`` that, when called, returns the example data.

    Examples:
        >>> # create_task_magicmock("my_package.tasks", "fetch_data")
        >>> # Returns a MockSyncTask whose calls return the example data.
    """
    real_task = _import_task(anchor, func_name)
    example_path = _find_example_return_path(anchor, func_name)
    example_data = _load_example_return(example_path)

    sig = inspect.signature(real_task.func)
    mock_func = MagicMock(spec=real_task.func, return_value=example_data)
    mock_func.__signature__ = sig

    return MockSyncTask(
        func=mock_func,
        tags=real_task.tags,
        description=real_task.description,
        task_instance_id=real_task.task_instance_id,
    )
