"""Requirement handling for rattler channels and match specifications."""

import os
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Annotated, TypedDict, cast
from urllib.parse import urlparse

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


def _channel_from_str(value: str) -> Channel:
    """Convert a string to a Channel object."""
    for channel in CHANNELS:
        # TODO(cisaacstern): base_url equality check can be stymied by presence or absence
        # of trailing slash on the base_url. Sanitize the base_url to prevent this issue.
        if channel.name == value or channel.base_url == value:
            return channel
    raise ValueError(f"Unknown channel {value}; only {CHANNELS} are supported")


def _serialize_channel(value: Channel | str) -> str:
    """Serialize a Channel object to a string."""
    # Handle strings that might have been stored in defaults
    if isinstance(value, str):
        return value
    if value in [
        LOCAL_CHANNEL,
        RELEASE_CHANNEL,
        CUSTOM_LOCAL_CHANNEL,
        CUSTOM_RELEASE_CHANNEL,
        WT_LOCAL_CHANNEL,
    ]:
        return value.base_url
    assert value.name is not None, f"Expected name to be set for {value}"  # noqa: S101  # type narrowing for mypy
    return value.name


ChannelType = Annotated[
    Channel,
    BeforeValidator(_channel_from_str),
    PlainSerializer(_serialize_channel),
]


def _platform_from_str(value: str) -> Platform:
    """Convert a string to a Platform object."""
    for platform in PLATFORMS:
        if str(platform) == value:
            return platform
    raise ValueError(f"Unknown platform {value}")


PlatformType = Annotated[
    Platform,
    BeforeValidator(_platform_from_str),
    PlainSerializer(lambda value: str(value)),
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

    The channel can be either a channel name or a base_url.
    Raises ValueError if the channel is not recognized.

    Args:
        value: Dictionary with 'version' and 'channel' keys

    Returns:
        A NamelessMatchSpec object

    Raises:
        AssertionError: If 'version' or 'channel' keys are missing
        ValueError: If the channel is not recognized

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
    """
    assert "version" in value, f"Expected 'version' key in {value}"  # noqa: S101  # input shape invariant
    assert "channel" in value, f"Expected 'channel' key in {value}"  # noqa: S101  # input shape invariant
    if not urlparse(value["channel"]).scheme:
        _base_url = _channel_from_str(value["channel"]).base_url
    else:
        _base_url = value["channel"]
    channel = next((c.base_url for c in CHANNELS if c.base_url == _base_url), None)
    if not channel:
        raise ValueError(f"Unknown channel {value['channel']}; only {CHANNELS} are supported")
    foo_pkg = "foo"  # placeholder to use from_match_spec constructor
    m = MatchSpec(f"{channel}::{foo_pkg} {value['version']}")
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
