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

Composition convention
----------------------
Hooks MUST call ``await super()._pre_run()`` / ``await super()._post_run()``
as their first line so multi-mixin composition works correctly: the base
:class:`AbstractInvoker` hooks are no-ops, but if a future mixin is inserted
into the MRO ahead of the base class, skipping the ``super()`` call would
silently drop its hook.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx
import stamina

from .exceptions import PixiUnpackError

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
# Default chosen for the 100 MB – 2 GB typical transfer range against cloud
# object storage. 8 MiB keeps syscall overhead negligible (~128 reads/GB) and
# comfortably covers the GCP inter-region bandwidth-delay-product so TCP
# doesn't stall on app-layer drain lag.
TRANSFER_CHUNK_SIZE = int(
    os.environ.get("WT_INVOKERS__TRANSFER_CHUNK_SIZE", str(8 * 1024 * 1024))
)


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
# Safe archive helper (producer-side TarSlip hardening)
# ---------------------------------------------------------------------------


def _archive_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
    """Archive-time safety filter: reject TarSlip-capable entries.

    The workflow that wrote the source directory is untrusted and may plant
    unsafe entries (symlinks pointing outside the tree, absolute paths,
    device nodes, setuid bits, ``..`` traversal). We want none of those to
    cross the sandbox boundary into the tarball we ship out, so that
    whatever opens the archive downstream — Python, GNU tar, a Go service,
    a human — gets a tarball that is safe by construction.

    The hard check to get right is symlink/hardlink target escape (classic
    TarSlip is almost always a symlink variant, not a ``..`` filename).
    :func:`tarfile.data_filter` ships that check — along with absolute-path /
    traversal / special-file / setuid checks — as part of the stdlib
    extraction-safety API added in 3.12 (PEP 706). We repurpose it at
    archive time so we inherit the stdlib's security-reviewed check battery
    instead of hand-rolling it.

    The two-line normalization below exists because ``data_filter`` is
    extraction-oriented: it nulls ``uid`` / ``gid`` / ``uname`` / ``gname``
    (and ``mode`` for dirs/symlinks) on the assumption those fields get
    recomputed at extract time. The tar *header writer* can't serialize
    ``None``, so we set anonymized defaults before handing the TarInfo back
    to ``add()``. ``FilterError`` on a rejected member propagates and aborts
    the archive — correct behavior for a sandbox that should never be the
    hands that pass a loaded gun downstream.
    """
    filtered = tarfile.data_filter(tarinfo, "")
    # data_filter's type stub claims ``mode`` is ``int``, but at runtime it
    # sets mode to ``None`` for directories and symlinks (see stdlib
    # ``_get_filtered_attrs``). ``getattr`` dodges the unreachable-branch
    # warning without weakening the runtime check.
    if getattr(filtered, "mode", None) is None:
        filtered.mode = 0o755 if tarinfo.isdir() else 0o644
    filtered.uid = 0
    filtered.gid = 0
    filtered.uname = ""
    filtered.gname = ""
    return filtered


def archive_results_safely(results_dir: Path, dest: Path) -> None:
    """Tar ``results_dir`` into ``dest`` (gzip), applying :func:`_archive_filter`
    to every member; unsafe entries abort the archive.

    See :func:`_archive_filter` for the threat model and the set of checks
    applied. Exfiltration of readable regular files is out of scope here and
    is handled architecturally (container hardening, egress policy, signed
    upload URL).
    """
    with tarfile.open(dest, "w:gz") as tar:
        for item in results_dir.iterdir():
            tar.add(item, arcname=item.name, filter=_archive_filter)


# ---------------------------------------------------------------------------
# PixiUnpackMixin
# ---------------------------------------------------------------------------


