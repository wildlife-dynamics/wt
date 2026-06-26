"""Tests for wt_compiler.requirements module."""
# ruff: noqa: S108  # /tmp paths are test data

import importlib

import pytest
from rattler import Channel, NamelessMatchSpec

import wt_compiler.requirements as req_mod
from wt_compiler.requirements import (
    CONDA_FORGE_CHANNEL,
    MICROSOFT_CHANNEL,
    RELEASE_CHANNEL,
    _channel_from_str,
    _namelessmatchspec_from_dict,
    _serialize_channel,
    _serialize_namelessmatchspec,
)

CUSTOM_CHANNEL_URL = "https://repo.prefix.dev/ecoscope-workflows-gcf/"


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


class TestChannelFromStr:
    """Tests for _channel_from_str shortcut resolution and URL pass-through."""

    def test_custom_url_passes_through(self) -> None:
        """A custom prefix.dev channel URL parses generically, no allowlist needed."""
        channel = _channel_from_str(CUSTOM_CHANNEL_URL)

        assert channel.name == "ecoscope-workflows-gcf"
        assert channel.base_url == CUSTOM_CHANNEL_URL

    def test_unknown_bare_name_raises(self) -> None:
        """A bare name that is neither a known shortcut nor a URL still raises."""
        with pytest.raises(ValueError, match="Unknown channel"):
            _channel_from_str("not-a-real-channel")

    def test_known_name_resolves_to_shortcut(self) -> None:
        """A known channel name resolves to its preconfigured shortcut."""
        channel = _channel_from_str("ecoscope-workflows")

        assert channel.base_url == RELEASE_CHANNEL.base_url

    def test_known_base_url_resolves_to_shortcut(self) -> None:
        """A known channel base_url resolves to its preconfigured shortcut."""
        channel = _channel_from_str(RELEASE_CHANNEL.base_url)

        assert channel.base_url == RELEASE_CHANNEL.base_url


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        (CONDA_FORGE_CHANNEL, "conda-forge"),
        (MICROSOFT_CHANNEL, "microsoft"),
        (RELEASE_CHANNEL, "https://repo.prefix.dev/ecoscope-workflows/"),
        (Channel(CUSTOM_CHANNEL_URL), CUSTOM_CHANNEL_URL),
    ],
)
def test_serialize_channel(channel: Channel, expected: str) -> None:
    """Channels that round-trip from name serialize as the name, else as base_url.

    ``conda-forge`` / ``microsoft`` reconstruct from their bare name under
    rattler's default alias, so they serialize compactly. prefix.dev channels
    (standard or custom) do not, so they serialize as their base_url to
    round-trip unambiguously.
    """
    assert _serialize_channel(channel) == expected


def test_serialize_channel_passthrough_str() -> None:
    """A string value (e.g. stored in defaults) passes through unchanged."""
    assert _serialize_channel("conda-forge") == "conda-forge"


class TestNamelessMatchSpecFromDictCustomChannel:
    """Tests for _namelessmatchspec_from_dict with custom (non-allowlisted) channels."""

    def test_custom_channel_url_accepted(self) -> None:
        """A custom prefix.dev channel URL is accepted and preserves version + channel."""
        value = {"version": ">=1.0", "channel": CUSTOM_CHANNEL_URL}
        nms = _namelessmatchspec_from_dict(value)

        assert nms.version == ">=1.0"
        assert nms.channel.base_url == CUSTOM_CHANNEL_URL
