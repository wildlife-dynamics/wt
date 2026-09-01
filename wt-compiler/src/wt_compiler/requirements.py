"""Requirement handling for rattler channels and match specifications."""

import os
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Annotated, TypedDict, cast
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict
from pydantic.functional_serializers import PlainSerializer
from pydantic.functional_validators import BeforeValidator
from rattler import Channel, ChannelConfig, MatchSpec, NamelessMatchSpec, Platform

LOCAL_CHANNEL = Channel(
    "artifacts",
    ChannelConfig(channel_alias="file:///tmp/ecoscope-workflows/release/"),
)
CUSTOM_LOCAL_CHANNEL = Channel(
    "ecoscope-workflows-custom/release/artifacts",
    ChannelConfig(channel_alias="file:///tmp/"),
)
_wt_channel_path = PurePosixPath(os.environ.get("WT_CONDA_CHANNEL") or "/tmp/wt-conda-channel")  # noqa: S108  # default fallback path; overridden by env var in deployments
WT_LOCAL_CHANNEL = Channel(
    _wt_channel_path.name,
    ChannelConfig(channel_alias=f"file://{_wt_channel_path.parent}/"),
)
RELEASE_CHANNEL = Channel(
    "ecoscope-workflows",
    ChannelConfig(channel_alias="https://repo.prefix.dev/"),
)
CUSTOM_RELEASE_CHANNEL = Channel(
    "ecoscope-workflows-custom",
    ChannelConfig(channel_alias="https://repo.prefix.dev/"),
)
CONDA_FORGE_CHANNEL = Channel("conda-forge")
MICROSOFT_CHANNEL = Channel("microsoft", ChannelConfig(channel_alias="https://conda.anaconda.org/"))
CHANNELS: list[Channel] = [
    LOCAL_CHANNEL,
    CUSTOM_LOCAL_CHANNEL,
    WT_LOCAL_CHANNEL,
    RELEASE_CHANNEL,
    CUSTOM_RELEASE_CHANNEL,
    CONDA_FORGE_CHANNEL,
    MICROSOFT_CHANNEL,
]
PLATFORMS: list[Platform] = [
    Platform("linux-64"),
    Platform("linux-aarch64"),
    Platform("osx-arm64"),
    Platform("win-64"),
    Platform("osx-64"),
]

# Minimum Linux kernel the compiled workflow must tolerate. Pixi's default for a
# bare "linux-*" platform is __linux = "4.18"; we loosen it so the image also runs
# on older Docker hosts. This is declared inline on the linux entries of
# DEFAULT_WORKSPACE_PLATFORMS below -- the `[system-requirements]` table that used
# to carry it was deprecated in pixi v0.71.0.
LINUX_KERNEL_VERSION = "4.4.0"


def _channel_from_str(value: str) -> Channel:
    """Convert a string to a Channel object.

    Known channel names and base URLs resolve to their preconfigured
    :data:`CHANNELS` shortcut. Any other explicit channel URL (one with a
    URL scheme) is parsed directly into a :class:`Channel`, so custom
    channels need not be hardcoded. A bare name that is neither a known
    shortcut nor a URL raises ``ValueError`` to guard against typos.

    Examples:
        A known shortcut resolves to its preconfigured channel:

        >>> _channel_from_str("conda-forge").name
        'conda-forge'

        An explicit custom channel URL passes through generically:

        >>> _channel_from_str("https://repo.prefix.dev/ecoscope-workflows-gcf/").name
        'ecoscope-workflows-gcf'
    """
    for channel in CHANNELS:
        # TODO(cisaacstern): base_url equality check can be stymied by presence or absence
        # of trailing slash on the base_url. Sanitize the base_url to prevent this issue.
        if channel.name == value or channel.base_url == value:
            return channel
    if urlparse(value).scheme:
        return Channel(value)
    raise ValueError(
        f"Unknown channel {value}; expected an explicit channel URL or one of the "
        f"known channel shortcuts {CHANNELS}"
    )


