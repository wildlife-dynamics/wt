"""Tests for wt_compiler.wizard.providers module."""
# ruff: noqa: SIM117  # nested with-blocks read clearer here

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wt_compiler.wizard.abstract import AbstractWizardProvider
from wt_compiler.wizard.providers import get_available_providers, load_provider_class

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


class _FakeProvider(AbstractWizardProvider):
    """Minimal concrete provider for testing."""

    def get_questions(self) -> list:  # type: ignore[override]
        return []


# ---------------------------------------------------------------------------
# TestGetAvailableProviders
# ---------------------------------------------------------------------------


class TestGetAvailableProviders:
    """Tests for get_available_providers()."""

    def test_returns_empty_when_no_eps(self) -> None:
        """Returns [] when no entry points are installed."""
        with patch("wt_compiler.wizard.providers.entry_points", return_value=[]):
            result = get_available_providers()
        assert result == []

    def test_returns_name_and_package(self) -> None:
        """Returns list with name and package for a single installed EP."""
        mock_ep = MagicMock()
        mock_ep.name = "my-provider"
        mock_ep.dist = MagicMock()
        mock_ep.dist.metadata = {"Name": "my-wt-pkg"}
        with patch("wt_compiler.wizard.providers.entry_points", return_value=[mock_ep]):
            result = get_available_providers()
        assert result == [{"name": "my-provider", "package": "my-wt-pkg"}]

    def test_handles_none_dist(self) -> None:
        """EP with dist=None produces package field of empty string."""
        mock_ep = MagicMock()
        mock_ep.name = "my-provider"
        mock_ep.dist = None
        with patch("wt_compiler.wizard.providers.entry_points", return_value=[mock_ep]):
            result = get_available_providers()
        assert result == [{"name": "my-provider", "package": ""}]


# ---------------------------------------------------------------------------
# TestLoadProviderClass
# ---------------------------------------------------------------------------


class TestLoadProviderClass:
    """Tests for load_provider_class()."""

    def test_returns_class_for_installed_provider(self) -> None:
        """EP found → returns class."""
        mock_ep = MagicMock()
        mock_ep.name = "my-p"
        mock_ep.load.return_value = _FakeProvider
        with patch("wt_compiler.wizard.providers.entry_points", return_value=[mock_ep]):
            result = load_provider_class("my-p")
        assert result is _FakeProvider

    def test_raises_value_error_when_not_found(self) -> None:
        """EP list is non-empty but name missing → ValueError with 'not found' and available names."""
        mock_ep = MagicMock()
        mock_ep.name = "other"
        with patch("wt_compiler.wizard.providers.entry_points", return_value=[mock_ep]):
            with pytest.raises(ValueError, match="not found"):
                load_provider_class("unknown")

    def test_raises_value_error_when_empty_ep_list(self) -> None:
        """No EPs at all → ValueError containing '(none)'."""
        with patch("wt_compiler.wizard.providers.entry_points", return_value=[]):
            with pytest.raises(ValueError, match=r"\(none\)"):
                load_provider_class("missing")

    def test_raises_value_error_on_ep_load_failure(self) -> None:
        """ep.load() raises → ValueError with 'Failed to load provider'."""
        mock_ep = MagicMock()
        mock_ep.name = "my-p"
        mock_ep.load.side_effect = ImportError("missing transitive dep")
        with patch("wt_compiler.wizard.providers.entry_points", return_value=[mock_ep]):
            with pytest.raises(ValueError, match="Failed to load provider"):
                load_provider_class("my-p")

    def test_raises_type_error_on_invalid_class(self) -> None:
        """Loaded class not a subclass of AbstractWizardProvider → TypeError."""
        mock_ep = MagicMock()
        mock_ep.name = "my-p"
        mock_ep.load.return_value = str  # not an AbstractWizardProvider subclass
        with patch("wt_compiler.wizard.providers.entry_points", return_value=[mock_ep]):
            with pytest.raises(TypeError, match="not a subclass of AbstractWizardProvider"):
                load_provider_class("my-p")
