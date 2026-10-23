"""The cache's runtime settings, in one place.

Operations, not authoring: these say how *this run* should treat the cache, so
they are deliberately env-and-file only. There is no way to set them from
`spec.yaml` — a workflow author should not be deciding another deployment's
freshness policy or where its store lives.

Read once per `run_scope`, so a DAG does not re-read the environment per step.
"""

from __future__ import annotations

import contextlib
import re
import warnings
from contextvars import ContextVar
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError, field_validator
from pydantic_settings import (
    BaseSettings,
    PyprojectTomlConfigSettingsSource,
    SettingsConfigDict,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic_settings import PydanticBaseSettingsSource

ENV_PREFIX = "WT_CACHE__"
PYPROJECT_TABLE = ("tool", "wt", "cache")

_DURATION = re.compile(r"(\d+)([smhd]?)")
_UNIT_SECONDS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}

# What a field falls back to when its value will not parse and strict is off:
# always refetch, which costs time but never serves something older than asked.
_FAIL_SAFE: dict[str, Any] = {"io_ttl": timedelta(0)}


def parse_duration(raw: str) -> timedelta | None:
    """Read an `io_ttl`: `forever`, `never`, or `<n>[s|m|h|d]`.

    Returns:
        None for "serve indefinitely", else the window. A zero window means
        never serve, which falls out of the `age < ttl` comparison for free.

    Raises:
        ValueError: On anything else. A bare integer is seconds.

    Examples:
        >>> parse_duration("30m")
        datetime.timedelta(seconds=1800)
        >>> parse_duration("forever") is None
        True
        >>> parse_duration("never")
        datetime.timedelta(0)
    """
    text = raw.strip().lower()
    if text in ("", "forever"):
        return None
    if text == "never":
        return timedelta(0)
    match = _DURATION.fullmatch(text)
    if match is None:
        raise ValueError(f"expected 'forever', 'never' or <n>[s|m|h|d], got {raw!r}")
    return timedelta(seconds=int(match[1]) * _UNIT_SECONDS[match[2]])


class _Sources(BaseSettings):
    """Where every cache setting is looked up, and in what order."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        pyproject_toml_table_header=PYPROJECT_TABLE,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003  # unused source
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Explicit arguments beat the environment beats `.env` beats pyproject."""
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            PyprojectTomlConfigSettingsSource(settings_cls),
        )


class _StrictOnly(_Sources):
    """Reads `strict` alone, so a value that will not parse cannot hide it."""

    strict: bool = False


class CacheSettings(_Sources):
    """How this run treats the cache.

    Every field is read from `WT_CACHE__<FIELD>`, from a `.env` file, or from a
    `[tool.wt.cache]` table in `pyproject.toml`, in that order of precedence.
    The defaults are what the cache did before any of them existed.

    Attributes:
        store: Where entries live — a local path or an object-store URL. Empty
            means the cache is inert and every step runs.
        epoch: Manual invalidator, mixed into every key. Derive it from the
            task-library build, not the per-workflow image, or two workflows
            shipping the same library would never share an entry.
        scope: Folded into io-tagged steps' keys, to separate principals that
            share a connection name.
        io_ttl: How long an io-tagged step's stored result may be served.
            None serves indefinitely; a zero window never serves and always
            refetches. Derived steps never expire.
        verify: Re-run every step and compare against what is stored, without
            serving or writing.
        strict: Raise where the cache would otherwise degrade to uncacheable —
            an unresolvable codec, a setting that will not parse.

    Examples:
        >>> CacheSettings(io_ttl="30m").io_ttl
        datetime.timedelta(seconds=1800)
        >>> CacheSettings().store
        ''
    """

    store: str = ""
    epoch: str = ""
    scope: str = ""
    io_ttl: timedelta | None = None
    verify: bool = False
    strict: bool = False

    @field_validator("io_ttl", mode="before")
    @classmethod
    def _duration(cls, value: Any) -> Any:  # noqa: ANN401  # whatever a source supplies
        return parse_duration(value) if isinstance(value, str) else value


def load_settings(**overrides: Any) -> CacheSettings:  # noqa: ANN401  # field values
    """Build the settings, degrading rather than failing a run.

    A value that will not parse warns and falls back to the safest reading of
    that field. `strict` is resolved on its own first, because it is what
    decides whether to raise — and it must stay readable when a neighbouring
    field is what broke.

    Raises:
        ValidationError: If anything will not parse and `strict` is set.
    """
    try:
        return CacheSettings(**overrides)
    except ValidationError as e:
        if _StrictOnly().strict:
            raise
        broken = {str(err["loc"][0]) for err in e.errors() if err["loc"]}
        warnings.warn(
            f"Ignoring unusable cache settings ({', '.join(sorted(broken))}): {e}",
            stacklevel=2,
        )
        return CacheSettings(**{**overrides, **{f: _FAIL_SAFE[f] for f in broken}})


_RUN_SETTINGS: ContextVar[CacheSettings] = ContextVar("_RUN_SETTINGS")


@contextlib.contextmanager
def use_settings(settings: CacheSettings) -> Iterator[CacheSettings]:
    """Make `settings` the ones every part of the cache reads, for this scope."""
    token = _RUN_SETTINGS.set(settings)
    try:
        yield settings
    finally:
        _RUN_SETTINGS.reset(token)


def active_settings() -> CacheSettings:
    """The settings for the current run.

    Outside a `run_scope` — a task called directly in a test or a REPL — they
    are built on demand, which keeps behaviour identical at the cost of
    re-reading the sources. A generated DAG always runs inside a scope.
    """
    current = _RUN_SETTINGS.get(None)
    return current if current is not None else load_settings()
