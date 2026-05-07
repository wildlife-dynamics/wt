"""Tests for wt_compiler.requirements module."""

import importlib
import os

import pytest

import wt_compiler.requirements as req_mod


class TestWtLocalChannel:
    """Tests for WT_LOCAL_CHANNEL configuration via WT_CONDA_CHANNEL env var."""

    @staticmethod
    def _reload_wt_local_channel():
        """Reload the requirements module and return the WT_LOCAL_CHANNEL."""
        importlib.reload(req_mod)
        return req_mod.WT_LOCAL_CHANNEL

    def test_default_when_env_var_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test WT_LOCAL_CHANNEL uses default path when WT_CONDA_CHANNEL is not set."""
        monkeypatch.delenv("WT_CONDA_CHANNEL", raising=False)
        channel = self._reload_wt_local_channel()

        assert channel.base_url == "file:///tmp/wt-conda-channel/"

    def test_default_when_env_var_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test WT_LOCAL_CHANNEL uses default path when WT_CONDA_CHANNEL is empty string."""
        monkeypatch.setenv("WT_CONDA_CHANNEL", "")
        channel = self._reload_wt_local_channel()

        assert channel.base_url == "file:///tmp/wt-conda-channel/"

    def test_custom_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test WT_LOCAL_CHANNEL respects WT_CONDA_CHANNEL env var."""
        monkeypatch.setenv(
            "WT_CONDA_CHANNEL", "/tmp/ecoscope-workflows/release/artifacts"
        )
        channel = self._reload_wt_local_channel()

        assert channel.base_url == "file:///tmp/ecoscope-workflows/release/artifacts/"

    def test_custom_path_with_trailing_slash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test WT_LOCAL_CHANNEL handles trailing slash in WT_CONDA_CHANNEL."""
        monkeypatch.setenv(
            "WT_CONDA_CHANNEL", "/tmp/ecoscope-workflows/release/artifacts/"
        )
        channel = self._reload_wt_local_channel()

        assert channel.base_url == "file:///tmp/ecoscope-workflows/release/artifacts/"

    def test_simple_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test WT_LOCAL_CHANNEL works with a simple single-directory path."""
        monkeypatch.setenv("WT_CONDA_CHANNEL", "/opt/my-channel")
        channel = self._reload_wt_local_channel()

        assert channel.base_url == "file:///opt/my-channel/"
