"""Tests for CLI functionality."""

import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from wt_registry import register
from wt_registry.cli import (
    _traverse_module,
    auto_discover,
    discover_public_paths,
    filter_by_function_names,
    main,
    serialize_entries,
)
from wt_registry.models import RegistryEntry, RegistryMetadata
from wt_registry.registry import clear_registry, get_registry, register_entry


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    """Clear the registry before each test for isolation."""
    clear_registry()


def test_cli_json_format_default(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that default CLI output is JSON format."""

    def test_func(x: int) -> str:
        return str(x)

    register(title="Test", description="Test function")(test_func)

    with patch.object(sys, "argv", ["wt-registry"]):
        main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert isinstance(data, dict)
    assert len(data) > 0


def test_cli_json_format_explicit(capsys: pytest.CaptureFixture[str]) -> None:
    """Test explicit --format json argument."""

    def test_func(x: int) -> str:
        return str(x)

    register(title="Test", description="Test function")(test_func)

    with patch.object(sys, "argv", ["wt-registry", "--format", "json"]):
        main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert isinstance(data, dict)


def test_cli_pretty_format(capsys: pytest.CaptureFixture[str]) -> None:
    """Test --format pretty output."""

    def pretty_func(x: int) -> str:
        return str(x)

    register(title="Pretty Function", description="A pretty function", tags=["test", "pretty"])(
        pretty_func
    )

    with patch.object(sys, "argv", ["wt-registry", "--format", "pretty"]):
        main()

    captured = capsys.readouterr()
    output = captured.out

    assert "===" in output
    assert "Title: Pretty Function" in output
    assert "Description: A pretty function" in output
    assert "Tags: test, pretty" in output
    assert "Deprecated: No" in output


def test_cli_empty_registry(capsys: pytest.CaptureFixture[str]) -> None:
    """Test CLI with empty registry."""
    with patch.object(sys, "argv", ["wt-registry"]):
        main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    # New format: RegistryOutput with entries and version
    assert data == {"entries": {}, "version": "1.0.0"}


def test_cli_filter_single_function(capsys: pytest.CaptureFixture[str]) -> None:
    """Test filtering by a single function name."""

    def func1(x: int) -> str:
        return str(x)

    def func2(y: int) -> str:
        return str(y)

    register(title="Function 1", description="First function")(func1)
    register(title="Function 2", description="Second function")(func2)

    # Function name includes <locals> for functions defined in test functions
    with patch.object(
        sys,
        "argv",
        [
            "wt-registry",
            "--function",
            "test_cli_filter_single_function.<locals>.func1",
        ],
    ):
        main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    # New format: RegistryOutput with entries and version
    assert len(data["entries"]) == 1
    # Find the entry with function_name containing "func1"
    func1_entries = [v for v in data["entries"].values() if "func1" in v["function_name"]]
    assert len(func1_entries) == 1


def test_cli_filter_multiple_functions(capsys: pytest.CaptureFixture[str]) -> None:
    """Test filtering by multiple function names."""

    def func1(x: int) -> str:
        return str(x)

    def func2(y: int) -> str:
        return str(y)

    def func3(z: int) -> str:
        return str(z)

    register(title="Function 1", description="First")(func1)
    register(title="Function 2", description="Second")(func2)
    register(title="Function 3", description="Third")(func3)

    # Function names include <locals> for functions defined in test functions
    with patch.object(
        sys,
        "argv",
        [
            "wt-registry",
            "--function",
            "test_cli_filter_multiple_functions.<locals>.func1",
            "--function",
            "test_cli_filter_multiple_functions.<locals>.func3",
        ],
    ):
        main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    # New format: RegistryOutput with entries and version
    assert len(data["entries"]) == 2
    function_names = [v["function_name"] for v in data["entries"].values()]
    # Check that func1 and func3 are present, func2 is not
    assert any("func1" in name for name in function_names)
    assert any("func3" in name for name in function_names)
    assert not any("func2" in name for name in function_names)


def test_cli_filter_function_not_found(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that non-existent function names don't cause errors."""

    def real_func(x: int) -> str:
        return str(x)

    register(title="Real Function", description="A real function")(real_func)

    # Request a function that doesn't exist - should not error
    with patch.object(sys, "argv", ["wt-registry", "--function", "nonexistent"]):
        main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    # Should return RegistryOutput with empty entries since no functions match
    assert data == {"entries": {}, "version": "1.0.0"}


def test_cli_filter_function_partial_match(capsys: pytest.CaptureFixture[str]) -> None:
    """Test filtering when some functions exist and some don't."""

    def real_func(x: int) -> str:
        return str(x)

    register(title="Real Function", description="A real function")(real_func)

    # Use correct function name including <locals>, plus one that doesn't exist
    with patch.object(
        sys,
        "argv",
        [
            "wt-registry",
            "--function",
            "test_cli_filter_function_partial_match.<locals>.real_func",
            "--function",
            "fake_func",
        ],
    ):
        main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    # Should only include real_func
    assert len(data["entries"]) == 1
    function_names = [v["function_name"] for v in data["entries"].values()]
    assert any("real_func" in name for name in function_names)


def test_cli_filter_no_functions_match(capsys: pytest.CaptureFixture[str]) -> None:
    """Test when all specified functions don't exist."""

    def some_func(x: int) -> str:
        return str(x)

    register(title="Some Function", description="Some function")(some_func)

    with patch.object(sys, "argv", ["wt-registry", "--function", "fake1", "--function", "fake2"]):
        main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    # Should return RegistryOutput with empty entries
    assert data == {"entries": {}, "version": "1.0.0"}


def test_cli_filter_only_generates_schema_for_selected() -> None:
    """Test that JSON schema is only generated for selected functions."""

    def func1(x: int) -> str:
        return str(x)

    def func2(y: int) -> str:
        return str(y)

    metadata1 = RegistryMetadata(title="Function 1", description="First")
    metadata2 = RegistryMetadata(title="Function 2", description="Second")

    entry1 = RegistryEntry(
        metadata=metadata1,
        module_path="test",
        function_name="func1",
    )
    entry1._func_ref = func1

    entry2 = RegistryEntry(
        metadata=metadata2,
        module_path="test",
        function_name="func2",
    )
    entry2._func_ref = func2

    register_entry(entry1)
    register_entry(entry2)

    registry = get_registry()

    # Filter to only include func1
    filtered = filter_by_function_names(registry, ["func1"])

    assert len(filtered) == 1
    assert "test.func1" in filtered

    # Serialize only the filtered entries
    registry_output = serialize_entries(filtered)

    # Only func1 should be in the output
    assert len(registry_output.entries) == 1
    assert "test.func1" in registry_output.entries
    assert "test.func2" not in registry_output.entries

    # json_schema should be present for func1
    assert registry_output.entries["test.func1"].json_schema is not None


def test_cli_deprecated_function_json(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that deprecated functions are correctly represented in JSON output."""

    def old_func(x: int) -> int:
        return x

    register(
        title="Old Function",
        description="An old function",
        deprecated=True,
        deprecation_message="Use new_func instead",
    )(old_func)

    with patch.object(sys, "argv", ["wt-registry"]):
        main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    # New format: RegistryOutput with entries and version
    entry = next(iter(data["entries"].values()))
    assert entry["metadata"]["deprecated"] is True
    assert entry["metadata"]["deprecation_message"] == "Use new_func instead"


def test_cli_deprecated_function_pretty(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that deprecated functions are correctly represented in pretty format."""

    def old_func(x: int) -> int:
        return x

    register(
        title="Old Function",
        description="An old function",
        deprecated=True,
        deprecation_message="Use new_func instead",
    )(old_func)

    with patch.object(sys, "argv", ["wt-registry", "--format", "pretty"]):
        main()

    captured = capsys.readouterr()
    output = captured.out

    assert "Deprecated: Yes (Use new_func instead)" in output


def test_cli_function_with_no_tags(capsys: pytest.CaptureFixture[str]) -> None:
    """Test function with empty tags list."""

    def no_tags_func(x: int) -> str:
        return str(x)

    register(title="No Tags Function", description="Function without tags")(no_tags_func)

    with patch.object(sys, "argv", ["wt-registry", "--format", "pretty"]):
        main()

    captured = capsys.readouterr()
    output = captured.out

    # Should not include Tags line when there are no tags
    assert "Title: No Tags Function" in output
    # Tags line should not appear for empty tags
    lines = output.split("\n")
    tags_lines = [line for line in lines if line.startswith("Tags:")]
    assert len(tags_lines) == 0


def test_cli_duplicate_function_names_different_modules(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test two functions with same name but different modules."""

    def helper_func(x: int) -> str:
        return str(x)

    # Create two entries with same function name but different modules
    metadata1 = RegistryMetadata(title="Helper 1", description="First helper")
    entry1 = RegistryEntry(
        metadata=metadata1,
        module_path="module1",
        function_name="helper",
    )
    entry1._func_ref = helper_func

    metadata2 = RegistryMetadata(title="Helper 2", description="Second helper")
    entry2 = RegistryEntry(
        metadata=metadata2,
        module_path="module2",
        function_name="helper",
    )
    entry2._func_ref = helper_func

    register_entry(entry1)
    register_entry(entry2)

    # Filter by function name "helper" - should get both
    with patch.object(sys, "argv", ["wt-registry", "--function", "helper"]):
        main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    # Both entries should be included
    assert len(data["entries"]) == 2
    assert "module1.helper" in data["entries"]
    assert "module2.helper" in data["entries"]


def test_cli_json_compact_default(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that default JSON output is compact (single line, no indentation)."""

    def compact_func(x: int) -> str:
        return str(x)

    register(title="Compact Test", description="Test compact output")(compact_func)

    with patch.object(sys, "argv", ["wt-registry"]):
        main()

    captured = capsys.readouterr()
    output = captured.out

    # Compact JSON should not have newlines in the middle (only trailing newline from print)
    # Remove the trailing newline from print, then check there are no other newlines
    output_without_trailing = output.rstrip("\n")
    assert "\n" not in output_without_trailing, "Compact JSON should be single line"

    # Verify it's still valid JSON
    data = json.loads(output)
    assert isinstance(data, dict)
    assert len(data) > 0


def test_cli_json_pretty_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that --pretty flag produces indented JSON output."""

    def pretty_func(x: int) -> str:
        return str(x)

    register(title="Pretty Test", description="Test pretty output")(pretty_func)

    with patch.object(sys, "argv", ["wt-registry", "--pretty"]):
        main()

    captured = capsys.readouterr()
    output = captured.out

    # Pretty JSON should have newlines and indentation
    assert "\n" in output, "Pretty JSON should have newlines"
    # Check for indentation (spaces at start of lines)
    lines = output.split("\n")
    indented_lines = [line for line in lines if line.startswith("  ")]
    assert len(indented_lines) > 0, "Pretty JSON should have indented lines"

    # Verify it's still valid JSON
    data = json.loads(output)
    assert isinstance(data, dict)
    assert len(data) > 0


def test_cli_json_compact_with_format_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """Test compact output with explicit --format json (no --pretty)."""

    def compact_func(x: int) -> str:
        return str(x)

    register(title="Compact Test", description="Test compact output")(compact_func)

    with patch.object(sys, "argv", ["wt-registry", "--format", "json"]):
        main()

    captured = capsys.readouterr()
    output = captured.out

    # Should be compact
    output_without_trailing = output.rstrip("\n")
    assert "\n" not in output_without_trailing, "Compact JSON should be single line"

    data = json.loads(output)
    assert isinstance(data, dict)


def test_cli_json_pretty_with_format_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that --pretty works with --format json."""

    def pretty_func(x: int) -> str:
        return str(x)

    register(title="Pretty Test", description="Test pretty output")(pretty_func)

    with patch.object(sys, "argv", ["wt-registry", "--format", "json", "--pretty"]):
        main()

    captured = capsys.readouterr()
    output = captured.out

    # Should be pretty
    assert "\n" in output
    lines = output.split("\n")
    indented_lines = [line for line in lines if line.startswith("  ")]
    assert len(indented_lines) > 0

    data = json.loads(output)
    assert isinstance(data, dict)


def test_cli_pretty_flag_doesnt_affect_pretty_format(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that --pretty flag doesn't affect --format pretty (text) output."""

    def text_func(x: int) -> str:
        return str(x)

    register(title="Text Test", description="Test text output", tags=["test"])(text_func)

    # Get output without --pretty
    with patch.object(sys, "argv", ["wt-registry", "--format", "pretty"]):
        main()
    captured = capsys.readouterr()
    output_without_flag = captured.out

    # Get output with --pretty
    with patch.object(sys, "argv", ["wt-registry", "--format", "pretty", "--pretty"]):
        main()
    captured = capsys.readouterr()
    output_with_flag = captured.out

    # Both should produce the same text output
    assert output_without_flag == output_with_flag
    assert "===" in output_with_flag
    assert "Title: Text Test" in output_with_flag


# --- Tests for public path discovery ---


class TestDiscoverPublicPaths:
    """Tests for discover_public_paths() and _traverse_module() functions."""

    def test_discover_public_paths_finds_reexported_function(self) -> None:
        """Test that discover_public_paths finds a function re-exported in __init__.py."""
        import wt_registry.cli as cli_module

        # Create a mock function that appears to be defined in a private module
        def my_func(x: int) -> str:
            return str(x)

        my_func.__module__ = "pkg.tasks._internal"

        # Create registry entry for this function
        metadata = RegistryMetadata(title="My Func", description="Test")
        entry = RegistryEntry(
            metadata=metadata,
            module_path="pkg.tasks._internal",
            function_name="my_func",
        )
        entry._func_ref = my_func
        registry = {"pkg.tasks._internal.my_func": entry}

        # Create a simple namespace object to act as a module
        mock_module = types.SimpleNamespace(__name__="pkg.tasks", my_func=my_func)

        import importlib

        with patch.object(importlib, "import_module", return_value=mock_module):
            with patch.object(
                cli_module,
                "getmembers",
                return_value=[("my_func", my_func)],
            ):
                public_paths = discover_public_paths(registry, ["pkg.tasks"])

        # Should find the public path
        assert ("pkg.tasks._internal", "my_func") in public_paths
        assert public_paths[("pkg.tasks._internal", "my_func")] == "pkg.tasks"

    def test_discover_public_paths_returns_empty_when_no_reexport(self) -> None:
        """Test that discover_public_paths returns empty when function is not re-exported."""
        import wt_registry.cli as cli_module

        # Create a mock function
        def my_func(x: int) -> str:
            return str(x)

        my_func.__module__ = "pkg.tasks._internal"

        # Create registry entry
        metadata = RegistryMetadata(title="My Func", description="Test")
        entry = RegistryEntry(
            metadata=metadata,
            module_path="pkg.tasks._internal",
            function_name="my_func",
        )
        entry._func_ref = my_func
        registry = {"pkg.tasks._internal.my_func": entry}

        # Create a simple namespace object that does NOT re-export the function
        mock_module = types.SimpleNamespace(__name__="pkg.tasks")

        import importlib

        with patch.object(importlib, "import_module", return_value=mock_module):
            with patch.object(cli_module, "getmembers", return_value=[]):
                public_paths = discover_public_paths(registry, ["pkg.tasks"])

        # Should not find any public path
        assert ("pkg.tasks._internal", "my_func") not in public_paths

    def test_discover_public_paths_handles_import_error(self) -> None:
        """Test that discover_public_paths handles ImportError gracefully."""
        registry: dict[str, RegistryEntry] = {}

        import importlib

        with patch.object(
            importlib,
            "import_module",
            side_effect=ImportError("Module not found"),
        ):
            public_paths = discover_public_paths(registry, ["nonexistent.package"])

        # Should return empty dict without raising
        assert public_paths == {}

    def test_traverse_module_skips_private_attributes(self) -> None:
        """Test that _traverse_module skips attributes starting with underscore."""
        import wt_registry.cli as cli_module

        # Create a mock function
        def _private_func(x: int) -> str:
            return str(x)

        _private_func.__module__ = "pkg.tasks._internal"

        # Create registry entry
        metadata = RegistryMetadata(title="Private", description="Test")
        entry = RegistryEntry(
            metadata=metadata,
            module_path="pkg.tasks._internal",
            function_name="_private_func",
        )
        entry._func_ref = _private_func
        registry = {"pkg.tasks._internal._private_func": entry}

        # Create simple namespace object
        mock_module = types.SimpleNamespace(__name__="pkg.tasks")
        public_paths: dict[tuple[str, str], str] = {}

        # The mock getmembers returns a private function
        with patch.object(
            cli_module,
            "getmembers",
            return_value=[("_private_func", _private_func)],
        ):
            _traverse_module(mock_module, registry, public_paths, visited=set())

        # Should not find the private function
        assert ("pkg.tasks._internal", "_private_func") not in public_paths

    def test_traverse_module_prevents_infinite_recursion(self) -> None:
        """Test that _traverse_module prevents infinite recursion on circular imports."""
        import wt_registry.cli as cli_module

        # Create a simple namespace object
        mock_module = types.SimpleNamespace(__name__="pkg.tasks")

        registry: dict[str, RegistryEntry] = {}
        public_paths: dict[tuple[str, str], str] = {}
        visited: set[int] = set()

        # First call should work
        with patch.object(cli_module, "getmembers", return_value=[]):
            _traverse_module(mock_module, registry, public_paths, visited)

        # Module should be in visited
        assert id(mock_module) in visited

        # Second call with same module should do nothing (already visited)
        with patch.object(cli_module, "getmembers") as mock_getmembers:
            _traverse_module(mock_module, registry, public_paths, visited)
            # getmembers should not be called since module is already visited
            mock_getmembers.assert_not_called()


class TestSerializeEntriesPublicPaths:
    """Tests for serialize_entries() with public path discovery."""

    def test_serialize_entries_populates_public_module_path(self) -> None:
        """Test that serialize_entries populates public_module_path field."""
        import wt_registry.cli as cli_module

        def my_func(x: int) -> str:
            return str(x)

        my_func.__module__ = "pkg.tasks._internal"

        metadata = RegistryMetadata(title="My Func", description="Test")
        entry = RegistryEntry(
            metadata=metadata,
            module_path="pkg.tasks._internal",
            function_name="my_func",
        )
        entry._func_ref = my_func
        entries = {"pkg.tasks._internal.my_func": entry}

        # Create simple namespace object that re-exports the function
        mock_module = types.SimpleNamespace(__name__="pkg.tasks", my_func=my_func)

        import importlib

        with patch.object(importlib, "import_module", return_value=mock_module):
            with patch.object(
                cli_module,
                "getmembers",
                return_value=[("my_func", my_func)],
            ):
                output = serialize_entries(entries, packages=["pkg.tasks"])

        # Check that public_module_path is populated
        contract_entry = output.entries["pkg.tasks._internal.my_func"]
        assert contract_entry.public_module_path == "pkg.tasks"
        assert contract_entry.module_path == "pkg.tasks._internal"
        # Import statement should use public path
        assert "from pkg.tasks import my_func as my_func" == contract_entry.import_statement

    def test_serialize_entries_falls_back_to_private_path(self) -> None:
        """Test that serialize_entries falls back to private path when no public path found."""

        def my_func(x: int) -> str:
            return str(x)

        my_func.__module__ = "pkg.tasks._internal"

        metadata = RegistryMetadata(title="My Func", description="Test")
        entry = RegistryEntry(
            metadata=metadata,
            module_path="pkg.tasks._internal",
            function_name="my_func",
        )
        entry._func_ref = my_func
        entries = {"pkg.tasks._internal.my_func": entry}

        # No packages provided, so no public path discovery
        output = serialize_entries(entries, packages=None)

        # public_module_path should fall back to module_path
        contract_entry = output.entries["pkg.tasks._internal.my_func"]
        assert contract_entry.public_module_path == "pkg.tasks._internal"
        assert contract_entry.module_path == "pkg.tasks._internal"

    def test_serialize_entries_uses_as_clause_in_import(self) -> None:
        """Test that serialize_entries always uses 'as' clause in import statement."""

        def my_func(x: int) -> str:
            return str(x)

        metadata = RegistryMetadata(title="My Func", description="Test")
        entry = RegistryEntry(
            metadata=metadata,
            module_path="pkg.tasks",
            function_name="my_func",
        )
        entry._func_ref = my_func
        entries = {"pkg.tasks.my_func": entry}

        output = serialize_entries(entries)

        # Import statement should always use "as" clause
        contract_entry = output.entries["pkg.tasks.my_func"]
        assert "as my_func" in contract_entry.import_statement
        assert contract_entry.import_statement == "from pkg.tasks import my_func as my_func"


# --- Tests for auto_discover() entry point discovery ---


class TestAutoDiscover:
    """Tests for auto_discover() using importlib.metadata entry points."""

    def test_auto_discover_calls_entry_points(self) -> None:
        """auto_discover() calls importlib.metadata.entry_points(group='wt_registry')."""
        mock_ep = MagicMock()
        mock_ep.name = "my-pkg"
        mock_ep.value = "my_pkg.tasks"

        with patch("wt_registry.cli.importlib.metadata.entry_points", return_value=[mock_ep]) as mock_eps:
            with patch("wt_registry.cli.importlib.import_module") as mock_import:
                result = auto_discover()

        mock_eps.assert_called_once_with(group="wt_registry")
        mock_import.assert_called_once_with("my_pkg.tasks")
        assert result == ["my_pkg.tasks"]

    def test_auto_discover_multiple_entry_points(self) -> None:
        """auto_discover() imports all discovered entry point modules."""
        ep1 = MagicMock(name="pkg-a", value="pkg_a.tasks")
        ep1.name = "pkg-a"
        ep1.value = "pkg_a.tasks"
        ep2 = MagicMock(name="pkg-b", value="pkg_b.core.tasks")
        ep2.name = "pkg-b"
        ep2.value = "pkg_b.core.tasks"

        with patch("wt_registry.cli.importlib.metadata.entry_points", return_value=[ep1, ep2]):
            with patch("wt_registry.cli.importlib.import_module") as mock_import:
                result = auto_discover()

        assert mock_import.call_count == 2
        mock_import.assert_any_call("pkg_a.tasks")
        mock_import.assert_any_call("pkg_b.core.tasks")
        assert result == ["pkg_a.tasks", "pkg_b.core.tasks"]

    def test_auto_discover_handles_import_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """auto_discover() prints warning and continues when a module fails to import."""
        ep_good = MagicMock()
        ep_good.name = "good-pkg"
        ep_good.value = "good_pkg.tasks"
        ep_bad = MagicMock()
        ep_bad.name = "bad-pkg"
        ep_bad.value = "bad_pkg.tasks"

        def side_effect(module_path: str) -> None:
            if module_path == "bad_pkg.tasks":
                raise ImportError("No module named 'bad_pkg'")

        with patch("wt_registry.cli.importlib.metadata.entry_points", return_value=[ep_good, ep_bad]):
            with patch("wt_registry.cli.importlib.import_module", side_effect=side_effect):
                result = auto_discover()

        # good_pkg should succeed, bad_pkg should fail gracefully
        assert result == ["good_pkg.tasks"]
        captured = capsys.readouterr()
        assert "bad_pkg.tasks" in captured.err
        assert "Warning" in captured.err

    def test_auto_discover_no_entry_points(self) -> None:
        """auto_discover() returns empty list when no entry points are found."""
        with patch("wt_registry.cli.importlib.metadata.entry_points", return_value=[]):
            result = auto_discover()

        assert result == []

    def test_main_calls_auto_discover(self, capsys: pytest.CaptureFixture[str]) -> None:
        """main() calls auto_discover() before processing."""
        with patch("wt_registry.cli.auto_discover", return_value=[]) as mock_ad:
            with patch.object(sys, "argv", ["wt-registry"]):
                main()

        mock_ad.assert_called_once()

    def test_main_combines_auto_discover_and_packages(self, capsys: pytest.CaptureFixture[str]) -> None:
        """main() combines auto-discovered and --package modules for public path discovery."""

        def test_func(x: int) -> str:
            return str(x)

        register(title="Test", description="Test function")(test_func)

        with patch("wt_registry.cli.auto_discover", return_value=["auto_pkg.tasks"]):
            with patch.object(sys, "argv", ["wt-registry", "--package", "manual_pkg.tasks"]):
                with patch("wt_registry.cli.importlib.import_module"):
                    main()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, dict)
        assert "entries" in data
