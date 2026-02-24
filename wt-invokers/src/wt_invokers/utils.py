"""Utility functions for wt-invokers package.

This module provides utility functions used by various invoker implementations.
"""

from __future__ import annotations

import json

import ruamel.yaml


def yaml_to_json(text: str) -> str:
    """Convert YAML text to JSON string.

    Args:
        text: YAML-formatted string

    Returns:
        JSON-formatted string

    Raises:
        ValueError: If the input text is not valid YAML

    Examples:
        Converting simple YAML to JSON:

        >>> yaml_text = '''
        ... name: test
        ... value: 42
        ... items:
        ...   - a
        ...   - b
        ... '''
        >>> json_str = yaml_to_json(yaml_text)
        >>> import json
        >>> data = json.loads(json_str)
        >>> data["name"]
        'test'
        >>> data["value"]
        42

        Invalid YAML raises ValueError:

        >>> yaml_to_json("invalid: yaml: [")
        Traceback (most recent call last):
            ...
        ValueError: Invalid YAML: ...
    """
    try:
        yaml = ruamel.yaml.YAML(typ="safe")
        data = yaml.load(text)
        return json.dumps(data)
    except Exception as e:  # ruamel.yaml.YAMLError not accessible via type system
        # Check if exception is YAMLError or any of its subclasses
        if any("YAMLError" in cls.__name__ for cls in type(e).__mro__):
            raise ValueError(f"Invalid YAML: {e}") from e
        raise
