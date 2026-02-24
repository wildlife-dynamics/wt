"""Tests for utility functions.

This module tests the utility functions in wt-invokers, particularly
YAML to JSON conversion.
"""

from __future__ import annotations

import json

import pytest

from wt_invokers.utils import yaml_to_json


def test_yaml_to_json_simple() -> None:
    """Test converting simple YAML to JSON."""
    yaml_text = """
name: test
value: 42
"""
    json_str = yaml_to_json(yaml_text)
    data = json.loads(json_str)

    assert data["name"] == "test"
    assert data["value"] == 42


def test_yaml_to_json_nested() -> None:
    """Test converting nested YAML to JSON."""
    yaml_text = """
parent:
  child1: value1
  child2: value2
  nested:
    deep: value3
"""
    json_str = yaml_to_json(yaml_text)
    data = json.loads(json_str)

    assert data["parent"]["child1"] == "value1"
    assert data["parent"]["child2"] == "value2"
    assert data["parent"]["nested"]["deep"] == "value3"


def test_yaml_to_json_list() -> None:
    """Test converting YAML with lists to JSON."""
    yaml_text = """
items:
  - item1
  - item2
  - item3
"""
    json_str = yaml_to_json(yaml_text)
    data = json.loads(json_str)

    assert data["items"] == ["item1", "item2", "item3"]


def test_yaml_to_json_mixed_types() -> None:
    """Test converting YAML with mixed types to JSON."""
    yaml_text = """
string: hello
integer: 42
float: 3.14
boolean: true
null_value: null
list:
  - 1
  - 2
  - 3
"""
    json_str = yaml_to_json(yaml_text)
    data = json.loads(json_str)

    assert data["string"] == "hello"
    assert data["integer"] == 42
    assert data["float"] == 3.14
    assert data["boolean"] is True
    assert data["null_value"] is None
    assert data["list"] == [1, 2, 3]


def test_yaml_to_json_empty() -> None:
    """Test converting empty YAML to JSON."""
    yaml_text = ""
    json_str = yaml_to_json(yaml_text)
    data = json.loads(json_str)

    assert data is None


def test_yaml_to_json_invalid() -> None:
    """Test converting invalid YAML raises ValueError."""
    yaml_text = """
invalid: yaml: [
"""
    with pytest.raises(ValueError, match="Invalid YAML"):
        yaml_to_json(yaml_text)


def test_yaml_to_json_malformed_indentation() -> None:
    """Test converting YAML with malformed indentation parses as separate keys."""
    yaml_text = """
parent:
child: value
"""
    # This YAML is actually valid - parent is null, child is a separate key
    json_str = yaml_to_json(yaml_text)
    data = json.loads(json_str)
    assert "parent" in data
    assert "child" in data
    assert data["parent"] is None
    assert data["child"] == "value"


def test_yaml_to_json_preserves_structure() -> None:
    """Test that YAML to JSON conversion preserves data structure."""
    yaml_text = """
workflow:
  name: test-workflow
  version: 1.0.0
  params:
    - name: input
      type: string
      required: true
    - name: threshold
      type: float
      default: 0.5
  tasks:
    - id: task1
      function: process_data
    - id: task2
      function: save_results
"""
    json_str = yaml_to_json(yaml_text)
    data = json.loads(json_str)

    assert data["workflow"]["name"] == "test-workflow"
    assert data["workflow"]["version"] == "1.0.0"
    assert len(data["workflow"]["params"]) == 2
    assert len(data["workflow"]["tasks"]) == 2
    assert data["workflow"]["tasks"][0]["id"] == "task1"


def test_yaml_to_json_multiline_string() -> None:
    """Test converting YAML with multiline strings."""
    yaml_text = """
description: |
  This is a multiline
  string with multiple
  lines of text.
"""
    json_str = yaml_to_json(yaml_text)
    data = json.loads(json_str)

    assert "multiline" in data["description"]
    assert "multiple" in data["description"]


def test_yaml_to_json_special_characters() -> None:
    """Test converting YAML with special characters."""
    yaml_text = """
text: "Special chars: @#$%^&*()[]{}|\\/<>?"
unicode: "Unicode: αβγδε"
quotes: 'Single quotes'
"""
    json_str = yaml_to_json(yaml_text)
    data = json.loads(json_str)

    assert "@#$%^&*()" in data["text"]
    assert "αβγδε" in data["unicode"]
    assert data["quotes"] == "Single quotes"


def test_yaml_to_json_numeric_keys() -> None:
    """Test converting YAML with numeric keys."""
    yaml_text = """
2023: "year"
42: "answer"
"""
    json_str = yaml_to_json(yaml_text)
    data = json.loads(json_str)

    # YAML treats numeric keys as integers, which become strings in JSON
    assert str(2023) in json_str or 2023 in data
    assert str(42) in json_str or 42 in data
