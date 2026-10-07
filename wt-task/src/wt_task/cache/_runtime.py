"""Running a step through the cache."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, TypeVar

from ._codec import get_registry
from ._entry import CacheEntry
from ._key import record, step_identity
from ._store import open_store

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from ._spec import CacheSpec
    from ._store import Store

R = TypeVar("R")

KEYS_PREFIX = "keys"
CAS_PREFIX = "cas"


class CacheCorruptionError(RuntimeError):
    """Raised when a stored payload exists but its codec cannot decode it.

    Not downgraded to a miss: the entry names an installed codec and a payload
    that is present, so a failure here means the store is lying about its
    contents, and recomputing would hide that. Format changes belong in a
    codec's id (`json/v1`), which misses cleanly instead.
    """


def _load(store: Store, identity: str) -> tuple[CacheEntry, Any] | None:
    """Return the entry and decoded value, or None for any kind of miss."""
    raw = store.get(f"{KEYS_PREFIX}/{identity}")
    if raw is None:
        return None
    try:
        entry = CacheEntry.model_validate_json(raw)
    except ValueError:  # pydantic's ValidationError subclasses ValueError
        return None

    codec = get_registry().for_id(entry.codec_id)
    if codec is None:
        # Whatever wrote this is no longer installed; recompute with what is.
        return None

    payload = store.get(f"{CAS_PREFIX}/{entry.content_id}")
    if payload is None:
        # Evicted, or the key outlived its payload. Stale, not corrupt.
        return None

    try:
        return entry, codec.decode(payload)
    except Exception as e:
        raise CacheCorruptionError(
            f"Codec {entry.codec_id!r} could not decode {CAS_PREFIX}/{entry.content_id} "
            f"for cache key {identity}: {e!r}"
        ) from e


def _save(store: Store, identity: str, value: Any) -> str | None:  # noqa: ANN401  # stores any task return
    """Store `value` and return its content id, or None if it was not stored."""
    codec = get_registry().for_value(value)
    if codec is None:
        return None

    content_id = f"{codec.codec_id}/{codec.digest(value)}"
    try:
        store.put(f"{CAS_PREFIX}/{content_id}", codec.encode(value))
        entry = CacheEntry(
            content_id=content_id, codec_id=codec.codec_id, media_type=codec.media_type
        )
        store.put(f"{KEYS_PREFIX}/{identity}", entry.model_dump_json().encode("utf-8"))
    except Exception as e:  # noqa: BLE001  # a store that cannot write must not fail the run
        warnings.warn(f"Could not write cache entry {identity}: {e!r}", stacklevel=2)
        return None
    return content_id


def _downstream(spec: CacheSpec, identity: str, content_id: str | None) -> str | None:
    """What dependents of this step should fold into their own keys.

    A source contributes its output's content id rather than its own identity:
    re-reading a source that returns unchanged data then leaves every key below
    it untouched, and re-reading changed data moves all of them.
    """
    if content_id is None:
        return None
    return content_id if spec.source else identity


def cached_call(spec: CacheSpec, run: Callable[[], R]) -> tuple[R, bool]:
    """Run `run()` through the cache, returning its result and whether it hit.

    Every failure path falls back to running normally and marks this step
    uncacheable for its dependents: an unset store, an unpinnable distribution,
    an uncacheable upstream, a value no codec claims, or a store that will not
    accept a write.
    """
    store = open_store()
    identity = step_identity(spec) if store is not None else None
    if store is None or identity is None:
        record(spec.task_instance_id, None)
        return run(), False

    loaded = _load(store, identity)
    if loaded is not None:
        entry, value = loaded
        record(spec.task_instance_id, _downstream(spec, identity, entry.content_id))
        return value, True

    result = run()
    record(spec.task_instance_id, _downstream(spec, identity, _save(store, identity, result)))
    return result, False
