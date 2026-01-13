"""Utility functions for handling import references."""


def rsplit_importable_reference(reference: str) -> list[str]:
    """Split enclosing module (or anchor) and object name from importable reference.

    Args:
        reference: A dotted import reference like "package.module.function"

    Returns:
        A list with two elements: [module_path, object_name]

    Examples:
        >>> rsplit_importable_reference("ecoscope_workflows_ext.tasks.io.get_events")
        ['ecoscope_workflows_ext.tasks.io', 'get_events']

        >>> rsplit_importable_reference("mypackage.MyClass")
        ['mypackage', 'MyClass']
    """
    return reference.rsplit(".", 1)


def validate_importable_reference(reference: str) -> str:
    """Validate that a reference is a valid importable reference.

    Without importing the reference, does the best we can to ensure that it will be importable.

    Args:
        reference: A dotted import reference like "package.module.function"

    Returns:
        The validated reference (unchanged)

    Raises:
        AssertionError: If the reference is not valid

    Examples:
        >>> validate_importable_reference("package.module.function")
        'package.module.function'

        >>> validate_importable_reference("package")  # doctest: +SKIP
        Traceback (most recent call last):
        ...
        AssertionError: package is not a valid importable reference...
    """
    parts = rsplit_importable_reference(reference)
    assert len(parts) == 2, (
        f"{reference} is not a valid importable reference, must be a dotted string."
    )
    assert parts[1].isidentifier(), (
        f"{parts[1]} is not a valid Python identifier, it will not be importable."
    )
    assert all(module_part.isidentifier() for module_part in parts[0].split(".")), (
        f"{parts[0]} is not a valid Python module path, it will not be importable."
    )
    return reference
