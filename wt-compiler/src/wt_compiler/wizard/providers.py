"""Wizard provider registry for wt-compiler.

Manages installation and registration of third-party ``AbstractWizardProvider``
implementations via ``wt_compiler.wizard_providers`` entry points. Registered
providers are stored in an allowlist at ``~/.config/wt-compiler/providers.json``
(respecting ``XDG_CONFIG_HOME``).

Examples:
    Register a provider package and list registered providers::

        >>> from wt_compiler.wizard.providers import get_provider_registry_path
        >>> get_provider_registry_path().name
        'providers.json'
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from importlib.metadata import distribution, entry_points
from pathlib import Path
from typing import cast

from wt_compiler.wizard.abstract import AbstractWizardProvider

# PEP 508 / PyPA distribution name: letters, digits, hyphens, underscores, dots.
_SAFE_PKG_NAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$")


def _config_dir() -> Path:
    """Return the wt-compiler XDG config directory.

    Reads ``XDG_CONFIG_HOME`` from the environment. An empty string is treated
    as unset per the XDG Base Directory Specification.

    Returns:
        Path to ``<config-home>/wt-compiler``.

    Examples:
        >>> import os, pathlib
        >>> os.environ['XDG_CONFIG_HOME'] = '/tmp/custom'
        >>> _config_dir() == pathlib.Path('/tmp/custom/wt-compiler')
        True
        >>> del os.environ['XDG_CONFIG_HOME']
    """
    xdg = os.environ.get("XDG_CONFIG_HOME") or ""
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "wt-compiler"


def get_provider_registry_path() -> Path:
    """Return the path to the providers registry JSON file.

    Returns:
        Path to ``<config-dir>/providers.json``.

    Examples:
        >>> get_provider_registry_path().name
        'providers.json'
    """
    return _config_dir() / "providers.json"


def load_provider_registry() -> list[dict[str, str]]:
    """Load registered providers from the registry file.

    Returns an empty list if the file does not exist. Validates that the
    JSON structure is ``{"providers": [{...}, ...]}``.

    Returns:
        List of provider entry dicts, each with ``"name"`` and ``"package"`` keys.

    Raises:
        json.JSONDecodeError: If the file contains invalid JSON (a ``ValueError``
            subclass — propagates without wrapping).
        ValueError: If the JSON structure does not match the expected schema.

    Examples:
        >>> load_provider_registry()  # doctest: +SKIP
        []
    """
    registry_path = get_provider_registry_path()
    if not registry_path.exists():
        return []
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("providers"), list):
        raise ValueError(f'Malformed providers.json: expected {{"providers": [...]}}, got {data!r}')
    for entry in data["providers"]:
        if not isinstance(entry, dict) or "name" not in entry or "package" not in entry:
            raise ValueError(
                f"Malformed providers.json: each entry must have 'name' and 'package', "
                f"got {entry!r}"
            )
    return cast(list[dict[str, str]], data["providers"])


def save_provider_registry(entries: list[dict[str, str]]) -> None:
    """Save provider entries to the registry file.

    Creates parent directories if they do not exist. Writes with 2-space
    indentation and a trailing newline.

    Args:
        entries: List of provider dicts, each with ``"name"`` and ``"package"`` keys.

    Examples:
        >>> save_provider_registry([{"name": "my-p", "package": "my-pkg"}])  # doctest: +SKIP
    """
    registry_path = get_provider_registry_path()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, list[dict[str, str]]] = {"providers": entries}
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=registry_path.parent, prefix="providers-", suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, registry_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _build_install_command(pkg_name: str, installer: str) -> list[str]:
    """Return the install command for the given installer.

    Args:
        pkg_name: Package name to install.
        installer: One of ``"uv"``, ``"pixi"``, or ``"pip"``.

    Returns:
        Command list suitable for ``subprocess.run()``.

    Raises:
        ValueError: If ``installer`` is not a recognised value.

    Examples:
        >>> _build_install_command("my-pkg", "uv")  # doctest: +SKIP
        ['uv', 'pip', 'install', '--python', '/path/to/python', 'my-pkg']
        >>> _build_install_command("my-pkg", "pip")  # doctest: +SKIP
        ['/path/to/python', '-m', 'pip', 'install', 'my-pkg']
    """
    match installer:
        case "uv":
            return ["uv", "pip", "install", "--python", sys.executable, pkg_name]
        case "pixi":
            return ["pixi", "global", "install", pkg_name]
        case "pip":
            return [sys.executable, "-m", "pip", "install", pkg_name]
        case _:
            raise ValueError(f"Unknown installer {installer!r}. Choose from: uv, pixi, pip")


def install_and_register(pkg_name: str, installer: str) -> list[str]:
    """Install a package and register its wizard provider entry points.

    Installs the package using the specified installer, then discovers
    all ``wt_compiler.wizard_providers`` entry points and adds new ones to
    the allowlist at the registry path. Duplicate entry point names are
    skipped with a warning printed to stderr.

    Args:
        pkg_name: Package name to install (e.g. ``"my-wt-provider"``).
        installer: Package installer to use — one of ``"uv"``, ``"pixi"``,
            or ``"pip"``.

    Returns:
        List of newly registered provider names (excludes already-registered
        duplicates). Returns ``[]`` if all discovered entry points were
        already registered.

    Raises:
        ValueError: If ``pkg_name`` fails the safe-name validation check or
            ``installer`` is not a recognised value.
        subprocess.CalledProcessError: If the package installation fails.
        importlib.metadata.PackageNotFoundError: If the package is not found
            after installation.
        ValueError: If the package exposes no ``wt_compiler.wizard_providers``
            entry points.

    Examples:
        >>> install_and_register("my-wt-pkg", "uv")  # doctest: +SKIP
        ['my-provider']
    """
    if not _SAFE_PKG_NAME_RE.match(pkg_name):
        raise ValueError(
            f"Invalid package name: {pkg_name!r}. "
            "Package names must contain only letters, digits, hyphens, underscores, and dots."
        )
    subprocess.run(_build_install_command(pkg_name, installer), check=True)
    dist = distribution(pkg_name)
    dist_name = dist.metadata["Name"]
    eps = [ep for ep in dist.entry_points if ep.group == "wt_compiler.wizard_providers"]
    if not eps:
        raise ValueError(
            f"Package {pkg_name!r} exposes no 'wt_compiler.wizard_providers' entry points."
        )
    registry = load_provider_registry()
    existing_names = [e["name"] for e in registry]
    newly_added: list[str] = []
    for ep in eps:
        if ep.name in existing_names:
            existing_pkg = next(e["package"] for e in registry if e["name"] == ep.name)
            print(
                f"Warning: provider {ep.name!r} already registered from package "
                f"{existing_pkg!r}, skipping.",
                file=sys.stderr,
            )
        else:
            registry.append({"name": ep.name, "package": dist_name})
            newly_added.append(ep.name)
    save_provider_registry(registry)
    return newly_added


def get_registered_providers() -> list[dict[str, str]]:
    """Return all registered wizard providers.

    Semantic alias for :func:`load_provider_registry` for caller clarity.

    Returns:
        List of provider entry dicts with ``"name"`` and ``"package"`` keys.

    Examples:
        >>> get_registered_providers()  # doctest: +SKIP
        [{"name": "my-provider", "package": "my-pkg"}]
    """
    return load_provider_registry()


def load_provider_class(name: str) -> type[AbstractWizardProvider]:
    """Load a registered wizard provider class by name.

    Checks the allowlist first, then loads the entry point from installed
    packages. Uses ``ValueError`` (not ``KeyError``) for error cases to avoid
    extra repr-quoting in formatted error messages.

    Args:
        name: Entry point name of the registered provider.

    Returns:
        The loaded provider class (a subclass of ``AbstractWizardProvider``).

    Raises:
        ValueError: If the provider is not registered, its package is not
            currently installed, or the entry point fails to load.
        TypeError: If the loaded entry point is not a subclass of
            ``AbstractWizardProvider``.

    Examples:
        >>> load_provider_class("my-provider")  # doctest: +SKIP
        <class 'my_wt_pkg.MyProvider'>
    """
    registry = load_provider_registry()
    registered_names = [e["name"] for e in registry]
    if name not in registered_names:
        raise ValueError(
            f"Provider {name!r} is not registered. Registered: {registered_names or ['(none)']}"
        )
    stored_pkg = next(e["package"] for e in registry if e["name"] == name)
    all_eps = list(entry_points(group="wt_compiler.wizard_providers"))
    matching = [ep for ep in all_eps if ep.name == name]
    # Only load the EP that belongs to the registered package.  If another installed
    # package exposes an EP with the same name, refuse to load rather than silently
    # falling back — a name collision is a security signal, not a graceful degradation.
    ep_to_use = next(
        (
            ep
            for ep in matching
            if ep.dist is not None and ep.dist.metadata.get("Name") == stored_pkg
        ),
        None,
    )
    conflicting = [
        ep.dist.metadata.get("Name")
        for ep in matching
        if ep.dist is not None and ep.dist.metadata.get("Name") != stored_pkg
    ]
    if ep_to_use is None:
        if conflicting:
            raise ValueError(
                f"Provider {name!r} is registered from {stored_pkg!r}, but a conflicting "
                f"entry point with the same name was found from: {conflicting}. "
                f"Refusing to load an unverified provider."
            )
        raise ValueError(
            f"Provider {name!r} is registered but its package is not installed. "
            f"Re-run: wt-compiler register-provider <package>"
        )
    try:
        cls = ep_to_use.load()
    except Exception as e:
        raise ValueError(f"Failed to load provider {name!r}: {e}") from e
    if not (isinstance(cls, type) and issubclass(cls, AbstractWizardProvider)):
        raise TypeError(
            f"Entry point {name!r} loaded {cls!r}, which is not a subclass of "
            f"AbstractWizardProvider."
        )
    return cls
