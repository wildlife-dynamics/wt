"""Content-addressed step caching for compiled DAGs.

Opt-in at compile time. A step is keyed by its code, its arguments, and the
content digests of the steps feeding it, and a hit returns the stored value
instead of executing. What a result *is* comes from the task's return type —
`wt_contracts.declared_structure` resolves it, the compiler emits it, and
`resolve_structure` turns it into the `Tree` that encodes the whole step.
Everything degrades to running normally: with `WT_CACHE` unset, or for any
return type that declares no codec, the cache is inert.
"""

from ._codec import BYTES, JSON, PATH, SKIP, URL, Codec, Undigestible, enum_codec
from ._entry import CacheEntry
from ._key import CacheRecord, record, run_report, run_scope, step_identity
from ._runtime import CacheCorruptionError, CacheMismatchWarning, cached_call
from ._spec import CacheSpec
from ._store import open_store
from ._tree import CacheMismatch, Tree, resolve_structure

__all__ = [
    "BYTES",
    "JSON",
    "PATH",
    "SKIP",
    "URL",
    "CacheCorruptionError",
    "CacheEntry",
    "CacheMismatch",
    "CacheMismatchWarning",
    "CacheRecord",
    "CacheSpec",
    "Codec",
    "Tree",
    "Undigestible",
    "cached_call",
    "enum_codec",
    "open_store",
    "record",
    "resolve_structure",
    "run_report",
    "run_scope",
    "step_identity",
]
