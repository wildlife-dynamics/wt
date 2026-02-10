"""Tests for the @register decorator."""

import pytest

from wt_registry import get_registry, register
from wt_registry.exceptions import (
    DuplicateRegistrationError,
    ValidationError,
)
from wt_registry.registry import clear_registry


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    """Clear the registry before each test for isolation."""
    clear_registry()


def test_register_basic_function() -> None:
    """Test registering a basic function."""

    @register(title="Test Function", description="A test function")
    def test_func(x: int) -> str:
        return str(x)

    registry = get_registry()
    assert len(registry) == 1

    # Check the function is in the registry
    fqn = next(iter(registry.keys()))
    assert "test_func" in fqn

    # Check metadata
    entry = registry[fqn]
    assert entry.metadata.title == "Test Function"
    assert entry.metadata.description == "A test function"


def test_register_with_all_metadata() -> None:
    """Test registering with all metadata fields."""

    @register(
        title="Complex Function",
        description="A function with all metadata",
        tags=["test", "example"],
        deprecated=True,
        deprecation_message="Use new_function instead",
    )
    def complex_func(x: int, y: str) -> bool:
        return True

    registry = get_registry()
    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    assert entry.metadata.title == "Complex Function"
    assert entry.metadata.description == "A function with all metadata"
    assert entry.metadata.tags == ["test", "example"]
    assert entry.metadata.deprecated is True
    assert entry.metadata.deprecation_message == "Use new_function instead"


def test_register_preserves_function() -> None:
    """Test that @register returns the original function unchanged."""

    @register(title="Add", description="Add two numbers")
    def add(a: int, b: int) -> int:
        return a + b

    # Function should still work normally
    assert add(2, 3) == 5
    assert add.__name__ == "add"


def test_register_captures_module_and_name() -> None:
    """Test that register captures the correct module and function name."""

    @register(title="Module Test", description="Test module capture")
    def module_test_func(x: int) -> int:
        return x

    registry = get_registry()
    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    assert "test_decorator" in entry.module_path
    # __qualname__ includes parent scope for nested functions
    assert "module_test_func" in entry.function_name


def test_register_generates_json_schema() -> None:
    """Test that register generates a JSON schema."""

    @register(title="Schema Test", description="Test schema generation")
    def schema_func(x: int, y: str = "default") -> dict[str, int]:
        return {"result": x}

    registry = get_registry()
    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    # Check that json_schema exists and has expected structure
    assert isinstance(entry.json_schema, dict)
    # Pydantic TypeAdapter generates schemas for callables
    assert "type" in entry.json_schema or "$defs" in entry.json_schema


def test_register_duplicate_raises_error() -> None:
    """Test that registering the same function twice raises an error."""

    @register(title="First", description="First registration")
    def duplicate_func(x: int) -> int:
        return x

    # Attempting to register again should fail
    with pytest.raises(DuplicateRegistrationError):

        @register(title="Second", description="Second registration")
        def duplicate_func(x: int) -> int:
            return x * 2


def test_register_untyped_function_raises_error() -> None:
    """Test that accessing schema for untyped function raises ValidationError."""

    @register(title="Untyped", description="Untyped function")
    def untyped_func(x) -> int:  # type: ignore
        return 1

    # Registration succeeds (lazy validation), but accessing schema fails
    registry = get_registry()
    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    with pytest.raises(ValidationError) as exc_info:
        _ = entry.json_schema

    assert "untyped parameters" in str(exc_info.value)


def test_register_no_return_type_raises_error() -> None:
    """Test that accessing schema for function without return type raises ValidationError."""

    @register(title="No Return", description="No return type")
    def no_return_func(x: int):  # type: ignore
        pass

    # Registration succeeds (lazy validation), but accessing schema fails
    registry = get_registry()
    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    with pytest.raises(ValidationError) as exc_info:
        _ = entry.json_schema

    assert "no return type annotation" in str(exc_info.value)


def test_register_async_function_raises_error() -> None:
    """Test that accessing schema for async function raises ValidationError."""

    @register(title="Async", description="Async function")
    async def async_func(x: int) -> str:
        return "test"

    # Registration succeeds (lazy validation), but accessing schema fails
    registry = get_registry()
    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    with pytest.raises(ValidationError) as exc_info:
        _ = entry.json_schema

    assert "Async functions are not supported" in str(exc_info.value)


def test_register_multiple_functions() -> None:
    """Test registering multiple different functions."""

    @register(title="Func1", description="First function")
    def func1(x: int) -> str:
        return str(x)

    @register(title="Func2", description="Second function")
    def func2(y: float) -> int:
        return int(y)

    @register(title="Func3", description="Third function")
    def func3(z: str) -> bool:
        return bool(z)

    registry = get_registry()
    assert len(registry) == 3


