"""Tests for `CacheSettings`: where the cache's runtime knobs come from."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from wt_task.cache import CacheSettings, run_scope
from wt_task.cache._settings import (
    ENV_PREFIX,
    active_settings,
    load_settings,
    use_settings,
)

FIELDS = ("store", "epoch", "scope", "io_ttl", "verify", "strict")


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    """No stray environment, and no .env or pyproject.toml unless a test writes one."""
    for field in FIELDS:
        monkeypatch.delenv(f"{ENV_PREFIX}{field.upper()}", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write(path, text):
    path.write_text(text)


# --- defaults ---------------------------------------------------------------


def test_the_defaults_are_what_the_cache_did_before_any_of_this():
    settings = CacheSettings()
    assert settings.store == ""
    assert settings.epoch == ""
    assert settings.scope == ""
    assert settings.io_ttl is None  # serve indefinitely
    assert settings.verify is False
    assert settings.strict is False


# --- the environment --------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("store", "s3://bucket/cache", "s3://bucket/cache"),
        ("epoch", "sha-abc", "sha-abc"),
        ("scope", "tenant-a", "tenant-a"),
        ("io_ttl", "30m", timedelta(minutes=30)),
        ("verify", "1", True),
        ("strict", "true", True),
    ],
)
def test_each_field_comes_from_its_env_var(monkeypatch, field, raw, expected):
    monkeypatch.setenv(f"{ENV_PREFIX}{field.upper()}", raw)
    assert getattr(load_settings(), field) == expected


def test_env_names_are_case_insensitive(monkeypatch):
    monkeypatch.setenv("wt_cache__scope", "tenant-a")
    assert load_settings().scope == "tenant-a"


def test_an_unrelated_prefixed_variable_is_ignored(monkeypatch):
    monkeypatch.setenv(f"{ENV_PREFIX}NOT_A_SETTING", "x")
    assert load_settings().store == ""


# --- file sources -----------------------------------------------------------


def test_a_dotenv_file_is_read(clean):
    write(clean / ".env", f"{ENV_PREFIX}SCOPE=from-dotenv\n{ENV_PREFIX}IO_TTL=1h\n")
    settings = load_settings()
    assert settings.scope == "from-dotenv"
    assert settings.io_ttl == timedelta(hours=1)


def test_a_pyproject_table_is_read(clean):
    write(clean / "pyproject.toml", '[tool.wt.cache]\nscope = "from-pyproject"\nio_ttl = "7d"\n')
    settings = load_settings()
    assert settings.scope == "from-pyproject"
    assert settings.io_ttl == timedelta(days=7)


def test_a_pyproject_without_the_table_contributes_nothing(clean):
    write(clean / "pyproject.toml", '[project]\nname = "something-else"\n')
    assert load_settings().scope == ""


def test_a_bare_integer_in_pyproject_is_seconds(clean):
    write(clean / "pyproject.toml", "[tool.wt.cache]\nio_ttl = 90\n")
    assert load_settings().io_ttl == timedelta(seconds=90)


# --- precedence -------------------------------------------------------------


def test_the_environment_beats_a_dotenv_file(clean, monkeypatch):
    write(clean / ".env", f"{ENV_PREFIX}SCOPE=from-dotenv\n")
    monkeypatch.setenv(f"{ENV_PREFIX}SCOPE", "from-env")
    assert load_settings().scope == "from-env"


def test_a_dotenv_file_beats_pyproject(clean):
    write(clean / ".env", f"{ENV_PREFIX}SCOPE=from-dotenv\n")
    write(clean / "pyproject.toml", '[tool.wt.cache]\nscope = "from-pyproject"\n')
    assert load_settings().scope == "from-dotenv"


def test_explicit_arguments_beat_everything(clean, monkeypatch):
    write(clean / ".env", f"{ENV_PREFIX}SCOPE=from-dotenv\n")
    write(clean / "pyproject.toml", '[tool.wt.cache]\nscope = "from-pyproject"\n')
    monkeypatch.setenv(f"{ENV_PREFIX}SCOPE", "from-env")
    assert load_settings(scope="explicit").scope == "explicit"


def test_the_full_order_holds_for_one_field(clean, monkeypatch):
    # Each source in turn is the most specific one present.
    write(clean / "pyproject.toml", '[tool.wt.cache]\nscope = "pyproject"\n')
    assert load_settings().scope == "pyproject"
    write(clean / ".env", f"{ENV_PREFIX}SCOPE=dotenv\n")
    assert load_settings().scope == "dotenv"
    monkeypatch.setenv(f"{ENV_PREFIX}SCOPE", "env")
    assert load_settings().scope == "env"
    assert load_settings(scope="init").scope == "init"


# --- io_ttl through the model ----------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", None),
        ("forever", None),
        ("NEVER", timedelta(0)),
        ("0", timedelta(0)),
        ("45s", timedelta(seconds=45)),
        ("2h", timedelta(hours=2)),
    ],
)
def test_io_ttl_parses_through_the_model(raw, expected):
    assert CacheSettings(io_ttl=raw).io_ttl == expected


def test_a_bad_io_ttl_degrades_to_never_with_a_warning(monkeypatch):
    monkeypatch.setenv(f"{ENV_PREFIX}IO_TTL", "soon")
    with pytest.warns(UserWarning, match="io_ttl"):
        assert load_settings().io_ttl == timedelta(0)


def test_a_bad_io_ttl_raises_under_strict(monkeypatch):
    monkeypatch.setenv(f"{ENV_PREFIX}IO_TTL", "soon")
    monkeypatch.setenv(f"{ENV_PREFIX}STRICT", "1")
    with pytest.raises(ValidationError):
        load_settings()


def test_strict_is_still_readable_when_a_neighbour_is_what_broke(clean, monkeypatch):
    # `strict` decides whether to raise, so it is resolved on its own first.
    write(clean / "pyproject.toml", "[tool.wt.cache]\nstrict = true\n")
    monkeypatch.setenv(f"{ENV_PREFIX}IO_TTL", "soon")
    with pytest.raises(ValidationError):
        load_settings()


def test_the_other_fields_survive_a_bad_one(monkeypatch):
    monkeypatch.setenv(f"{ENV_PREFIX}IO_TTL", "soon")
    monkeypatch.setenv(f"{ENV_PREFIX}SCOPE", "tenant-a")
    with pytest.warns(UserWarning, match="io_ttl"):
        settings = load_settings()
    assert settings.scope == "tenant-a"


# --- the active settings ----------------------------------------------------


def test_outside_a_scope_the_settings_are_built_on_demand(monkeypatch):
    monkeypatch.setenv(f"{ENV_PREFIX}SCOPE", "first")
    assert active_settings().scope == "first"
    monkeypatch.setenv(f"{ENV_PREFIX}SCOPE", "second")
    assert active_settings().scope == "second"


def test_inside_a_scope_the_settings_are_fixed(monkeypatch):
    monkeypatch.setenv(f"{ENV_PREFIX}SCOPE", "first")
    with run_scope():
        monkeypatch.setenv(f"{ENV_PREFIX}SCOPE", "second")
        assert active_settings().scope == "first"
    assert active_settings().scope == "second"


def test_a_scope_can_be_given_its_settings_outright(monkeypatch):
    monkeypatch.setenv(f"{ENV_PREFIX}SCOPE", "from-env")
    with run_scope(settings=CacheSettings(scope="explicit")):
        assert active_settings().scope == "explicit"


def test_use_settings_restores_the_previous_ones():
    with use_settings(CacheSettings(scope="outer")):
        with use_settings(CacheSettings(scope="inner")):
            assert active_settings().scope == "inner"
        assert active_settings().scope == "outer"
