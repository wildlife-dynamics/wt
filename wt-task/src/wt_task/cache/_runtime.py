"""Running a step through the cache."""

from __future__ import annotations

import os
import warnings
from typing import TYPE_CHECKING, Any, TypeVar, cast

from ._entry import CacheEntry
from ._key import Outcome, record, step_identity_with_reason
from ._store import open_store
from ._tree import TREE_CODEC_ID, CacheMismatch

if TYPE_CHECKING:
    from collections.abc import Callable

    from ._spec import CacheSpec
    from ._store import Store
    from ._tree import Tree

R = TypeVar("R")

KEYS_PREFIX = "keys"
CAS_PREFIX = "cas"

VERIFY_ENV_VAR = "WT_CACHE_VERIFY"


class CacheCorruptionError(RuntimeError):
    """Raised when a stored payload exists but cannot be read back at all.

    Not downgraded to a miss: the payload is present and the declaration that
    wrote it still resolves, so a failure here means the store is lying about
    its contents, and recomputing would hide that. A declaration that moved
    raises `CacheMismatch` instead, which misses cleanly.
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


def _load(store: Store, identity: str, tree: Tree) -> tuple[CacheEntry, Any] | None:
    """Return the entry and decoded value, or None for any kind of miss."""
    entry = _read_entry(store, identity)
    if entry is None:
        return None

    payload = store.get(f"{CAS_PREFIX}/{entry.content_id}")
    if payload is None:
        # Evicted, or the key outlived its payload. Stale, not corrupt.
        return None

    try:
        return entry, tree.decode(payload)
    except CacheMismatch:
        # A leaf codec or a declared type moved since this was written.
        return None
    except Exception as e:
        raise CacheCorruptionError(
            f"Could not decode {CAS_PREFIX}/{entry.content_id} for cache key {identity}: {e!r}"
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


def _save(
    store: Store,
    identity: str,
    tree: Tree,
    content_id: str,
    value: Any,  # noqa: ANN401  # stores any task return
) -> bool:
    """Store `value` under `identity`, returning whether the store accepted it."""
    try:
        store.put(f"{CAS_PREFIX}/{content_id}", tree.encode(value))
        entry = CacheEntry(
            content_id=content_id, codec_id=tree.codec_id, media_type=tree.media_type
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


def _no_tree_reason(spec: CacheSpec) -> tuple[Outcome, str]:
    """Why a step with no resolved tree is not cacheable, as (outcome, reason)."""
    if spec.structure is None:
        return "uncacheable", "return type declares no codec"
    return "refused", "declared codec refs could not be imported"


def cached_call(spec: CacheSpec, run: Callable[[], R], tree: Tree | None = None) -> tuple[R, bool]:
    """Run `run()` through the cache, returning its result and whether it hit.

    Every step promotes the digest of its output to its dependents' keys, so a
    step that re-executes but returns unchanged data stops the recomputation
    there. Every failure path falls back to running normally and marks this step
    uncacheable for its dependents: an unset store, an unpinnable distribution,
    an uncacheable upstream, a return type with no codec, a value the declared
    structure refuses, or a store that will not accept a write.
    """
    store = open_store()
    if store is None:
        record(spec.task_instance_id, None, "inert", "no cache store configured")
        return run(), False
    if tree is None:
        outcome, reason = _no_tree_reason(spec)
        record(spec.task_instance_id, None, outcome, reason)
        return run(), False

    identity, blocked_by = step_identity_with_reason(spec)
    if identity is None:
        record(spec.task_instance_id, None, "uncacheable", blocked_by)
        return run(), False

    verifying = _verifying()
    if spec.servable and not verifying:
        loaded = _load(store, identity, tree)
        if loaded is not None:
            entry, value = loaded
            record(spec.task_instance_id, entry.content_id, "hit")
            return cast("R", value), True

    result = run()
    if spec.method != "call":
        # The executor may hand back any sequence; a hit always yields a list,
        # so a miss has to as well.
        result = cast("R", list(cast("Any", result)))

    try:
        content_id = f"{TREE_CODEC_ID}/{tree.digest(result)}"
        promoted: str | None = content_id
        if spec.servable:
            if verifying:
                # A verify run must not write, so the baseline stays fixed and
                # the check can be repeated.
                _verify(store, spec, identity, content_id)
            elif not _save(store, identity, tree, content_id, result):
                promoted = None
    except Exception as e:  # noqa: BLE001  # a codec that declines must not fail the run
        warnings.warn(
            f"Not caching task instance {spec.task_instance_id!r} "
            f"({spec.anchor}.{spec.function}): {e!r}",
            stacklevel=2,
        )
        record(spec.task_instance_id, None, "refused", repr(e))
        return result, False

    record(
        spec.task_instance_id,
        promoted,
        "miss" if spec.servable else "unservable",
        None if promoted is not None else "store would not accept the write",
    )
    return result, False
