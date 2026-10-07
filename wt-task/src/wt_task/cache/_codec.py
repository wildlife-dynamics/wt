"""Codec registry: how a task's return value becomes bytes, and back.

A value with no registered codec is simply not cached. There is deliberately no
pickle fallback: pickle couples every stored entry to the exact version of the
code that wrote it and turns the cache into a deserialization surface. Refusing
is always safe — the step runs normally.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.metadata
import json
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from wt_task.skip import SKIP_SENTINEL, SkipSentinel

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

ENTRY_POINT_GROUP = "wt_task.codecs"


class CodecConflictError(RuntimeError):
    """Raised when two codecs claim the same id, or the same type at equal priority."""


@dataclass(frozen=True)
class Codec:
    """Encodes one family of runtime values to bytes, and digests them for identity.

    `digest` is separate from `encode` on purpose: it must be stable across
    encodings, because an unstable digest silently invalidates every downstream
    cache entry on each run. Parquet in particular is not byte-stable, so a
    frame codec digests a canonical form rather than the bytes it writes.

    Attributes:
        codec_id: Stable identifier recorded in the cache entry and used to find
            this codec again at decode time. Changing it invalidates old entries.
        media_type: Media type of the encoded payload.
        types: Runtime types this codec claims, narrowed by MRO. A claim on a
            base type covers its subclasses unless something claims them more
            specifically.
        matches: Optional content check, for when the type alone is too coarse.
            A keyed iterable is a plain `list`, so a codec for it has to look at
            the contents; returning False hands the value to the next candidate
            rather than refusing it outright.
        priority: Orders candidates claiming the same type, highest first. Two
            codecs claiming one type at the same priority is an error rather
            than a coin toss, because the winner would otherwise depend on
            plugin import order and change how values were encoded.
    """

    codec_id: str
    media_type: str
    types: tuple[type, ...]
    encode: Callable[[Any], bytes]
    decode: Callable[[bytes], Any]
    digest: Callable[[Any], str]
    matches: Callable[[Any], bool] | None = None
    priority: int = 0


def json_digest(value: Any) -> str:  # noqa: ANN401  # digests arbitrary JSON-able values
    """Return a stable sha256 over a JSON-able value.

    Examples:
        >>> json_digest({"b": 1, "a": 2}) == json_digest({"a": 2, "b": 1})
        True
    """
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _json_encode(value: Any) -> bytes:  # noqa: ANN401  # encodes arbitrary JSON-able values
    return json.dumps(value, sort_keys=True, default=str).encode("utf-8")


def _json_decode(data: bytes) -> Any:  # noqa: ANN401  # decoded JSON is dynamic
    return json.loads(data)


def _bytes_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


JSON_CODEC = Codec(
    codec_id="json/v1",
    media_type="application/json",
    types=(str, int, float, bool, list, dict, type(None)),
    encode=_json_encode,
    decode=_json_decode,
    digest=json_digest,
    priority=-100,
)

BYTES_CODEC = Codec(
    codec_id="bytes/v1",
    media_type="application/octet-stream",
    types=(bytes,),
    encode=lambda v: v,
    decode=lambda d: d,
    digest=_bytes_digest,
    priority=-100,
)

_SKIP_MARKER = b'{"wt_task":"skip"}'


def _skip_encode(value: SkipSentinel) -> bytes:  # noqa: ARG001  # the sentinel carries no state
    return _SKIP_MARKER


def _skip_decode(data: bytes) -> SkipSentinel:  # noqa: ARG001  # the marker carries no state
    return SKIP_SENTINEL


# A skipped step is cached like any other result. Without this the sentinel would
# have no codec, the step would record itself uncacheable, and every step below a
# skip would lose its cache.
SKIP_CODEC = Codec(
    codec_id="skip/v1",
    media_type="application/json",
    types=(SkipSentinel,),
    encode=_skip_encode,
    decode=_skip_decode,
    digest=lambda _v: hashlib.sha256(_SKIP_MARKER).hexdigest(),
)

BUILTIN_CODECS: tuple[Codec, ...] = (JSON_CODEC, BYTES_CODEC, SKIP_CODEC)


@dataclass(frozen=True)
class CodecRegistry:
    """Resolves a runtime value, or a recorded codec id, to its codec."""

    by_id: dict[str, Codec]
    _dispatch: Callable[[Any], Codec | None]

    def for_value(self, value: Any) -> Codec | None:  # noqa: ANN401  # dispatches on any runtime value
        """Return the codec claiming `value`'s type, or None if it is uncacheable."""
        return self._dispatch(value)

    def for_id(self, codec_id: str) -> Codec | None:
        """Return the codec that wrote an entry, or None if it is no longer installed."""
        return self.by_id.get(codec_id)


