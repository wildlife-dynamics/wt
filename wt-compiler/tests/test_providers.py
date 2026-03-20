"""Tests for wt_compiler.providers module."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wt_compiler.providers import (
    _config_dir,
    get_registered_providers,
    get_registry_path,
    install_and_register,
    load_provider_class,
    load_registry,
    save_registry,
)
from wt_compiler.wizard.abstract import AbstractWizardProvider

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect get_registry_path() to a tmp file for isolation."""
    path = tmp_path / "providers.json"
    monkeypatch.setattr("wt_compiler.providers.get_registry_path", lambda: path)
    return path


# ---------------------------------------------------------------------------
# TestConfigDir
# ---------------------------------------------------------------------------


class TestConfigDir:
    """Tests for _config_dir()."""

    def test_uses_xdg_config_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """XDG_CONFIG_HOME is used when set to a non-empty value."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert _config_dir() == tmp_path / "wt-compiler"

    def test_falls_back_to_home_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to ~/.config/wt-compiler when XDG_CONFIG_HOME is unset."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        result = _config_dir()
        assert str(result).endswith(".config/wt-compiler")

    def test_empty_xdg_config_home_treated_as_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty XDG_CONFIG_HOME is treated as unset per XDG spec."""
        monkeypatch.setenv("XDG_CONFIG_HOME", "")
        result = _config_dir()
        assert str(result).endswith(".config/wt-compiler")
        assert not str(result).startswith("wt-compiler")


# ---------------------------------------------------------------------------
# TestGetRegistryPath
# ---------------------------------------------------------------------------


class TestGetRegistryPath:
    """Tests for get_registry_path()."""

    def test_returns_providers_json(self) -> None:
        """Path ends with wt-compiler/providers.json."""
        path = get_registry_path()
        assert str(path).endswith("wt-compiler/providers.json")

    def test_respects_xdg_config_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Path starts with XDG_CONFIG_HOME when set."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        result = get_registry_path()
        assert str(result).startswith(str(tmp_path))


# ---------------------------------------------------------------------------
# TestLoadRegistry
# ---------------------------------------------------------------------------


class TestLoadRegistry:
    """Tests for load_registry()."""

    def test_returns_empty_list_when_file_absent(self, registry_path: Path) -> None:
        """Returns [] when registry file does not exist."""
        assert not registry_path.exists()
        assert load_registry() == []

    def test_parses_valid_json(self, registry_path: Path) -> None:
        """Correctly parses a valid registry JSON file."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            '{"providers": [{"name": "my-p", "package": "my-pkg"}]}'
        )
        result = load_registry()
        assert result == [{"name": "my-p", "package": "my-pkg"}]

    def test_raises_on_malformed_json(self, registry_path: Path) -> None:
        """Raises ValueError (json.JSONDecodeError subclass) on invalid JSON."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text("not json")
        with pytest.raises(ValueError):
            load_registry()

    def test_raises_on_missing_providers_key(self, registry_path: Path) -> None:
        """Raises ValueError when 'providers' key is absent."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text('{"other": []}')
        with pytest.raises(ValueError):
            load_registry()

    def test_raises_on_providers_not_list(self, registry_path: Path) -> None:
        """Raises ValueError when 'providers' is not a list."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text('{"providers": "bad"}')
        with pytest.raises(ValueError):
            load_registry()

    def test_raises_on_entry_missing_name(self, registry_path: Path) -> None:
        """Raises ValueError when an entry is missing the 'name' key."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text('{"providers": [{"package": "x"}]}')
        with pytest.raises(ValueError):
            load_registry()


# ---------------------------------------------------------------------------
# TestSaveRegistry
# ---------------------------------------------------------------------------


class TestSaveRegistry:
    """Tests for save_registry()."""

    def test_creates_parent_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Creates parent directories if they don't exist."""
        nested = tmp_path / "nested" / "subdir" / "providers.json"
        monkeypatch.setattr("wt_compiler.providers.get_registry_path", lambda: nested)
        assert not nested.parent.exists()
        save_registry([])
        assert nested.exists()

    def test_writes_correct_structure(self, registry_path: Path) -> None:
        """Written file can be read back and matches input."""
        entries = [{"name": "p1", "package": "pkg1"}]
        save_registry(entries)
        data = json.loads(registry_path.read_text())
        assert data == {"providers": entries}

    def test_round_trip(self, registry_path: Path) -> None:
        """save_registry + load_registry returns the same entries."""
        entries = [
            {"name": "p1", "package": "pkg1"},
            {"name": "p2", "package": "pkg2"},
        ]
        save_registry(entries)
        assert load_registry() == entries

    def test_writes_with_indent_2_and_trailing_newline(self, registry_path: Path) -> None:
        """File uses 2-space indentation and ends with a newline."""
        save_registry([{"name": "p", "package": "pkg"}])
        raw = registry_path.read_text()
        assert "  " in raw  # 2-space indentation
        assert raw.endswith("\n")  # trailing newline


