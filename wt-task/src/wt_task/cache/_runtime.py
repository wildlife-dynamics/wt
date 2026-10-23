"""Running a step through the cache."""

from __future__ import annotations

import re
import warnings
from typing import TYPE_CHECKING, Any, TypeVar, cast

from ._entry import CacheEntry, utcnow
from ._key import Outcome, record, step_identity_with_reason
from ._settings import ENV_PREFIX, active_settings
from ._store import open_store
from ._tree import CacheMismatch, is_safe_codec_dir, strict

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import timedelta

    from ._spec import CacheSpec, ResolvedTask
    from ._store import Store
    from ._tree import Tree

R = TypeVar("R")

KEYS_PREFIX = "keys"
CONTENT_PREFIX = "content"


def _seconds(delta: timedelta) -> str:
    return f"{int(delta.total_seconds())}s"


def _too_old(spec: CacheSpec, entry: CacheEntry) -> str | None:
    """Why this entry is too old to serve, or None if it may be.

    Only io-tagged steps age. A derived step is a pure function of its input
    digests, so the same key cannot describe different content and its age
    says nothing about freshness.
    """
    if not spec.scoped:
        return None
    ttl = active_settings().io_ttl
    if ttl is None:
        return None
    if not ttl:
        return f"{ENV_PREFIX}IO_TTL is zero: io steps always refetch"
    age = utcnow() - entry.created_at
    if age < ttl:
        return None
    return f"older than {_seconds(ttl)} (age {_seconds(age)})"


def _path(prefix: str, name: str) -> str:
    """Locate one stored object: `keys/<hex>`, or `content/<codec>/<hex>`.

    Flat, because the codec directories already split `content/`, and keys are
    only ever read one at a time.
    """
    return f"{prefix}/{name}"


_HEX_DIGEST = re.compile(r"[0-9a-f]{64}")


def _is_content_id(content_id: str) -> bool:
    """Whether a stored entry's `content_id` is one this build would write.

    It becomes a store path, so an entry that does not fit is read as a miss
    rather than followed out of `content/`.
    """
    directory, _, digest = content_id.rpartition("/")
    return bool(directory) and is_safe_codec_dir(directory) and bool(_HEX_DIGEST.fullmatch(digest))


class CacheCorruptionError(RuntimeError):
    """Raised under `strict` when a stored payload exists but cannot be read back.

    Otherwise it warns and misses, and the recompute rewrites the payload: the
    store may be lying about its contents, but losing the cache is still
    preferable to losing the run. A declaration that moved raises
    `CacheMismatch` instead, which misses without a warning.
    """


class CacheMismatchWarning(UserWarning):
    """Warned under the `verify` setting when a step reproduced a different output.

    Its own category so that a verify run can collect the whole report with
    `warnings.catch_warnings(record=True)` rather than scraping stderr.
    """


def _servable(spec: CacheSpec) -> tuple[bool, str | None]:
    """Whether a stored result may be served for this step, and if not, why.

    An io step with no scope set is not: credentials are keyed by connection
    name, so another principal's entry would sit under the same key. It still
    runs and promotes its digest, so the steps below it keep hitting on
    identical content, which no principal can address without already holding.
    """
    if not spec.servable:
        return False, "no-cache tag"
    if spec.scoped and not active_settings().scope:
        return False, f"io step with {ENV_PREFIX}SCOPE unset"
    return True, None


def _verifying() -> bool:
    """Whether this run is checking stored outputs instead of serving them."""
    return active_settings().verify


def _load(store: Store, entry: CacheEntry, identity: str, tree: Tree) -> tuple[Any] | None:
    """Return the decoded value in a one-tuple, or None for any kind of miss.

    Takes the entry the caller already read, so that an entry rejected on age
    costs no payload read.
    """
    if not _is_content_id(entry.content_id):
        return None
    payload = store.get(_path(CONTENT_PREFIX, entry.content_id))
    if payload is None:
        # Evicted, or the key outlived its payload. Stale, not corrupt.
        return None

    try:
        return (tree.decode(payload),)
    except CacheMismatch:
        # A leaf codec or a declared type moved since this was written.
        return None
    except Exception as e:
        error = CacheCorruptionError(
            f"Could not decode {_path(CONTENT_PREFIX, entry.content_id)} "
            f"for cache key {identity}: {e!r}"
        )
        if strict():
            raise error from e
        warnings.warn(f"{error} Recomputing.", stacklevel=2)
        return None


