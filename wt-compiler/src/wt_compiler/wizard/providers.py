"""Wizard provider discovery for wt-compiler.

Discovers third-party ``AbstractWizardProvider`` implementations via the
``wt_compiler.wizard_providers`` entry-point group.  Any installed package
that exposes this entry point is automatically available — no registration
step required.

Examples:
    List all installed providers and load one by name::

        >>> from wt_compiler.wizard.providers import get_available_providers
        >>> providers = get_available_providers()  # doctest: +SKIP
        >>> providers  # doctest: +SKIP
        [{'name': 'my-provider', 'package': 'my-wt-pkg'}]
"""

from __future__ import annotations

from importlib.metadata import entry_points

from wt_compiler.wizard.abstract import AbstractWizardProvider


def get_available_providers() -> list[dict[str, str]]:
    """Discover all installed wizard providers via entry points.

    Returns:
        List of provider entry dicts with ``"name"`` and ``"package"`` keys.
        Returns an empty list when no providers are installed.

    Examples:
        >>> get_available_providers()  # doctest: +SKIP
        [{'name': 'my-provider', 'package': 'my-wt-pkg'}]
    """
    all_eps = entry_points(group="wt_compiler.wizard_providers")
    return [
        {
            "name": ep.name,
            "package": ep.dist.metadata["Name"] if ep.dist is not None else "",
        }
        for ep in all_eps
    ]


def load_provider_class(name: str) -> type[AbstractWizardProvider]:
    """Load an installed wizard provider class by entry-point name.

    Args:
        name: Entry point name of the provider (e.g. ``"my-provider"``).

    Returns:
        The loaded provider class (a subclass of ``AbstractWizardProvider``).

    Raises:
        ValueError: If no entry point with the given name is installed, or
            the entry point fails to load.
        TypeError: If the loaded entry point is not a subclass of
            ``AbstractWizardProvider``.

    Examples:
        >>> load_provider_class("my-provider")  # doctest: +SKIP
        <class 'my_wt_pkg.MyProvider'>
    """
    all_eps = list(entry_points(group="wt_compiler.wizard_providers"))
    matching = [ep for ep in all_eps if ep.name == name]
    if not matching:
        available = [ep.name for ep in all_eps]
        raise ValueError(f"Provider {name!r} not found. Available: {available or ['(none)']}")
    try:
        cls = matching[0].load()
    except Exception as e:
        raise ValueError(f"Failed to load provider {name!r}: {e}") from e
    if not (isinstance(cls, type) and issubclass(cls, AbstractWizardProvider)):
        raise TypeError(
            f"Entry point {name!r} loaded {cls!r}, which is not a subclass of "
            "AbstractWizardProvider."
        )
    return cls
