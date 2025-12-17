"""Tests for CLI functionality."""

import json
import sys
from unittest.mock import patch

import pytest

from wt_registry import register
from wt_registry.cli import filter_by_function_names, main, serialize_entries
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