# ---------------------------------------------------------------------------
# TestInstallAndRegister
# ---------------------------------------------------------------------------


def _make_mock_dist(dist_name: str, ep_names: list[str]) -> MagicMock:
    """Build a mock distribution object with wizard_providers entry points."""
    mock_dist = MagicMock()
    mock_dist.metadata = {"Name": dist_name}
    eps = []
    for name in ep_names:
        ep = MagicMock()
        ep.name = name
        ep.group = "wt_compiler.wizard_providers"
        eps.append(ep)
    mock_dist.entry_points = eps
    return mock_dist


class TestInstallAndRegister:
    """Tests for install_and_register()."""

    def test_uses_uv_when_available(
        self, registry_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Uses uv when it is found on PATH."""
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        with patch("wt_compiler.providers.shutil.which", return_value="/usr/bin/uv"):
            with patch("wt_compiler.providers.subprocess.run") as mock_run:
                with patch(
                    "wt_compiler.providers.distribution",
                    return_value=_make_mock_dist("my-pkg", ["my-provider"]),
                ):
                    install_and_register("my-pkg")
        mock_run.assert_called_once_with(
            ["uv", "pip", "install", "--python", sys.executable, "my-pkg"], check=True
        )

    def test_uses_conda_when_no_uv_and_conda_prefix_set(
        self, registry_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Uses conda when CONDA_PREFIX is set and uv is not found."""
        monkeypatch.setenv("CONDA_PREFIX", "/opt/conda")

        def which_side_effect(name: str) -> str | None:
            return None if name == "uv" else "/opt/conda/bin/conda"

        with patch("wt_compiler.providers.shutil.which", side_effect=which_side_effect):
            with patch("wt_compiler.providers.subprocess.run") as mock_run:
                with patch(
                    "wt_compiler.providers.distribution",
                    return_value=_make_mock_dist("my-pkg", ["my-provider"]),
                ):
                    install_and_register("my-pkg")
        mock_run.assert_called_once_with(["conda", "install", "-y", "my-pkg"], check=True)

    def test_falls_back_to_pip(
        self, registry_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falls back to sys.executable -m pip when uv and conda are absent."""
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        with patch("wt_compiler.providers.shutil.which", return_value=None):
            with patch("wt_compiler.providers.subprocess.run") as mock_run:
                with patch(
                    "wt_compiler.providers.distribution",
                    return_value=_make_mock_dist("my-pkg", ["my-provider"]),
                ):
                    install_and_register("my-pkg")
        mock_run.assert_called_once_with(
            [sys.executable, "-m", "pip", "install", "my-pkg"], check=True
        )

    def test_raises_value_error_on_no_entry_points(
        self, registry_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raises ValueError when the package has no wizard_providers entry points."""
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        mock_dist = MagicMock()
        mock_dist.metadata = {"Name": "my-pkg"}
        mock_dist.entry_points = []
        with patch("wt_compiler.providers.shutil.which", return_value=None):
            with patch("wt_compiler.providers.subprocess.run"):
                with patch("wt_compiler.providers.distribution", return_value=mock_dist):
                    with pytest.raises(ValueError, match="no 'wt_compiler.wizard_providers'"):
                        install_and_register("my-pkg")

    def test_skips_duplicate_with_warning(
        self, registry_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Skips already-registered providers and prints a warning to stderr."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text('{"providers": [{"name": "my-p", "package": "old-pkg"}]}')
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        with patch("wt_compiler.providers.shutil.which", return_value=None):
            with patch("wt_compiler.providers.subprocess.run"):
                with patch(
                    "wt_compiler.providers.distribution",
                    return_value=_make_mock_dist("new-pkg", ["my-p"]),
                ):
                    result = install_and_register("new-pkg")
        assert result == []
        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert "my-p" in captured.err

    def test_returns_newly_registered_names_only(
        self, registry_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns only the names of newly added providers."""
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        with patch("wt_compiler.providers.shutil.which", return_value=None):
            with patch("wt_compiler.providers.subprocess.run"):
                with patch(
                    "wt_compiler.providers.distribution",
                    return_value=_make_mock_dist("my-pkg", ["p1", "p2"]),
                ):
                    result = install_and_register("my-pkg")
        assert set(result) == {"p1", "p2"}

    def test_uses_normalized_dist_name(
        self, registry_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Saves the normalized distribution name from dist.metadata['Name']."""
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        with patch("wt_compiler.providers.shutil.which", return_value=None):
            with patch("wt_compiler.providers.subprocess.run"):
                with patch(
                    "wt_compiler.providers.distribution",
                    return_value=_make_mock_dist("My-Pkg", ["my-p"]),
                ):
                    install_and_register("my-pkg")
        saved = load_registry()
        assert saved[0]["package"] == "My-Pkg"

    def test_raises_value_error_on_invalid_package_name(
        self, registry_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raises ValueError for package names containing flag-like characters."""
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        with pytest.raises(ValueError, match="Invalid package name"):
            install_and_register("--extra-index-url http://evil.com/simple/")

    def test_raises_value_error_on_package_name_with_spaces(
        self, registry_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raises ValueError for package names containing spaces."""
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        with pytest.raises(ValueError, match="Invalid package name"):
            install_and_register("my pkg")

    def test_propagates_called_process_error(
        self, registry_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CalledProcessError from subprocess.run propagates to caller."""
        import subprocess as _subprocess

        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        with patch("wt_compiler.providers.shutil.which", return_value=None):
            with patch(
                "wt_compiler.providers.subprocess.run",
                side_effect=_subprocess.CalledProcessError(1, "pip"),
            ):
                with pytest.raises(_subprocess.CalledProcessError):
                    install_and_register("my-pkg")


# ---------------------------------------------------------------------------
# TestGetRegisteredProviders
# ---------------------------------------------------------------------------


class TestGetRegisteredProviders:
    """Tests for get_registered_providers()."""

    def test_returns_load_registry(self, registry_path: Path) -> None:
        """Returns same data as load_registry()."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        entries = [{"name": "p1", "package": "pkg1"}]
        registry_path.write_text(json.dumps({"providers": entries}))
        assert get_registered_providers() == load_registry()


# ---------------------------------------------------------------------------
# TestLoadProviderClass
# ---------------------------------------------------------------------------


class _FakeProvider(AbstractWizardProvider):
    """Minimal concrete provider for testing."""

    def get_questions(self) -> list:  # type: ignore[override]
        return []


class TestLoadProviderClass:
    """Tests for load_provider_class()."""

    def test_returns_class_for_registered_provider(self, registry_path: Path) -> None:
        """Returns the provider class for a registered, installed provider."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text('{"providers": [{"name": "my-p", "package": "my-pkg"}]}')
        mock_ep = MagicMock()
        mock_ep.name = "my-p"
        mock_ep.dist = MagicMock()
        mock_ep.dist.metadata = {"Name": "my-pkg"}
        mock_ep.load.return_value = _FakeProvider
        with patch("wt_compiler.providers.entry_points", return_value=[mock_ep]):
            result = load_provider_class("my-p")
        assert result is _FakeProvider

    def test_raises_value_error_when_not_in_registry(self, registry_path: Path) -> None:
        """Raises ValueError with '(none)' message when registry is empty."""
        with pytest.raises(ValueError, match=r"\(none\)"):
            load_provider_class("unknown")

    def test_raises_value_error_when_registered_but_not_installed(
        self, registry_path: Path
    ) -> None:
        """Raises ValueError when no EP with the registered package name is found."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text('{"providers": [{"name": "my-p", "package": "my-pkg"}]}')
        with patch("wt_compiler.providers.entry_points", return_value=[]):
            with pytest.raises(ValueError, match="not installed"):
                load_provider_class("my-p")

    def test_raises_value_error_on_conflicting_ep_from_other_package(
        self, registry_path: Path
    ) -> None:
        """Raises ValueError (not silently loads) when only a conflicting EP is found."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text('{"providers": [{"name": "my-p", "package": "my-pkg"}]}')
        evil_ep = MagicMock()
        evil_ep.name = "my-p"
        evil_ep.dist = MagicMock()
        evil_ep.dist.metadata = {"Name": "evil-pkg"}
        with patch("wt_compiler.providers.entry_points", return_value=[evil_ep]):
            with pytest.raises(ValueError, match="conflicting"):
                load_provider_class("my-p")
        evil_ep.load.assert_not_called()

    def test_raises_type_error_on_invalid_class(self, registry_path: Path) -> None:
        """Raises TypeError when loaded class is not an AbstractWizardProvider subclass."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text('{"providers": [{"name": "my-p", "package": "my-pkg"}]}')
        mock_ep = MagicMock()
        mock_ep.name = "my-p"
        mock_ep.dist = MagicMock()
        mock_ep.dist.metadata = {"Name": "my-pkg"}
        mock_ep.load.return_value = str  # not an AbstractWizardProvider subclass
        with patch("wt_compiler.providers.entry_points", return_value=[mock_ep]):
            with pytest.raises(TypeError, match="not a subclass of AbstractWizardProvider"):
                load_provider_class("my-p")

    def test_prefers_registered_package_when_multiple_eps(self, registry_path: Path) -> None:
        """When multiple EPs share a name, loads the one from the registered package."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            '{"providers": [{"name": "my-p", "package": "correct-pkg"}]}'
        )
        wrong_ep = MagicMock()
        wrong_ep.name = "my-p"
        wrong_ep.dist = MagicMock()
        wrong_ep.dist.metadata = {"Name": "wrong-pkg"}
        wrong_ep.load.return_value = object  # would fail type check

        correct_ep = MagicMock()
        correct_ep.name = "my-p"
        correct_ep.dist = MagicMock()
        correct_ep.dist.metadata = {"Name": "correct-pkg"}
        correct_ep.load.return_value = _FakeProvider

        with patch("wt_compiler.providers.entry_points", return_value=[wrong_ep, correct_ep]):
            result = load_provider_class("my-p")
        assert result is _FakeProvider
        wrong_ep.load.assert_not_called()

    def test_raises_value_error_on_ep_load_failure(self, registry_path: Path) -> None:
        """ep.load() raising ImportError → ValueError with helpful message."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            '{"providers": [{"name": "my-p", "package": "my-pkg"}]}'
        )
        mock_ep = MagicMock()
        mock_ep.name = "my-p"
        mock_ep.dist = MagicMock()
        mock_ep.dist.metadata = {"Name": "my-pkg"}
        mock_ep.load.side_effect = ImportError("missing transitive dep")
        with patch("wt_compiler.providers.entry_points", return_value=[mock_ep]):
            with pytest.raises(ValueError, match="Failed to load provider"):
                load_provider_class("my-p")

    def test_error_message_lists_registered_names(self, registry_path: Path) -> None:
        """ValueError message includes all registered provider names."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            '{"providers": [{"name": "p1", "package": "pkg1"}, {"name": "p2", "package": "pkg2"}]}'
        )
        with pytest.raises(ValueError) as exc_info:
            load_provider_class("unknown")
        msg = str(exc_info.value)
        assert "p1" in msg
        assert "p2" in msg
