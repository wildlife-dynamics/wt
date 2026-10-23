"""The per-run cache report the generated CLI writes beside `result.json`.

Its own file rather than a field of the result envelope, so that it is written
even when the run fails: a failed run's report says how far it got.
"""

from __future__ import annotations

import json
import warnings
from collections import Counter
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from ._key import _LAST_EXIT, _RUN_IDS, run_report
from ._settings import active_settings, load_settings
from ._store import _local_root

if TYPE_CHECKING:
    from datetime import timedelta

    from ._settings import CacheSettings

REPORT_NAME = "cache-report.json"


def _ttl(ttl: timedelta | None) -> str:
    """Render `io_ttl` the way `WT_CACHE__IO_TTL` would spell it."""
    if ttl is None:
        return "forever"
    if not ttl:
        return "never"
    return f"{int(ttl.total_seconds())}s"


def _redacted(settings: CacheSettings) -> dict[str, Any]:
    """The effective settings, without anything that could leak.

    A store URL can name a bucket path and a scope is often derived from a
    token, so only whether they are set — and the store's scheme — is reported.
    """
    store = settings.store
    scheme = None
    if store:
        scheme = "file" if _local_root(store) is not None else urlparse(store).scheme
    return {
        "store": {"configured": bool(store), "scheme": scheme},
        "io_ttl": _ttl(settings.io_ttl),
        "verify": settings.verify,
        "strict": settings.strict,
        "epoch_set": bool(settings.epoch),
        "scope_set": bool(settings.scope),
    }


def cache_report(error: str | None = None) -> dict[str, Any]:
    """Build this run's cache report: how it ended, and what each step's cache did.

    Read inside a `run_scope` it describes the run so far, with status
    `running`; after the scope it describes how the scope ended, including on
    failure, with the rows recorded up to that point.

    Args:
        error: The run's error as the caller saw it, for a failure the DAG's
            scope did not see — one raised after it closed, or before it opened.

    Returns:
        `{status, error?, failed_step?, summary, settings, steps}`, JSON-able.

    Examples:
        >>> from wt_task.cache import CacheSettings, record, run_scope
        >>> with run_scope(settings=CacheSettings()):
        ...     record("a", None, "inert", "no cache store configured")
        >>> report = cache_report()
        >>> report["status"], report["summary"], report["settings"]["store"]
        ('completed', {'inert': 1}, {'configured': False, 'scheme': None})
    """
    steps = run_report()
    if _RUN_IDS.get(None) is not None:
        status, settings, failure, failed_step = "running", active_settings(), None, None
    else:
        settings = _LAST_EXIT.settings or load_settings()
        failure, failed_step = _LAST_EXIT.error or error, _LAST_EXIT.failed_step
        status = "failed" if failure else "completed"

    report: dict[str, Any] = {"status": status}
    if failure:
        report["error"] = failure
    if failed_step:
        report["failed_step"] = failed_step
    report["summary"] = dict(sorted(Counter(row["outcome"] for row in steps.values()).items()))
    report["settings"] = _redacted(settings)
    report["steps"] = steps
    return report


def put_cache_report(store: Any, error: str | None = None) -> bool:  # noqa: ANN401  # any store with `put(key, bytes)`
    """Write `cache-report.json` to `store`, returning whether it was written.

    Never raises: a report that cannot be written must not replace the run's
    own result or error, so the failure is only warned about.

    Args:
        store: Anything with `put(key, data)`, such as the obstore store the
            generated CLI writes `result.json` to.
        error: As for `cache_report`.

    Examples:
        >>> class Store(dict):
        ...     def put(self, key, data):
        ...         self[key] = data
        >>> store = Store()
        >>> put_cache_report(store)
        True
        >>> sorted(json.loads(store["cache-report.json"]))
        ['settings', 'status', 'steps', 'summary']
    """
    try:
        store.put(REPORT_NAME, json.dumps(cache_report(error), indent=2).encode("utf-8"))
    except Exception as e:  # noqa: BLE001  # reporting must never fail the run
        warnings.warn(f"Could not write {REPORT_NAME}: {e!r}", stacklevel=2)
        return False
    return True