class PixiUnpackMixin:
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

    # These attributes come from :class:`AbstractInvoker` at runtime; declared
    # here for the type checker only (no runtime class-dict pollution).
    if TYPE_CHECKING:
        run_args: MappingProxyType[str, Any]
        run_state: dict[str, Any]
        work_dir: str

    async def _pre_run(self) -> None:
        await super()._pre_run()  # type: ignore[misc]
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
            shutil.copy2(url2pathname(parsed.path), tar_path)
        elif parsed.scheme in ("http", "https"):
            await self._download_with_retries(environment_tar_url, tar_path)
        else:
            raise ValueError(
                f"Unsupported scheme for environment_tar_url: {parsed.scheme}"
            )

        try:
            subprocess.run(
                ["pixi-unpack", str(tar_path)],
                cwd=self.work_dir,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            raise PixiUnpackError(
                f"pixi-unpack failed with exit code {e.returncode}",
                returncode=e.returncode,
                stdout=e.stdout,
                stderr=e.stderr,
            ) from e

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
                        # Offload blocking file I/O so the event loop stays
                        # responsive (matters if a concurrent driver ever
                        # shares the loop with the download).
                        await asyncio.to_thread(f.write, chunk)

        await _do_download()


# ---------------------------------------------------------------------------
# UploadResultsArchiveMixin
# ---------------------------------------------------------------------------


class UploadResultsArchiveMixin:
    """Post-run hook that tars the results directory and uploads the archive.

    Reads ``results_url`` (a ``file://`` URL identifying the local results
    directory written by the workflow) and ``results_upload_url`` (the
    destination for the tarball) from :attr:`~AbstractInvoker.run_args`.
    Supports ``file://`` destinations for local testing as well as ``http://``
    / ``https://`` signed-URL uploads via ``PUT`` (used for GCS signed URLs).

    This hook runs even when the workflow exited non-zero so that a
    ``result.json`` describing the failure is still uploaded.

    Security note: this mixin carries untrusted-workflow output out of the
    sandbox. The archive stage is hardened against TarSlip via
    :func:`archive_results_safely`; exfiltration of readable files is a
    separate architectural concern (see the container / IAM / egress policy
    of the deployment).
    """

    # See :class:`PixiUnpackMixin` — typing shim only, no runtime effect.
    if TYPE_CHECKING:
        run_args: MappingProxyType[str, Any]
        run_state: dict[str, Any]
        work_dir: str

    async def _post_run(self) -> None:
        await super()._post_run()  # type: ignore[misc]
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
        results_dir = Path(url2pathname(parsed.path))
        if not results_dir.exists():
            raise RuntimeError(f"Results directory does not exist: {results_dir}")

        # NamedTemporaryFile creates and opens the file; we only need the path,
        # so close the handle and unlink in the finally block below.
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tar_file:
            tar_path = Path(tar_file.name)
        try:
            archive_results_safely(results_dir, tar_path)

            upload_parsed = urlparse(results_upload_url)
            if upload_parsed.scheme == "file":
                dest = Path(url2pathname(upload_parsed.path))
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

        Streams the file in ``TRANSFER_CHUNK_SIZE`` chunks rather than reading
        the whole archive into memory. The upload includes an explicit
        ``Content-Length`` header (required by GCS signed-URL uploads) sourced
        from the file's stat size, so the server can validate the request
        without the chunked ``Transfer-Encoding`` fallback.
        """

        size = tar_path.stat().st_size

        @stamina.retry(
            on=(httpx.TransportError, RetryableHTTPError),
            attempts=TRANSFER_MAX_ATTEMPTS,
            wait_initial=TRANSFER_RETRY_WAIT_INITIAL,
            wait_max=TRANSFER_RETRY_WAIT_MAX,
        )
        async def _do_upload() -> None:
            async def _chunks() -> AsyncIterator[bytes]:
                with open(tar_path, "rb") as f:
                    while True:
                        # Offload the blocking read so the event loop can
                        # service other tasks while we wait on disk.
                        chunk = await asyncio.to_thread(f.read, TRANSFER_CHUNK_SIZE)
                        if not chunk:
                            break
                        yield chunk

            async with httpx.AsyncClient(timeout=_timeout()) as client:
                response = await client.put(
                    url,
                    content=_chunks(),
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
