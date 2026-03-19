"""Default wizard provider for scaffolding new workflow projects.

Implements ``DefaultWizardProvider``, the reference implementation of
``AbstractWizardProvider``.  Defines the standard set of questions for
creating a new workflow project directory (workflow ID, name, description,
author, license, and requirements).

Examples:
    Drive the wizard with a sequence of answers::

        >>> from wt_compiler.wizard.default import DefaultWizardProvider
        >>> p = DefaultWizardProvider()
        >>> gen = p.input_generator()
        >>> q = next(gen)
        >>> q["dest"]
        'workflow_id'
"""

from __future__ import annotations

import argparse
import builtins
import copy
import json
import keyword
import os
from typing import Any
from urllib.parse import urlparse

from rattler import NamelessMatchSpec

from wt_compiler.requirements import CHANNELS, _serialize_channel
from wt_compiler.wizard.abstract import (
    AbstractWizardProvider,
    WizardQuestion,
)

# --- Validation callables ---------------------------------------------------


def workflow_id_type(value: str) -> str:
    """Validate a workflow ID string.

    Must be a valid Python identifier, at most 64 characters, and not a
    Python keyword or builtin name.

    Args:
        value: The workflow ID to validate.

    Returns:
        The validated workflow ID string.

    Raises:
        argparse.ArgumentTypeError: If validation fails.

    Examples:
        >>> workflow_id_type("my_workflow")
        'my_workflow'
        >>> workflow_id_type("")
        Traceback (most recent call last):
            ...
        argparse.ArgumentTypeError: Workflow ID cannot be empty.
    """
    if not value or not value.strip():
        raise argparse.ArgumentTypeError("Workflow ID cannot be empty.")
    if not value.isidentifier():
        raise argparse.ArgumentTypeError(f"`{value}` is not a valid Python identifier.")
    if len(value) > 64:
        raise argparse.ArgumentTypeError(f"`{value}` is too long; max length is 64 characters.")
    if keyword.iskeyword(value):
        raise argparse.ArgumentTypeError(f"`{value}` is a Python keyword.")
    if value in dir(builtins):
        raise argparse.ArgumentTypeError(f"`{value}` is a built-in Python function.")
    return value


def non_empty_str(value: str) -> str:
    """Validate that a string is non-empty after stripping whitespace.

    Args:
        value: The string to validate.

    Returns:
        The stripped string.

    Raises:
        argparse.ArgumentTypeError: If the string is empty or whitespace-only.

    Examples:
        >>> non_empty_str("hello")
        'hello'
        >>> non_empty_str("  ")
        Traceback (most recent call last):
            ...
        argparse.ArgumentTypeError: Value cannot be empty.
    """
    stripped = value.strip() if value else ""
    if not stripped:
        raise argparse.ArgumentTypeError("Value cannot be empty.")
    return stripped


def requirement_version_type(value: str) -> str:
    """Validate a version string as a ``NamelessMatchSpec``.

    Args:
        value: The version specification string.

    Returns:
        The validated version string.

    Raises:
        argparse.ArgumentTypeError: If the version string is not a valid
            ``NamelessMatchSpec``.

    Examples:
        >>> requirement_version_type("*")
        '*'
        >>> requirement_version_type(">=1.0")
        '>=1.0'
    """
    try:
        NamelessMatchSpec(value)
    except Exception as e:
        raise argparse.ArgumentTypeError(str(e)) from e
    return value


