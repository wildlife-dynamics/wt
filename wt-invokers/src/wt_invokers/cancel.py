"""Cancel a run by a marker beside its results.

The caller and the process running a workflow may share nothing but the run's
results location (either side may have scaled out across instances), so a run is
cancelled by writing :data:`CANCEL_MARKER` there. :func:`wait_unless_cancelled`
polls for it while waiting and, once it appears, cancels the wait. For subprocess
invokers that stops the run: ``SubprocessInvokerBase._wait`` terminates, then kills,
the run's process group. Other invokers only stop being waited on.

Local results directories are checked with the standard library. Object-store URLs
need ``obstore``, from the ``gcp`` extra or the ``wt-invokers-gcp`` metapackage;
without it, a remote run can't be cancelled and simply runs to completion.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from urllib.request import url2pathname

if TYPE_CHECKING:
    from .abstract import AbstractInvoker

logger = logging.getLogger(__name__)

CANCEL_MARKER = "cancel"
DEFAULT_POLL_SECONDS = 2.0


async def cancel_requested(results_url: str) -> bool:
    """Whether a cancel marker sits beside the run's results.

    A failed check reads as "not cancelled": a flaky store must not stop a run.

    Examples:
        >>> import asyncio, tempfile
        >>> asyncio.run(cancel_requested(tempfile.mkdtemp()))
        False
    """
    parsed = urlparse(results_url)
    if parsed.scheme in ("", "file"):
        local = Path(url2pathname(parsed.path) if parsed.scheme else results_url)
        return (local / CANCEL_MARKER).is_file()  # one stat, not worth a thread
    try:
        import obstore  # noqa: PLC0415  # optional: only object-store URLs need it
        import obstore.exceptions  # noqa: PLC0415
    except ImportError:
        _warn_no_obstore()
        return False
    try:
        await obstore.head_async(obstore.store.from_url(results_url), CANCEL_MARKER)
    except obstore.exceptions.NotFoundError:
        return False
    except Exception:
        logger.warning("Cancel check failed for %s", results_url, exc_info=True)
        return False
    return True


@functools.cache
def _warn_no_obstore() -> None:
    logger.warning(
        "obstore is not installed, so runs with object-store results can't be cancelled; "
        "install wt-invokers[gcp] or wt-invokers-gcp."
    )


async def wait_unless_cancelled(
    invoker: AbstractInvoker,
    results_url: str,
    timeout: float | None = None,  # noqa: ASYNC109  # forwarded to the invoker's wait()
    poll_seconds: float = DEFAULT_POLL_SECONDS,
) -> int | None:
    """Wait for `invoker`'s run, returning None once its cancel marker appears.

    Args:
        invoker: An invoker whose ``run()`` has been called.
        results_url: The run's results location, where the marker is written.
        timeout: Passed to ``invoker.wait()``; its timeout error propagates as usual.
        poll_seconds: How often to check for the marker.

    Returns:
        The run's exit code, or None if it was cancelled.
    """
    wait = asyncio.ensure_future(invoker.wait(timeout=timeout))
    while True:
        done, _ = await asyncio.wait({wait}, timeout=poll_seconds)
        if wait in done:
            result: int = wait.result()
            return result
        if await cancel_requested(results_url):
            wait.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await wait
            return None
