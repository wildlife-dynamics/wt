"""Execute a compiled workflow package via a wt-invokers invoker.

This is the "run" half: given a compiled package on disk (produced by
:mod:`wt_compiler_service.builder`), it launches the package's generated CLI as
an isolated subprocess in the same (shared) environment via
:class:`wt_invokers.CompiledPackageInvoker` — the same run mechanic
``wt-runner`` uses, rather than a bespoke reimplementation.

Results support both shapes: the caller may pass a ``results_url`` to persist
to (any obstore-supported URL the compiled CLI writes to), or omit it to use a
temporary ``file://`` store; either way the ``result.json`` is read back and
returned inline when it is locally readable.
"""

from __future__ import annotations

import io
import json
import logging
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import ruamel.yaml
from wt_invokers import CompiledPackageInvoker

logger = logging.getLogger(__name__)

_yaml = ruamel.yaml.YAML(typ="safe")


def _dump_yaml(params: dict[str, Any]) -> str:
    """Serialize params to a YAML string for the compiled CLI's config file."""
    stream = io.StringIO()
    _yaml.dump(params, stream)
    return stream.getvalue()


def _read_result(results_url: str) -> dict[str, Any] | None:
    """Read ``result.json`` from a local results URL, or None if not readable.

    Only ``file://`` URLs are read back inline; for remote stores the result is
    persisted at ``results_url`` and inline read-back is not attempted (the
    caller fetches it from there).
    """
    parsed = urlparse(results_url)
    if parsed.scheme not in ("file", ""):
        return None
    path = Path(url2pathname(parsed.path)) / "result.json"
    if not path.exists():
        return None
    loaded = json.loads(path.read_text())
    return loaded if isinstance(loaded, dict) else None


async def run_build(
    release_dir: Path,
    package_name: str,
    params: dict[str, Any],
    *,
    execution_mode: str = "sequential",
    mock_io: bool = False,
    env: dict[str, str] | None = None,
    timeout: float | None = None,  # noqa: ASYNC109  # forwarded to the invoker's wait(); not an asyncio.timeout() candidate
    results_url: str | None = None,
    results_env_var: str = "WT_RESULTS",
) -> dict[str, Any]:
    """Run a compiled package via a CompiledPackageInvoker.

    Args:
        release_dir: Directory containing the compiled package (on ``PYTHONPATH``).
        package_name: Importable package name to invoke.
        params: Workflow parameters.
        execution_mode: Execution mode; only ``"sequential"`` is supported by
            the generated dispatcher.
        mock_io: Whether to run the mock-I/O DAG variant (no real data access).
        env: Optional environment variables for the run subprocess (e.g.
            data-connection secrets for non-mock runs).
        timeout: Optional timeout in seconds for the run subprocess.
        results_url: Optional URL to persist results to. When omitted, a
            temporary ``file://`` store is used and the result is returned inline.
        results_env_var: Name of the env var the compiled CLI reads for its
            results URL. Must match what the package was compiled with (the
            builder threads this through), default ``"WT_RESULTS"``.

    Returns:
        A mapping with ``results_url``, ``result``/``error``/``trace`` (the
        workflow response envelope; task failures are captured as ``error``),
        ``run_ms``, and ``returncode``.
    """
    if results_url is None:
        results_url = Path(tempfile.mkdtemp(prefix="wt-results-")).as_uri()

    invoker = CompiledPackageInvoker(
        release_dir=release_dir, package_name=package_name, results_env_var=results_env_var
    )
    logger.info(
        "Running workflow %s from %s (execution_mode=%s, mock_io=%s, results_url=%s)",
        package_name,
        release_dir,
        execution_mode,
        mock_io,
        results_url,
    )
    t_run = time.monotonic()
    await invoker.run(
        workflow_run_id=uuid.uuid4().hex,
        config_text=_dump_yaml(params),
        results_url=results_url,
        execution_mode=execution_mode,
        mock_io=mock_io,
        extra_env=env,
    )
    # Grab the process ref before wait() clears run_state, so we can surface
    # stderr if the CLI dies before writing a result.
    proc = invoker.run_state.get("process")
    returncode = await invoker.wait(timeout=timeout)
    run_ms = round((time.monotonic() - t_run) * 1000, 1)
    logger.info("Finished workflow %s: returncode=%s, run_ms=%s", package_name, returncode, run_ms)

    envelope = _read_result(results_url)
    if envelope is None:
        if returncode == 0:
            # Success, but not read back inline (e.g. a remote results_url); the
            # result is persisted at results_url for the caller to fetch.
            envelope = {"result": None, "error": None, "trace": None}
        else:
            stderr = ""
            if proc is not None and proc.stderr is not None:
                stderr = proc.stderr.read().decode(errors="replace").strip()
            envelope = {"result": None, "error": stderr or "run failed", "trace": None}

    return {
        "results_url": results_url,
        "result": envelope.get("result"),
        "error": envelope.get("error"),
        "trace": envelope.get("trace"),
        "run_ms": run_ms,
        "returncode": returncode,
    }