def pip_source_type(value: str) -> str:
    """Validate a pip installable source: absolute path, URL, or git+ URL.

    Accepts:
    - Absolute filesystem paths (e.g. ``/home/user/mypackage``)
    - HTTP/HTTPS URLs (e.g. ``https://example.com/pkg.whl``)
    - Git URLs with ``git+`` prefix (e.g. ``git+https://github.com/org/pkg.git``)

    Args:
        value: The source string to validate.

    Returns:
        The validated source string (stripped of surrounding whitespace).

    Raises:
        argparse.ArgumentTypeError: If the source is not a recognized format.

    Examples:
        >>> pip_source_type("/home/user/mypackage")
        '/home/user/mypackage'
        >>> pip_source_type("https://example.com/pkg.whl")
        'https://example.com/pkg.whl'
        >>> pip_source_type("git+https://github.com/org/pkg.git")
        'git+https://github.com/org/pkg.git'
    """
    stripped = value.strip()
    if not stripped:
        raise argparse.ArgumentTypeError("Pip source cannot be empty.")
    if os.path.isabs(stripped):
        return stripped
    parsed = urlparse(stripped)
    if parsed.scheme in ("http", "https", "git+https", "git+http", "git+ssh"):
        return stripped
    raise argparse.ArgumentTypeError(
        f"Invalid pip source '{stripped}': must be an absolute filesystem path or a URL "
        "(http/https/git+https://...)."
    )


CHANNEL_CHOICES: list[str] = [_serialize_channel(c) for c in CHANNELS]
"""Channel choices list built from ``requirements.CHANNELS``."""

# --- Default question definitions --------------------------------------------

_Q_WORKFLOW_ID: WizardQuestion = {
    "dest": "workflow_id",
    "argparse": {
        "help": "Workflow ID (valid Python identifier, ≤64 chars)",
        "type": workflow_id_type,
    },
    "wizard": {},
}

_Q_WORKFLOW_NAME: WizardQuestion = {
    "dest": "workflow_name",
    "argparse": {"help": "Workflow name (human-readable)", "type": non_empty_str},
    "wizard": {},
}

_Q_WORKFLOW_DESCRIPTION: WizardQuestion = {
    "dest": "workflow_description",
    "argparse": {"help": "Workflow description (optional)", "type": str, "default": ""},
    "wizard": {},
}

_Q_AUTHOR_NAME: WizardQuestion = {
    "dest": "author_name",
    "argparse": {"help": "Author name", "type": non_empty_str},
    "wizard": {},
}

_Q_LICENSE_TYPE: WizardQuestion = {
    "dest": "license_type",
    "argparse": {
        "help": "License type",
        "type": str,
        "choices": ["BSD-3-Clause", "MIT", "Apache-2.0"],
        "default": "BSD-3-Clause",
    },
    "wizard": {},
}

def _requirements_batch_type(value: str) -> dict[str, Any]:
    """Parse and validate a requirement JSON object for batch mode.

    Infers ``req_type`` from the keys present if not explicitly supplied:
    a dict containing a ``source`` key is treated as ``"pip"``; otherwise
    ``"conda"`` is assumed.

    Args:
        value: JSON string representing a single requirement.

    Returns:
        Validated dict with ``req_type`` set and type-checked fields.

    Raises:
        argparse.ArgumentTypeError: On JSON parse failure or invalid fields.

    Examples:
        Conda (inferred):

        >>> import json
        >>> d = _requirements_batch_type(
        ...     '{"name":"numpy","version":">=1.0","channel":"conda-forge"}'
        ... )
        >>> d["req_type"]
        'conda'

        Pip (inferred from ``source``):

        >>> d = _requirements_batch_type('{"name":"mypkg","source":"/home/user/mypkg"}')
        >>> d["req_type"]
        'pip'
    """
    try:
        d: dict[str, Any] = json.loads(value)
    except json.JSONDecodeError as e:
        raise argparse.ArgumentTypeError(f"Invalid JSON: {e}") from e
    if not isinstance(d, dict):
        raise argparse.ArgumentTypeError(f"Expected a JSON object (got {type(d).__name__})")

    try:
        d["name"] = non_empty_str(str(d.get("name", "")))
    except argparse.ArgumentTypeError as e:
        raise argparse.ArgumentTypeError(f"Invalid name: {e}") from e

    req_type = d.get("req_type", "pip" if "source" in d else "conda")
    if req_type not in ("conda", "pip"):
        raise argparse.ArgumentTypeError(
            f"Invalid req_type '{req_type}': must be 'conda' or 'pip'"
        )
    d["req_type"] = req_type

    if req_type == "conda":
        try:
            d["version"] = requirement_version_type(str(d.get("version", "*")))
        except argparse.ArgumentTypeError as e:
            raise argparse.ArgumentTypeError(f"Invalid version: {e}") from e
        channel = str(d.get("channel", "conda-forge"))
        if channel not in CHANNEL_CHOICES:
            raise argparse.ArgumentTypeError(
                f"Invalid channel '{channel}': must be one of {CHANNEL_CHOICES}"
            )
        d["channel"] = channel
    else:
        try:
            d["source"] = pip_source_type(str(d.get("source", "")))
        except argparse.ArgumentTypeError as e:
            raise argparse.ArgumentTypeError(f"Invalid source: {e}") from e

    return d