def _read_entry(store: Store, identity: str) -> CacheEntry | None:
    """Return the stored entry for `identity`, or None if there is none to read."""
    raw = store.get(_path(KEYS_PREFIX, identity))
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
        store.put(_path(CONTENT_PREFIX, content_id), tree.encode(value))
        entry = CacheEntry(
            content_id=content_id, codec_id=tree.codec_id, media_type=tree.media_type
        )
        store.put(_path(KEYS_PREFIX, identity), entry.model_dump_json().encode("utf-8"))
    except Exception as e:  # noqa: BLE001  # a store that cannot write must not fail the run
        warnings.warn(f"Could not write cache entry {identity}: {e!r}", stacklevel=2)
        return False
    return True


def _verify(
    store: Store, resolved: ResolvedTask, task_instance_id: str, identity: str, content_id: str
) -> None:
    """Warn if a stored output for this key differs from the one just computed.

    A mismatch is proof that identical declared inputs produced different
    output — the empirical way to find which tasks need the `no-cache` tag,
    including the ones whose author misspelled it.
    """
    entry = _read_entry(store, identity)
    if entry is None or entry.content_id == content_id:
        return
    warnings.warn(
        f"Cache verification failed for task instance {task_instance_id!r} "
        f"({resolved.anchor}.{resolved.function}): stored output {entry.content_id} but "
        f"recomputed {content_id} for cache key {identity}. The same declared "
        f"inputs produced different output.",
        CacheMismatchWarning,
        stacklevel=2,
    )


def cached_call(
    spec: CacheSpec,
    run: Callable[[], R],
    resolved: ResolvedTask,
    task_instance_id: str,
    method: str = "call",
) -> tuple[R, bool]:
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
        record(task_instance_id, None, "inert", "no cache store configured")
        return run(), False

    tree = resolved.tree(method)
    if tree is None:
        record(
            task_instance_id,
            None,
            resolved.outcome or "uncacheable",
            resolved.reason or f"no codec for the {method!r} method",
        )
        return run(), False

    identity, blocked_by = step_identity_with_reason(spec, resolved, task_instance_id, method)
    if identity is None:
        record(task_instance_id, None, "uncacheable", blocked_by)
        return run(), False

    verifying = _verifying()
    servable, unservable_reason = _servable(spec)
    expired: str | None = None
    if servable and not verifying:
        entry = _read_entry(store, identity)
        if entry is not None:
            expired = _too_old(spec, entry)
            loaded = _load(store, entry, identity, tree) if expired is None else None
            if loaded is not None:
                record(task_instance_id, entry.content_id, "hit")
                return cast("R", loaded[0]), True

    result = run()
    if method != "call":
        # The executor may hand back any sequence; a hit always yields a list,
        # so a miss has to as well.
        result = cast("R", list(cast("Any", result)))

    try:
        content_id = f"{resolved.content_dir(method, tree)}/{tree.digest(result)}"
        promoted: str | None = content_id
        if servable:
            if verifying:
                # A verify run must not write, so the baseline stays fixed and
                # the check can be repeated.
                _verify(store, resolved, task_instance_id, identity, content_id)
            elif not _save(store, identity, tree, content_id, result):
                promoted = None
    except Exception as e:  # noqa: BLE001  # a codec that declines must not fail the run
        warnings.warn(
            f"Not caching task instance {task_instance_id!r} "
            f"({resolved.anchor}.{resolved.function}): {e!r}",
            stacklevel=2,
        )
        record(task_instance_id, None, "refused", repr(e))
        return result, False

    outcome: Outcome = "miss"
    reason: str | None = None
    if not servable:
        outcome, reason = "unservable", unservable_reason
    elif expired is not None:
        outcome, reason = "expired", expired
    record(
        task_instance_id,
        promoted,
        outcome,
        reason if promoted is not None else "store would not accept the write",
    )
    return result, False
