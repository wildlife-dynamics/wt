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
import keyword

from rattler import NamelessMatchSpec

from wt_compiler.requirements import CHANNELS, _channel_from_str, _serialize_channel
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


def channel_type(value: str) -> str:
    """Validate a channel string and return its base URL.

    Looks up *value* in ``CHANNELS`` by name or base URL and returns the
    matched channel's ``base_url``.

    Args:
        value: Channel name or base URL to look up.

    Returns:
        The ``base_url`` of the matched channel.

    Raises:
        argparse.ArgumentTypeError: If *value* does not match any known channel.

    Examples:
        >>> channel_type("conda-forge")
        'https://conda.anaconda.org/conda-forge/'
        >>> channel_type("unknown-channel")
        Traceback (most recent call last):
            ...
        argparse.ArgumentTypeError: Unknown channel unknown-channel; ...
    """
    try:
        channel = _channel_from_str(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e
    return channel.base_url


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

_Q_REQUIREMENTS: WizardQuestion = {
    "dest": "requirements",
    "questions": [
        {
            "dest": "name",
            "argparse": {"help": "Package name", "type": non_empty_str},
            "wizard": {},
        },
        {
            "dest": "version",
            "argparse": {"help": "Version spec", "type": requirement_version_type, "default": "*"},
            "wizard": {},
        },
        {
            "dest": "channel",
            "argparse": {
                "help": "Channel",
                "type": channel_type,
                "default": channel_type("conda-forge"),
            },
            "wizard": {},
        },
    ],
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