_is_conda = lambda entry: entry.get("req_type", "conda") == "conda"  # noqa: E731
_is_pip = lambda entry: entry.get("req_type", "conda") == "pip"  # noqa: E731

_Q_REQUIREMENTS_LOOP_QUESTIONS: list[WizardQuestion] = [
    {
        "dest": "name",
        "argparse": {"help": "Package name", "type": non_empty_str},
        "wizard": {},
    },
    {
        "dest": "req_type",
        "argparse": {
            "help": "Requirement type",
            "choices": ["conda", "pip"],
            "default": "conda",
        },
        "wizard": {},
    },
    {
        "dest": "version",
        "argparse": {"help": "Version spec", "type": requirement_version_type, "default": "*"},
        "wizard": {"condition": _is_conda},
    },
    {
        "dest": "channel",
        "argparse": {"help": "Channel", "choices": CHANNEL_CHOICES, "default": "conda-forge"},
        "wizard": {"condition": _is_conda},
    },
    {
        "dest": "source",
        "argparse": {
            "help": "Pip source: absolute path, http/https URL, or git+https:// URL",
            "type": pip_source_type,
        },
        "wizard": {"condition": _is_pip},
    },
]
_Q_REQUIREMENTS: WizardQuestion = {
    "dest": "requirements",
    "argparse": {
        "action": "append",
        "default": None,
        "help": (
            "Requirement as JSON: conda: {'name':'pkg','version':'*','channel':'conda-forge'} "
            "or pip: {'name':'pkg','source':'/path/or/url'} (batch mode; repeatable)"
        ),
        "type": _requirements_batch_type,
    },
    "questions": _Q_REQUIREMENTS_LOOP_QUESTIONS,
}

_DEFAULT_QUESTIONS: list[WizardQuestion] = [
    _Q_WORKFLOW_ID,
    _Q_WORKFLOW_NAME,
    _Q_WORKFLOW_DESCRIPTION,
    _Q_AUTHOR_NAME,
    _Q_LICENSE_TYPE,
    _Q_REQUIREMENTS,
]


class DefaultWizardProvider(AbstractWizardProvider):
    """Default wizard provider for scaffolding new workflow projects.

    Provides the standard set of questions: workflow ID, name, description,
    author, license type, and conda requirements.

    Override ``get_questions()`` in subclasses to customize the question flow.

    Examples:
        >>> p = DefaultWizardProvider()
        >>> qs = p.get_questions()
        >>> [q["dest"] for q in qs]  # doctest: +NORMALIZE_WHITESPACE
        ['workflow_id', 'workflow_name', 'workflow_description',
         'author_name', 'license_type', 'requirements']
    """

    def get_questions(self) -> list[WizardQuestion]:
        """Return the default question list for project scaffolding.

        Returns:
            Ordered list of ``WizardQuestion`` dicts.
        """
        return copy.deepcopy(_DEFAULT_QUESTIONS)
