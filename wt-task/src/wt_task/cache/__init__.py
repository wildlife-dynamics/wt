"""Content-addressed step caching for compiled DAGs.

Opt-in at compile time. A step is keyed by what produced it — its code, its
arguments, and the identities of the steps feeding it — and a hit returns the
stored value instead of executing. Everything degrades to running normally:
with `WT_CACHE` unset, or for any value no codec claims, the cache is inert.
"""

from ._codec import Codec, CodecConflictError, get_registry, json_digest
from ._entry import CacheEntry
from ._key import record, run_scope, step_identity
from ._runtime import CacheCorruptionError, cached_call
from ._spec import CacheSpec
from ._store import open_store

__all__ = [
    "CacheCorruptionError",
    "CacheEntry",
    "CacheSpec",
    "Codec",
    "CodecConflictError",
    "cached_call",
    "get_registry",
    "json_digest",
    "open_store",
    "record",
    "run_scope",
    "step_identity",
]
