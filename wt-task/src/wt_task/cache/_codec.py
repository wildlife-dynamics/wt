"""Leaf codecs: how one declared value becomes bytes, and back.

Which codec applies is not decided here — the task's return type declares it
(`wt_contracts.codecs`) and `_tree` resolves it. This module only holds the
builtin leaves and the shape a task library's own codecs must have.

There is deliberately no pickle fallback: pickle couples every stored entry to
the exact version of the code that wrote it and turns the cache into a
deserialization surface. Refusing is always safe — the step runs normally.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic_core import Url

from wt_task.skip import SKIP_SENTINEL, SkipSentinel

if TYPE_CHECKING:
    import enum
    from collections.abc import Callable


class Undigestible(Exception):  # noqa: N818  # named for what a codec does, not for a failure
    """Raised by a codec that cannot handle the value it was handed.

    The step then runs normally and records itself uncacheable, so a codec can
    decline a value (an unhashable cell, a subclass it does not cover) without
    the caller having to probe it first.
    """


@dataclass(frozen=True)
class Codec:
    """Encodes one family of runtime values to bytes, and digests them.

    `digest` is separate from `encode` on purpose: it must be stable across
    encodings, because an unstable digest silently invalidates every downstream
    cache entry on each run. Parquet in particular is not byte-stable, so a
    frame codec digests a canonical form rather than the bytes it writes.

    Attributes:
        codec_id: Stable identifier recorded in the payload header. Changing it
            makes old entries miss rather than decode wrongly.
        media_type: Media type of the encoded payload.
        types: Runtime types this codec accepts. Used only to pick an arm of a
            declared union; at a non-union position the declaration already
            settled it.
        encode: Value to bytes.
        decode: Bytes back to a value.
        digest: Stable content digest. May raise `Undigestible`.
        accepts_subclasses: Match with `isinstance` rather than
            `type(value) is types[0]`. Cleared by class-parameterized codecs,
            which must not accept a subclass their encoder would silently narrow.
    """

    codec_id: str
    media_type: str
    types: tuple[type, ...]
    encode: Callable[[Any], bytes]
    decode: Callable[[bytes], Any]
    digest: Callable[[Any], str]
    accepts_subclasses: bool = True


def json_digest(value: Any) -> str:  # noqa: ANN401  # digests arbitrary JSON-able values
    """Return a stable sha256 over a JSON-able value, stringifying what it must.

    The lenient `default=str` is for cache *keys*, whose inputs are compiler
    literals and params rather than task results. Payload digests use the
    strict `JSON` codec instead.

    Examples:
        >>> json_digest({"b": 1, "a": 2}) == json_digest({"a": 2, "b": 1})
        True
    """
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _strict_json(value: Any) -> bytes:  # noqa: ANN401  # encodes arbitrary JSON-able values
    """Serialize `value` as JSON, declining anything JSON cannot hold losslessly."""
    try:
        return json.dumps(value, sort_keys=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as e:
        raise Undigestible(f"not JSON-native: {e}") from e


JSON = Codec(
    codec_id="json/v1",
    media_type="application/json",
    types=(str, int, float, bool, list, dict, type(None)),
    encode=_strict_json,
    decode=json.loads,
    digest=lambda v: hashlib.sha256(_strict_json(v)).hexdigest(),
)
"""JSON-native values. Reached only through an explicit `CodecRef`, as the
declaration that a loosely-typed return really does hold plain JSON."""

BYTES = Codec(
    codec_id="bytes/v1",
    media_type="application/octet-stream",
    types=(bytes,),
    encode=lambda v: v,
    decode=lambda d: d,
    digest=lambda v: hashlib.sha256(v).hexdigest(),
)

PATH = Codec(
    codec_id="path/v1",
    media_type="text/plain",
    types=(pathlib.PurePath,),
    encode=lambda v: str(v).encode("utf-8"),
    decode=lambda d: pathlib.Path(d.decode("utf-8")),
    digest=lambda v: hashlib.sha256(str(v).encode("utf-8")).hexdigest(),
)
"""Paths travel as the path, not as the bytes they point at. A task returning
one is claiming the location is the result; `no-cache` is the way to say
otherwise."""

URL = Codec(
    codec_id="url/v1",
    media_type="text/plain",
    types=(Url,),
    encode=lambda v: str(v).encode("utf-8"),
    decode=lambda d: Url(d.decode("utf-8")),
    digest=lambda v: hashlib.sha256(str(v).encode("utf-8")).hexdigest(),
)

_SKIP_MARKER = b'{"wt_task":"skip"}'

SKIP = Codec(
    codec_id="skip/v1",
    media_type="application/json",
    types=(SkipSentinel,),
    encode=lambda _v: _SKIP_MARKER,
    decode=lambda _d: SKIP_SENTINEL,
    digest=lambda _v: hashlib.sha256(_SKIP_MARKER).hexdigest(),
)
"""A skipped step is cached like any other result. Without this the sentinel
would have no codec and every step below a skip would lose its cache."""


def enum_codec(cls: type[enum.Enum]) -> Codec:
    """Build the codec for one enum class: the member's value, round-tripped.

    Args:
        cls: The enum class, as named by the declared structure.

    Returns:
        A codec accepting exactly `cls`.

    Examples:
        >>> import enum
        >>> class Unit(enum.Enum):
        ...     km = "km"
        >>> codec = enum_codec(Unit)
        >>> codec.decode(codec.encode(Unit.km))
        <Unit.km: 'km'>
    """
    return Codec(
        codec_id=f"enum/v1/{cls.__module__}.{cls.__qualname__}",
        media_type="application/json",
        types=(cls,),
        encode=lambda v: _strict_json(v.value),
        decode=lambda d: cls(json.loads(d)),
        digest=lambda v: hashlib.sha256(_strict_json(v.value)).hexdigest(),
        accepts_subclasses=False,
    )