def test_register_with_complex_types() -> None:
    """Test registering functions with complex type annotations."""

    @register(title="Complex Types", description="Function with complex types")
    def complex_types(
        data: list[dict[str, int]], mapping: dict[str, list[float]]
    ) -> tuple[str, int, list[str]]:
        return ("result", 42, ["a", "b"])

    registry = get_registry()
    assert len(registry) == 1


def test_register_with_optional_types() -> None:
    """Test registering functions with optional/union types."""

    @register(title="Optional Types", description="Function with optional types")
    def optional_func(x: int | None, y: str | int = "default") -> list[str] | None:
        return None

    registry = get_registry()
    assert len(registry) == 1


def test_register_tags_default_to_empty_list() -> None:
    """Test that tags default to an empty list when not provided."""

    @register(title="No Tags", description="Function without tags")
    def no_tags_func(x: int) -> int:
        return x

    registry = get_registry()
    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    assert entry.metadata.tags == []


def test_register_deprecated_defaults_to_false() -> None:
    """Test that deprecated defaults to False when not provided."""

    @register(title="Not Deprecated", description="Active function")
    def active_func(x: int) -> int:
        return x

    registry = get_registry()
    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    assert entry.metadata.deprecated is False
    assert entry.metadata.deprecation_message is None


def test_import_statement_property() -> None:
    """Test that the import_statement property works correctly."""

    @register(title="Import Test", description="Test import statement")
    def import_test_func(x: int) -> int:
        return x

    registry = get_registry()
    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    import_stmt = entry.import_statement
    assert "from" in import_stmt
    assert "import" in import_stmt
    assert "import_test_func" in import_stmt


def test_fully_qualified_name_property() -> None:
    """Test that the fully_qualified_name property works correctly."""

    @register(title="FQN Test", description="Test FQN")
    def fqn_test_func(x: int) -> int:
        return x

    registry = get_registry()
    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    assert entry.fully_qualified_name == fqn
    assert "test_decorator" in fqn
    assert "fqn_test_func" in fqn


def test_register_function_with_docstring() -> None:
    """Test that registering a function preserves its docstring."""

    @register(title="Docstring Test", description="Test docstring preservation")
    def documented_func(x: int) -> int:
        """This is a docstring."""
        return x

    # Docstring should be preserved
    assert documented_func.__doc__ == "This is a docstring."


def test_register_class_method_fails() -> None:
    """Test that accessing schema for a class raises ValidationError."""

    @register(title="Class", description="This is a class")
    class MyClass:  # type: ignore
        pass

    # Registration succeeds (lazy validation), but accessing schema fails
    registry = get_registry()
    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    with pytest.raises(ValidationError) as exc_info:
        _ = entry.json_schema

    assert "Classes are not supported" in str(exc_info.value)


def test_register_no_arguments() -> None:
    """Test registering a function with @register() and no arguments."""

    @register()
    def simple_func(x: int) -> str:
        return str(x)

    registry = get_registry()
    assert len(registry) == 1

    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    # Title should be auto-generated from function name
    assert entry.metadata.title == "Simple Func"
    # Description should default to None
    assert entry.metadata.description is None


def test_register_auto_generated_title() -> None:
    """Test that title is auto-generated from snake_case function name."""

    @register()
    def get_patrol_observations_from_params(x: int) -> str:
        return str(x)

    registry = get_registry()
    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    assert entry.metadata.title == "Get Patrol Observations From Params"


def test_register_explicit_title_takes_precedence() -> None:
    """Test that an explicit title overrides auto-generation."""

    @register(title="Custom Title")
    def my_function_name(x: int) -> str:
        return str(x)

    registry = get_registry()
    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    # Explicit title should be used, not auto-generated
    assert entry.metadata.title == "Custom Title"


def test_register_none_description_default() -> None:
    """Test that description defaults to None."""

    @register(title="Test")
    def func_with_default_description(x: int) -> str:
        return str(x)

    registry = get_registry()
    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    assert entry.metadata.description is None


def test_register_with_tags_only() -> None:
    """Test registering with only tags (title auto-generated)."""

    @register(tags=["io", "earthranger"])
    def fetch_events(url: str) -> dict:
        return {}

    registry = get_registry()
    fqn = next(iter(registry.keys()))
    entry = registry[fqn]

    # Title auto-generated
    assert entry.metadata.title == "Fetch Events"
    # Tags set
    assert entry.metadata.tags == ["io", "earthranger"]
    # Description defaults to None
    assert entry.metadata.description is None