def _serialize_channel(value: Channel | str) -> str:
    """Serialize a Channel object to a string.

    A channel is serialized as its bare ``name`` only when that name
    round-trips to the same ``base_url`` under rattler's default channel
    alias (``conda.anaconda.org``); otherwise it is serialized as its
    explicit ``base_url`` so it reconstructs unambiguously. This keeps
    standard channels (e.g. ``conda-forge``, ``microsoft``) compact while
    letting prefix.dev, ``file://``, and other custom channels round-trip.
    """
    # Handle strings that might have been stored in defaults
    if isinstance(value, str):
        return value
    assert value.name is not None, f"Expected name to be set for {value}"  # noqa: S101  # type narrowing for mypy
    if Channel(value.name).base_url == value.base_url:
        return value.name
    return value.base_url


ChannelType = Annotated[
    Channel,
    BeforeValidator(_channel_from_str),
    PlainSerializer(_serialize_channel),
]


def _platform_from_str(value: str | Platform) -> Platform:
    """Convert a platform name to a Platform object, restricted to known platforms.

    Already-constructed :class:`Platform` objects pass through unchanged, so the
    same validator serves both TOML input (strings) and the in-code defaults in
    :data:`DEFAULT_WORKSPACE_PLATFORMS`.
    """
    if isinstance(value, Platform):
        return value
    for platform in PLATFORMS:
        if str(platform) == value:
            return platform
    raise ValueError(f"Unknown platform {value}")


PlatformType = Annotated[
    Platform,
    BeforeValidator(_platform_from_str),
    PlainSerializer(lambda value: str(value)),
]


