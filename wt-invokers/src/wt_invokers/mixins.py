"""Pre/post-run mixins for invokers.

This module defines mixins that hook into :class:`AbstractInvoker`'s
``_pre_run`` / ``_post_run`` lifecycle methods. Mixins are composed in MRO
order on concrete invokers (see :class:`wt_invokers.sandbox.SandboxInvoker`).

Two mixins are provided:

* :class:`PixiUnpackMixin` — downloads a pixi-pack environment tarball from a
  URL and unpacks it before the workflow runs.
* :class:`UploadResultsArchiveMixin` — tars the results directory after the
  workflow finishes and uploads the archive to a signed URL.

Both mixins share a common HTTP transfer configuration (retry policy,
timeouts, chunk size) via module-level constants that can be overridden via
environment variables.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlparse

import httpx
import stamina

# ---------------------------------------------------------------------------
# Shared HTTP transfer configuration
# ---------------------------------------------------------------------------
# Override via environment variables. These govern both download
# (PixiUnpackMixin) and upload (UploadResultsArchiveMixin).

TRANSFER_MAX_ATTEMPTS = int(os.environ.get("WT_INVOKERS__TRANSFER_MAX_ATTEMPTS", "5"))
TRANSFER_RETRY_WAIT_INITIAL = float(
    os.environ.get("WT_INVOKERS__TRANSFER_RETRY_WAIT_INITIAL", "1.0")
)
TRANSFER_RETRY_WAIT_MAX = float(
    os.environ.get("WT_INVOKERS__TRANSFER_RETRY_WAIT_MAX", "60.0")
)
TRANSFER_CONNECT_TIMEOUT = float(
    os.environ.get("WT_INVOKERS__TRANSFER_CONNECT_TIMEOUT", "30.0")
)
TRANSFER_TIMEOUT = float(os.environ.get("WT_INVOKERS__TRANSFER_TIMEOUT", "1800.0"))
TRANSFER_CHUNK_SIZE = int(os.environ.get("WT_INVOKERS__TRANSFER_CHUNK_SIZE", "65536"))


class RetryableHTTPError(Exception):
    """Raised on 5xx HTTP errors to trigger stamina retry."""


def _timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=TRANSFER_CONNECT_TIMEOUT,
        read=TRANSFER_TIMEOUT,
        write=TRANSFER_TIMEOUT,
        pool=TRANSFER_CONNECT_TIMEOUT,
    )


# ---------------------------------------------------------------------------
# Protocol-like helper: mixins read per-invocation args from self.run_args and
# self.run_state. They do not declare the full AbstractInvoker interface.
# ---------------------------------------------------------------------------


class _RunContextMixin:
    """Common typing shim for mixins that read from ``run_args``/``run_state``.

    Both mixins below rely on the AbstractInvoker contract; declaring these
    properties here keeps mypy happy when the mixin is used standalone in
    isolation (e.g. in tests).
    """

    run_args: MappingProxyType[str, Any]
    run_state: dict[str, Any]
    work_dir: str


# ---------------------------------------------------------------------------
# PixiUnpackMixin
# ---------------------------------------------------------------------------


class PixiUnpackMixin(_RunContextMixin):
    """Pre-run hook that downloads and unpacks a pixi-pack environment tarball.

    Reads ``environment_tar_url`` from :attr:`~AbstractInvoker.run_args`,
    writes the downloaded tarball to ``{work_dir}/environment.tar``, invokes
    ``pixi-unpack`` on it, and records the path to the activation script in
    :attr:`~AbstractInvoker.run_state` under the key ``"activate_path"`` so
    downstream ``_run`` implementations can source it.

    Supports ``file://``, ``http://``, and ``https://`` URL schemes for the
    tarball source. HTTP(S) downloads are retried via ``stamina`` on transport
    errors and 5xx responses.
    """

    async def _pre_run(self) -> None:
        if shutil.which("pixi-unpack") is None:
            raise RuntimeError(
                "pixi-unpack not found. Install via conda "
                "(included in the wt-invokers conda package) or manually "
                "from https://github.com/Quantco/pixi-pack"
            )

        environment_tar_url = self.run_args.get("environment_tar_url")
        if not environment_tar_url:
            raise ValueError(
                "environment_tar_url is required -- pass it as a kwarg to run()"
            )

        Path(self.work_dir).mkdir(parents=True, exist_ok=True)
        tar_path = Path(self.work_dir) / "environment.tar"

        parsed = urlparse(environment_tar_url)
        if parsed.scheme == "file":
            shutil.copy2(parsed.path, tar_path)
        elif parsed.scheme in ("http", "https"):
            await self._download_with_retries(environment_tar_url, tar_path)
        else:
            raise ValueError(
                f"Unsupported scheme for environment_tar_url: {parsed.scheme}"
            )

        subprocess.run(
            ["pixi-unpack", str(tar_path)],
            cwd=self.work_dir,
            check=True,
            capture_output=True,
        )

        self.run_state["activate_path"] = str(Path(self.work_dir) / "activate.sh")

    async def _download_with_retries(self, url: str, dest: Path) -> None:
        """Download ``url`` to ``dest`` with retries on transient failure."""

        @stamina.retry(
            on=(httpx.TransportError, RetryableHTTPError),
            attempts=TRANSFER_MAX_ATTEMPTS,
            wait_initial=TRANSFER_RETRY_WAIT_INITIAL,
            wait_max=TRANSFER_RETRY_WAIT_MAX,
        )
        async def _do_download() -> None:
            async with (
                httpx.AsyncClient(timeout=_timeout()) as client,
                client.stream("GET", url) as response,
            ):
                if 500 <= response.status_code < 600:
                    raise RetryableHTTPError(
                        f"Server error {response.status_code} downloading {url}"
                    )
                response.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in response.aiter_bytes(
                        chunk_size=TRANSFER_CHUNK_SIZE
                    ):
                        f.write(chunk)

        await _do_download()


# ---------------------------------------------------------------------------
# UploadResultsArchiveMixin
# ---------------------------------------------------------------------------


class UploadResultsArchiveMixin(_RunContextMixin):
    """Post-run hook that tars the results directory and uploads the archive.

    Reads ``results_url`` (a ``file://`` URL identifying the local results
    directory written by the workflow) and ``results_upload_url`` (the
    destination for the tarball) from :attr:`~AbstractInvoker.run_args`.
    Supports ``file://`` destinations for local testing as well as ``http://``
    / ``https://`` signed-URL uploads via ``PUT`` (used for GCS signed URLs).

    This hook runs even when the workflow exited non-zero so that a
    ``result.json`` describing the failure is still uploaded.
    """

    async def _post_run(self) -> None:
        results_url = self.run_args.get("results_url")
        if not results_url:
            raise ValueError("results_url is required -- pass it as an arg to run()")
        results_upload_url = self.run_args.get("results_upload_url")
        if not results_upload_url:
            raise ValueError(
                "results_upload_url is required -- pass it as a kwarg to run()"
            )

        parsed = urlparse(results_url)
        if parsed.scheme not in ("file", ""):
            raise ValueError(
                f"results_url must be a file:// URL for sandbox invoker, "
                f"got: {results_url}"
            )
        results_dir = Path(parsed.path)
        if not results_dir.exists():
            raise RuntimeError(f"Results directory does not exist: {results_dir}")

        # NamedTemporaryFile creates and opens the file; we only need the path,
        # so close the handle and unlink in the finally block below.
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tar_file:
            tar_path = Path(tar_file.name)
        try:
            with tarfile.open(tar_path, "w:gz") as tar:
                for item in results_dir.iterdir():
                    tar.add(item, arcname=item.name)

            upload_parsed = urlparse(results_upload_url)
            if upload_parsed.scheme == "file":
                dest = Path(upload_parsed.path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(tar_path, dest)
            elif upload_parsed.scheme in ("http", "https"):
                await self._upload_with_retries(tar_path, results_upload_url)
            else:
                raise ValueError(
                    f"Unsupported scheme for results_upload_url: {upload_parsed.scheme}"
                )
        finally:
            tar_path.unlink(missing_ok=True)

    async def _upload_with_retries(self, tar_path: Path, url: str) -> None:
        """Upload ``tar_path`` to ``url`` via ``PUT`` with retries.

        Reads the file bytes each attempt so that a retry after a partial
        upload re-sends from the start. The upload includes an explicit
        ``Content-Length`` header (via ``bytes`` payload) which is required
        by GCS signed-URL uploads.
        """

        size = tar_path.stat().st_size

        @stamina.retry(
            on=(httpx.TransportError, RetryableHTTPError),
            attempts=TRANSFER_MAX_ATTEMPTS,
            wait_initial=TRANSFER_RETRY_WAIT_INITIAL,
            wait_max=TRANSFER_RETRY_WAIT_MAX,
        )
        async def _do_upload() -> None:
            data = tar_path.read_bytes()
            async with httpx.AsyncClient(timeout=_timeout()) as client:
                response = await client.put(
                    url,
                    content=data,
                    headers={
                        "Content-Type": "application/gzip",
                        "Content-Length": str(size),
                    },
                )
            if 500 <= response.status_code < 600:
                raise RetryableHTTPError(
                    f"Server error {response.status_code} uploading to {url}"
                )
            response.raise_for_status()

        await _do_upload()
