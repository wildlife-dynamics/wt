"""Utility functions for wt-invokers package.

This module provides utility functions used by various invoker implementations.
"""

from __future__ import annotations

import json
import re

import ruamel.yaml

# Expected environment-tar digest format: a ``sha256:`` prefix followed by
# exactly 64 hexadecimal characters (case-insensitive). This mirrors the
# digest emitted by the workflow-environment build pipeline (lowercase
# ``"sha256:" + sha256(environment.tar).hexdigest()``).
_ENVIRONMENT_TAR_DIGEST_RE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")


def validate_environment_tar_digest(digest: str) -> None:
    """Validate the format of an expected ``environment.tar`` sha256 digest.

    The digest must be a literal ``sha256:`` prefix followed by exactly 64
    hexadecimal characters (case-insensitive), matching the format produced
    by the workflow-environment build pipeline. This validates *format* only;
    the actual integrity comparison against the downloaded tarball happens in
    :class:`~wt_invokers.mixins.PixiUnpackMixin`.

    Args:
        digest: The expected digest string, e.g. ``"sha256:<64 hex chars>"``.

    Raises:
        ValueError: If ``digest`` is not a ``sha256:`` prefix followed by
            exactly 64 hexadecimal characters.

    Examples:
        A well-formed digest is accepted (returns ``None``):

        >>> validate_environment_tar_digest("sha256:" + "a" * 64)

        Uppercase hex is also accepted:

        >>> validate_environment_tar_digest("sha256:" + "A" * 64)

        A wrong algorithm, missing prefix, or bad hex length is rejected:

        >>> validate_environment_tar_digest("md5:" + "a" * 32)
        Traceback (most recent call last):
            ...
        ValueError: environment_tar_digest must be 'sha256:<64 hex chars>', got: ...
    """
    if not _ENVIRONMENT_TAR_DIGEST_RE.match(digest):
        raise ValueError(
            f"environment_tar_digest must be 'sha256:<64 hex chars>', got: {digest}"
        )


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