def _candidates(claimed: type, codecs: list[Codec]) -> list[Codec]:
    """Codecs eligible for `claimed`, most specific first, then highest priority.

    Includes codecs claiming an ancestor, so a value whose own type declines on
    content still falls through to a more general codec instead of becoming
    uncacheable.
    """
    ranked: list[tuple[int, int, Codec]] = []
    for codec in codecs:
        distances = [claimed.__mro__.index(t) for t in codec.types if t in claimed.__mro__]
        if distances:
            ranked.append((min(distances), -codec.priority, codec))
    # The sort key is unique: MRO distance is unique per claimed type, and two
    # codecs claiming one type at equal priority is rejected below.
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [codec for _, _, codec in ranked]


def build_registry(codecs: Iterable[Codec]) -> CodecRegistry:
    """Build a registry, rejecting duplicate ids and ambiguous type claims.

    Raises:
        CodecConflictError: On a duplicate `codec_id`, or on two codecs claiming
            the same type at the same priority.

    Examples:
        >>> reg = build_registry(BUILTIN_CODECS)
        >>> reg.for_value({"a": 1}).codec_id
        'json/v1'
        >>> reg.for_value(b"x").codec_id
        'bytes/v1'
        >>> reg.for_value(object()) is None
        True
    """
    codecs = list(codecs)
    by_id: dict[str, Codec] = {}
    seen: dict[tuple[type, int], Codec] = {}
    for codec in codecs:
        if codec.codec_id in by_id:
            raise CodecConflictError(
                f"Duplicate codec_id {codec.codec_id!r}: already registered by "
                f"{by_id[codec.codec_id]}. Codec ids must be unique across all "
                f"{ENTRY_POINT_GROUP} entry points."
            )
        by_id[codec.codec_id] = codec
        for typ in codec.types:
            incumbent = seen.get((typ, codec.priority))
            if incumbent is not None:
                raise CodecConflictError(
                    f"Codecs {incumbent.codec_id!r} and {codec.codec_id!r} both claim "
                    f"{typ.__name__} at priority {codec.priority}. Give one a higher "
                    f"priority to disambiguate."
                )
            seen[(typ, codec.priority)] = codec

    claimed_types = {typ for codec in codecs for typ in codec.types}

    @functools.singledispatch
    def dispatch(value: Any) -> Codec | None:  # noqa: ANN401, ARG001  # fallback for unclaimed types
        return None

    for claimed in claimed_types:
        candidates = _candidates(claimed, codecs)
        dispatch.register(claimed, functools.partial(_first_match, candidates=candidates))

    return CodecRegistry(by_id=by_id, _dispatch=dispatch)


def _first_match(value: Any, candidates: list[Codec]) -> Codec | None:  # noqa: ANN401  # inspects any runtime value
    """Return the first candidate that claims `value`, or None if all decline."""
    for codec in candidates:
        if codec.matches is None or codec.matches(value):
            return codec
    return None


def _load_plugin(ep: importlib.metadata.EntryPoint) -> list[Codec]:
    """Load one entry point's codecs, disabling it on failure rather than raising.

    Caching is an optimization, never a correctness requirement, so a broken
    plugin costs its codecs' cache coverage and nothing else.
    """
    try:
        return list(ep.load()())
    except Exception as e:  # noqa: BLE001  # a broken plugin must not break the run
        warnings.warn(
            f"Codec entry point {ep.name!r} failed to load ({e!r}); "
            f"values it would have handled will not be cached.",
            stacklevel=2,
        )
        return []


@functools.lru_cache(maxsize=1)
def get_registry() -> CodecRegistry:
    """Return the process-wide registry, discovering plugins on first use.

    Task libraries extend this inward by declaring a `wt_task.codecs` entry
    point whose value is a zero-argument callable returning an iterable of
    `Codec`.
    """
    codecs: list[Codec] = list(BUILTIN_CODECS)
    for ep in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        codecs.extend(_load_plugin(ep))
    return build_registry(codecs)
