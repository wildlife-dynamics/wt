"""Content-addressed step caching for compiled DAGs.

Opt-in at compile time. A step is keyed by its code, its arguments, and the
content digests of the steps feeding it, and a hit returns the stored value
instead of executing. What a result *is* comes from the task's return type —
`wt_contracts.declared_structure` resolves it at run time, and
`resolve_structure` turns it into the `Tree` that encodes the whole step.
Everything degrades to running normally: with `WT_CACHE__STORE` unset, or for any
return type that declares no codec, the cache is inert.

Runtime knobs live in `CacheSettings`, read once per `run_scope`.
"""

from ._codec import BYTES, JSON, PATH, SKIP, URL, Codec, Undigestible, enum_codec
from ._entry import CacheEntry
from ._key import CacheRecord, record, run_report, run_scope, step_identity, step_params
from ._report import REPORT_NAME, cache_report, put_cache_report
from ._runtime import CacheCorruptionError, CacheMismatchWarning, cached_call
from ._settings import CacheSettings, load_settings
from ._spec import CacheSpec, ResolvedTask, resolve_task
from ._store import open_store
from ._tree import CacheMismatch, Tree, resolve_structure

__all__ = [
    "BYTES",
    "JSON",
    "PATH",
    "REPORT_NAME",
    "SKIP",
    "URL",
    "CacheCorruptionError",
    "CacheEntry",
    "CacheMismatch",
    "CacheMismatchWarning",
    "CacheRecord",
    "CacheSettings",
    "CacheSpec",
    "Codec",
    "ResolvedTask",
    "Tree",
    "Undigestible",
    "cache_report",
    "cached_call",
    "enum_codec",
    "load_settings",
    "open_store",
    "put_cache_report",
    "record",
    "resolve_structure",
    "resolve_task",
    "run_report",
    "run_scope",
    "step_identity",
    "step_params",
]
