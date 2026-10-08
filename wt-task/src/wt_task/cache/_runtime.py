"""Running a step through the cache."""

from __future__ import annotations

import os
import warnings
from typing import TYPE_CHECKING, TypeVar

from ._codec import get_registry
from ._entry import CacheEntry
from ._key import record, step_identity
from ._store import open_store

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from ._codec import Codec
    from ._spec import CacheSpec
    from ._store import Store

R = TypeVar("R")

KEYS_PREFIX = "keys"
CAS_PREFIX = "cas"

VERIFY_ENV_VAR = "WT_CACHE_VERIFY"


class CacheCorruptionError(RuntimeError):
    """Raised when a stored payload exists but its codec cannot decode it.

    Not downgraded to a miss: the entry names an installed codec and a payload
    that is present, so a failure here means the store is lying about its
    contents, and recomputing would hide that. Format changes belong in a
    codec's id (`json/v1`), which misses cleanly instead.
    """


class CacheMismatchWarning(UserWarning):
    """Warned under `WT_CACHE_VERIFY` when a step reproduced a different output.

    Its own category so that a verify run can collect the whole report with
    `warnings.catch_warnings(record=True)` rather than scraping stderr.
    """


def _verifying() -> bool:
    """Whether this run is checking stored outputs instead of serving them.

    Read per call rather than at import, matching the other `WT_CACHE_*` knobs,
    so a test or a notebook can turn it on without reimporting.
    """
    return os.environ.get(VERIFY_ENV_VAR, "") not in ("", "0")


def _load(store: Store, identity: str) -> tuple[CacheEntry, Any] | None:
    """Return the entry and decoded value, or None for any kind of miss."""
    entry = _read_entry(store, identity)
    if entry is None:
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


def _read_entry(store: Store, identity: str) -> CacheEntry | None:
    """Return the stored entry for `identity`, or None if there is none to read."""
    raw = store.get(f"{KEYS_PREFIX}/{identity}")
    if raw is None:
        return None
    try:
        return CacheEntry.model_validate_json(raw)
    except ValueError:  # pydantic's ValidationError subclasses ValueError
        return None


def _content_id(codec: Codec, value: Any) -> str:  # noqa: ANN401  # digests any task return
    """Content-address `value`, namespaced by codec so two cannot collide.

    Separate from `_save` because an unservable step still needs the digest —
    that is what it promotes to its dependents — but stores nothing.
    """
    return f"{codec.codec_id}/{codec.digest(value)}"


def _save(
    store: Store,
    identity: str,
    codec: Codec,
    content_id: str,
    value: Any,  # noqa: ANN401  # stores any task return
) -> bool:
    """Store `value` under `identity`, returning whether the store accepted it."""
    try:
        store.put(f"{CAS_PREFIX}/{content_id}", codec.encode(value))
        entry = CacheEntry(
            content_id=content_id, codec_id=codec.codec_id, media_type=codec.media_type
        )
        store.put(f"{KEYS_PREFIX}/{identity}", entry.model_dump_json().encode("utf-8"))
    except Exception as e:  # noqa: BLE001  # a store that cannot write must not fail the run
        warnings.warn(f"Could not write cache entry {identity}: {e!r}", stacklevel=2)
        return False
    return True


def _verify(store: Store, spec: CacheSpec, identity: str, content_id: str) -> None:
    """Warn if a stored output for this key differs from the one just computed.

    A mismatch is proof that identical declared inputs produced different
    output — the empirical way to find which tasks need the `no-cache` tag,
    including the ones whose author misspelled it.
    """
    entry = _read_entry(store, identity)
    if entry is None or entry.content_id == content_id:
        return
    warnings.warn(
        f"Cache verification failed for task instance {spec.task_instance_id!r} "
        f"({spec.anchor}.{spec.function}): stored output {entry.content_id} but "
        f"recomputed {content_id} for cache key {identity}. The same declared "
        f"inputs produced different output.",
        CacheMismatchWarning,
        stacklevel=2,
    )


def cached_call(spec: CacheSpec, run: Callable[[], R]) -> tuple[R, bool]:
    """Run `run()` through the cache, returning its result and whether it hit.

    Every step promotes the digest of its output to its dependents' keys, so a
    step that re-executes but returns unchanged data stops the recomputation
    there. Every failure path falls back to running normally and marks this step
    uncacheable for its dependents: an unset store, an unpinnable distribution,
    an uncacheable upstream, a value no codec claims, or a store that will not
    accept a write.
    """
    store = open_store()
    identity = step_identity(spec) if store is not None else None
    if store is None or identity is None:
        record(spec.task_instance_id, None)
        return run(), False

    verifying = _verifying()
    if spec.servable and not verifying:
        loaded = _load(store, identity)
        if loaded is not None:
            entry, value = loaded
            record(spec.task_instance_id, entry.content_id)
            return value, True

    result = run()
    codec = get_registry().for_value(result)
    if codec is None:
        record(spec.task_instance_id, None)
        return result, False

    digest = _content_id(codec, result)
    promoted: str | None = digest
    if spec.servable:
        if verifying:
            # A verify run must not write, so the baseline stays fixed and the
            # check can be repeated.
            _verify(store, spec, identity, digest)
        elif not _save(store, identity, codec, digest, result):
            promoted = None
    record(spec.task_instance_id, promoted)
    return result, False