class PlatformWithLinuxRequirement(BaseModel):
    """A ``[workspace].platforms`` entry pinning a minimum Linux kernel version.

    Pixi calls these "rich platforms": a platform declared as an inline table
    rather than a bare name, carrying system requirements alongside it. Only the
    keys named here are customised; every other virtual package keeps pixi's
    default for that platform.

    This models exactly the one requirement we pin. Other rich-platform keys
    (``glibc``, ``cuda``, ``archspec``) are deliberately not represented.

    Examples:
        >>> entry = PlatformWithLinuxRequirement(platform="linux-64", linux="4.4.0")
        >>> str(entry.platform)
        'linux-64'
        >>> entry.linux
        '4.4.0'
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    platform: PlatformType
    linux: str


def _workspace_platform_from_value(
    value: str | dict[str, str] | Platform | PlatformWithLinuxRequirement,
) -> Platform | PlatformWithLinuxRequirement:
    """Parse a single ``[workspace].platforms`` entry.

    An entry is either a bare platform name (``"osx-arm64"``) or an inline table
    carrying system requirements (``{platform = "linux-64", linux = "4.4.0"}``).
    Both shapes appear in manifests we emit and in manifests we read back via
    :meth:`wt_compiler.artifacts.PixiToml.from_file`, so both must parse.

    Dispatching explicitly on the input shape -- rather than relying on a bare
    ``Platform | PlatformWithLinuxRequirement`` union -- keeps parsing
    independent of pydantic's smart-union ordering.

    Args:
        value: A raw entry as read from TOML, or an already-parsed object.

    Returns:
        The parsed entry.

    Raises:
        ValueError: If a bare name is not a known platform.

    Examples:
        >>> str(_workspace_platform_from_value("osx-arm64"))
        'osx-arm64'
        >>> parsed = _workspace_platform_from_value({"platform": "linux-64", "linux": "4.4.0"})
        >>> parsed.linux
        '4.4.0'
    """
    if isinstance(value, PlatformWithLinuxRequirement | Platform):
        return value
    if isinstance(value, dict):
        return PlatformWithLinuxRequirement.model_validate(value)
    return _platform_from_str(value)


def _serialize_workspace_platform(
    value: Platform | PlatformWithLinuxRequirement,
) -> str | dict[str, str]:
    """Serialize a single ``[workspace].platforms`` entry to TOML-ready data.

    Bare platforms stay strings and rich entries become plain dicts, so the
    emitted list is a *mixed* array. That mix is load-bearing: ``tomli_w``
    promotes an array whose items are *all* mappings into ``[[table]]``
    array-of-tables sections, which pixi does not accept for ``platforms``.

    Args:
        value: A parsed platforms entry.

    Returns:
        A string for a bare platform, or a dict for a rich entry.

    Examples:
        >>> _serialize_workspace_platform(Platform("osx-arm64"))
        'osx-arm64'
        >>> entry = PlatformWithLinuxRequirement(platform="linux-64", linux="4.4.0")
        >>> _serialize_workspace_platform(entry)
        {'platform': 'linux-64', 'linux': '4.4.0'}
    """
    if isinstance(value, PlatformWithLinuxRequirement):
        return {"platform": str(value.platform), "linux": value.linux}
    return str(value)


WorkspacePlatformType = Annotated[
    Platform | PlatformWithLinuxRequirement,
    BeforeValidator(_workspace_platform_from_value),
    PlainSerializer(_serialize_workspace_platform),
]

# Platforms that take the kernel pin. Everything else in PLATFORMS stays a bare
# name -- which also keeps the emitted array mixed; see
# _serialize_workspace_platform.
_LINUX_PLATFORMS = frozenset({"linux-64", "linux-aarch64"})

# Default `[workspace].platforms` for a compiled workflow, derived from PLATFORMS so
# the two cannot drift. Held as raw str/dict data rather than parsed objects: pydantic
# deep-copies mutable field defaults, and rattler's `Platform` cannot be pickled.
DEFAULT_WORKSPACE_PLATFORMS: list[str | dict[str, str]] = [
    {"platform": str(p), "linux": LINUX_KERNEL_VERSION} if str(p) in _LINUX_PLATFORMS else str(p)
    for p in PLATFORMS
]


class _SerializedNamelessMatchSpecDict(TypedDict):
    """TypedDict for NamelessMatchSpec serialization.

    Version is a string, channel is a string that can be either a
    channel name or a base_url.
    """

    version: str
    channel: str


class _SerializedNamelessMatchSpecDictMinimal(TypedDict):
    """TypedDict for NamelessMatchSpec serialization with only a version.

    This is used when the channel is not specified.
    """

    version: str


if TYPE_CHECKING:
    # these types are useful for type safety and expressiveness, but are only used
    # for type checking and should not be used at runtime, because if used at runtime
    # they confuse pydantic's construction of DagCompiler & Spec classes in compiler.py...
    SerializedNamelessMatchSpecDict = _SerializedNamelessMatchSpecDict
    SerializedNamelessMatchSpecDictMinimal = _SerializedNamelessMatchSpecDictMinimal
else:
    # ...so at runtime we let them be just dicts
    SerializedNamelessMatchSpecDict = dict[str, str]
    SerializedNamelessMatchSpecDictMinimal = dict[str, str]


def _namelessmatchspec_from_dict(
    value: SerializedNamelessMatchSpecDict,
) -> NamelessMatchSpec:
    """Create a NamelessMatchSpec from a dictionary with version and channel.

    The channel can be either a known channel name or an explicit channel
    URL. Bare names are resolved via :func:`_channel_from_str` (which still
    rejects unknown bare names to guard against typos); explicit URLs pass
    through generically, so custom channels need not be hardcoded.

    Args:
        value: Dictionary with 'version' and 'channel' keys

    Returns:
        A NamelessMatchSpec object

    Raises:
        AssertionError: If 'version' or 'channel' keys are missing
        ValueError: If the channel is a bare name that is not a known shortcut

    Examples:
        >>> value = {
        ...     "version": ">=0.1.0",
        ...     "channel": "https://repo.prefix.dev/ecoscope-workflows/",
        ... }
        >>> nms = _namelessmatchspec_from_dict(value)
        >>> nms.version
        '>=0.1.0'
        >>> nms.channel.name
        'ecoscope-workflows'
        >>> nms.channel.base_url
        'https://repo.prefix.dev/ecoscope-workflows/'

        Using channel name:

        >>> value_with_channel_name = {
        ...     "version": ">=0.1.0",
        ...     "channel": "ecoscope-workflows",
        ... }
        >>> nms_from_channel_name = _namelessmatchspec_from_dict(value_with_channel_name)
        >>> nms_from_channel_name.channel.name
        'ecoscope-workflows'
        >>> nms_from_channel_name.channel.base_url
        'https://repo.prefix.dev/ecoscope-workflows/'

        A custom channel URL passes through without being hardcoded:

        >>> custom = {
        ...     "version": ">=1.0",
        ...     "channel": "https://repo.prefix.dev/ecoscope-workflows-gcf/",
        ... }
        >>> nms_custom = _namelessmatchspec_from_dict(custom)
        >>> nms_custom.version
        '>=1.0'
        >>> nms_custom.channel.base_url
        'https://repo.prefix.dev/ecoscope-workflows-gcf/'
    """
    assert "version" in value, f"Expected 'version' key in {value}"  # noqa: S101  # input shape invariant
    assert "channel" in value, f"Expected 'channel' key in {value}"  # noqa: S101  # input shape invariant
    if not urlparse(value["channel"]).scheme:
        _base_url = _channel_from_str(value["channel"]).base_url
    else:
        _base_url = value["channel"]
    foo_pkg = "foo"  # placeholder to use from_match_spec constructor
    m = MatchSpec(f"{_base_url}::{foo_pkg} {value['version']}")
    return NamelessMatchSpec.from_match_spec(m)


def _namelessmatchspec_from_str(value: str) -> NamelessMatchSpec:
    """Create a NamelessMatchSpec from a version string."""
    return NamelessMatchSpec(value)


def _parse_namelessmatchspec(
    value: str | SerializedNamelessMatchSpecDict | NamelessMatchSpec,
) -> NamelessMatchSpec:
    """Parse a NamelessMatchSpec from string, dictionary, or pass through if already parsed."""
    # Pass through already-validated NamelessMatchSpec objects
    if isinstance(value, NamelessMatchSpec):
        return value
    if isinstance(value, str):
        return _namelessmatchspec_from_str(value)
    # Handle dict with or without channel key
    if "channel" not in value:
        # No channel specified, use simple string parser
        return _namelessmatchspec_from_str(value.get("version", "*"))
    return _namelessmatchspec_from_dict(value)


def _serialize_namelessmatchspec(
    value: NamelessMatchSpec,
) -> SerializedNamelessMatchSpecDictMinimal | SerializedNamelessMatchSpecDict:
    """Serialize a NamelessMatchSpec to a dictionary.

    Returns a dictionary with version and (conditionally) channel.
    If the channel is None, only the version is returned.

    Args:
        value: The NamelessMatchSpec to serialize

    Returns:
        Dictionary with 'version' and optionally 'channel' keys

    Raises:
        ValueError: If channel.base_url has unexpected type

    Examples:
        Without channel:

        >>> nms = NamelessMatchSpec(">=0.1.0")
        >>> serialized = _serialize_namelessmatchspec(nms)
        >>> serialized
        {'version': '>=0.1.0'}

        Wildcard ``"*"`` round-trips to the literal ``"*"`` rather than
        ``"None"`` (``NamelessMatchSpec("*").version`` is ``None``):

        >>> _serialize_namelessmatchspec(NamelessMatchSpec("*"))
        {'version': '*'}

        With channel:

        >>> value = {
        ...     "version": ">=0.1.0",
        ...     "channel": "https://repo.prefix.dev/ecoscope-workflows/",
        ... }
        >>> nms = _namelessmatchspec_from_dict(value)
        >>> serialized = _serialize_namelessmatchspec(nms)
        >>> serialized
        {'version': '>=0.1.0', 'channel': 'https://repo.prefix.dev/ecoscope-workflows/'}
    """
    channel_base_url = value.channel.base_url if value.channel else None
    version_dict = {"version": "*" if value.version is None else str(value.version)}
    match channel_base_url:
        case None:
            return cast("SerializedNamelessMatchSpecDictMinimal", version_dict)
        case str():
            return cast(
                "SerializedNamelessMatchSpecDict",
                version_dict | {"channel": channel_base_url},
            )
        case _:
            raise ValueError(
                f"Unexpected channel.base_url type {type(channel_base_url)} in {value.channel}"
            )


NamelessMatchSpecType = Annotated[
    NamelessMatchSpec,
    BeforeValidator(_parse_namelessmatchspec),
    PlainSerializer(_serialize_namelessmatchspec),
]
