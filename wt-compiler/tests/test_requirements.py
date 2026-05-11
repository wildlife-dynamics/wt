"""Tests for wt_compiler.requirements module."""
# ruff: noqa: S108  # /tmp paths are test data

import importlib

import pytest
from rattler import NamelessMatchSpec

import wt_compiler.requirements as req_mod
from wt_compiler.requirements import _serialize_namelessmatchspec


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
        monkeypatch.setenv("WT_CONDA_CHANNEL", "/tmp/ecoscope-workflows/release/artifacts")
        channel = self._reload_wt_local_channel()

        assert channel.base_url == "file:///tmp/ecoscope-workflows/release/artifacts/"

    def test_custom_path_with_trailing_slash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test WT_LOCAL_CHANNEL handles trailing slash in WT_CONDA_CHANNEL."""
        monkeypatch.setenv("WT_CONDA_CHANNEL", "/tmp/ecoscope-workflows/release/artifacts/")
        channel = self._reload_wt_local_channel()

        assert channel.base_url == "file:///tmp/ecoscope-workflows/release/artifacts/"

    def test_simple_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test WT_LOCAL_CHANNEL works with a simple single-directory path."""
        monkeypatch.setenv("WT_CONDA_CHANNEL", "/opt/my-channel")
        channel = self._reload_wt_local_channel()

        assert channel.base_url == "file:///opt/my-channel/"


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("*", {"version": "*"}),
        (">=1.0", {"version": ">=1.0"}),
    ],
)
def test_serialize_namelessmatchspec_version(spec: str, expected: dict[str, str]) -> None:
    """Wildcard ``"*"`` round-trips to ``"*"`` rather than the literal ``"None"``.

    Regression: ``NamelessMatchSpec("*").version`` is ``None``, so previously
    ``str(value.version)`` produced ``"None"`` for unbounded specs, which pixi
    rejected at solve time (``No candidates were found for pandas ==none``).
    """
    assert _serialize_namelessmatchspec(NamelessMatchSpec(spec)) == expected
