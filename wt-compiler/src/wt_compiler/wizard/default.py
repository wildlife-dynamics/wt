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
from types import MappingProxyType
from typing import Any
from urllib.parse import urlparse

from rattler import NamelessMatchSpec

from wt_compiler.requirements import CHANNELS, _serialize_channel
from wt_compiler.wizard.abstract import (
    AbstractWizardProvider,
    ArgparseKwargs,
    SingleWizardQuestion,
    WizardKwargs,
    WizardQuestion,
    WizardQuestionLoop,
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


def _absolute_path_type(value: str) -> str:
    """Validate an absolute filesystem path.

    Args:
        value: The path string to validate.

    Returns:
        The validated path string (stripped of surrounding whitespace).

    Raises:
        argparse.ArgumentTypeError: If the path is empty or not absolute.

    Examples:
        >>> _absolute_path_type("/home/user/mypackage")
        '/home/user/mypackage'
        >>> _absolute_path_type("relative/path")
        Traceback (most recent call last):
            ...
        argparse.ArgumentTypeError: 'relative/path' is not an absolute filesystem path.
    """
    stripped = value.strip()
    if not stripped:
        raise argparse.ArgumentTypeError("Path cannot be empty.")
    if not os.path.isabs(stripped):
        raise argparse.ArgumentTypeError(f"'{stripped}' is not an absolute filesystem path.")
    return stripped


def _http_url_type(value: str) -> str:
    """Validate an HTTP or HTTPS URL.

    Args:
        value: The URL string to validate.

    Returns:
        The validated URL string (stripped of surrounding whitespace).

    Raises:
        argparse.ArgumentTypeError: If the URL is empty or not http/https.

    Examples:
        >>> _http_url_type("https://example.com/pkg.whl")
        'https://example.com/pkg.whl'
        >>> _http_url_type("ftp://example.com/pkg")
        Traceback (most recent call last):
            ...
        argparse.ArgumentTypeError: 'ftp://example.com/pkg' is not a valid http/https URL.
    """
    stripped = value.strip()
    if not stripped:
        raise argparse.ArgumentTypeError("URL cannot be empty.")
    parsed = urlparse(stripped)
    if parsed.scheme not in ("http", "https"):
        raise argparse.ArgumentTypeError(f"'{stripped}' is not a valid http/https URL.")
    return stripped


def _git_url_type(value: str) -> str:
    """Validate a git repository URL (without ``git+`` prefix).

    Accepts ``http``, ``https``, ``git``, and ``ssh`` schemes.

    Args:
        value: The git URL string to validate.

    Returns:
        The validated URL string (stripped of surrounding whitespace).

    Raises:
        argparse.ArgumentTypeError: If the URL is empty or has an unsupported scheme.

    Examples:
        >>> _git_url_type("https://github.com/org/pkg.git")
        'https://github.com/org/pkg.git'
        >>> _git_url_type("git+https://github.com/org/pkg.git")
        Traceback (most recent call last):
            ...
        argparse.ArgumentTypeError: 'git+https://github.com/org/pkg.git' is not a valid git URL \
(expected http/https/git/ssh scheme).
    """
    stripped = value.strip()
    if not stripped:
        raise argparse.ArgumentTypeError("Git URL cannot be empty.")
    parsed = urlparse(stripped)
    if parsed.scheme not in ("http", "https", "git", "ssh"):
        raise argparse.ArgumentTypeError(
            f"'{stripped}' is not a valid git URL (expected http/https/git/ssh scheme)."
        )
    return stripped


CHANNEL_CHOICES: list[str] = [_serialize_channel(c) for c in CHANNELS]
"""Channel choices list built from ``requirements.CHANNELS``."""

REQ_TYPE_CHOICES: list[str] = ["conda", "local path", "url", "git"]
"""Allowed ``req_type`` values for the requirements loop."""

# --- Condition callables ----------------------------------------------------


def _is_conda(entry: MappingProxyType[str, Any]) -> bool:
    """Return True when the current entry uses a conda requirement type.

    Args:
        entry: Partial answer dict for the current loop iteration.

    Returns:
        True if ``req_type`` is ``"conda"`` or absent (the default).
    """
    return bool(entry.get("req_type", "conda") == "conda")


def _is_pip_path(entry: MappingProxyType[str, Any]) -> bool:
    """Return True when the current entry uses a local filesystem path.

    Args:
        entry: Partial answer dict for the current loop iteration.

    Returns:
        True if ``req_type`` is ``"local path"``.
    """
    return entry.get("req_type") == "local path"


def _is_pip_url(entry: MappingProxyType[str, Any]) -> bool:
    """Return True when the current entry uses an HTTP/HTTPS URL.

    Args:
        entry: Partial answer dict for the current loop iteration.

    Returns:
        True if ``req_type`` is ``"url"``.
    """
    return entry.get("req_type") == "url"


def _is_pip_git(entry: MappingProxyType[str, Any]) -> bool:
    """Return True when the current entry uses a git repository URL.

    Args:
        entry: Partial answer dict for the current loop iteration.

    Returns:
        True if ``req_type`` is ``"git"``.
    """
    return entry.get("req_type") == "git"


def _is_pip_git_with_ref(entry: MappingProxyType[str, Any]) -> bool:
    """Return True when the current entry is a git requirement with a ref specified.

    Args:
        entry: Partial answer dict for the current loop iteration.

    Returns:
        True if ``req_type`` is ``"git"`` and ``git_ref_type`` is not ``"none"``.
    """
    return entry.get("req_type") == "git" and entry.get("git_ref_type", "none") != "none"


# --- Default question definitions --------------------------------------------

_Q_WORKFLOW_ID = SingleWizardQuestion(
    dest="workflow_id",
    argparse=ArgparseKwargs(
        help="Workflow ID (valid Python identifier, ≤64 chars)",
        type=workflow_id_type,
    ),
    wizard=WizardKwargs(),
)

_Q_WORKFLOW_NAME = SingleWizardQuestion(
    dest="workflow_name",
    argparse=ArgparseKwargs(help="Workflow name (human-readable)", type=non_empty_str),
    wizard=WizardKwargs(),
)

_Q_WORKFLOW_DESCRIPTION = SingleWizardQuestion(
    dest="workflow_description",
    argparse=ArgparseKwargs(help="Workflow description (optional)", type=str, default=""),
    wizard=WizardKwargs(),
)

_Q_AUTHOR_NAME = SingleWizardQuestion(
    dest="author_name",
    argparse=ArgparseKwargs(help="Author name", type=non_empty_str),
    wizard=WizardKwargs(),
)

_Q_LICENSE_TYPE = SingleWizardQuestion(
    dest="license_type",
    argparse=ArgparseKwargs(
        help="License type",
        type=str,
        choices=["BSD-3-Clause", "MIT", "Apache-2.0"],
        default="BSD-3-Clause",
    ),
    wizard=WizardKwargs(),
)


def _requirements_batch_type(value: str) -> dict[str, Any]:
    """Parse and validate a requirement JSON object for batch mode.

    Infers ``req_type`` from the keys present if not explicitly supplied:
    a dict with a ``path`` key → ``"local path"``; ``url`` key → ``"url"``;
    ``git`` key → ``"git"``; otherwise ``"conda"`` is assumed.

    Git references may be supplied as ``rev``/``branch``/``tag`` keys
    (normalized to ``git_ref_type`` + ``git_ref_value``) or directly as
    ``git_ref_type`` + ``git_ref_value``.

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

        Local path (inferred from ``path``):

        >>> d = _requirements_batch_type('{"name":"mypkg","path":"/home/user/mypkg"}')
        >>> d["req_type"]
        'local path'
    """
    try:
        d: dict[str, Any] = json.loads(value)
    except json.JSONDecodeError as e:
        raise argparse.ArgumentTypeError(f"Invalid JSON: {e}") from e
    if not isinstance(d, dict):
        raise argparse.ArgumentTypeError(f"Expected a JSON object (got {type(d).__name__})")

    name = d.get("name")
    if name is None:
        raise argparse.ArgumentTypeError("Invalid name: name is required")
    try:
        d["name"] = non_empty_str(str(name))
    except argparse.ArgumentTypeError as e:
        raise argparse.ArgumentTypeError(f"Invalid name: {e}") from e

    # Infer req_type from key presence when not explicitly supplied
    if "req_type" not in d:
        if "path" in d:
            d["req_type"] = "local path"
        elif "url" in d:
            d["req_type"] = "url"
        elif "git" in d:
            d["req_type"] = "git"
        else:
            d["req_type"] = "conda"

    req_type = d["req_type"]
    if req_type not in REQ_TYPE_CHOICES:
        raise argparse.ArgumentTypeError(
            f"Invalid req_type '{req_type}': must be one of {REQ_TYPE_CHOICES}"
        )

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
    elif req_type == "local path":
        try:
            d["path"] = _absolute_path_type(str(d.get("path", "")))
        except argparse.ArgumentTypeError as e:
            raise argparse.ArgumentTypeError(f"Invalid path: {e}") from e
        editable = d.get("editable", "false")
        d["editable"] = "true" if str(editable).lower() == "true" else "false"
    elif req_type == "url":
        try:
            d["url"] = _http_url_type(str(d.get("url", "")))
        except argparse.ArgumentTypeError as e:
            raise argparse.ArgumentTypeError(f"Invalid url: {e}") from e
    else:  # git
        try:
            d["git"] = _git_url_type(str(d.get("git", "")))
        except argparse.ArgumentTypeError as e:
            raise argparse.ArgumentTypeError(f"Invalid git URL: {e}") from e
        # Normalize git ref: accept rev/branch/tag keys or git_ref_type+git_ref_value
        if "git_ref_type" not in d:
            for ref_type in ("rev", "branch", "tag"):
                if ref_type in d:
                    d["git_ref_type"] = ref_type
                    d["git_ref_value"] = non_empty_str(str(d.pop(ref_type)))
                    break
            else:
                d["git_ref_type"] = "none"
        git_ref_type = d["git_ref_type"]
        if git_ref_type not in ("none", "rev", "branch", "tag"):
            raise argparse.ArgumentTypeError(
                f"Invalid git_ref_type '{git_ref_type}': must be 'none', 'rev', 'branch', or 'tag'"
            )
        if git_ref_type != "none":
            if "git_ref_value" not in d:
                raise argparse.ArgumentTypeError(
                    f"git_ref_value is required when git_ref_type is '{git_ref_type}'"
                )
            try:
                d["git_ref_value"] = non_empty_str(str(d["git_ref_value"]))
            except argparse.ArgumentTypeError as e:
                raise argparse.ArgumentTypeError(f"Invalid git_ref_value: {e}") from e

    return d


_Q_REQUIREMENTS_LOOP_QUESTIONS: list[WizardQuestion] = [
    SingleWizardQuestion(
        dest="name",
        argparse=ArgparseKwargs(help="Package name", type=non_empty_str),
        wizard=WizardKwargs(),
    ),
    SingleWizardQuestion(
        dest="req_type",
        argparse=ArgparseKwargs(
            help="Requirement type",
            choices=REQ_TYPE_CHOICES,
            default="conda",
        ),
        wizard=WizardKwargs(),
    ),
    # --- conda-specific ---
    SingleWizardQuestion(
        dest="version",
        argparse=ArgparseKwargs(help="Version spec", type=requirement_version_type, default="*"),
        wizard=WizardKwargs(condition=_is_conda),
    ),
    SingleWizardQuestion(
        dest="channel",
        argparse=ArgparseKwargs(help="Channel", choices=CHANNEL_CHOICES, default="conda-forge"),
        wizard=WizardKwargs(condition=_is_conda),
    ),
    # --- local path ---
    SingleWizardQuestion(
        dest="path",
        argparse=ArgparseKwargs(
            help="Absolute filesystem path to package",
            type=_absolute_path_type,
        ),
        wizard=WizardKwargs(condition=_is_pip_path),
    ),
    SingleWizardQuestion(
        dest="editable",
        argparse=ArgparseKwargs(
            help="Install in editable mode",
            choices=["false", "true"],
            default="false",
        ),
        wizard=WizardKwargs(condition=_is_pip_path),
    ),
    # --- url ---
    SingleWizardQuestion(
        dest="url",
        argparse=ArgparseKwargs(
            help="HTTP/HTTPS URL to package wheel or sdist",
            type=_http_url_type,
        ),
        wizard=WizardKwargs(condition=_is_pip_url),
    ),
    # --- git ---
    SingleWizardQuestion(
        dest="git",
        argparse=ArgparseKwargs(
            help="Git repository URL (e.g. https://github.com/org/pkg.git)",
            type=_git_url_type,
        ),
        wizard=WizardKwargs(condition=_is_pip_git),
    ),
    SingleWizardQuestion(
        dest="git_ref_type",
        argparse=ArgparseKwargs(
            help="Git reference type",
            choices=["none", "rev", "branch", "tag"],
            default="none",
        ),
        wizard=WizardKwargs(condition=_is_pip_git),
    ),
    SingleWizardQuestion(
        dest="git_ref_value",
        argparse=ArgparseKwargs(
            help="Git reference value (commit hash, branch name, or tag)",
            type=non_empty_str,
        ),
        wizard=WizardKwargs(condition=_is_pip_git_with_ref),
    ),
]

_Q_REQUIREMENTS = WizardQuestionLoop(
    dest="requirements",
    argparse=ArgparseKwargs(
        action="append",
        default=None,
        help=(
            'Requirement as JSON. Conda: {"name":"pkg","version":"*",'
            '"channel":"conda-forge"}. '
            'Pip path: {"name":"pkg","path":"/abs/path"}. '
            'Pip URL: {"name":"pkg","url":"https://..."}. '
            'Pip git: {"name":"pkg","git":"https://github.com/org/pkg.git",'
            '"branch":"main"}. (batch mode; repeatable)'
        ),
        type=_requirements_batch_type,
    ),
    questions=_Q_REQUIREMENTS_LOOP_QUESTIONS,
)

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
